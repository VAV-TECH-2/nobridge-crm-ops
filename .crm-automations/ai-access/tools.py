"""The tool registry — one definition per tool, rendered as both MCP and OpenAPI.

ONE REGISTRY, TWO PROTOCOLS. `TOOLS` is the only place a tool's name, description and JSON Schema
exist. `server.py` renders it as MCP `tools/list`; `openapi.py` renders the same list as OpenAPI 3.1
for a ChatGPT Custom GPT. Neither hand-writes a schema, so the two clients cannot drift apart — the
failure the retired ops connector had, where the stdio and cloud variants each kept their own copy.

Reads go to Postgres, writes go to the REST API. That split is the autopilot's and it is deliberate:
a read here is bulk and relational ("for every record, the last inbound mail and the next booked
meeting" is one query and hundreds of REST calls), while a write must fire Twenty's own business
logic, timeline and search indexing. db.py is read-only by construction, so a read cannot mutate
anything even by accident.

Every tool returns either a str (delivered as text) or a JSON-serialisable object. A refusal raises
ToolError, which the transports turn into an `isError` result with instructive text so the model can
self-correct instead of retrying blindly.
"""
import datetime
import json
import os
import sqlite3

import deps  # noqa: F401
import bizdays
import context
import crm
import db
import evidence
import guard
import rules
import spec
import store
import twclient as tw

# Boards in a stable order for anything that sweeps all of them.
SIDES = ["buy", "sell", "other", "fulfillment", "networking"]

# Parameters that recur. Defined once so every tool describes them the same way — an undescribed
# parameter is one a model guesses at, and selfcheck.py warns about any that slip through.
_BOARD = {"type": "string", "enum": SIDES,
          "description": "Which board the deal is on. find_record tells you."}
_RECORD = {"type": "string", "description": "The deal's id, as returned by find_record."}
_REASON = {"type": "string",
           "description": "Why, in the user's own words. Recorded in the audit trail, and it is the "
                          "only explanation anybody reading this later will have."}


class ToolError(Exception):
    """A refusal the model should read and act on, not retry."""


TOOLS = []


def tool(name, description, properties=None, required=None, readonly=True, writes=False,
         confirm=False):
    """Decorator: register a tool. `properties`/`required` are plain JSON Schema."""
    def wrap(fn):
        props = dict(properties or {})
        req = list(required or [])
        if confirm:
            props["confirm"] = {
                "type": "boolean",
                "description": "Must be true to actually apply the change. Called without it (or "
                               "with false) this returns the exact diff it would apply and changes "
                               "nothing — show that to the user, get a yes, then call again with "
                               "confirm true.",
            }
        TOOLS.append({
            "name": name,
            "description": description.strip(),
            "input_schema": {"type": "object", "properties": props, "required": req,
                             "additionalProperties": False},
            "readonly": readonly,
            "writes": writes,
            "confirm": confirm,
            "run": fn,
        })
        return fn
    return wrap


def by_name(name):
    for t in TOOLS:
        if t["name"] == name:
            return t
    return None


def tool_lines():
    """One line per tool, for the prompt renderings in context.py."""
    out = []
    for t in TOOLS:
        first = t["description"].strip().splitlines()[0]
        mark = "" if t["readonly"] else " [writes, needs confirm]"
        out.append("- `%s` — %s%s" % (t["name"], first, mark))
    return "\n".join(out)


def tool_reference():
    """The full calling reference: every tool, every parameter, generated from the registry.

    For an agent that speaks HTTP itself there is no schema to import, so the parameters have to be
    written out. Generating them from the same TOOLS list the OpenAPI document comes from is the only
    way a hand-written reference cannot go stale — which it would, on the first parameter added.
    """
    out = []
    for t in TOOLS:
        head = t["name"]
        if t["writes"]:
            head += "   [WRITES — needs confirm]"
        out.append(head)
        out.append("  " + " ".join(t["description"].split()))
        props = t["input_schema"].get("properties") or {}
        required = set(t["input_schema"].get("required") or [])
        if not props:
            out.append("  takes no arguments — send {}")
        for name in sorted(props, key=lambda n: (n not in required, n == "confirm", n)):
            spec_ = props[name]
            bits = [spec_.get("type", "any")]
            if spec_.get("enum"):
                bits.append("one of: " + " | ".join(spec_["enum"]))
            if spec_.get("items", {}).get("type"):
                bits.append("of " + spec_["items"]["type"])
            flag = "REQUIRED" if name in required else "optional"
            out.append("    %-12s (%s) %s" % (name, ", ".join(bits), flag))
            desc = " ".join((spec_.get("description") or "").split())
            if desc:
                # Wrap by hand: an agent prompt is read as plain text, not reflowed.
                line = "        "
                for word in desc.split():
                    if len(line) + len(word) > 96:
                        out.append(line)
                        line = "        "
                    line += word + " "
                out.append(line.rstrip())
        out.append("")
    return "\n".join(out).rstrip()


# ── shared helpers ─────────────────────────────────────────────────────────────────────────────

_COLS = {}


def _cols(side):
    if side not in _COLS:
        _COLS[side] = {c["name"] for c in evidence.columns(side)}
    return _COLS[side]


def _has(side, col):
    return col in _cols(side)


def _lit(s):
    return evidence.db_literal(s)


def _q(sql):
    return sql.replace("{S}", db.SCHEMA)


def side_or_die(side):
    if side not in crm.BOARDS:
        raise ToolError("%r is not a board. Use one of: %s." % (side, ", ".join(SIDES)))
    return side


def _ts(col, alias=None):
    """A timestamptz rendered the way Twenty's REST API accepts it back."""
    return 'to_char(o."%s", \'YYYY-MM-DD"T"HH24:MI:SSOF\') AS "%s"' % (col, alias or col)


def _date(col, alias=None):
    return 'to_char(o."%s", \'YYYY-MM-DD\') AS "%s"' % (col, alias or col)


