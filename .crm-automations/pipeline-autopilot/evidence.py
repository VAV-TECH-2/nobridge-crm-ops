"""Layer 1 — what happened, gathered from the CRM's own synced data. Reads only.

Three sources, all already in the building:
  email     workspace message / messageParticipant / messageThread, populated by Twenty's Gmail
            sync every ~60s for vilca@, fadil@ and fachri@
  calendar  workspace calendarEvent / calendarEventParticipant
  calls     engine.db call_summaries, opened READ-ONLY — Call Intelligence has already read the
            Gemini notes and extracted a summary, an outcome and decisions. Never re-read Meet.

DIRECTION COMES FROM THE `from` PARTICIPANT, NOT FROM messageChannelMessageAssociation.direction.
That column looks authoritative and is not: 2,229 of 6,860 live messages carry BOTH directions,
because a message sent by one staff member and copied to another is OUTGOING in the sender's channel
and INCOMING in the recipient's. Whether the `from` handle is @nobridge.co is unambiguous.

ATTRIBUTION, and its hazard. A record's counterparties are its point of contact plus anyone else at
the same company - the join the two incumbent 06:30 SQL jobs already use. That is right for "last
contacted" and dangerous for a stage move, because a company tagged onto three boards attributes the
same email to all three records. So `company_boards()` reports which companies are multi-board, and
the caller must treat those records as ambiguous unless something else disambiguates.
"""
import os
import sqlite3

import bizdays
import crm
import db

STAFF_DOMAIN = "@nobridge.co"
ENGINE_DB = os.environ.get("AUTOPILOT_ENGINE_DB",
                           "/home/azureuser/sales-engine/data/engine.db")

# Columns present on every object that carry no business meaning; never fetched.
_SYSTEM_COLS = {
    "createdBySource", "createdByWorkspaceMemberId", "createdByName", "createdByContext",
    "updatedBySource", "updatedByWorkspaceMemberId", "updatedByName", "updatedByContext",
    "position", "searchVector", "deletedAt",
}


def _q(sql):
    return sql.replace("{S}", db.SCHEMA)


# ── the record set ─────────────────────────────────────────────────────────────────────────────

def columns(side):
    """Live, non-system columns on a board, straight from information_schema."""
    table = crm.BOARDS[side]["table"]
    rows = db.rows(_q("""
        SELECT column_name AS name, data_type AS type
        FROM information_schema.columns
        WHERE table_schema = '{S}' AND table_name = %s AND is_generated = 'NEVER'
        ORDER BY ordinal_position
    """) % db_literal(table))
    return [r for r in rows if r["name"] not in _SYSTEM_COLS]


def db_literal(s):
    return "'" + str(s).replace("'", "''") + "'"


def records(side, record_id=None):
    """Every live record on a board, with all of its business columns.

    Enum columns are cast to text so json_agg gives plain strings rather than the per-table enum
    type, which is how the same value ends up spelled differently between boards.
    """
    table = crm.BOARDS[side]["table"]
    cols = columns(side)
    sel = []
    for c in cols:
        if c["type"] == "USER-DEFINED":
            sel.append('o."%s"::text AS "%s"' % (c["name"], c["name"]))
        elif c["type"] == "date":
            # A DATE must come back as YYYY-MM-DD. Rendering it with a time component makes every
            # fulfillment record's lastContact look changed against what the 06:35 job wrote, which
            # would have produced ~300 pointless writes on the first run.
            sel.append('to_char(o."%s", \'YYYY-MM-DD\') AS "%s"' % (c["name"], c["name"]))
        elif c["type"] == "timestamp with time zone":
            sel.append('to_char(o."%s", \'YYYY-MM-DD"T"HH24:MI:SSOF\') AS "%s"'
                       % (c["name"], c["name"]))
        else:
            sel.append('o."%s"' % c["name"])
    where = 'o."deletedAt" IS NULL'
    if record_id:
        where += " AND o.id = %s" % db_literal(record_id)
    # person.name is a composite field: Twenty stores it as nameFirstName / nameLastName, there is
    # no `name` column to select or dereference.
    return db.rows(_q("""
        SELECT %s,
               c.name AS "companyName",
               c."clientType"::text[] AS "companyClientType",
               LOWER(poc."emailsPrimaryEmail") AS "pocEmail",
               poc."nameFirstName" AS "pocFirstName",
               poc."nameLastName"  AS "pocLastName",
               poc."jobTitle"      AS "pocJobTitle"
        FROM "{S}"."%s" o
        LEFT JOIN "{S}".company c ON c.id = o."companyId"
        LEFT JOIN "{S}".person poc ON poc.id = o."pointOfContactId"
        WHERE %s
        ORDER BY o.name
    """) % (",\n               ".join(sel), table, where))


