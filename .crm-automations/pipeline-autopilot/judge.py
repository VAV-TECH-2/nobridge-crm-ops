"""Layer 3 — judgement, via Azure OpenAI gpt-5-mini. Proposes; never writes.

Everything this module returns goes through rules.validate() before it can touch a record. It has no
CRM credentials and no write path on purpose, the same separation Call Intelligence keeps for its
extractor (extract.ts:1-14).

THE PROMPT IS GENERATED FROM workflow_spec.py AT REQUEST TIME. That is the whole point: the rules the
model reasons with are the same rules WORKFLOWS.md prints, so editing the spec changes behaviour with
no code change and there is no second copy to drift. The model is handed each step's `trigger`,
`condition`, `writes`, `exit` and `owner` prose verbatim, plus the loop parameters those steps cite.

THREE THINGS ABOUT THIS DEPLOYMENT, all learned the hard way by Call Intelligence and repeated here
rather than rediscovered (Sales Engine VM/src/callintel/extract.ts:129-191):
  * the auth header is `api-key`, NOT `Authorization: Bearer`
  * the gpt-5 family rejects `max_tokens` and `temperature` outright; it is `max_completion_tokens`
  * finish_reason == "length" is a FAILURE, not a partial answer - a truncated JSON object that
    happens to parse is the most dangerous possible result
"""
import json
import os
import subprocess
import urllib.error
import urllib.request

import bizdays
import crm
import rules
import spec

ENGINE_ENV = "/home/azureuser/sales-engine/.env"
VM = "azureuser@20.189.126.94"
TIMEOUT = int(os.environ.get("AUTOPILOT_LLM_TIMEOUT", "90"))
MAX_COMPLETION_TOKENS = int(os.environ.get("AUTOPILOT_MAX_COMPLETION_TOKENS", "8000"))

_cfg = None


def _from_engine_env(keys):
    """Read keys out of the engine .env: locally if we are on the VM, else over SSH so the key
    never lands on this disk. Same approach tw.py uses for APP_SECRET."""
    out = {}
    if os.path.exists(ENGINE_ENV):
        with open(ENGINE_ENV, encoding="utf-8") as fh:
            lines = fh.readlines()
    else:
        p = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=20", VM,
             "cat " + ENGINE_ENV],
            capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            raise RuntimeError("cannot read %s: %s" % (ENGINE_ENV, p.stderr[:200]))
        lines = p.stdout.splitlines()
    for line in lines:
        line = line.strip()
        for k in keys:
            if line.startswith(k + "="):
                v = line.split("=", 1)[1].strip()
                if v[:1] in ("'", '"') and v[-1:] == v[:1] and len(v) > 1:
                    v = v[1:-1]
                out[k] = v
    return out


def config():
    global _cfg
    if _cfg:
        return _cfg
    keys = ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT",
            "AZURE_OPENAI_API_VERSION"]
    cfg = {k: os.environ.get(k) for k in keys}
    if not (cfg["AZURE_OPENAI_ENDPOINT"] and cfg["AZURE_OPENAI_API_KEY"]):
        cfg.update({k: v for k, v in _from_engine_env(keys).items() if v})
    cfg.setdefault("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini")
    cfg["AZURE_OPENAI_DEPLOYMENT"] = cfg.get("AZURE_OPENAI_DEPLOYMENT") or "gpt-5-mini"
    cfg["AZURE_OPENAI_API_VERSION"] = cfg.get("AZURE_OPENAI_API_VERSION") or "2024-10-21"
    if not cfg["AZURE_OPENAI_ENDPOINT"] or not cfg["AZURE_OPENAI_API_KEY"]:
        raise RuntimeError("Azure OpenAI is not configured (endpoint/key missing)")
    _cfg = cfg
    return _cfg