def _summary_select(side):
    """A uniform projection over any board, built from the columns that board actually has.

    The boards are not congruent — fulfillment has `followUpDate` where buy has `nextActionDue`,
    networking has neither, and `lastContact` is a DATE on one board and `lastContactedAt` a
    timestamp on another. Substituting NULL for what is missing keeps one UNION query workable
    instead of five round trips.
    """
    parts = [
        "%s AS side" % _lit(side),
        "o.id",
        "o.name",
        ('o.stage::text AS stage' if _has(side, "stage") else "NULL::text AS stage"),
        'c.name AS company',
        'o."companyId" AS company_id',
        'LOWER(p."emailsPrimaryEmail") AS poc_email',
        'NULLIF(TRIM(CONCAT_WS(\' \', p."nameFirstName", p."nameLastName")), \'\') AS poc_name',
    ]
    if _has(side, "ownerId"):
        parts.append('NULLIF(TRIM(CONCAT_WS(\' \', wm."nameFirstName", wm."nameLastName")), \'\')'
                     ' AS owner')
        parts.append('LOWER(wm."userEmail") AS owner_email')
    else:
        parts += ["NULL::text AS owner", "NULL::text AS owner_email"]
    parts.append(_ts("nextActionDue", "next_action_due") if _has(side, "nextActionDue")
                 else "NULL::text AS next_action_due")
    parts.append(_date("followUpDate", "follow_up_date") if _has(side, "followUpDate")
                 else "NULL::text AS follow_up_date")
    if _has(side, "lastContactedAt"):
        parts.append(_ts("lastContactedAt", "last_contacted"))
    elif _has(side, "lastContact"):
        parts.append(_date("lastContact", "last_contacted"))
    else:
        parts.append("NULL::text AS last_contacted")
    parts.append(_ts("stageChangedAt", "stage_changed_at") if _has(side, "stageChangedAt")
                 else "NULL::text AS stage_changed_at")
    parts.append(_ts("updatedAt", "updated_at"))
    return ",\n       ".join(parts)


def _summary_from(side, where):
    join_owner = ('LEFT JOIN "{S}"."workspaceMember" wm ON wm.id = o."ownerId"'
                  if _has(side, "ownerId") else "")
    return _q("""
      SELECT %s
      FROM "{S}"."%s" o
      LEFT JOIN "{S}".company c ON c.id = o."companyId"
      LEFT JOIN "{S}".person p  ON p.id = o."pointOfContactId"
      %s
      WHERE o."deletedAt" IS NULL AND (%s)
    """ % (_summary_select(side), crm.BOARDS[side]["table"], join_owner, where))


def _sweep(where_for_side, sides=None):
    """UNION ALL the uniform projection across boards. `where_for_side` is a callable."""
    sides = sides or SIDES
    return db.rows(" UNION ALL ".join(_summary_from(s, where_for_side(s)) for s in sides))


def _scope(p, sides=None):
    """Narrow a sweep to the boards this token holds."""
    sides = sides or SIDES
    if p and p.get("boards"):
        sides = [s for s in sides if s in p["boards"]]
        if not sides:
            raise ToolError("this token is scoped to %s, which excludes every board asked for"
                            % ", ".join(p["boards"]))
    return sides


def _stage_label(side, stage_enum):
    pipe = crm.BOARDS[side]["pipeline"]
    if not pipe or not stage_enum:
        return None
    for n in spec.stage_names(pipe):
        if spec.enum_value(n) == stage_enum:
            return n
    return None


def _days_since(iso):
    dt = bizdays.parse_dt(iso)
    if not dt:
        return None
    return (bizdays.now() - dt).days


# ── autopilot history (read-only) ──────────────────────────────────────────────────────────────

def _ap(sql, args=()):
    """Read the autopilot's audit DB read-only. Absent DB is not an error — it means the automation
    is not deployed here, and a missing history must never fail a read."""
    path = store.DB_PATH
    if not os.path.exists(path):
        return []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=6)
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute(sql, args).fetchall()]
        con.close()
        return rows
    except sqlite3.OperationalError:
        return []


def _history(record_id, limit=5):
    dec = _ap("SELECT d.id, d.run_id, d.created_at, d.stage_before, d.stage_after, d.confidence,"
              " d.reason, d.needs_human, d.applied, r.dry_run"
              " FROM decisions d JOIN runs r ON r.id = d.run_id"
              " WHERE d.record_id = ? ORDER BY d.id DESC LIMIT ?", (record_id, limit))
    writes = _ap("SELECT run_id, field, old_value, new_value, source, created_at, reverted_at"
                 " FROM field_writes WHERE record_id = ? ORDER BY id DESC LIMIT 20", (record_id,))
    return {"decisions": [d for d in dec if not d.get("dry_run")], "field_writes": writes}


# ══ READ TOOLS ═════════════════════════════════════════════════════════════════════════════════

@tool("crm_context",
      """Read the CRM's operating manual: how the boards work, every field and its meaning, the
      workflow stage by stage, the 12 chase ladders, and the surprises worth knowing before you
      trust a field. Call with no arguments for the index of sections. Read this before answering
      anything about how the pipeline is supposed to work.""",
      {"section": {"type": "string",
                   "description": "Section key from the index, e.g. overview, boards, gotchas, "
                                  "recipes, schema:buy, workflow:sell, loops. Omit for the index."}})
def crm_context(args, p):
    return context.render(args.get("section"))


@tool("find_record",
      """Find deals, by anything you know: company name, person name, email address or domain.
      Always call this before creating anything — duplicate companies are the most common damage.
      Returns one row per matching deal, across every board.""",
      {"query": {"type": "string",
                 "description": "Company name, person name, email address or domain. Partial is "
                                "fine; matching is case-insensitive and substring."},
       "board": {"type": "string", "enum": SIDES,
                 "description": "Restrict to one board. Omit to search all five."},
       "limit": {"type": "integer", "description": "Max rows (default 25, max 100)."}},
      required=["query"])
def find_record(args, p):
    q = (args.get("query") or "").strip()
    if len(q) < 2:
        raise ToolError("give me at least two characters to search for")
    limit = max(1, min(int(args.get("limit") or 25), 100))
    sides = _scope(p, [side_or_die(args["board"])] if args.get("board") else None)
    pat = _lit("%" + q.lower() + "%")

    def where(_side):
        return ("LOWER(o.name) LIKE {pat} OR LOWER(c.name) LIKE {pat}"
                " OR LOWER(c.\"domainNamePrimaryLinkUrl\") LIKE {pat}"
                " OR LOWER(p.\"emailsPrimaryEmail\") LIKE {pat}"
                " OR LOWER(CONCAT_WS(' ', p.\"nameFirstName\", p.\"nameLastName\")) LIKE {pat}"
                ).replace("{pat}", pat)

    rows = _sweep(where, sides)
    multi = evidence.company_boards()
    out = []
    for r in rows[:limit]:
        r["stage_label"] = _stage_label(r["side"], r.get("stage"))
        if not r.get("stage"):
            r["stage_note"] = ("this record has NO stage — it is unplaced and does not appear on "
                               "the kanban")
        other = multi.get(r.get("company_id"))
        if other and len(other) > 1:
            r["also_on_boards"] = other
            r["ambiguity_note"] = ("this company has deals on %s — email and meetings cannot be "
                                   "attributed to one of them from the mail alone"
                                   % ", ".join(other))
        out.append(r)
    return {"query": q, "matches": len(rows), "returned": len(out), "records": out,
            "next": "Call get_deal with board and record_id for the full picture."}