def company_boards():
    """{companyId: [side, ...]} for every company carrying records on more than one board.

    This is the ambiguity map. An email to a company on both the buy and fulfillment boards is
    evidence about one of them, and nothing in the mail says which.
    """
    unions = " UNION ALL ".join(
        'SELECT "companyId" AS cid, %s AS side FROM "{S}"."%s" WHERE "deletedAt" IS NULL '
        'AND "companyId" IS NOT NULL' % (db_literal(side), b["table"])
        for side, b in crm.BOARDS.items())
    rows = db.rows(_q("""
        SELECT cid, array_agg(DISTINCT side ORDER BY side) AS sides, count(*) AS n
        FROM (%s) u
        GROUP BY cid
        HAVING count(DISTINCT side) > 1
    """) % _q(unions))
    return {r["cid"]: r["sides"] for r in rows}


# ── email ──────────────────────────────────────────────────────────────────────────────────────

# record -> person, then person -> messages. Joining on messageParticipant.personId first (11,804
# rows carry it) and falling back to a lowercased handle match, which is all the incumbent jobs do.
_RP = """
    rp AS (
      SELECT DISTINCT o.id AS rid, p.id AS pid, LOWER(p."emailsPrimaryEmail") AS email
      FROM "{S}"."%(table)s" o
      JOIN "{S}".person p
        ON (p.id = o."pointOfContactId" OR p."companyId" = o."companyId")
      WHERE o."deletedAt" IS NULL AND p."deletedAt" IS NULL
        AND (p."emailsPrimaryEmail" IS NOT NULL OR p.id IS NOT NULL)
        %(rid_filter)s
    ),
    msg AS (
      SELECT m.id, m."messageThreadId" AS tid, m.subject, m."receivedAt", m.text,
             (SELECT LOWER(mp2.handle) FROM "{S}"."messageParticipant" mp2
               WHERE mp2."messageId" = m.id AND mp2.role::text ILIKE 'from' LIMIT 1) AS from_handle
      FROM "{S}".message m
      WHERE m."deletedAt" IS NULL %(since_filter)s
    ),
    linked AS (
      SELECT DISTINCT rp.rid, msg.id, msg.tid, msg.subject, msg."receivedAt", msg.text,
             msg.from_handle,
             (msg.from_handle LIKE '%%%%%(staff)s') AS outbound
      FROM rp
      -- Match on EITHER the person link or the handle, not the link in preference to it. Preferring
      -- personId loses mail that the incumbent 06:30 job finds: where two Person rows share an
      -- address (this CRM has known duplicates), the participant's personId points at the other
      -- copy while the handle still matches this one. Getting that wrong regressed a record from
      -- "7 days ago" to "No contact logged".
      JOIN "{S}"."messageParticipant" mp
        ON (mp."personId" = rp.pid
            OR (rp.email IS NOT NULL AND LOWER(mp.handle) = rp.email))
      JOIN msg ON msg.id = mp."messageId"
      WHERE mp."deletedAt" IS NULL
    )
"""


def _rp_sql(side, since=None, rids=None):
    table = crm.BOARDS[side]["table"]
    since_filter = ""
    if since:
        since_filter = 'AND m."receivedAt" >= %s' % db_literal(bizdays.iso(since))
    rid_filter = ""
    if rids:
        rid_filter = "AND o.id IN (%s)" % ", ".join(db_literal(r) for r in rids)
    return _RP % {"table": table, "since_filter": since_filter, "rid_filter": rid_filter,
                  "staff": STAFF_DOMAIN}


