#!/usr/bin/env python3
"""Blocklist guard for the Nobridge Twenty CRM. Runs ON THE VM every 2 minutes.

Twenty's native blocklist (Settings -> Accounts -> Blocklist) stops blocked
handles from syncing, but it is per-workspace-member and it never removes
Companies/People that already exist. This guard closes both gaps:

1. MIRROR - the admin's (vilca@nobridge.co) blocklist is the master list,
   edited in the CRM UI. Entries are copied to every other active workspace
   member. Rows the guard creates are tagged createdByName='blocklist-guard'
   (createdBySource='SYSTEM'); only those are removed again when a master entry
   disappears, so teammates' personal blocklist entries are never touched.

2. SWEEP - for every '@domain' entry on the master list, soft-delete matching
   companies (domainNamePrimaryLinkUrl) and people (primary/additional email),
   catching records created by any path the sync filter can't stop (sent mail,
   manual entry, imports). A record referenced by real work - any workspace
   table pointing at it other than message/calendar/timeline plumbing - is
   skipped and reported instead of deleted.

Soft-deletes are recoverable from the CRM trash; every deleted id is also
appended to swept.json next to this script (rollback manifest).
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

SCHEMA = "workspace_4cukon3ltvwq3m1goqws3p4lv"
MASTER = "3a7817ce-f274-4a2c-b2eb-a43a9506a88f"  # vilca@nobridge.co
TAG = "blocklist-guard"
MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "swept.json")
MAX_DELETES_PER_RUN = 200
PROTECTED_DOMAINS = {"nobridge.co"}  # never sweep the main domain
# Tables that reference person/company but are sync/UI plumbing, not real work.
# A reference from any OTHER table (opportunity boards, fulfillment, notes,
# tasks, ...) blocks deletion.
PLUMBING = {
    "person",
    "messageParticipant",
    "calendarEventParticipant",
    "timelineActivity",
    "favorite",
    "attachment",
}


def psql(sql):
    r = subprocess.run(
        ["docker", "exec", "-i", "twenty-db-1",
         "psql", "-U", "postgres", "-d", "default",
         "-q", "-v", "ON_ERROR_STOP=1", "-tA", "-F", "\x1f", "-f", "-"],
        input=sql, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("psql failed: %s\nSQL: %s" % (r.stderr[:800], sql[:400]))
    return [ln for ln in r.stdout.split("\n") if ln != ""]


def q(s):
    return "'" + s.replace("'", "''") + "'"


def master_handles():
    return set(psql(
        'SELECT lower(handle) FROM %s.blocklist '
        'WHERE "workspaceMemberId"=%s AND "deletedAt" IS NULL '
        'AND handle IS NOT NULL AND handle<>\'\';' % (SCHEMA, q(MASTER))))


def mirror(master):
    members = psql(
        'SELECT id FROM %s."workspaceMember" '
        'WHERE "deletedAt" IS NULL AND id<>%s;' % (SCHEMA, q(MASTER)))
    added = removed = 0
    for m in members:
        have = set(psql(
            'SELECT lower(handle) FROM %s.blocklist '
            'WHERE "workspaceMemberId"=%s AND "deletedAt" IS NULL '
            'AND handle IS NOT NULL;' % (SCHEMA, q(m))))
        missing = sorted(master - have)
        if missing:
            vals = ",".join(
                "(%s,%s,%s,'SYSTEM',%s,'SYSTEM')" % (q(h), q(m), q(TAG), q(TAG))
                for h in missing)
            psql('INSERT INTO %s.blocklist '
                 '(handle,"workspaceMemberId","createdByName","createdBySource",'
                 '"updatedByName","updatedBySource") VALUES %s;' % (SCHEMA, vals))
            added += len(missing)
        # retire guard-created rows whose handle left the master list
        not_in = ""
        if master:
            not_in = (" AND lower(handle) NOT IN (%s)"
                      % ",".join(q(h) for h in sorted(master)))
        gone = psql('UPDATE %s.blocklist SET "deletedAt"=now(), "updatedAt"=now() '
                    'WHERE "workspaceMemberId"=%s AND "deletedAt" IS NULL '
                    'AND "createdByName"=%s%s RETURNING id;'
                    % (SCHEMA, q(m), q(TAG), not_in))
        removed += len(gone)
    return len(members), added, removed


def ref_tables(col):
    """Workspace tables holding a <col> foreign key that count as real work."""
    rows = psql(
        "SELECT c.table_name || '\x1f' || "
        "  EXISTS (SELECT 1 FROM information_schema.columns d "
        "          WHERE d.table_schema=c.table_schema "
        "          AND d.table_name=c.table_name AND d.column_name='deletedAt') "
        "FROM information_schema.columns c "
        "JOIN information_schema.tables t ON t.table_schema=c.table_schema "
        "  AND t.table_name=c.table_name AND t.table_type='BASE TABLE' "
        "WHERE c.table_schema='%s' AND c.column_name='%s';" % (SCHEMA, col))
    out = []
    for row in rows:
        name, has_deleted = row.split("\x1f")
        if name not in PLUMBING:
            out.append((name, has_deleted == "t"))
    return out


def blocked_ids(candidates, col):
    """Subset of candidate ids referenced by real work via <col>."""
    if not candidates:
        return set()
    ids = ",".join(q(c) for c in candidates)
    blocked = set()
    for table, has_deleted in ref_tables(col):
        cond = ' AND "deletedAt" IS NULL' if has_deleted else ""
        hits = psql('SELECT DISTINCT "%s" FROM %s."%s" '
                    'WHERE "%s" IN (%s)%s;' % (col, SCHEMA, table, col, ids, cond))
        if hits:
            print("  blocked by %s: %d record(s)" % (table, len(hits)))
        blocked |= set(hits)
    return blocked


def load_manifest():
    if os.path.exists(MANIFEST):
        with open(MANIFEST) as f:
            return json.load(f)
    return []


def sweep(master):
    domains = sorted({h[1:] for h in master if h.startswith("@")} - PROTECTED_DOMAINS)
    if not domains:
        return 0, 0
    alt = "|".join(re.escape(d) for d in domains)
    manifest = load_manifest()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    deleted = skipped = 0

    # -- companies ---------------------------------------------------------
    rows = psql(
        'SELECT id || \'\x1f\' || name || \'\x1f\' || '
        'coalesce("domainNamePrimaryLinkUrl",\'\') FROM %s.company '
        'WHERE "deletedAt" IS NULL AND '
        'lower(coalesce("domainNamePrimaryLinkUrl",\'\')) ~ %s;'
        % (SCHEMA, q("(^|[/.])(%s)(/|$)" % alt)))
    cands = {r.split("\x1f")[0]: r for r in rows}
    blocked = blocked_ids(list(cands), "companyId")
    todel = [i for i in cands if i not in blocked][:MAX_DELETES_PER_RUN]
    if todel:
        psql('UPDATE %s.company SET "deletedAt"=now(), "updatedAt"=now() '
             'WHERE id IN (%s);' % (SCHEMA, ",".join(q(i) for i in todel)))
    for i in sorted(cands):
        _, name, dom = cands[i].split("\x1f")
        if i in blocked:
            print("  SKIP company %s (%s / %s): referenced by real work" % (i, name, dom))
            skipped += 1
        elif i in todel:
            manifest.append({"ts": now, "type": "company", "id": i,
                             "name": name, "match": dom, "action": "soft-deleted"})
            deleted += 1

    # -- people ------------------------------------------------------------
    rows = psql(
        'SELECT id || \'\x1f\' || coalesce("nameFirstName",\'\') || \' \' || '
        'coalesce("nameLastName",\'\') || \'\x1f\' || '
        'coalesce("emailsPrimaryEmail",\'\') FROM %s.person '
        'WHERE "deletedAt" IS NULL AND ('
        'lower(coalesce("emailsPrimaryEmail",\'\')) ~ %s '
        'OR lower(coalesce("emailsAdditionalEmails"::text,\'\')) ~ %s);'
        % (SCHEMA, q("@(%s)$" % alt), q('@(%s)"' % alt)))
    cands = {r.split("\x1f")[0]: r for r in rows}
    blocked = blocked_ids(list(cands), "personId")
    todel = [i for i in cands if i not in blocked][:MAX_DELETES_PER_RUN]
    if todel:
        psql('UPDATE %s.person SET "deletedAt"=now(), "updatedAt"=now() '
             'WHERE id IN (%s);' % (SCHEMA, ",".join(q(i) for i in todel)))
    for i in sorted(cands):
        _, name, email = cands[i].split("\x1f")
        if i in blocked:
            print("  SKIP person %s (%s / %s): referenced by real work" % (i, name.strip(), email))
            skipped += 1
        elif i in todel:
            manifest.append({"ts": now, "type": "person", "id": i,
                             "name": name.strip(), "match": email, "action": "soft-deleted"})
            deleted += 1

    if deleted:
        tmp = MANIFEST + ".tmp"
        with open(tmp, "w") as f:
            json.dump(manifest, f, indent=1)
        os.replace(tmp, MANIFEST)
    return deleted, skipped


def main():
    master = master_handles()
    members, added, removed = mirror(master)
    deleted, skipped = sweep(master)
    print("blocklist-guard: master=%d handles | mirrored to %d member(s) "
          "(+%d/-%d) | swept: %d deleted, %d skipped"
          % (len(master), members, added, removed, deleted, skipped))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("blocklist-guard FAILED: %s" % e, file=sys.stderr)
        sys.exit(1)