@tool("get_deal",
      """The full picture of one deal: every field, where it sits in the pipeline, how long it has
      been there, which chase ladder is running and which touch is next, what the workflow says
      happens at this stage, the last email in and out, the next booked meeting, the last call
      summary, and what the autopilot has recently changed. Use this before answering "where is this
      deal" or "what's next", and before any write.""",
      {"board": {"type": "string", "enum": SIDES, "description": "Which board the deal is on."},
       "record_id": {"type": "string", "description": "The deal's id, from find_record."},
       "company": {"type": "string",
                   "description": "Instead of board+record_id: a company name to look up. If it "
                                  "matches exactly one deal, that deal is returned; otherwise you "
                                  "get the candidates back."},
       "include_email": {"type": "boolean",
                         "description": "Include recent message subjects and extracts (default "
                                        "true)."}})
def get_deal(args, p):
    side, rid = args.get("board"), args.get("record_id")
    if not (side and rid):
        if not args.get("company"):
            raise ToolError("give me either board + record_id, or company")
        found = find_record({"query": args["company"], "limit": 10}, p)
        recs = found["records"]
        if len(recs) != 1:
            return {"ambiguous": True, "candidates": recs,
                    "note": ("%d deals match %r. Pick one and call get_deal again with its board "
                             "and record_id." % (len(recs), args["company"]))}
        side, rid = recs[0]["side"], recs[0]["id"]
    side_or_die(side)
    if p:
        from auth import check_board
        check_board(p, side)

    recs = evidence.records(side, record_id=rid)
    if not recs:
        raise ToolError("no live record %s on %s (deleted, or the id is from another board)"
                        % (rid, side))
    rec = recs[0]
    live = crm.fields(side)
    pipe = crm.BOARDS[side]["pipeline"]

    act = evidence.activity(side, rids=[rid]).get(rid) or {}
    mtg = evidence.meetings(side, rids=[rid]).get(rid) or {}
    calls = evidence.calls([rec["companyId"]]).get(rec["companyId"]) or [] \
        if rec.get("companyId") else []

    # Fields, with labels, empties dropped — an empty field is reported once, in `empty`, rather
    # than as 40 nulls the model has to read past.
    filled, empty = {}, []
    for k, v in sorted(rec.items()):
        if k in ("id",) or k.startswith("_"):
            continue
        meta = live.get(k)
        label = meta.get("label") if meta else None
        if v in (None, "", []):
            empty.append(k)
            continue
        entry = {"value": v}
        if label:
            entry["label"] = label
        if meta and meta.get("options") and isinstance(v, str):
            entry["meaning"] = (meta.get("option_labels") or {}).get(v)
        filled[k] = entry

    stage = rec.get("stage")
    where = {"board": side, "stage": stage, "stage_label": _stage_label(side, stage)}
    if pipe and stage:
        order = spec.stage_enums(pipe)
        if stage in order:
            where["position"] = "%d of %d" % (order.index(stage) + 1, len(order))
            nxt = order[order.index(stage) + 1] if order.index(stage) + 1 < len(order) else None
            where["next_stage_allowed"] = nxt
            where["also_allowed"] = "CLOSED (with a verdict)" if stage != "CLOSED" else None
    elif not stage:
        where["warning"] = ("this record has NO stage. It is unplaced, not at the first stage, and "
                            "does not appear on the kanban.")
    if not pipe:
        where["warning"] = ("the %s board has no workflow in the spec, so there are no steps, no "
                            "ladders and no stage moves for it" % side)
    if rec.get("stageChangedAt"):
        d = _days_since(rec["stageChangedAt"])
        where["days_at_stage"] = d

    # The ladder.
    loop = rules.loop_state(side, rec, act, mtg) if pipe else None
    ladder = None
    if loop:
        lp = spec.loop(loop["loop"])
        ladder = dict(loop)
        ladder["schedule"] = lp["schedule"] if lp else None
        ladder["touch"] = ("%s of %s" % ((loop["elapsed"] or 0), loop["touches"]))
        if loop["exhausted"]:
            ladder["note"] = ("this ladder has RUN OUT. The rule for that is: %s"
                              % loop["on_exhaust"])
        elif loop["stopped_by"]:
            ladder["note"] = ("this ladder has already been satisfied by %s, so no further touch is "
                              "due" % ", ".join(loop["stopped_by"]))
    elif pipe and stage:
        # No ladder is running. Say WHICH field would start each one, because "the anchor is empty"
        # is only actionable if you know what to stamp.
        cands = []
        for s in spec.steps_for_stage(pipe, _stage_label(side, stage) or ""):
            if not (s.get("loop") and s.get("anchor")):
                continue
            lp = spec.loop(s["loop"])
            anchor = s["anchor"]
            cands.append({
                "ladder": s["loop"], "name": lp["name"] if lp else None,
                "step": s["id"], "starts_when": s["trigger"],
                "anchor_field": anchor,
                "anchor_value": (rec.get(anchor) if not anchor.startswith("derived:") else None),
                "schedule": lp["schedule"] if lp else None,
            })
        if cands:
            ids = sorted({c["ladder"] for c in cands})
            ladder = {
                "none_running": True,
                "note": ("No follow-up ladder is counting. %s %s at this stage, but the field each "
                         "counts from is empty — stamp the step that sets it (stamp_step) and the "
                         "schedule starts itself."
                         % (", ".join(ids), "applies" if len(ids) == 1 else "apply")),
                "candidates": cands,
            }

    # What the rules say happens here.
    next_steps = []
    if pipe and stage:
        sname = _stage_label(side, stage)
        for s in spec.steps_for_stage(pipe, sname):
            next_steps.append({
                "step": s["id"], "name": s["name"], "when": s["trigger"], "timing": s["timing"],
                "writes": s.get("writes"), "owner": s["owner"], "done_when": s["exit"],
                "who": context._WHO.get(s.get("who"), s.get("who")),
                "stage": s["stage"],
            })

    email = None
    if args.get("include_email", True):
        msgs = evidence.threads(side, [rid], per_record=4, body_chars=400).get(rid) or []
        email = [{"at": m["at"], "direction": "out" if m["outbound"] else "in",
                  "from": m["from_handle"], "subject": m["subject"], "extract": m["body"]}
                 for m in msgs]

    contact = {
        "messages": act.get("msgs") or 0,
        "last_any": act.get("last_any"), "last_inbound": act.get("last_in"),
        "last_outbound": act.get("last_out"),
        "days_since_any": _days_since(act.get("last_any")),
    }
    if not act.get("msgs"):
        contact["note"] = ("no synced email is linked to this record. That is not proof of no "
                           "contact: calls and cold outreach through Instantly never appear here.")

    multi = evidence.company_boards().get(rec.get("companyId"))
    out = {
        "board": side, "record_id": rid, "name": rec.get("name"),
        "company": {"id": rec.get("companyId"), "name": rec.get("companyName"),
                    "client_type": rec.get("companyClientType")},
        "point_of_contact": {"email": rec.get("pocEmail"), "first": rec.get("pocFirstName"),
                             "last": rec.get("pocLastName"), "title": rec.get("pocJobTitle")},
        "where_it_is": where,
        "ladder": ladder,
        "what_should_happen_next": next_steps,
        "contact": contact,
        "meetings": {"count": mtg.get("events") or 0, "last_held": mtg.get("last_held_end"),
                     "next_booked": mtg.get("next_booked"),
                     "last_cancelled": mtg.get("last_cancelled"),
                     "latest_title": mtg.get("latest_title")},
        "calls": [{"title": c.get("title"), "at": c.get("started_at"),
                   "outcome": c.get("outcome"), "summary": (c.get("summary") or "")[:1200]}
                  for c in calls],
        "recent_email": email,
        "fields": filled,
        "empty_fields": empty,
        "automation_history": _history(rid),
    }
    if multi and len(multi) > 1:
        out["ambiguity"] = {
            "boards": multi,
            "note": ("this company has deals on %s. Email and meetings are linked to all of them "
                     "and the mail does not say which one it is about — say so rather than choosing."
                     % ", ".join(multi))}
    return out