def _url():
    c = config()
    endpoint = c["AZURE_OPENAI_ENDPOINT"].strip().strip('"\'').rstrip("/")
    return ("%s/openai/deployments/%s/chat/completions?api-version=%s"
            % (endpoint, c["AZURE_OPENAI_DEPLOYMENT"], c["AZURE_OPENAI_API_VERSION"]))


# ── the response contract ──────────────────────────────────────────────────────────────────────
# Azure strict json_schema requires every property to appear in `required` and
# additionalProperties:false everywhere. Optionality is expressed with a null type, not by omission.
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["stage_decision", "field_updates", "active_loop", "note", "next_steps",
                 "needs_human", "human_reason", "board_attribution"],
    "properties": {
        "stage_decision": {
            "type": "object", "additionalProperties": False,
            "required": ["move", "to", "reason", "confidence"],
            "properties": {
                "move": {"type": "boolean"},
                "to": {"type": ["string", "null"],
                       "description": "the exact stage option value, or null when not moving"},
                "reason": {"type": "string"},
                "confidence": {"type": "number"},
            },
        },
        "field_updates": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["field", "value", "reason", "confidence", "quote"],
                "properties": {
                    "field": {"type": "string"},
                    "value": {"type": ["string", "null"]},
                    "reason": {"type": "string"},
                    "confidence": {"type": "number"},
                    "quote": {"type": ["string", "null"],
                              "description": "the sentence that justifies this, required for "
                                             "Do Not Contact"},
                },
            },
        },
        "active_loop": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "reason"],
            "properties": {"id": {"type": ["string", "null"]}, "reason": {"type": "string"}},
        },
        "note": {
            "type": "object", "additionalProperties": False,
            "required": ["should_write", "title", "markdown"],
            "properties": {
                "should_write": {"type": "boolean"},
                "title": {"type": "string"},
                "markdown": {"type": "string"},
            },
        },
        "next_steps": {"type": "string",
                       "description": "one or two sentences: where this deal was left"},
        "needs_human": {"type": "boolean"},
        "human_reason": {"type": "string"},
        "board_attribution": {
            "type": "string",
            "enum": ["buy", "sell", "other", "fulfillment", "networking",
                     "ambiguous"],
        },
    },
}


# ── prompt assembly, entirely from the spec ────────────────────────────────────────────────────

def _rules_text(side, record):
    pipe = crm.BOARDS[side]["pipeline"]
    if not pipe:
        return ("This board has no pipeline in the workflow spec. Do NOT propose a stage move or a "
                "verdict. You may only summarise what happened and suggest next steps.")
    stage = record.get("stage")
    stage_name = rules._stage_name(pipe, stage) if stage else None
    p = spec.pipeline(pipe)
    lines = ["PIPELINE: %s — %s" % (p["title"], p["intro"]),
             "BUSINESS HOURS: %s Asia/Jakarta, Mon-Fri." % p["hours"], "",
             "STAGES, in order (a move may go one forward, or straight to Closed):"]
    for i, (name, note, _new) in enumerate(p["stages"], start=1):
        mark = "  <-- the record is here" if name == stage_name else ""
        lines.append("  %d. %-18s %s = %s%s" % (i, spec.enum_value(name), name, note, mark))

    # A record with NO stage is a different question from a record that might move. It is not
    # "should this advance?" but "where does this belong?" - and with no current stage there is no
    # stage whose rules to quote, so without this the model saw no rules at all and declined to act.
    if not stage_name:
        lines += ["",
                  "*** THIS RECORD HAS NO STAGE AT ALL. That is invalid - it does not appear on the "
                  "board and nobody can work it. Your job here is to PLACE it, not to advance it: "
                  "set stage_decision.move = true and choose the stage whose description best "
                  "matches what the evidence shows has already happened. If outreach has gone out "
                  "and nobody has replied, that is the first stage. If they have replied, it is "
                  "further along. Any stage is available to you. Only set move = false if there is "
                  "genuinely no evidence at all to place it by. ***"]

    steps = spec.steps_for_stage(pipe, stage_name) if stage_name else spec.steps(pipe)
    lines += ["", "THE RULES THAT APPLY AT %s (verbatim from the workflow spec):"
              % (stage_name or "EVERY stage, since this record has none")]
    for st in steps:
        lines.append("  [%s] %s%s" % (st["id"], st["name"],
                                      "  (loop %s)" % st["loop"] if st["loop"] else ""))
        lines.append("      trigger:   %s" % st["trigger"])
        if st["condition"] != "—":
            lines.append("      condition: %s" % st["condition"])
        lines.append("      writes:    %s" % st["writes"])
        lines.append("      owner:     %s   exit: %s" % (st["owner"], st["exit"]))
        if st.get("note"):
            lines.append("      note:      %s" % st["note"])

    loops = spec.loops_for_stage(pipe, stage_name) if stage_name else []
    if loops:
        lines += ["", "THE LOOPS THOSE RULES CITE:"]
        for lp in loops:
            lines.append("  %s %s — %d touches on %s"
                         % (lp["id"], lp["name"], len(lp["at"]), lp["schedule"]))
            lines.append("      entry: %s" % lp["entry"])
            lines.append("      exit:  %s" % lp["exit"])
            lines.append("      when it runs out: %s" % lp["on_exhaust"])
    return "\n".join(lines)