def activity(side, since=None, rids=None):
    """{rid: {...}} email aggregates per record. `since` bounds only what counts as NEW."""
    sql = _q("WITH " + _rp_sql(side, None, rids) + """
        SELECT rid,
               count(*)                                                        AS msgs,
               count(*) FILTER (WHERE outbound)                                AS out_msgs,
               count(*) FILTER (WHERE NOT outbound)                            AS in_msgs,
               count(DISTINCT tid)                                             AS threads,
               to_char(max("receivedAt"), 'YYYY-MM-DD"T"HH24:MI:SSOF')          AS last_any,
               to_char(max("receivedAt") FILTER (WHERE outbound),
                       'YYYY-MM-DD"T"HH24:MI:SSOF')                            AS last_out,
               to_char(max("receivedAt") FILTER (WHERE NOT outbound),
                       'YYYY-MM-DD"T"HH24:MI:SSOF')                            AS last_in
        FROM linked
        GROUP BY rid
    """)
    return {r["rid"]: r for r in db.rows(sql)}


def new_activity(side, since, rids=None):
    """{rid: n} how many messages arrived since the watermark. The run's work list."""
    if not since:
        return {}
    sql = _q("WITH " + _rp_sql(side, since, rids) + """
        SELECT rid, count(*) AS n,
               count(*) FILTER (WHERE NOT outbound) AS n_in,
               count(*) FILTER (WHERE outbound)     AS n_out
        FROM linked GROUP BY rid
    """)
    return {r["rid"]: r for r in db.rows(sql)}


def threads(side, rids, since=None, per_record=6, body_chars=1200):
    """{rid: [message, ...]} the actual mail, newest first, for the judgement layer.

    Internal-only threads are dropped: a thread every participant of which is @nobridge.co is us
    talking to ourselves and is not evidence about a deal.
    """
    if not rids:
        return {}
    sql = _q("WITH " + _rp_sql(side, since, rids) + """
        , ext AS (
          SELECT DISTINCT mp."messageId"
          FROM "{S}"."messageParticipant" mp
          WHERE mp."deletedAt" IS NULL AND LOWER(mp.handle) NOT LIKE '%%""" + STAFF_DOMAIN + """'
        ),
        ranked AS (
          SELECT l.*, row_number() OVER (PARTITION BY l.rid ORDER BY l."receivedAt" DESC) AS rn
          FROM linked l
          WHERE l.id IN (SELECT "messageId" FROM ext)
        )
        SELECT rid, id, tid, subject,
               to_char("receivedAt", 'YYYY-MM-DD"T"HH24:MI:SSOF') AS at,
               outbound, from_handle,
               left(regexp_replace(COALESCE(text,''), E'[\\\\r\\\\n\\\\t]+', ' ', 'g'), %d) AS body
        FROM ranked WHERE rn <= %d
        ORDER BY rid, "receivedAt" DESC
    """ % (body_chars, per_record))
    out = {}
    for r in db.rows(sql):
        out.setdefault(r["rid"], []).append(r)
    return out


# ── calendar ───────────────────────────────────────────────────────────────────────────────────