@tool("whats_next",
      """The work queue: what is overdue, due today, due this week, and what has stalled with no
      next action at all. Optionally for one person or one board. This is the answer to "what do I
      need to do".""",
      {"owner": {"type": "string",
                 "description": "Name or email of a person. Omit for everybody."},
       "board": {"type": "string", "enum": SIDES, "description": "Restrict to one board."},
       "include_closed": {"type": "boolean",
                          "description": "Include closed deals (default false)."},
       "limit": {"type": "integer", "description": "Max rows per bucket (default 25)."}})
def whats_next(args, p):
    limit = max(1, min(int(args.get("limit") or 25), 100))
    sides = _scope(p, [side_or_die(args["board"])] if args.get("board") else None)
    owner = (args.get("owner") or "").strip().lower()

    def where(side):
        w = ["TRUE"]
        if not args.get("include_closed") and _has(side, "stage"):
            w.append("o.stage::text <> 'CLOSED'")
        if owner and _has(side, "ownerId"):
            pat = _lit("%" + owner + "%")
            w.append("(LOWER(wm.\"userEmail\") LIKE %s OR LOWER(CONCAT_WS(' ',"
                     " wm.\"nameFirstName\", wm.\"nameLastName\")) LIKE %s)" % (pat, pat))
        elif owner:
            w.append("FALSE")          # board has no owner column: it can hold nobody's work
        return " AND ".join(w)

    rows = _sweep(where, sides)
    now = bizdays.now()
    today = now.date()
    week = today + datetime.timedelta(days=7)

    buckets = {"overdue": [], "today": [], "this_week": [], "later": [], "stalled": []}
    for r in rows:
        due_raw = r.get("next_action_due") or r.get("follow_up_date")
        r["due"] = due_raw
        r["stage_label"] = _stage_label(r["side"], r.get("stage"))
        due = bizdays.parse_dt(due_raw)
        if not due:
            r["why"] = "no next action date is set"
            buckets["stalled"].append(r)
            continue
        d = due.date()
        r["days"] = (d - today).days
        if d < today:
            buckets["overdue"].append(r)
        elif d == today:
            buckets["today"].append(r)
        elif d <= week:
            buckets["this_week"].append(r)
        else:
            buckets["later"].append(r)

    for k in buckets:
        buckets[k].sort(key=lambda r: (r.get("due") or "9999"))
    counts = {k: len(v) for k, v in buckets.items()}
    return {
        "as_of": bizdays.iso(now),
        "owner": args.get("owner") or "everybody",
        "boards": sides,
        "counts": counts,
        "overdue": buckets["overdue"][:limit],
        "today": buckets["today"][:limit],
        "this_week": buckets["this_week"][:limit],
        "stalled": buckets["stalled"][:limit],
        "note": ("`stalled` is the bucket worth raising unprompted: those deals have no next action "
                 "date at all, so nothing will ever surface them. `later` is counted but not listed."),
    }


@tool("pipeline_summary",
      """How the pipeline looks right now: how many deals sit at each stage on each board, plus the
      records in a bad state — no stage at all, no next action, closed with no verdict, or no
      recorded contact for a long time.""",
      {"board": {"type": "string", "enum": SIDES, "description": "Restrict to one board."},
       "stale_days": {"type": "integer",
                      "description": "Count a deal as gone quiet after this many days without "
                                     "contact (default 30)."}})