def _writable_text(side, record):
    allow = rules.allowed_fields(side, record)
    live = crm.fields(side)
    if not allow:
        return "WRITABLE FIELDS: none at this stage. Propose no field_updates."
    out = ["WRITABLE FIELDS at this stage (anything else is refused):"]
    for field, vspec in sorted(allow.items()):
        meta = live.get(field)
        if not meta or field == "stage":
            continue
        kind, _p = spec.value_spec(vspec)
        if kind in ("now", "loop_next", "offset"):
            continue        # computed deterministically; the model must not supply these
        t = meta["type"]
        detail = ("one of: " + " ".join(meta["options"])) if meta["options"] else t
        out.append("  %-18s %-10s %s" % (field, t, detail))
    return "\n".join(out)


def _evidence_text(item):
    rec = item["record"]
    lines = []
    a = item["activity"] or {}
    lines.append("ACTIVITY TOTALS: %s messages (%s from them, %s from us) across %s threads."
                 % (a.get("msgs", 0), a.get("in_msgs", 0), a.get("out_msgs", 0),
                    a.get("threads", 0)))
    if a.get("last_in"):
        lines.append("  last inbound:  %s" % a["last_in"][:16])
    if a.get("last_out"):
        lines.append("  last outbound: %s" % a["last_out"][:16])
    m = item["meetings"] or {}
    if m:
        lines.append("MEETINGS: %s total. last held ended %s · next booked %s · last cancelled %s"
                     % (m.get("events", 0), (m.get("last_held_end") or "-")[:16],
                        (m.get("next_booked") or "-")[:16], (m.get("last_cancelled") or "-")[:16]))
        if m.get("latest_title"):
            lines.append("  most recent event title: %s" % m["latest_title"])
    lp = item["loop"]
    if lp:
        lines.append("LOOP STATE (computed, trust this over your own arithmetic): %s %s, touch %s "
                     "of %s, next due %s%s"
                     % (lp["loop"], lp["loop_name"], lp["elapsed"], lp["touches"],
                        (lp["next_due"] or "-")[:16],
                        ", EXHAUSTED" if lp["exhausted"] else ""))
    if item["calls"]:
        lines.append("CALL INTELLIGENCE (already extracted from the Meet notes):")
        for c in item["calls"]:
            lines.append("  %s · outcome %s · %s"
                         % ((c.get("started_at") or "")[:16], c.get("outcome"),
                            (c.get("summary") or "")[:400]))
    if item["threads"]:
        lines.append("")
        lines.append("THE MAIL, newest first:")
        for msg in item["threads"]:
            lines.append("  --- %s · %s · from %s"
                         % (msg["at"][:16], "WE SENT" if msg["outbound"] else "THEY SENT",
                            msg["from_handle"]))
            lines.append("      subject: %s" % (msg["subject"] or "(none)"))
            body = (msg["body"] or "").strip()
            if body:
                lines.append("      %s" % body[:900])
    return "\n".join(lines)


