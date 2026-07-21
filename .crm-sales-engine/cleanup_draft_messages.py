"""Remove Gmail DRAFTS that Twenty's sync imported as sent "history" (LIVE, mutates prod).

Twenty v2.7.3 bug: the incremental Gmail sync (history.list) has no way to exclude
drafts, so reply drafts (recipient pre-filled) get imported as OUTGOING messages —
and Gmail assigns a new message id on every draft autosave, so one draft can land
in a thread several times. This script cross-checks every OUTGOING message against
the owning Gmail mailbox and soft-deletes the ghosts:

  - Gmail says labelIds contains DRAFT  -> live draft imported as history -> ghost
  - Gmail returns 404                   -> message no longer exists (draft was
                                           superseded by autosave / deleted on send;
                                           real sent mail never 404s)   -> ghost
  - anything else (200 sans DRAFT, 401/403/5xx) -> kept / skipped

Ghosts get "deletedAt"=now() on message + messageParticipant + the channel
association (soft delete only). Every run appends a manifest entry to
~/crm-draft-cleanup/cleaned.json for rollback.

RUN ON THE VM (needs docker + outbound Gmail API):
  python3 cleanup_draft_messages.py                 # dry-run (default): list only
  python3 cleanup_draft_messages.py --apply         # actually soft-delete
  python3 cleanup_draft_messages.py --apply --since-days 3   # recent msgs only (timer mode)
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

DB_CONTAINER = "twenty-db-1"
SERVER_CONTAINER = "twenty-server-1"
WORKSPACE_SCHEMA = "workspace_4cukon3ltvwq3m1goqws3p4lv"
MANIFEST_DIR = os.path.expanduser("~/crm-draft-cleanup")
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_MSG_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}?format=minimal"
SLEEP_BETWEEN_CALLS = 0.05  # stay far below Gmail per-user quota


def psql(sql):
    """Run SQL in the twenty DB, return stdout (raises on error)."""
    return subprocess.run(
        ["sudo", "docker", "exec", "-i", DB_CONTAINER,
         "psql", "-U", "postgres", "-d", "default", "-v", "ON_ERROR_STOP=1", "-Atq"],
        input=sql, capture_output=True, text=True, check=True,
    ).stdout.strip()


def psql_json(sql):
    out = psql(f"SELECT COALESCE(json_agg(t), '[]') FROM ({sql}) t;")
    return json.loads(out)


def server_env(name):
    return subprocess.run(
        ["sudo", "docker", "exec", SERVER_CONTAINER, "printenv", name],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


# Twenty stores connectedAccount tokens as enc:v2:<keyId>:<base64(iv||ct||tag)>,
# AES-256-GCM under HKDF(ENCRYPTION_KEY||APP_SECRET, info='twenty:enc:v2:<workspaceId>').
# Decrypt inside the server container so the key never leaves it (node has hkdfSync).
DECRYPT_JS = """
const {hkdfSync, createDecipheriv} = require('crypto');
const ct = process.env.CT, wsid = process.env.WSID;
const raw = process.env.ENCRYPTION_KEY || process.env.APP_SECRET;
const payload = ct.slice('enc:v2:'.length).replace(/^[0-9a-f]{8}:/, '');
const buf = Buffer.from(payload, 'base64');
const iv = buf.subarray(0, 12), tag = buf.subarray(buf.length - 16);
const body = buf.subarray(12, buf.length - 16);
const key = Buffer.from(hkdfSync('sha256', Buffer.from(raw), Buffer.alloc(32),
  Buffer.from('twenty:enc:v2:' + wsid), 32));