def pipeline_summary(args, p):
    sides = _scope(p, [side_or_die(args["board"])] if args.get("board") else None)
    stale = max(1, min(int(args.get("stale_days") or 30), 365))
    rows = _sweep(lambda _s: "TRUE", sides)

    out = {"as_of": bizdays.iso(bizdays.now()), "boards": {}, "problems": {}}
    no_stage, no_action, quiet = [], [], []
    for side in sides:
        pipe = crm.BOARDS[side]["pipeline"]
        mine = [r for r in rows if r["side"] == side]
        counts = {}
        for r in mine:
            counts[r.get("stage") or "(no stage)"] = counts.get(r.get("stage") or "(no stage)", 0) + 1
        # Report in board order, not in whatever order the rows arrived.
        ordered = {}
        if pipe:
            for e in spec.stage_enums(pipe):
                ordered[e] = counts.pop(e, 0)
        for k in sorted(counts):
            ordered[k] = counts[k]
        out["boards"][side] = {"total": len(mine), "by_stage": ordered,
                               "has_workflow": bool(pipe)}
        for r in mine:
            if not r.get("stage"):
                no_stage.append(r)
            if r.get("stage") != "CLOSED" and not (r.get("next_action_due")
                                                   or r.get("follow_up_date")):
                no_action.append(r)
            d = _days_since(r.get("last_contacted"))
            if r.get("stage") != "CLOSED" and (d is None or d > stale):
                r["days_since_contact"] = d
                quiet.append(r)

    out["problems"] = {
        "no_stage": {"count": len(no_stage), "records": no_stage[:25],
                     "note": "unplaced — invisible on the kanban"},
        "no_next_action": {"count": len(no_action), "records": no_action[:25],
                           "note": "nothing will ever surface these"},
        "quiet_over_%dd" % stale: {"count": len(quiet), "records": quiet[:25],
                                   "note": ("no recorded contact. Calls nobody logged and cold "
                                            "outreach through Instantly do not appear here.")},
    }
    return out


@tool("explain_workflow",
      """What the rules say, in the pipeline's own words. Ask for a board to get its stages, a stage
      to get the steps that apply there, or a ladder id (L1-L12) to get its schedule and what
      happens when it runs out. This is generated from the same spec the automation obeys, so it is
      never out of date.""",
      {"board": {"type": "string", "enum": ["buy", "sell", "other", "fulfillment"],
                 "description": "Which pipeline. `other` follows `buy`."},
       "stage": {"type": "string",
                 "description": "A stage name or enum, e.g. 'Pitch' or 'PITCH'. Omit for the whole "
                                "board."},
       "loop": {"type": "string", "description": "A ladder id, e.g. L8. Board is then optional."}})
def explain_workflow(args, p):
    if args.get("loop"):
        lid = args["loop"].strip().upper()
        lines = context.loop_block(lid)
        anchors = []
        for pipe in ("buy", "sell", "fulfillment"):
            for s in spec.steps(pipe):
                if s.get("loop") == lid and s.get("anchor"):
                    anchors.append("- %s at %s counts from `%s`" % (pipe, s["stage"], s["anchor"]))
        if anchors:
            lines += ["**Timed from:**", ""] + anchors
        return "\n".join(lines)

    side = args.get("board")
    if not side:
        raise ToolError("tell me which board, or which ladder (L1-L12)")
    pipe = crm.BOARDS[side]["pipeline"] if side in crm.BOARDS else side
    if not pipe or pipe not in spec.pipelines():
        raise ToolError("%s has no workflow in the spec. Described pipelines: %s. (`other` follows "
                        "`buy`; `networking` has none at all.)"
                        % (side, ", ".join(spec.pipelines())))

    if not args.get("stage"):
        return context.render("workflow:" + pipe)

    want = args["stage"].strip()
    sname = None
    for n in spec.stage_names(pipe):
        if n.lower() == want.lower() or spec.enum_value(n) == spec.enum_value(want):
            sname = n
            break
    if not sname:
        raise ToolError("%r is not a stage on %s. It has: %s."
                        % (want, side, " · ".join(spec.stage_names(pipe))))

    steps = spec.steps_for_stage(pipe, sname)
    lines = ["# %s — %s" % (pipe, sname), "",
             (spec.stage_notes(pipe).get(sname) or ""), "",
             "%d step(s) apply here, including any that fire at every stage." % len(steps), ""]
    for s in steps:
        lines += context.step_block(s)
    lps = spec.loops_for_stage(pipe, sname)
    if lps:
        lines += ["## Ladders running at this stage", ""]
        for lp in lps:
            lines += context.loop_block(lp["id"])
    return "\n".join(lines)


@tool("recent_activity",
      """The evidence behind a deal: recent emails with extracts, meetings held and booked, and any
      call summaries. Use when somebody asks what actually happened, or why a deal looks stuck.""",
      {"board": _BOARD,
       "record_id": _RECORD,
       "days": {"type": "integer", "description": "How far back to look (default 60)."},
       "messages": {"type": "integer", "description": "Max messages (default 10, max 30)."}},
      required=["board", "record_id"])
def recent_activity(args, p):
    side = side_or_die(args["board"])
    if p:
        from auth import check_board
        check_board(p, side)
    rid = args["record_id"]
    n = max(1, min(int(args.get("messages") or 10), 30))
    days = max(1, min(int(args.get("days") or 60), 730))
    since = bizdays.now() - datetime.timedelta(days=days)

    recs = evidence.records(side, record_id=rid)
    if not recs:
        raise ToolError("no live record %s on %s" % (rid, side))
    rec = recs[0]
    msgs = evidence.threads(side, [rid], since=since, per_record=n, body_chars=900).get(rid) or []
    mtg = evidence.meetings(side, rids=[rid]).get(rid) or {}
    calls = evidence.calls([rec["companyId"]]).get(rec["companyId"]) or [] \
        if rec.get("companyId") else []
    return {
        "board": side, "record_id": rid, "name": rec.get("name"),
        "window_days": days,
        "email": [{"at": m["at"], "direction": "out" if m["outbound"] else "in",
                   "from": m["from_handle"], "subject": m["subject"], "extract": m["body"]}
                  for m in msgs],
        "meetings": mtg,
        "calls": [{"title": c.get("title"), "at": c.get("started_at"),
                   "outcome": c.get("outcome"), "summary": c.get("summary"),
                   "matched_by": c.get("match_method")} for c in calls],
        "note": ("Direction is derived from the sender's address (@nobridge.co = outbound), because "
                 "the message's own direction flag is wrong on about a third of messages. "
                 "Internal-only threads are excluded."),
    }


@tool("list_members",
      """Who exists in the CRM, with their email addresses. Use this before assigning an owner
      rather than guessing a name or an id.""",
      {})
def list_members(args, p):
    members = [m for m in crm.workspace_members() if m.get("id")]
    return {"members": members, "count": len(members),
            "note": "Assign by email or full name; the write tools resolve it to the right id."}


# ══ WRITE TOOLS ════════════════════════════════════════════════════════════════════════════════
# Every one of these is a two-call tool: without `confirm` it returns the diff it would apply and
# changes nothing. The confirmation belongs in the conversation, with the person, not in the CRM
# afterwards. See guard.py for the validation and the audit trail.

