"""The audit trail — every run, every decision, every field write, and the watermark.

SQLite, in the autopilot's own data dir. Three properties it exists to provide:

  REVERSIBILITY   field_writes keeps the old value of everything written, so revert.py can put a
                  run back exactly as it was. This is what makes autonomous writing acceptable.
  TRACEABILITY    every decision records the spec sha256 that produced it, the evidence it saw and
                  the model's raw reply, so "why did it do that" has an answer months later.
  IDEMPOTENCE     the watermark advances only on a clean pass, copied from Call Intelligence
                  (reconciler.ts:263-289): a failed record is never recorded, so it is retried -
                  but only while it is still inside the query window, which is why advancing past
                  an error would silently abandon it.

The dashboard opens this file READ-ONLY (mode=ro) exactly as it does engine.db.

SECOND WRITER, since 2026-08-11: the AI Access connector (.crm-automations/ai-access/) records its
writes here too, as runs with source='ai' and the asking person in `actor`. That is deliberate and it
is the whole reason `revert.py --run N --apply` undoes a chat-driven change exactly the way it undoes
an hourly one — one audit trail, one undo tool, rather than a second half-built one. WAL mode plus
the busy timeout carries the concurrency; the two writers are never both busy for long, since the
autopilot runs for minutes once an hour. `stage_moves_today` counting both is a feature: an AI move
spends that deal's daily allowance so the autopilot will not move it again an hour later.
"""
import json
import os
import sqlite3

DB_PATH = os.environ.get(
    "AUTOPILOT_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "autopilot.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at      TEXT NOT NULL,
  finished_at     TEXT,
  dry_run         INTEGER NOT NULL DEFAULT 1,
  spec_sha        TEXT,
  watermark_from  TEXT,
  watermark_to    TEXT,
  records_scanned INTEGER DEFAULT 0,
  records_changed INTEGER DEFAULT 0,
  stage_moves     INTEGER DEFAULT 0,
  fields_written  INTEGER DEFAULT 0,
  notes_written   INTEGER DEFAULT 0,
  llm_calls       INTEGER DEFAULT 0,
  needs_human     INTEGER DEFAULT 0,
  errors          INTEGER DEFAULT 0,
  aborted_reason  TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);

CREATE TABLE IF NOT EXISTS decisions (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id        INTEGER NOT NULL,
  board         TEXT NOT NULL,
  record_id     TEXT NOT NULL,
  record_name   TEXT,
  stage_before  TEXT,
  stage_after   TEXT,
  loop_id       TEXT,
  loop_touch    TEXT,
  confidence    REAL,
  reason        TEXT,
  needs_human   INTEGER DEFAULT 0,
  human_reason  TEXT,
  attribution   TEXT,
  evidence_json TEXT,
  llm_json      TEXT,
  rejects_json  TEXT,
  flags_json    TEXT,
  note_id       TEXT,
  applied       INTEGER DEFAULT 0,
  error         TEXT,
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dec_run    ON decisions(run_id);
CREATE INDEX IF NOT EXISTS idx_dec_record ON decisions(record_id);
CREATE INDEX IF NOT EXISTS idx_dec_human  ON decisions(needs_human);

CREATE TABLE IF NOT EXISTS field_writes (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id      INTEGER NOT NULL,
  decision_id INTEGER,
  board       TEXT NOT NULL,
  record_id   TEXT NOT NULL,
  field       TEXT NOT NULL,
  old_value   TEXT,
  new_value   TEXT,
  source      TEXT NOT NULL,          -- deterministic | loop | judge
  reverted_at TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fw_run    ON field_writes(run_id);
CREATE INDEX IF NOT EXISTS idx_fw_record ON field_writes(record_id);

CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""

_con = None


def con():
    global _con
    if _con is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _con = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
        _con.row_factory = sqlite3.Row
        _con.execute("PRAGMA journal_mode=WAL")
        _con.execute("PRAGMA foreign_keys=ON")
        _con.executescript(SCHEMA)
        _migrate(_con)
        _con.commit()
    return _con


# Columns added after the table already existed in production. CREATE TABLE IF NOT EXISTS will not
# add them to a live file, so they go on by ALTER, guarded by what is actually there — an unguarded
# ALTER raises "duplicate column name" on the second run and takes the autopilot down with it.
_ADDED = {
    "runs": [("source", "TEXT"),      # autopilot | ai
             ("actor", "TEXT")],      # the email of the person who asked, when source='ai'
}


def _migrate(c):
    for table, cols in _ADDED.items():
        have = {r["name"] for r in c.execute("PRAGMA table_info(%s)" % table).fetchall()}
        for name, decl in cols:
            if name not in have:
                c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, decl))


# ── watermark ──────────────────────────────────────────────────────────────────────────────────

WATERMARK = "watermark"


def get(key, default=None):
    row = con().execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    return row["v"] if row else default


def put(key, value):
    con().execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                  (key, value))
    con().commit()