const d = createDecipheriv('aes-256-gcm', key, iv);
d.setAuthTag(tag);
process.stdout.write(Buffer.concat([d.update(body), d.final()]).toString('utf8'));
"""


def decrypt_token(ciphertext, workspace_id):
    return subprocess.run(
        ["sudo", "docker", "exec", "-e", f"CT={ciphertext}", "-e", f"WSID={workspace_id}",
         SERVER_CONTAINER, "node", "-e", DECRYPT_JS],
        capture_output=True, text=True, check=True,
    ).stdout


def refresh_access_token(client_id, client_secret, refresh_token):
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["access_token"]


def gmail_message_status(access_token, external_id):
    """Return ('draft'|'missing'|'ok'|'error', detail)."""
    req = urllib.request.Request(
        GMAIL_MSG_URL.format(mid=urllib.parse.quote(external_id)),
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "missing", "404 not found"
        return "error", f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return "error", f"network: {e.reason}"
    if "DRAFT" in (body.get("labelIds") or []):
        return "draft", "labelIds contains DRAFT"
    return "ok", ""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="actually soft-delete ghosts (default is dry-run)")
    ap.add_argument("--since-days", type=int, default=None,
                    help="only check messages received in the last N days")
    args = ap.parse_args()

    client_id = server_env("AUTH_GOOGLE_CLIENT_ID")
    client_secret = server_env("AUTH_GOOGLE_CLIENT_SECRET")

    accounts = psql_json(f"""
        SELECT ca.id, ca.handle, ca."refreshToken", ca."workspaceId", mc.id AS channel_id
        FROM core."connectedAccount" ca
        JOIN core."messageChannel" mc ON mc."connectedAccountId" = ca.id
        WHERE ca.provider = 'google' AND ca."refreshToken" IS NOT NULL
    """)
    print(f"connected gmail accounts: {[a['handle'] for a in accounts]}")

    since_filter = ""
    if args.since_days:
        since_filter = f"AND m.\"receivedAt\" >= now() - interval '{int(args.since_days)} days'"

    ghosts = []   # {message_id, external_id, handle, subject, received_at, reason}
    errors = 0
    for acc in accounts:
        rows = psql_json(f"""
            SELECT a."messageId" AS message_id, a."messageExternalId" AS external_id,
                   m.subject, m."receivedAt" AS received_at
            FROM {WORKSPACE_SCHEMA}."messageChannelMessageAssociation" a
            JOIN {WORKSPACE_SCHEMA}.message m ON m.id = a."messageId" AND m."deletedAt" IS NULL
            WHERE a."messageChannelId" = '{acc["channel_id"]}'
              AND a.direction = 'OUTGOING' AND a."deletedAt" IS NULL
              {since_filter}
            ORDER BY m."receivedAt" DESC
        """)
        print(f"\n{acc['handle']}: {len(rows)} outgoing messages to check")
        if not rows:
            continue
        try:
            refresh_token = decrypt_token(acc["refreshToken"], acc["workspaceId"])
            token = refresh_access_token(client_id, client_secret, refresh_token)
        except Exception as e:
            print(f"  !! token decrypt/refresh failed, skipping account: {e}")
            errors += 1
            continue
        for i, row in enumerate(rows, 1):
            status, detail = gmail_message_status(token, row["external_id"])
            if status in ("draft", "missing"):
                ghosts.append({**{k: row[k] for k in
                                  ("message_id", "external_id", "subject", "received_at")},
                               "handle": acc["handle"], "reason": detail})
                print(f"  GHOST [{detail}] {row['received_at']}  {(row['subject'] or '')[:70]}")
            elif status == "error":
                errors += 1
                print(f"  !! skip [{detail}] {row['external_id']}")
            if i % 250 == 0:
                print(f"  ... {i}/{len(rows)}")
            time.sleep(SLEEP_BETWEEN_CALLS)

    print(f"\n=== {len(ghosts)} ghost(s) found, {errors} error(s)/skip(s) ===")
    if not ghosts:
        return
    if not args.apply:
        print("dry-run: nothing deleted. Re-run with --apply to soft-delete the above.")
        return

    ids = sorted({g["message_id"] for g in ghosts})
    id_list = ",".join(f"'{i}'" for i in ids)
    psql(f"""
        BEGIN;
        UPDATE {WORKSPACE_SCHEMA}."messageChannelMessageAssociation"
           SET "deletedAt" = now() WHERE "messageId" IN ({id_list}) AND "deletedAt" IS NULL;
        UPDATE {WORKSPACE_SCHEMA}."messageParticipant"
           SET "deletedAt" = now() WHERE "messageId" IN ({id_list}) AND "deletedAt" IS NULL;
        UPDATE {WORKSPACE_SCHEMA}.message
           SET "deletedAt" = now() WHERE id IN ({id_list}) AND "deletedAt" IS NULL;
        COMMIT;
    """)
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    manifest_path = os.path.join(MANIFEST_DIR, "cleaned.json")
    history = []
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            history = json.load(f)
    history.append({"ranAt": datetime.now(timezone.utc).isoformat(), "ghosts": ghosts})
    with open(manifest_path, "w") as f:
        json.dump(history, f, indent=1, default=str)
    print(f"soft-deleted {len(ids)} message(s); manifest -> {manifest_path}")


if __name__ == "__main__":
    sys.exit(main())