def _write_target(args, p):
    """Resolve board + record_id for a write, and check the token may touch that board."""
    side = side_or_die(args.get("board") or "")
    from auth import check_board
    check_board(p, side)
    rid = (args.get("record_id") or "").strip()
    if not rid:
        raise ToolError("record_id is required — get it from find_record")
    return side, guard.load(side, rid)


@tool("update_deal",
      """Change fields on a deal: the owner, when the next action is due, a date, or free-text
      commentary like "where we last left off". Refuses any field the workflow does not authorise at
      that stage. For a stage change use set_stage; for "I just sent the X" use stamp_step, which
      knows which fields that event touches.""",
      {"board": _BOARD,
       "record_id": _RECORD,
       "fields": {"type": "object", "additionalProperties": True,
                  "description": "Field API names to values, e.g. {\"owner\": \"fadil@nobridge.co\", "
                                 "\"nextActionDue\": \"2026-08-20\"}. Names, not labels — see "
                                 "crm_context schema:<board>. An owner may be an email or a full "
                                 "name."},
       "reason": _REASON},
      required=["board", "record_id", "fields"], readonly=False, writes=True, confirm=True)
def update_deal(args, p):
    side, rec = _write_target(args, p)
    fields = args.get("fields") or {}
    if not isinstance(fields, dict) or not fields:
        raise ToolError("`fields` must be an object of field names to values")
    if "stage" in fields:
        raise ToolError("stage is not set here — use set_stage, which applies the pipeline's rules "
                        "about which moves are legal")
    writes, rejects, flags = guard.plan(side, rec, fields=fields, reason=args.get("reason"))
    what = "update %s" % ", ".join(sorted(fields))
    if not args.get("confirm"):
        return guard.preview(side, rec, writes, rejects, flags, what)
    return guard.apply(side, rec, writes, rejects, flags, p, what, reason=args.get("reason"))


@tool("set_stage",
      """Move a deal to another stage. One stage forward, or straight to Closed — never backwards,
      never skipping, and never out of Closed. Closing requires a verdict in the same call.""",
      {"board": _BOARD,
       "record_id": _RECORD,
       "stage": {"type": "string", "description": "Stage name or enum, e.g. \"Negotiation\" or "
                                                  "\"NEGOTIATION\"."},
       "verdict": {"type": "string",
                   "description": "Required when moving to Closed. One of the verdicts on that "
                                  "board — see crm_context boards."},
       "reason": _REASON},
      required=["board", "record_id", "stage"], readonly=False, writes=True, confirm=True)
def set_stage(args, p):
    side, rec = _write_target(args, p)
    target = spec.enum_value(args["stage"])
    live = crm.fields(side)
    fields = {}
    if args.get("verdict"):
        vf = "finalDecision" if "finalDecision" in live else (
            "outcome" if "outcome" in live else None)
        if not vf:
            raise ToolError("%s has no verdict field, so a verdict cannot be recorded on it" % side)
        fields[vf] = args["verdict"]
    writes, rejects, flags = guard.plan(side, rec, stage=target, fields=fields,
                                        reason=args.get("reason"))
    what = "move %s -> %s" % (rec.get("stage") or "(no stage)", target)
    if not args.get("confirm"):
        return guard.preview(side, rec, writes, rejects, flags, what)
    return guard.apply(side, rec, writes, rejects, flags, p, what, reason=args.get("reason"))


@tool("stamp_step",
      """Record that a workflow step happened — "I sent the proposal", "the NDA went out", "we had
      the call". Give the step id (from explain_workflow or get_deal) and it applies exactly the
      fields that step defines: the sent-at timestamp, who owns it next, and the follow-up date
      counted from the right field. Prefer this over setting a timestamp by hand: doing it by hand
      gets the date right and the follow-up ladder wrong.""",
      {"board": _BOARD,
       "record_id": _RECORD,
       "step": {"type": "string", "description": "A step id, e.g. B62 or F20."},
       "fields": {"type": "object", "additionalProperties": True,
                  "description": "Values for anything the step leaves to judgement, and overrides "
                                 "for anything it computes."},
       "reason": _REASON},
      required=["board", "record_id", "step"], readonly=False, writes=True, confirm=True)
def stamp_step(args, p):
    side, rec = _write_target(args, p)
    pipe = crm.BOARDS[side]["pipeline"]
    if not pipe:
        raise ToolError("%s has no workflow, so it has no steps to stamp" % side)
    want = args["step"].strip().upper()
    step = None
    for s in spec.steps(pipe):
        if s["id"].upper() == want:
            step = s
            break
    if not step:
        raise ToolError("no step %r in the %s workflow. Call explain_workflow with the board and "
                        "stage to see the step ids." % (args["step"], pipe))

    stage_name = _stage_label(side, rec.get("stage"))
    if step["stage"] not in (stage_name, "Any"):
        flag_note = ("step %s belongs to stage %s but this deal is at %s"
                     % (step["id"], step["stage"], stage_name or "(no stage)"))
    else:
        flag_note = None

    fields, stage, notes = guard.resolve_sets(side, rec, step, overrides=args.get("fields") or {})
    if not fields and not stage:
        raise ToolError("step %s writes nothing that can be applied here. %s"
                        % (step["id"], " ".join(notes) or ""))
    writes, rejects, flags = guard.plan(side, rec, stage=stage, fields=fields,
                                        reason=args.get("reason"))
    flags = list(flags) + notes + ([flag_note] if flag_note else [])
    what = "stamp %s (%s)" % (step["id"], step["name"])
    extra = {"step": {"id": step["id"], "name": step["name"], "stage": step["stage"],
                      "writes_prose": step.get("writes"), "ladder": step.get("loop"),
                      "timed_from": step.get("anchor"),
                      "moves_stage_to": stage}}
    if not args.get("confirm"):
        return guard.preview(side, rec, writes, rejects, flags, what, extra=extra)
    out = guard.apply(side, rec, writes, rejects, flags, p, what, reason=args.get("reason"))
    out.update(extra)
    return out


@tool("set_verdict",
      """Record how a deal ended: won, lost, not interested, disqualified, do not contact, or a
      follow-up window. This does not close the deal on its own — use set_stage with the verdict to
      do both at once.""",
      {"board": _BOARD,
       "record_id": _RECORD,
       "verdict": {"type": "string", "description": "See crm_context boards for the list."},
       "reason": {"type": "string",
                  "description": "Required. For Do Not Contact, quote the sentence that asked for "
                                 "it — the request has consequences outside the CRM."}},
      required=["board", "record_id", "verdict", "reason"], readonly=False, writes=True,
      confirm=True)