def meetings(side, rids=None):
    """{rid: {...}} last held / next booked / last cancelled meeting per record."""
    table = crm.BOARDS[side]["table"]
    rid_filter = ""
    if rids:
        rid_filter = "AND o.id IN (%s)" % ", ".join(db_literal(r) for r in rids)
    sql = _q("""
        WITH rp AS (
          SELECT DISTINCT o.id AS rid, p.id AS pid, LOWER(p."emailsPrimaryEmail") AS email
          FROM "{S}"."%(table)s" o
          JOIN "{S}".person p
            ON (p.id = o."pointOfContactId" OR p."companyId" = o."companyId")
          WHERE o."deletedAt" IS NULL AND p."deletedAt" IS NULL %(rid_filter)s
        ),
        ev AS (
          SELECT DISTINCT rp.rid, e.id, e.title, e."startsAt", e."endsAt", e."isCanceled",
                 e."conferenceLinkPrimaryLinkUrl" AS meet_url
          FROM rp
          JOIN "{S}"."calendarEventParticipant" cep
            ON (cep."personId" = rp.pid
                OR (cep."personId" IS NULL AND rp.email IS NOT NULL
                    AND LOWER(cep.handle) = rp.email))
          JOIN "{S}"."calendarEvent" e ON e.id = cep."calendarEventId"
          WHERE cep."deletedAt" IS NULL AND e."deletedAt" IS NULL
        )
        SELECT rid,
               count(*) AS events,
               to_char(max("endsAt")   FILTER (WHERE NOT "isCanceled" AND "endsAt" <= now()),
                       'YYYY-MM-DD"T"HH24:MI:SSOF') AS last_held_end,
               to_char(min("startsAt") FILTER (WHERE NOT "isCanceled" AND "startsAt" > now()),
                       'YYYY-MM-DD"T"HH24:MI:SSOF') AS next_booked,
               to_char(max("startsAt") FILTER (WHERE "isCanceled"),
                       'YYYY-MM-DD"T"HH24:MI:SSOF') AS last_cancelled,
               (array_agg(title ORDER BY "startsAt" DESC))[1] AS latest_title
        FROM ev GROUP BY rid
    """) % {"table": table, "rid_filter": rid_filter}
    return {r["rid"]: r for r in db.rows(sql)}


# ── calls (Call Intelligence output, read-only) ────────────────────────────────────────────────

def calls(company_ids, limit_per_company=3):
    """{companyId: [call, ...]} newest first, from engine.db. Silent when not deployed."""
    if not company_ids or not os.path.exists(ENGINE_DB):
        return {}
    out = {}
    try:
        con = sqlite3.connect("file:%s?mode=ro" % ENGINE_DB, uri=True, timeout=6)
        con.row_factory = sqlite3.Row
        marks = ",".join("?" for _ in company_ids)
        rows = con.execute(
            "SELECT company_id, title, started_at, summary, outcome, decisions_json, match_method "
            "FROM call_summaries WHERE company_id IN (%s) ORDER BY started_at DESC" % marks,
            list(company_ids)).fetchall()
        con.close()
    except sqlite3.OperationalError:
        # Call Intelligence not deployed here, or its schema predates call_summaries. Its absence
        # degrades the evidence; it must never fail the run.
        return {}
    for r in rows:
        bucket = out.setdefault(r["company_id"], [])
        if len(bucket) < limit_per_company:
            bucket.append(dict(r))
    return out


if __name__ == "__main__":
    import json
    multi = company_boards()
    print("companies on more than one board: %d" % len(multi))
    for side in crm.BOARDS:
        recs = records(side)
        act = activity(side)
        mtg = meetings(side)
        with_mail = sum(1 for r in recs if act.get(r["id"], {}).get("msgs"))
        with_mtg = sum(1 for r in recs if mtg.get(r["id"], {}).get("events"))
        amb = sum(1 for r in recs if r.get("companyId") in multi)
        print("%-12s %3d records | %3d with email | %3d with meetings | %3d on a multi-board company"
              % (side, len(recs), with_mail, with_mtg, amb))
    # One record end to end.
    recs = records("buy")
    hot = sorted((r for r in recs), key=lambda r: activity("buy").get(r["id"], {}).get("msgs") or 0,
                 reverse=True)[:1]
    if hot:
        rid = hot[0]["id"]
        print("\nsample record: %s (%s)" % (hot[0]["name"], hot[0].get("stage")))
        print("  activity:", json.dumps(activity("buy", rids=[rid]).get(rid), default=str))
        print("  meetings:", json.dumps(meetings("buy", rids=[rid]).get(rid), default=str))
        th = threads("buy", [rid], per_record=3)
        for m in th.get(rid, []):
            print("  %s %-7s %-52s %s" % (m["at"][:16], "OUT" if m["outbound"] else "IN",
                                          (m["subject"] or "")[:52], (m["body"] or "")[:60]))