def _record_text(side, record):
    live = crm.fields(side)
    interesting = [f for f in live
                   if record.get(f) not in (None, "")
                   and f not in ("id", "companyId", "pointOfContactId", "searchVector")]
    lines = ["THE RECORD: %s (company: %s)" % (record.get("name"), record.get("companyName"))]
    poc = " ".join(x for x in (record.get("pocFirstName"), record.get("pocLastName")) if x)
    if poc:
        lines.append("  point of contact: %s <%s> %s"
                     % (poc, record.get("pocEmail") or "?", record.get("pocJobTitle") or ""))
    lines.append("  CURRENT VALUES:")
    for f in sorted(interesting):
        lines.append("    %-20s %s" % (f, str(record.get(f))[:120]))
    return "\n".join(lines)


SYSTEM = """You keep a private-equity advisory firm's CRM truthful.

You are given one deal record, the rules that govern its current stage (taken verbatim from the
firm's workflow specification), and the email, meetings and call notes that have happened. You decide
what the record should now say.

HOW TO DECIDE
- Work only from the evidence shown. If the evidence does not support a change, do not propose one.
- A record with NO stage is the one case where you should move it without a promote trigger: it is
  being placed, not advanced, and leaving it stage-less leaves it invisible on the board.
- Otherwise a stage move needs the trigger of a promote rule to have actually happened. "They replied warmly"
  is not a booked meeting; a recap being sent is not agreement. Read the triggers literally.
- Prefer no move over a wrong move. Set needs_human when the evidence is genuinely unclear.
- confidence is your honest probability that a reviewer who read the same mail would agree. A stage
  move below 0.75 and a field below 0.60 will be discarded, so do not inflate.
- Never propose a value for a timestamp the system computes (anything "= now" or "the next touch").
- Do Not Contact requires an explicit request never to be contacted again, and you must put the
  exact sentence in `quote`. Irritation is not a do-not-contact.
- IF YOU MOVE A DEAL TO Closed YOU MUST ALSO SET ITS VERDICT in field_updates, in the same answer -
  finalDecision on the buy, sell and other boards, outcome on fulfillment. A deal at Closed with no
  verdict reads as finished with no record of how, and the move will be refused without one.
- next_steps is for the "Where we last left off" field: one or two plain sentences of where things
  stand, written for a colleague picking this up cold.
- Write a note only when something happened that a person reading this record later would need: a
  decision, a change of position, a commitment with a date. Not a summary of routine back-and-forth.
- board_attribution: which BOARD this exchange concerns - one of buy, sell, other,
  fulfillment, networking, ambiguous. Not the company name. If the company sits on several boards
  and the mail does not make clear which one it is about, answer "ambiguous" and set needs_human.

You are proposing, not writing. A validator will reject anything outside the rules."""


def build_messages(side, record, item, ambiguous_boards=None):
    parts = [_rules_text(side, record), "", _writable_text(side, record), "",
             _record_text(side, record), "", _evidence_text(item)]
    if ambiguous_boards:
        parts += ["", ("WARNING: this company also has records on: %s. The same email is attributed "
                       "to all of them. If you cannot tell from the mail which board this concerns, "
                       "set board_attribution to \"ambiguous\" and needs_human to true, and propose "
                       "no stage move." % ", ".join(ambiguous_boards))]
    parts += ["", "Today is %s (Asia/Jakarta)." % bizdays.now().strftime("%Y-%m-%d %H:%M %A")]
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "\n".join(parts)}]