def set_verdict(args, p):
    side, rec = _write_target(args, p)
    live = crm.fields(side)
    vf = "finalDecision" if "finalDecision" in live else ("outcome" if "outcome" in live else None)
    if not vf:
        raise ToolError("%s has no verdict field" % side)
    if not (args.get("reason") or "").strip():
        raise ToolError("a verdict needs a reason — it is the only record of why the deal ended "
                        "this way")
    writes, rejects, flags = guard.plan(side, rec, fields={vf: args["verdict"]},
                                        reason=args["reason"])
    what = "verdict %s = %s" % (vf, spec.enum_value(args["verdict"]))
    if not args.get("confirm"):
        return guard.preview(side, rec, writes, rejects, flags, what)
    return guard.apply(side, rec, writes, rejects, flags, p, what, reason=args["reason"])


@tool("log_note",
      """Add a note to a deal, and to its company and contact, so it shows up wherever somebody
      looks. Use for anything worth keeping that is not a field: what was discussed, what was
      agreed, context somebody picking this up cold would want.""",
      {"board": _BOARD,
       "record_id": _RECORD,
       "title": {"type": "string", "description": "A short subject line."},
       "body": {"type": "string", "description": "Markdown."}},
      required=["board", "record_id", "title", "body"], readonly=False, writes=True, confirm=True)
def log_note(args, p):
    side, rec = _write_target(args, p)
    targets = [(crm.BOARDS[side]["note_field"], rec["id"])]
    if rec.get("companyId"):
        targets.append(("companyId", rec["companyId"]))
    if rec.get("pointOfContactId"):
        targets.append(("personId", rec["pointOfContactId"]))
    title = (args.get("title") or "").strip()
    body = args.get("body") or ""
    if not title or not body:
        raise ToolError("a note needs both a title and a body")
    if not args.get("confirm"):
        return {"applied": False, "what": "note on %s" % rec.get("name"),
                "title": title, "body": body,
                "will_attach_to": [t[0] for t in targets],
                "confirm": "Nothing has been written. Call again with confirm true to add it."}
    note_id, linked, failed = crm.create_note(title, body, targets)
    guard.record_company_change(p, "note added", title,
                                {"company_id": rec.get("companyId"), "name": rec.get("name"),
                                 "note_id": note_id})
    return {"applied": True, "note_id": note_id, "linked_to": linked, "failed_links": failed,
             "note": ("Notes are history and are deliberately NOT undone by revert — delete it in "
                      "the CRM if it was wrong.")}


def _blocklisted(domain, email):
    """Handles on the admin's blocklist, which is the master list blocklist-guard mirrors."""
    if not (domain or email):
        return []
    want = [x.lower() for x in (domain, email) if x]
    rows = db.rows(_q("""
        SELECT LOWER(handle) AS handle FROM "{S}".blocklist
        WHERE "deletedAt" IS NULL AND handle IS NOT NULL AND handle <> ''
    """))
    hits = []
    for r in rows:
        h = r["handle"]
        for w in want:
            if h == w or (h.startswith("@") and w.endswith(h)) or w == h.lstrip("@"):
                hits.append(h)
    return sorted(set(hits))


@tool("create_company",
      """Create a company, optionally with a contact, for a lead that is not in the CRM yet. Always
      call find_record first — duplicate companies are the most common damage done here. This does
      NOT put the company on a board; call tag_company for that.""",
      {"name": {"type": "string", "description": "The company's name, as it should appear in the CRM."},
       "domain": {"type": "string", "description": "Website or email domain, e.g. acme.com."},
       "contact": {"type": "object", "additionalProperties": True,
                   "description": "Optional point of contact: {\"email\": ..., \"first_name\": ..., "
                                  "\"last_name\": ..., \"job_title\": ...}."},
       "reason": _REASON},
      required=["name"], readonly=False, writes=True, confirm=True)
def create_company(args, p):
    name = (args.get("name") or "").strip()
    if len(name) < 2:
        raise ToolError("a company needs a name")
    domain = (args.get("domain") or "").strip().lower().replace("https://", "").replace(
        "http://", "").strip("/")
    contact = args.get("contact") or {}
    email = (contact.get("email") or "").strip().lower()

    # Dedupe, loudly. This is the check whose absence produced the duplicate fulfillment records.
    pat = _lit("%" + name.lower() + "%")
    dpat = _lit("%" + domain + "%") if domain else None
    where = "LOWER(c.name) LIKE %s" % pat
    if dpat:
        where += " OR LOWER(c.\"domainNamePrimaryLinkUrl\") LIKE %s" % dpat
    existing = db.rows(_q("""
        SELECT c.id, c.name, c."domainNamePrimaryLinkUrl" AS domain,
               c."clientType"::text[] AS client_type
        FROM "{S}".company c WHERE c."deletedAt" IS NULL AND (%s) LIMIT 10
    """ % where))
    blocked = _blocklisted(domain, email)

    if not args.get("confirm"):
        return {"applied": False, "what": "create company %r" % name,
                "would_create": {"company": {"name": name, "domain": domain},
                                 "contact": contact or None},
                "possible_duplicates": existing,
                "blocklisted": blocked,
                "confirm": (("REFUSED: %s is on the blocklist. " % ", ".join(blocked)) if blocked
                            else ("Nothing has been created. %s Call again with confirm true."
                                  % ("There are possible duplicates above — check them first."
                                     if existing else ""))),
                "next": "After creating, call tag_company to put it on a board."}
    if blocked:
        raise ToolError("refusing to create %r: %s is on the CRM blocklist, which exists to keep "
                        "these records out. Nothing was created." % (name, ", ".join(blocked)))

    data = {"name": name}
    if domain:
        data["domainName"] = {"primaryLinkUrl": "https://" + domain}
    st, body = tw.rest("POST", "/companies", data)
    if st not in (200, 201):
        raise ToolError("could not create the company: %s %s" % (st, json.dumps(body)[:300]))
    company = (body.get("data") or {}).get("createCompany") or {}
    cid = company.get("id")

    person_id = None
    if email or contact.get("first_name"):
        pdata = {"companyId": cid}
        if email:
            pdata["emails"] = {"primaryEmail": email}
        nm = {}
        if contact.get("first_name"):
            nm["firstName"] = contact["first_name"]
        if contact.get("last_name"):
            nm["lastName"] = contact["last_name"]
        if nm:
            pdata["name"] = nm
        if contact.get("job_title"):
            pdata["jobTitle"] = contact["job_title"]
        pst, pbody = tw.rest("POST", "/people", pdata)
        if pst in (200, 201):
            person_id = ((pbody.get("data") or {}).get("createPerson") or {}).get("id")

    run_id = guard.record_company_change(
        p, "created company", args.get("reason"),
        {"company_id": cid, "name": name, "domain": domain, "person_id": person_id,
         "duplicates_seen": [e["name"] for e in existing]})
    return {"applied": True, "company": {"id": cid, "name": name, "domain": domain},
            "person": {"id": person_id, "email": email} if person_id else None,
            "run": run_id,
            "next": ("Nothing is on a board yet. Call tag_company with the segment for the board "
                     "this belongs on, then wait about 2 minutes."),
            "undo": ("Creating a record is NOT undone by revert — delete it in the CRM if it was "
                     "wrong.")}