# ── runs ───────────────────────────────────────────────────────────────────────────────────────

def start_run(started_at, dry_run, spec_sha, watermark_from, source="autopilot", actor=None):
    """Open a run. `source`/`actor` default to the hourly automation, so existing callers are
    unchanged; the AI Access connector passes source='ai' and the asking person's email."""
    cur = con().execute(
        "INSERT INTO runs(started_at, dry_run, spec_sha, watermark_from, source, actor)"
        " VALUES(?,?,?,?,?,?)",
        (started_at, 1 if dry_run else 0, spec_sha, watermark_from, source, actor))
    con().commit()
    return cur.lastrowid


def finish_run(run_id, finished_at, counts, watermark_to=None, aborted_reason=None):
    con().execute("""
        UPDATE runs SET finished_at=?, watermark_to=?, records_scanned=?, records_changed=?,
               stage_moves=?, fields_written=?, notes_written=?, llm_calls=?, needs_human=?,
               errors=?, aborted_reason=?
        WHERE id=?""",
        (finished_at, watermark_to, counts.get("scanned", 0), counts.get("changed", 0),
         counts.get("stage_moves", 0), counts.get("fields", 0), counts.get("notes", 0),
         counts.get("llm", 0), counts.get("human", 0), counts.get("errors", 0),
         aborted_reason, run_id))
    con().commit()


def add_decision(run_id, created_at, **kw):
    cols = ["board", "record_id", "record_name", "stage_before", "stage_after", "loop_id",
            "loop_touch", "confidence", "reason", "needs_human", "human_reason", "attribution",
            "evidence_json", "llm_json", "rejects_json", "flags_json", "note_id", "applied",
            "error"]
    vals = [kw.get(c) for c in cols]
    for i, c in enumerate(cols):
        if c.endswith("_json") and vals[i] is not None and not isinstance(vals[i], str):
            vals[i] = json.dumps(vals[i], default=str)
    cur = con().execute(
        "INSERT INTO decisions(run_id, created_at, %s) VALUES(?,?,%s)"
        % (", ".join(cols), ", ".join("?" for _ in cols)),
        [run_id, created_at] + vals)
    con().commit()
    return cur.lastrowid


def add_field_write(run_id, decision_id, created_at, board, record_id, field, old, new, source):
    con().execute("""
        INSERT INTO field_writes(run_id, decision_id, created_at, board, record_id, field,
                                 old_value, new_value, source)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (run_id, decision_id, created_at, board, record_id, field,
         None if old is None else str(old), None if new is None else str(new), source))
    con().commit()


def mark_applied(decision_id, applied=True, error=None):
    con().execute("UPDATE decisions SET applied=?, error=? WHERE id=?",
                  (1 if applied else 0, error, decision_id))
    con().commit()


# ── reads, for revert.py and the dashboard ─────────────────────────────────────────────────────

def run(run_id):
    return con().execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()


def recent_runs(limit=20):
    return con().execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def writes_for_run(run_id, only_unreverted=True):
    sql = "SELECT * FROM field_writes WHERE run_id=?"
    if only_unreverted:
        sql += " AND reverted_at IS NULL"
    return con().execute(sql + " ORDER BY id", (run_id,)).fetchall()


def writes_for_decision(decision_id, only_unreverted=True):
    sql = "SELECT * FROM field_writes WHERE decision_id=?"
    if only_unreverted:
        sql += " AND reverted_at IS NULL"
    return con().execute(sql + " ORDER BY id", (decision_id,)).fetchall()


def mark_reverted(write_id, at):
    con().execute("UPDATE field_writes SET reverted_at=? WHERE id=?", (at, write_id))
    con().commit()


def decisions_for_run(run_id):
    return con().execute("SELECT * FROM decisions WHERE run_id=? ORDER BY id",
                         (run_id,)).fetchall()


def stage_moves_today(record_id, day):
    """How many stage moves this record already had today. The one-move-per-day cap.

    A move that has since been REVERTED does not count. Otherwise undoing a bad move also spends
    the record's daily allowance, so the corrected move cannot be made until tomorrow - which is
    exactly backwards: reverting should free the record up, not lock it.
    """
    row = con().execute("""
        SELECT count(*) n FROM decisions d
        WHERE d.record_id=? AND d.stage_after IS NOT NULL AND d.applied=1
          AND substr(d.created_at,1,10)=?
          AND EXISTS (SELECT 1 FROM field_writes w
                       WHERE w.decision_id=d.id AND w.field='stage'
                         AND w.reverted_at IS NULL)""", (record_id, day)).fetchone()
    return row["n"] if row else 0


if __name__ == "__main__":
    c = con()
    print("db:", DB_PATH)
    for t in ("runs", "decisions", "field_writes", "kv"):
        n = c.execute("SELECT count(*) n FROM %s" % t).fetchone()["n"]
        print("  %-14s %d rows" % (t, n))
    print("  watermark:", get(WATERMARK) or "(never run)")