def call(messages, retries=3):
    body = {
        "messages": messages,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "pipeline_decision", "strict": True,
                                            "schema": SCHEMA}},
        # gpt-5 rejects max_tokens and temperature; neither appears here on purpose.
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
    }
    c = config()
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(
            _url(), data=json.dumps(body).encode(), method="POST",
            headers={"api-key": c["AZURE_OPENAI_API_KEY"], "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                payload = json.loads(r.read().decode())
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:400]
            last = "HTTP %s: %s" % (e.code, detail)
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                import time
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError(last)
        except Exception as e:                                  # noqa: BLE001
            last = repr(e)
            if attempt < retries - 1:
                import time
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(last)
    else:
        raise RuntimeError(last or "no response")

    choice = (payload.get("choices") or [{}])[0]
    if choice.get("finish_reason") == "length":
        # A truncated object that still parses is worse than an error, because it looks like an
        # answer. Call Intelligence treats this the same way (extract.ts:217-219).
        raise RuntimeError("response truncated (finish_reason=length); raise "
                           "AUTOPILOT_MAX_COMPLETION_TOKENS or trim the evidence")
    content = (choice.get("message") or {}).get("content")
    if not content:
        raise RuntimeError("empty response: %s" % json.dumps(payload)[:400])
    out = json.loads(content)
    usage = payload.get("usage") or {}
    out["_usage"] = {"prompt": usage.get("prompt_tokens"),
                     "completion": usage.get("completion_tokens")}
    return out


def judge(side, record, item, ambiguous_boards=None):
    """Propose changes for one record. Raises on transport or contract failure."""
    prop = call(build_messages(side, record, item, ambiguous_boards))
    # next_steps is prose the model owns; route it into the field the board uses for it. `nextSteps`
    # is labelled "Where we last left off" - history, not the plan - which is exactly what this is.
    text = (prop.get("next_steps") or "").strip()
    if text and "nextSteps" in crm.fields(side):
        prop.setdefault("field_updates", []).append(
            {"field": "nextSteps", "value": text[:800],
             "reason": "where the deal was left, from the latest exchange",
             "confidence": 0.8, "quote": None})
    if (prop.get("board_attribution") or "").lower() == "ambiguous":
        prop["needs_human"] = True
        sd = prop.get("stage_decision") or {}
        if sd.get("move"):
            sd["move"] = False
            sd["reason"] = ("refused: which board this exchange concerns is ambiguous. "
                            + (sd.get("reason") or ""))
    return prop


if __name__ == "__main__":
    import argparse

    import evidence
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default="buy")
    ap.add_argument("--record")
    ap.add_argument("--show-prompt", action="store_true")
    a = ap.parse_args()
    c = config()
    print("endpoint: %s | deployment: %s | api-version: %s"
          % (c["AZURE_OPENAI_ENDPOINT"], c["AZURE_OPENAI_DEPLOYMENT"],
             c["AZURE_OPENAI_API_VERSION"]))
    recs = evidence.records(a.board, record_id=a.record)
    act = evidence.activity(a.board)
    mtg = evidence.meetings(a.board)
    # pick the record with the most recent inbound mail - the most interesting one to judge
    recs = [r for r in recs if (act.get(r["id"]) or {}).get("last_in")]
    recs.sort(key=lambda r: act[r["id"]]["last_in"], reverse=True)
    if not recs:
        raise SystemExit("no record with inbound mail on %s" % a.board)
    rec = recs[0]
    rid = rec["id"]
    item = {"record": rec, "activity": act.get(rid), "meetings": mtg.get(rid),
            "new": None, "threads": evidence.threads(a.board, [rid]).get(rid, []),
            "calls": [], "loop": rules.loop_state(a.board, rec, act.get(rid), mtg.get(rid))}
    msgs = build_messages(a.board, rec, item)
    if a.show_prompt:
        print("\n===== PROMPT =====\n" + msgs[1]["content"])
    print("\n===== %s / %s =====" % (a.board, rec["name"]))
    print(json.dumps(judge(a.board, rec, item), indent=2)[:3000])
