"""aiaccess.db — per-person tokens and the request log.

Two tables and no more. Deal writes do NOT live here: they go into the autopilot's own
`autopilot.db` through its `store.py`, which is what makes `revert.py --run N --apply` undo an AI
write exactly the way it undoes an autopilot write. One audit trail, one undo tool. This file only
answers "who is allowed in" and "what did they ask".

Only the sha256 of a token is stored, so a leak of this file cannot be replayed against the CRM and
the dashboard genuinely cannot show you the secret again — which is why `tokens.py --issue` prints
it once and says so.

`args_json` holds tool arguments, and those will contain fragments of email. That makes this file
PII: it is gitignored, and the root repo is public. Do not move it, do not commit it, do not paste
it. It is capped rather than unbounded (`_ARG_CAP`) so a pasted thread cannot bloat it without limit.
"""
import hashlib
import json
import os
import secrets
import sqlite3

DB_PATH = os.environ.get(
    "AI_ACCESS_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                                 "aiaccess.db"))

# Longest tool-argument blob kept. Enough to reconstruct what was asked, short of storing a mailbox.
_ARG_CAP = 4000

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  label        TEXT,
  email        TEXT NOT NULL,
  scope        TEXT NOT NULL DEFAULT 'read',   -- read | write
  boards       TEXT,                           -- CSV of sides, or NULL for all
  token_sha256 TEXT NOT NULL UNIQUE,
  created_at   TEXT NOT NULL,
  created_by   TEXT,
  last_used_at TEXT,
  requests     INTEGER NOT NULL DEFAULT 0,
  revoked_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_tok_email ON tokens(email);

CREATE TABLE IF NOT EXISTS requests (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          TEXT NOT NULL,
  token_id    INTEGER,
  email       TEXT,
  client      TEXT,              -- mcp | openapi
  tool        TEXT NOT NULL,
  args_json   TEXT,
  ok          INTEGER NOT NULL DEFAULT 1,
  error       TEXT,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  run_id      INTEGER            -- autopilot.db runs.id when the call wrote something
);
CREATE INDEX IF NOT EXISTS idx_req_ts    ON requests(ts DESC);
CREATE INDEX IF NOT EXISTS idx_req_token ON requests(token_id);
CREATE INDEX IF NOT EXISTS idx_req_tool  ON requests(tool);
"""

_con = None


def con():
    global _con
    if _con is None:
        d = os.path.dirname(DB_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        _con = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
        _con.row_factory = sqlite3.Row
        _con.execute("PRAGMA journal_mode=WAL")
        _con.executescript(SCHEMA)
        _con.commit()
        try:
            os.chmod(DB_PATH, 0o600)
        except OSError:
            pass
    return _con


# ── tokens ─────────────────────────────────────────────────────────────────────────────────────

def new_secret():
    """64 hex characters, the same shape the retired ops connector used."""
    return secrets.token_hex(32)


def hash_token(secret):
    return hashlib.sha256(str(secret).strip().encode()).hexdigest()


def create_token(email, scope, created_at, label=None, boards=None, created_by=None, secret=None):
    """Insert a token and return (row_id, secret). The secret is returned ONCE and never stored."""
    secret = secret or new_secret()
    cur = con().execute(
        "INSERT INTO tokens (label, email, scope, boards, token_sha256, created_at, created_by)"
        " VALUES (?,?,?,?,?,?,?)",
        (label, email.strip().lower(), scope, boards, hash_token(secret), created_at, created_by))
    con().commit()
    return cur.lastrowid, secret


def active_tokens():
    return [dict(r) for r in con().execute(
        "SELECT * FROM tokens WHERE revoked_at IS NULL ORDER BY id").fetchall()]


def all_tokens():
    return [dict(r) for r in con().execute(
        "SELECT * FROM tokens ORDER BY revoked_at IS NOT NULL, id").fetchall()]


def token_row(token_id):
    r = con().execute("SELECT * FROM tokens WHERE id = ?", (token_id,)).fetchone()
    return dict(r) if r else None


def touch_token(token_id, at):
    con().execute("UPDATE tokens SET last_used_at = ?, requests = requests + 1 WHERE id = ?",
                  (at, token_id))
    con().commit()


def revoke_token(token_id, at):
    cur = con().execute("UPDATE tokens SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                        (at, token_id))
    con().commit()
    return cur.rowcount


# ── request log ────────────────────────────────────────────────────────────────────────────────

def log_request(ts, token_id, email, client, tool, args, ok, error=None, duration_ms=0,
                run_id=None):
    blob = None
    if args is not None:
        try:
            blob = json.dumps(args, default=str)[:_ARG_CAP]
        except (TypeError, ValueError):
            blob = str(args)[:_ARG_CAP]
    cur = con().execute(
        "INSERT INTO requests (ts, token_id, email, client, tool, args_json, ok, error,"
        " duration_ms, run_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (ts, token_id, email, client, tool, blob, 1 if ok else 0,
         (str(error)[:600] if error else None), int(duration_ms), run_id))
    con().commit()
    return cur.lastrowid


def recent_requests(limit=50):
    return [dict(r) for r in con().execute(
        "SELECT * FROM requests ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()]


def request_counts(since_ts):
    """{token_id: n} calls since a timestamp — what the dashboard shows per person."""
    rows = con().execute(
        "SELECT token_id, count(*) AS n FROM requests WHERE ts >= ? GROUP BY token_id",
        (since_ts,)).fetchall()
    return {r["token_id"]: r["n"] for r in rows}


def tool_counts(since_ts, limit=20):
    return [dict(r) for r in con().execute(
        "SELECT tool, count(*) AS n, sum(ok = 0) AS failed FROM requests WHERE ts >= ?"
        " GROUP BY tool ORDER BY n DESC LIMIT ?", (since_ts, int(limit))).fetchall()]


if __name__ == "__main__":
    print("db:", DB_PATH)
    print("tokens:  %d active / %d total" % (len(active_tokens()), len(all_tokens())))
    print("requests:", con().execute("SELECT count(*) FROM requests").fetchone()[0])