@tool("tag_company",
      """Put a company onto one or more boards by setting its clientType tags. A separate automation
      then creates the deal on each board, at that board's first stage, within about 2 minutes. This
      is how a new lead enters the pipeline.""",
      {"company_id": {"type": "string", "description": "From find_record or create_company."},
       "company": {"type": "string", "description": "Or the company name, if you do not have the id."},
       "segments": {"type": "array", "items": {"type": "string"},
                    "description": "BUY_SIDE, SELL_SIDE, OTHERS, FULFILLMENT or NETWORK. These are "
                                   "ADDED to whatever is already there."},
       "reason": _REASON},
      required=["segments"], readonly=False, writes=True, confirm=True)
def tag_company(args, p):
    valid = (crm.fields_for_object("company").get("clientType") or {}).get("options") or []
    want = [spec.enum_value(s) for s in (args.get("segments") or [])]
    bad = [s for s in want if s not in valid]
    if bad:
        raise ToolError("%s is not a clientType. Valid: %s." % (", ".join(bad), ", ".join(valid)))

    cid = (args.get("company_id") or "").strip()
    if not cid:
        if not args.get("company"):
            raise ToolError("give me company_id or company")
        pat = _lit("%" + args["company"].strip().lower() + "%")
        rows = db.rows(_q("""
            SELECT c.id, c.name, c."clientType"::text[] AS client_type
            FROM "{S}".company c WHERE c."deletedAt" IS NULL AND LOWER(c.name) LIKE %s LIMIT 10
        """ % pat))
        if len(rows) != 1:
            return {"applied": False, "ambiguous": True, "candidates": rows,
                    "note": "%d companies match %r — call again with company_id."
                            % (len(rows), args["company"])}
        cid = rows[0]["id"]

    cur = db.rows(_q("""
        SELECT c.id, c.name, c."clientType"::text[] AS client_type
        FROM "{S}".company c WHERE c.id = %s AND c."deletedAt" IS NULL
    """ % _lit(cid)))
    if not cur:
        raise ToolError("no live company %s" % cid)
    have = cur[0]["client_type"] or []
    merged = sorted(set(have) | set(want))
    added = [s for s in want if s not in have]

    boards_for = {crm.BOARDS[s]["segment"]: s for s in crm.BOARDS}
    if not args.get("confirm"):
        return {"applied": False, "what": "tag %s" % cur[0]["name"],
                "company": cur[0], "tags_now": have, "tags_after": merged, "adding": added,
                "creates_deals_on": [boards_for.get(s) for s in added],
                "confirm": ("Nothing has been changed. Call again with confirm true. %s"
                            % ("Nothing to add — it already carries those tags."
                               if not added else
                               "A deal will appear on %s within about 2 minutes."
                               % ", ".join(boards_for.get(s) or s for s in added)))}
    if not added:
        return {"applied": False, "note": "%s already carries %s — nothing to do."
                                          % (cur[0]["name"], ", ".join(want))}

    st, body = tw.rest("PATCH", "/companies/" + cid, {"clientType": merged})
    if st not in (200, 201):
        raise ToolError("could not tag the company: %s %s" % (st, json.dumps(body)[:300]))
    run_id = guard.record_company_change(
        p, "tagged company", args.get("reason"),
        {"company_id": cid, "name": cur[0]["name"], "tags_before": have, "tags_after": merged,
         "added": added})
    return {"applied": True, "company": cur[0]["name"], "tags_after": merged, "added": added,
            "run": run_id,
            "creates_deals_on": [boards_for.get(s) for s in added],
            "next": ("Wait about 2 minutes for the sync, then find_record to get the new deal and "
                     "set its owner."),
            "undo": ("Removing the tag does NOT delete the deal the sync creates — that has to be "
                     "done in the CRM by hand.")}


@tool("undo",
      """Undo a change this connector made, by its run number. Reverts every field to the value it
      held before, and skips anything a person has changed since. Notes are history and are never
      undone.""",
      {"run": {"type": "integer", "description": "The run number from a write result."}},
      required=["run"], readonly=False, writes=True, confirm=True)
def undo(args, p):
    import revert
    run_id = int(args["run"])
    row = store.run(run_id)
    if not row:
        raise ToolError("no run %d in the audit trail" % run_id)
    if row["dry_run"]:
        raise ToolError("run %d was a dry run — it wrote nothing, so there is nothing to undo"
                        % run_id)
    writes = store.writes_for_run(run_id, only_unreverted=True)
    if not writes:
        raise ToolError("run %d has nothing left to undo (already reverted, or it only wrote a note)"
                        % run_id)
    plan_rows = revert.plan_revert(writes)
    preview = [{"board": w["board"], "record_id": w["record_id"], "field": w["field"],
                "now": cur, "back_to": w["old_value"], "action": action}
               for w, cur, action in plan_rows]
    if not args.get("confirm"):
        return {"applied": False, "run": run_id, "would_revert": preview,
                "confirm": "Nothing has been changed. Call again with confirm true."}

    done, skipped = 0, []
    by_record = {}
    for w, _cur, action in plan_rows:
        if action != "revert":
            skipped.append({"field": w["field"], "why": action})
            continue
        by_record.setdefault((w["board"], w["record_id"]), []).append(w)
    for (board, rid), rows_ in by_record.items():
        data = {}
        for w in rows_:
            old = w["old_value"]
            data[w["field"]] = None if old in (None, "", "None") else old
        crm.patch(board, rid, data)
        for w in rows_:
            store.mark_reverted(w["id"], guard.now_iso())
            done += 1
    return {"applied": True, "run": run_id, "reverted_fields": done, "skipped": skipped,
            "note": "Any note the run created is still there — notes are history."}
