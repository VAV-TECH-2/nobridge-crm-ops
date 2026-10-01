"""The context engine — what an AI has to know before it can read this CRM like a person.

This is the difference between a connector and a brain. Raw CRM tools were tried once and retired
(the ops MCP, 2026-08-07): they could fetch any record and set any field, and they had no idea what
a stage meant, which ladder a deal was on, or that a deal must not close without a verdict. So they
produced confident nonsense.

Everything here is GENERATED from the two live sources, never hand-maintained:

    workflow_spec.py   the pipeline ruleset — stages, 135 steps, 12 loops. The same file the
                       autopilot obeys and WORKFLOWS.md is printed from, imported through the
                       autopilot's spec.py, so this pack cannot describe rules the automation is
                       not actually following.
    /metadata          live field names, types and option labels. Not a checked-in schema, because
                       the point is to notice when the CRM and the spec disagree.

The only hand-written parts are `gotchas` and `recipes`, and both are institutional knowledge that
exists nowhere in the schema: every entry is something that has already cost somebody a day.

Two audiences, one source:
    instructions()      goes in the MCP `initialize` reply, so Claude has the orientation BEFORE it
                        calls anything.
    gpt_instructions()  a compact version to paste into a ChatGPT Custom GPT, which has no
                        equivalent channel. Hard-capped at GPT_CAP characters because the Custom GPT
                        instructions box silently truncates at 8000.
Everything else is fetched on demand by the `crm_context` tool, section by section, because the
whole pack is far larger than any sensible system prompt.

    python3 context.py            print the whole pack
    python3 context.py boards     print one section
    python3 context.py --gpt      print the ChatGPT block, with a character count on stderr
"""
import hashlib
import sys

import deps  # noqa: F401
import crm
import rules
import spec

# The Custom GPT instructions box truncates at 8000 characters. Leave headroom for the URL and any
# personal preamble the user adds on top.
GPT_CAP = 7500

# Fields present on every object that describe the row rather than the deal.
_SYSTEM_FIELDS = {
    "id", "createdAt", "updatedAt", "deletedAt", "position", "searchVector",
    "createdBy", "updatedBy", "noteTargets", "taskTargets", "timelineActivities",
    "attachments", "favorites", "messageParticipants", "calendarEventParticipants",
}

_PIPELINE_SIDES = ["buy", "sell", "other", "fulfillment", "networking"]


# ── section catalogue ──────────────────────────────────────────────────────────────────────────

def sections():
    """[(key, one-line description)] — the index `crm_context` returns when asked for nothing."""
    out = [
        ("overview", "What this CRM is, how a lead becomes a deal, and what you may change"),
        ("boards", "The five boards, their stages in board order, and which is the first stage"),
    ]
    for side in _PIPELINE_SIDES:
        out.append(("schema:" + side,
                    "Every field on the %s board: API name, label, type, option labels" % side))
    out.append(("schema:company", "The Company object, including the clientType tags"))
    out.append(("schema:person", "The Person object (note: the name is a composite)"))
    for pipe in ("buy", "sell", "fulfillment"):
        out.append(("workflow:" + pipe,
                    "The %s pipeline stage by stage: trigger, timing, what to write, who does it"
                    % pipe))
    out += [
        ("loops", "The 12 chase ladders L1-L12: touches, schedule, entry, exit, and what happens "
                  "when one runs out"),
        ("gotchas", "Things that are true but surprising. Read this before trusting a field"),
        ("recipes", "How to answer the questions people actually ask"),
    ]
    return out


def section_keys():
    return [k for k, _d in sections()]


def render(section=None):
    """One section as markdown. No argument returns the index."""
    if not section:
        return _index()
    key = section.strip()
    if key in ("all", "*"):
        return full_markdown()
    if key == "overview":
        return _overview()
    if key == "boards":
        return _boards()
    if key == "loops":
        return _loops()
    if key == "gotchas":
        return _gotchas()
    if key == "recipes":
        return _recipes()
    if key.startswith("schema:"):
        return _schema(key.split(":", 1)[1])
    if key.startswith("workflow:"):
        return _workflow(key.split(":", 1)[1])
    return ("Unknown section %r.\n\nAvailable:\n" % section
            + "\n".join("  %-22s %s" % (k, d) for k, d in sections()))


def _index():
    lines = ["# CRM context — index", "",
             "Call `crm_context` again with one of these `section` values for the detail.", ""]
    for k, d in sections():
        lines.append("- `%s` — %s" % (k, d))
    lines += ["", "Start with `overview` if you have not read it this conversation.",
              "", "Fingerprint: `%s`" % fingerprint()]
    return "\n".join(lines)


# ── overview ───────────────────────────────────────────────────────────────────────────────────

def _overview():
    return """# What this CRM is

Nobridge runs an M&A advisory pipeline in a self-hosted Twenty CRM at `app.nobridge.co`. There is
one workspace. Deals do not live in a single "Opportunities" table — they are split across **five
boards**, one per line of business, and which board a deal sits on is decided by a tag on its
**Company**.

## How a lead becomes a deal

1. A **Company** record exists (or is created).
2. Somebody sets `Company.clientType` — a multi-select — to one or more of `BUY_SIDE`, `SELL_SIDE`,
   `OTHERS`, `FULFILLMENT`, `NETWORK`.
3. A separate automation (`clienttype-sync`, a systemd timer, every 2 minutes) notices the tag and
   **creates the deal record on the matching board**, named after the company, at that board's first
   stage. It never deletes anything.

So the way to put a new lead into the pipeline is to tag its company, then wait ~2 minutes. Do not
try to create a board record directly; the sync is the thing that knows where it goes.

## What moves a deal

- **People**, in the CRM UI, by hand. Most steps in the workflow are somebody's job.
- **`pipeline-autopilot`**, hourly. It reads synced email, calendar and call notes and writes stage,
  contact dates, next owner, next action due, meeting outcome, qualified, owner and a "where we last
  left off" note. It obeys the same rules you are reading.
- **You**, through this connector, when a person tells you to.

All three write to the same records, which is why this connector refuses changes the rules do not
sanction rather than trusting the instruction blindly. Every write it makes is recorded with the old
value and can be undone.

## What you can and cannot do here

You **can**: read any record and its full history; explain where a deal is and what the workflow says
happens next; move a stage one step forward or straight to Closed; set owner, next action, dates and
free-text commentary; record a verdict; add notes; create a Company and tag it onto a board.

You **cannot**: send email (that is still a person's job — though if you also hold the user's mailbox,
you can send it there and then stamp the CRM here); skip stages or move a deal backwards; reopen a
closed deal; close a deal without a verdict; see cold outreach (the Instantly sending domains never
sync, so those ladders are timed from a field, not from observed mail).

## How to behave

- **Look before you write.** Call `get_deal` first. It returns the record, where it sits, which
  ladder it is on and what the rules say happens next.
- **Write tools do nothing until confirmed.** Called without `confirm: true` they return the exact
  diff they would apply. Show that to the user, get a yes, then call again with `confirm: true`.
- **Quote the workflow, do not invent it.** If asked what should happen next, the answer comes from
  `get_deal`'s `next_steps` or from `explain_workflow` — never from what a CRM usually does.
- **Say when a field is empty.** An unset `lastContactedAt` means nobody has recorded contact, not
  that there has been none. Absence of evidence is not evidence of absence.
"""


# ── boards ─────────────────────────────────────────────────────────────────────────────────────

def _boards():
    lines = ["# The five boards", "",
             "`side` is the name every tool takes. Stages are listed in **board order** — which is",
             "the order a deal moves through, and is NOT the order the API returns options in.", ""]
    for side in _PIPELINE_SIDES:
        b = crm.BOARDS[side]
        pipe = b["pipeline"]
        lines.append("## %s" % side)
        lines.append("")
        lines.append("- object `%s`, tagged by `Company.clientType = %s`" % (b["object"],
                                                                            b["segment"]))
        if pipe:
            names = spec.stage_names(pipe)
            enums = spec.stage_enums(pipe)
            notes = spec.stage_notes(pipe)
            if pipe != side:
                lines.append("- follows the **%s** ruleset (its stages and verdicts are identical)"
                             % pipe)
            lines.append("- first stage `%s`, last stage `%s`, %d stages"
                         % (enums[0], enums[-1], len(enums)))
            lines.append("")
            lines.append("| # | stage | enum | what it means |")
            lines.append("|---|---|---|---|")
            for i, (n, e) in enumerate(zip(names, enums), 1):
                lines.append("| %d | %s | `%s` | %s |" % (i, n, e, (notes.get(n) or "").replace(
                    "|", "\\|")))
        else:
            live = " · ".join("`%s`" % s for s in crm.stage_options(side)) or "(none)"
            lines.append("- **no pipeline in the spec.** Nothing describes how this board is worked,")
            lines.append("  so there are no steps, no ladders and no stage automation. Reads work;")
            lines.append("  a stage move will be refused. Its stages are pre-v2: " + live)
        lines.append("")
    lines += ["## Verdicts",
              "",
              "A deal cannot reach `CLOSED` without one. On buy/sell/other the field is",
              "`finalDecision`; on fulfillment it is `outcome`.", ""]
    fin = crm.fields("buy").get("finalDecision") or {}
    for v in fin.get("options", []):
        lines.append("- `%s` — %s" % (v, (fin.get("option_labels") or {}).get(v) or v))
    return "\n".join(lines) + "\n"


# ── schema ─────────────────────────────────────────────────────────────────────────────────────

def _rule_driven_fields(pipe):
    """{field: [step ids]} — every field some step in this pipeline writes."""
    out = {}
    if not pipe:
        return out
    for st in spec.steps(pipe):
        for f in spec.step_sets(st):
            out.setdefault(f, []).append(st["id"])
    return out


def _schema(what):
    if what in crm.BOARDS:
        live = crm.fields(what)
        pipe = crm.BOARDS[what]["pipeline"]
        title = "the `%s` board (object `%s`)" % (what, crm.BOARDS[what]["object"])
    elif what in ("company", "person"):
        live = crm.fields_for_object(what)
        pipe = None
        title = "the `%s` object" % what
    else:
        return ("Unknown schema %r. Try one of: %s, company, person."
                % (what, ", ".join(_PIPELINE_SIDES)))

    driven = _rule_driven_fields(pipe)
    lines = ["# Fields on %s" % title, "",
             "Live from the metadata API. **Write the API name, not the label.**", ""]
    if pipe:
        lines += ["Legend: **rule** = some workflow step writes this, so it means something specific;",
                  "**free** = commentary, safe to write prose into; blank = neither, treat with care.",
                  ""]
    lines.append("| API name | label | type | rule/free | options |")
    lines.append("|---|---|---|---|---|")
    for name in sorted(live):
        if name in _SYSTEM_FIELDS:
            continue
        m = live[name]
        opts = ""
        if m.get("options"):
            labels = m.get("option_labels") or {}
            opts = " · ".join("`%s`=%s" % (o, labels.get(o) or o) for o in m["options"])
        kind = ""
        if name in driven:
            kind = "**rule** (%s)" % " ".join(driven[name][:4])
        elif name in rules.COMMENTARY_FIELDS:
            kind = "free"
        lines.append("| `%s` | %s | %s | %s | %s |"
                     % (name, m.get("label") or "", m.get("type") or "", kind,
                        opts.replace("|", "\\|")))
    if what in crm.BOARDS:
        lines += ["", "Relations read under one name and are written under another: set `ownerId`,",
                  "not `owner`. The tools do that translation for you."]
    if what == "person":
        lines += ["", "`name` is a composite: there is no `name` column, only `nameFirstName` and",
                  "`nameLastName`."]
    if what == "company":
        lines += ["", "`clientType` is the tag that decides which boards a company has deals on.",
                  "Adding a value creates a deal on that board within ~2 minutes; removing one does",
                  "NOT delete the deal."]
    return "\n".join(lines) + "\n"


# ── workflow ───────────────────────────────────────────────────────────────────────────────────

_WHO = {"auto": "runs on its own (the autopilot does this)",
        "approve": "the autopilot proposes it, a person approves on the Calls tab",
        "hand": "by hand — a person has to do this"}


def _workflow(pipe):
    if pipe not in spec.pipelines():
        return ("Unknown pipeline %r. The spec describes: %s. (`other` follows `buy`; `networking` "
                "has no pipeline at all.)" % (pipe, ", ".join(spec.pipelines())))
    p = spec.pipeline(pipe)
    steps = spec.steps(pipe)
    order = {n: i for i, (n, _d, _new) in enumerate(p["stages"])}
    ordered = sorted(steps, key=lambda s: order.get(s["stage"], len(order)))

    lines = ["# The %s pipeline" % pipe, "",
             p.get("intro", ""), "",
             "Business hours `%s`. %d stages, %d steps." % (p["hours"], len(p["stages"]),
                                                            len(steps)),
             "",
             "Steps whose stage is **Any** fire wherever the deal is. Every step's id (`%s`) is what"
             % (steps[0]["id"] if steps else "B1"),
             "`stamp_step` takes, and stamping one applies exactly the fields listed under *writes*.",
             ""]
    current = None
    for s in ordered:
        if s["stage"] != current:
            current = s["stage"]
            lines += ["", "## %s" % current, ""]
        lines += step_block(s)
    return "\n".join(lines)


def step_block(s):
    """One workflow step as markdown lines. Shared with `explain_workflow`, so the connector never
    describes a step differently from the way the generated document describes it."""
    lines = ["### %s — %s" % (s["id"], s["name"]), ""]
    lines.append("- **when** %s" % s["trigger"])
    lines.append("- **timing** %s" % s["timing"])
    if s.get("condition") and s["condition"] != "—":
        lines.append("- **only if** %s" % s["condition"])
    lines.append("- **writes** %s" % (s.get("writes") or "—"))
    sets = spec.step_sets(s)
    if sets:
        lines.append("- **fields** %s" % " · ".join("`%s`=%s" % (k, v)
                                                    for k, v in sorted(sets.items())))
    lines.append("- **then owned by** %s" % s["owner"])
    lines.append("- **done when** %s" % s["exit"])
    if s.get("escalation") and s["escalation"] != "—":
        lines.append("- **escalates** %s" % s["escalation"])
    if s.get("loop"):
        lp = spec.loop(s["loop"])
        lines.append("- **ladder** %s (%s) — %s"
                     % (s["loop"], lp["name"] if lp else "?", lp["schedule"] if lp else ""))
    if s.get("anchor"):
        lines.append("- **timed from** `%s`" % s["anchor"])
    lines.append("- **who** %s" % _WHO.get(s.get("who"), s.get("who")))
    if s.get("note"):
        lines.append("- > %s" % s["note"])
    lines.append("")
    return lines


def loop_block(loop_id):
    """One ladder as markdown lines."""
    lp = spec.loop(loop_id)
    if not lp:
        return ["Unknown ladder %r. The spec defines %s."
                % (loop_id, ", ".join(l["id"] for l in spec.loops()))]
    return ["### %s — %s" % (lp["id"], lp["name"]), "",
            "| | |", "|---|---|",
            "| touches | %d (%s) |" % (lp["touches"], lp["at_mode"]),
            "| schedule | %s |" % lp["schedule"],
            "| starts when | %s |" % lp["entry"],
            "| stops when | %s |" % lp["exit"],
            "| on a reply | %s |" % lp["on_reply"],
            "| **when it runs out** | %s |" % lp["on_exhaust"],
            "| escalates | %s |" % lp["escalation"],
            "| used by | %s |" % ", ".join(lp.get("used") or []),
            ""]


# ── loops ──────────────────────────────────────────────────────────────────────────────────────

def _loops():
    lines = ["# The chase ladders (L1-L12)", "",
             "A ladder is a fixed set of follow-up touches counted from an **anchor field**. If the",
             "anchor is empty the ladder has not started and nothing can be timed from it — that is",
             "why an unsent proposal has no due date rather than a due date of today.", "",
             "`absolute` means each touch is measured from the anchor; `relative` means each is a gap",
             "from the touch before it. Reading a relative ladder as absolute collapses six touches",
             "onto one day.", ""]
    for lp in spec.loops():
        lines += loop_block(lp["id"])
    lines += ["## Which field each ladder counts from", "",
              "The anchor is on the *step*, not the ladder, because the same ladder counts from a",
              "different field on different boards (L8 chases an unsigned NDA on fulfillment and an",
              "unsigned contract on buy).", "",
              "| ladder | board | stage | anchor field |", "|---|---|---|---|"]
    for pipe in ("buy", "sell", "fulfillment"):
        for s in spec.steps(pipe):
            if s.get("loop") and s.get("anchor"):
                lines.append("| %s | %s | %s | `%s` |" % (s["loop"], pipe, s["stage"], s["anchor"]))
    return "\n".join(lines) + "\n"


# ── gotchas ────────────────────────────────────────────────────────────────────────────────────

def _gotchas():
    return """# Things that are true but surprising

Every one of these has already cost somebody a day. Read them before trusting a field.

## Stages

- **`stage` has no default on any board.** A record created without one lands with no stage at all:
  it does not appear on the kanban, and it is NOT "at the first stage". Treat an empty stage as
  *unplaced* and say so.
- **The API returns stage options in creation order, not board order.** `LEAD` is not the first
  option the metadata hands back. Board order comes from the workflow spec, which is what every tool
  here uses. Never infer "the next stage" from an options list.
- **A deal can only go one stage forward, or straight to `CLOSED`.** Never backwards, never skipping.
  Re-engaging a closed deal opens a *new* deal (ladder L10); it never reopens the old one.
- **Closing requires a verdict** in the same change — `finalDecision`, or `outcome` on fulfillment.
  A closed deal with no verdict is the exact hanging state the v2 migration existed to remove.

## Fields

- **Write the API name, not the label.** "NDA Sent At" is `ndaSentAt`.
- **"Progress Type" is two different fields depending on the board.** On buy, sell and other it is
  `progressType`. On fulfillment the field *labelled* "Progress Type" is actually named
  `engagementStatus` — a rename that is still pending. Look the name up per board; do not carry it
  across.
- **`engagementStatus` means something else again on sell and networking**, where it is the pre-v2
  "Engagement Status" with its own options including `CRASH_OUT_DNC`. Sell therefore has BOTH fields.
  A do-not-contact request belongs in the verdict (`finalDecision = DO_NOT_CONTACT`), not here.
- **Relations read as `owner` and write as `ownerId`.** Sending `owner` is silently ignored — no
  error, no change. The tools translate this; a raw REST call would not.
- **`daysSinceContact` and `lastContactedAt` are written by an automation** and only ever move
  forward. If they look stale it may be because nobody logged a call, not because nothing happened.

## Activity

- **Email direction cannot be read from the message association.** 2,229 of 6,860 live messages carry
  both directions at once — the sender's channel says OUTGOING and a cc'd colleague's says INCOMING.
  Direction here is always derived from the *from* handle: `@nobridge.co` means outbound.
- **Cold outreach is invisible.** Mail sent through Instantly's sending domains never syncs, so the
  cold ladders (L1, L11, L12) are timed from a field somebody stamped, not from observed sending.
- **Some contact is real but unlogged.** A phone call nobody wrote down leaves no trace at all.

## Companies and boards

- **One company can have deals on several boards.** An email to that company is evidence about one
  of them and nothing in the mail says which. Tools flag this as ambiguous — pass it on to the user
  rather than picking.
- **Removing a `clientType` tag does not delete the deal.** The sync only ever creates and moves.
- **`networking` has no workflow.** No steps, no ladders, no v2 fields, and pre-v2 stages. You can
  read it; you cannot stage-manage it.
- **Duplicate Person rows exist.** Two rows can share an email address, so a lookup by handle may be
  more truthful than a lookup by the person link.

## This connector

- **Nothing you write is silent.** Every field write records the old value, so `revert.py` can undo a
  whole session. Do not treat that as a licence to guess.
- **One stage move per deal per day** is the autopilot's pacing rule. An explicit instruction from a
  person overrides it, and the override is recorded — but if you are moving the same deal twice in a
  day, say so out loud first.
"""


# ── recipes ────────────────────────────────────────────────────────────────────────────────────

def _recipes():
    return """# How to answer the questions people actually ask

## "Where is this lead / what stage is it at / what's next?"

`get_deal` with the company name. One call answers all of it: board, stage and its position in the
pipeline, how long it has been there, the active ladder with touch N of M and the next due date, the
workflow steps that apply at that stage, last inbound and outbound email, next booked meeting, the
last call summary, and what the autopilot has recently changed.

Report it in that order — where it is, then what the rules say happens next, then what the evidence
says actually happened. If the ladder has run out, lead with that: `on_exhaust` says where it goes.

## "What do I need to do today / this week?"

`whats_next`. Optionally by owner or board. It buckets into overdue, due today, due this week, and
**stalled** — records with no next action at all, which is the failure mode worth surfacing
unprompted.

## "A new lead came in" (from an email)

1. `find_record` on the company name and the sender's domain first. **Always.** Duplicates are the
   most common damage here.
2. If nothing exists: `create_company` (name, domain, and the contact as point of contact), then
   `tag_company` with the segment for the board it belongs on.
3. Wait ~2 minutes for the sync, then `find_record` again to get the new deal.
4. `update_deal` to set the owner and the next action.

Steps 2-4 each need `confirm: true`. Show the user what you are about to create before you create it.

## "I just sent the proposal / signed the NDA / had the call"

`stamp_step`, naming the workflow step. `explain_workflow` will tell you the step id if you do not
know it. Stamping applies exactly the fields that step defines — the sent-at timestamp, the next
owner, the next due date — so the ladder starts counting from the right field. Do not set the
timestamp by hand with `update_deal`: you will get the date right and the ladder wrong.

## "Assign these to Fadil"

`update_deal` with `owner`. A name, a first name or an email all resolve. If it does not resolve,
`list_members` shows who exists — do not guess a user id.

## "Why is this deal stuck?"

`get_deal`, then read three things together: the ladder's `exhausted` and `stopped_by`, whether
`nextActionDue` is in the past, and when the last inbound email was. A ladder that has run out with
no reply is a different problem from one that never started because its anchor was never stamped.

## "Mark them do not contact"

`set_verdict` with `DO_NOT_CONTACT` and a reason. This has consequences outside the CRM, so quote
the sentence that asked for it in the reason.

## When you are not sure

Say so. `crm_context` has a `gotchas` section for exactly the cases where a field does not mean what
it looks like. Guessing and writing is the one unrecoverable move here.
"""


# ── whole pack, fingerprint, and the two prompt renderings ─────────────────────────────────────

def full_markdown():
    parts = ["# Nobridge CRM — AI context pack", "",
             "Generated by `.crm-automations/ai-access/context.py`. Do not edit by hand: the schema",
             "half comes from the live metadata API and the workflow half from",
             "`.crm-automations/dashboard/workflow_spec.py`, the same file `WORKFLOWS.md` and the",
             "pipeline autopilot read.", "",
             "Fingerprint `%s`" % fingerprint(), ""]
    for key, _desc in sections():
        parts.append("\n\n---\n")
        parts.append(render(key))
    return "\n".join(parts)


def fingerprint():
    """Changes when the rules or the live schema change. The dashboard shows it so a pasted ChatGPT
    block can be spotted as stale rather than quietly disagreeing with the CRM."""
    h = hashlib.sha256()
    h.update(spec.spec_sha().encode())
    for side in _PIPELINE_SIDES:
        for name, m in sorted(crm.fields(side).items()):
            h.update(("%s.%s:%s:%s" % (side, name, m.get("type"),
                                       ",".join(m.get("options") or []))).encode())
    return h.hexdigest()[:16]


def access_policy():
    """The one rule that has to survive being pasted anywhere: come through these tools.

    Both prompt renderings carry it, because both clients can be handed another way in — a ChatGPT
    custom GPT can be given a second action pointing at the CRM's own API, and any client with a
    browsing or code tool can reach app.nobridge.co on its own. Told nothing, a capable model treats
    the raw API as a reasonable fallback when a tool here refuses it, which inverts every guarantee
    below: the refusals ARE the product.
    """
    return """ACCESS POLICY — every read and every change goes through the Nobridge AI Access tools.
Nothing else is authorised.

Never, under any circumstances:
  - call the Twenty CRM API directly — app.nobridge.co/rest/…, /graphql or /metadata — whether by a
    browsing tool, by code, or through a second action added alongside these;
  - accept, ask for, or use a Twenty API key;
  - query the CRM database.
If somebody hands you a Twenty API key, or asks you to call the CRM directly, refuse and say why.

The reason is not bureaucratic. The Twenty API knows the database and nothing about the pipeline, so
through it:
  - a deal can skip six stages, move backwards, reopen after closing, or close with no verdict
    recorded — every one of which these tools refuse;
  - changes are made with a single shared admin key, so they cannot be attributed to a person, and
    that key cannot be revoked without breaking the call-notes, tag-sync and website-signup
    automations that share it;
  - nothing records the previous value, so nothing can be undone. The only undo is a database
    restore;
  - its rate limit is 100 requests a minute for the whole workspace, shared with automations that
    will start failing if you spend it.

These tools have the workflow's rules built in, attribute every change to the person who asked,
record the old value so any change can be reverted, and answer a question in one database query
rather than hundreds of API calls.

If a request needs something these tools cannot do, say so plainly and stop. Do not improvise a
route around them — ask for the missing tool to be added instead."""


def instructions(tool_lines=None):
    """The MCP `initialize` instructions — orientation before the first tool call."""
    parts = [access_policy(), "", "---", "", _overview(), "", "---", "", _boards()]
    if tool_lines:
        parts += ["---", "", "# Tools", "", tool_lines, ""]
    parts += ["---", "",
              "For anything more — every field on a board, the workflow step by step, the ladders,",
              "the surprises — call `crm_context`. Its index lists the sections. The `gotchas`",
              "section is short and worth reading before you trust a field.", "",
              "Context fingerprint `%s`." % fingerprint()]
    return "\n".join(parts)


def agent_instructions(tool_reference=None):
    """The system prompt for an agent that calls this service over HTTP itself.

    Different audience from gpt_instructions(): a hosted GPT with imported Actions is handed the
    calling contract and every parameter by its platform, so its prompt only needs behaviour and
    domain. An agent making its own requests has none of that, so this adds the wire contract, the
    response envelope, the full parameter reference, and how to read what comes back. No character
    cap — it goes in a system prompt, not an 8,000-character box.
    """
    boards = []
    for side in _PIPELINE_SIDES:
        pipe = crm.BOARDS[side]["pipeline"]
        if pipe:
            boards.append("  %-12s tag %-11s %s"
                          % (side, crm.BOARDS[side]["segment"],
                             " -> ".join(spec.stage_enums(pipe))))
        else:
            boards.append("  %-12s tag %-11s no workflow: readable, but no stage moves"
                          % (side, crm.BOARDS[side]["segment"]))

    verdicts = crm.fields("buy").get("finalDecision") or {}
    vlist = "  " + "\n  ".join(
        "%-18s %s" % (v, (verdicts.get("option_labels") or {}).get(v) or v)
        for v in verdicts.get("options", []))

    return """You operate Nobridge's M&A deal pipeline through the Nobridge AI Access service. You are
not a database client: you are expected to know how the pipeline works and to answer as somebody who
does.

%(policy)s

================================================================================
HOW TO CALL IT
================================================================================

Every tool is one HTTP request. There is nothing else to learn.

  POST https://app.nobridge.co/ai/tools/<tool_name>
  Authorization: Bearer <YOUR_TOKEN>
  Content-Type: application/json

  Body: a JSON object of that tool's arguments. Send {} when it takes none.

One call, one tool. There is no batching, no session, no state between calls. Requests are handled
one at a time, so a slow read does not fail, it queues — do not fire calls in parallel expecting
speed, and do not retry on a timeout before ~90 seconds.

Example:

  POST https://app.nobridge.co/ai/tools/get_deal
  {"company": "Naluri"}

================================================================================
HOW TO READ WHAT COMES BACK
================================================================================

The reply is always HTTP 200 with a JSON envelope, in one of three shapes:

  {"ok": true,  "result": {...}, "text": null}    a structured answer — read `result`
  {"ok": true,  "result": null,  "text": "..."}   a prose answer in markdown — read `text`
                                                  (crm_context and explain_workflow answer this way)
  {"ok": false, "error": "..."}                   REFUSED. `error` says why, in plain language.

A refusal is not a transport failure and not a bug. It is the pipeline's rules saying no, and the
text tells you what would be acceptable instead. Read it and act on it. Never retry the same call
hoping for a different answer, and never look for another route to the same change.

Only three cases are not a 200:

  HTTP 404   the token is unknown or has been revoked. Stop; ask a person. Do not probe.
  HTTP 403   the token is valid but the person behind it no longer holds an Admin or Manager role in
             the CRM. Stop; ask a person.
  HTTP 413   your body was over 1MB. Send less.

================================================================================
CHANGING ANYTHING: THE CONFIRM GATE
================================================================================

Every tool marked WRITES does nothing on the first call. Called without `confirm`, it returns exactly
what it *would* change and changes nothing:

  {"ok": true, "result": {
      "applied": false,
      "would_write": [{"field": "...", "label": "...", "from": <old>, "to": <new>}],
      "refused":     [{"field": "...", "why": "..."}],
      "warnings":    ["..."],
      "confirm":     "Nothing has been changed. ..."}}

Show `would_write` to the person in their own terms — field label, from, to. Read out any `warnings`;
they exist because something is unusual. If they agree, call the identical tool again with
`"confirm": true`. Then:

  {"ok": true, "result": {
      "applied": true,
      "written": [...],
      "run": 24,
      "undo": "This was run 24. ..."}}

Keep the `run` number in the conversation. "Undo that" is the `undo` tool with that number, and it
puts every field back to what it was.

Do not confirm on your own initiative, and do not treat an earlier yes as covering a later change.
One confirmation, one change.

================================================================================
THE TOOLS
================================================================================

%(reference)s

================================================================================
WHAT WILL REFUSE YOU
================================================================================

These are structural. They are not preferences, they will not yield to rephrasing, and a person
insisting does not change them:

  - a deal moves ONE stage forward, or straight to Closed. Never backwards. Never skipping.
  - never out of Closed. Re-engaging a closed deal opens a NEW deal (ladder L10); it does not reopen
    the old one.
  - never Closed without a verdict recorded in the same change.
  - only fields the workflow authorises at that deal's current stage, plus free-text commentary.
  - values must be live options on THAT board — the boards are not identical.

If a person asks for something these forbid, say which rule refuses it and what the legal move would
be. Do not attempt it anyway to see what happens.

================================================================================
THE PIPELINE
================================================================================

Deals do not live in one table. They are split across five boards, and which board a deal sits on is
decided by the multi-select `clientType` tag on its Company. Tagging a company makes a separate
automation create the deal on that board, at that board's first stage, within about 2 minutes.

Stages below are in BOARD ORDER — the order a deal actually moves through:

%(boards)s

Verdicts (`finalDecision` on buy/sell/other, `outcome` on fulfillment):

%(verdicts)s

Two other things write to these same records: people, by hand in the CRM; and an hourly automation
that reads synced email and calendar. That is why your writes are validated rather than trusted —
and why a field you did not set may have changed since you last looked. Re-read before you write.

================================================================================
HOW TO READ A DEAL
================================================================================

`get_deal` is the one call worth mastering. Its `result` carries, in the order you should report it:

  where_it_is     board, stage, `position` ("7 of 9"), `days_at_stage`, `next_stage_allowed`.
                  A `warning` here means the record is in a bad state — most often NO stage at all,
                  which means unplaced and invisible on the kanban. Not "at the first stage".

  ladder          the follow-up sequence that is running: `loop`, `touch` ("2 of 4"), `next_due`,
                  `exhausted`, `stopped_by`, `on_exhaust`.
                  `none_running: true` with `candidates` means a sequence APPLIES here but has not
                  started, because the field it counts from is empty. `candidates[].anchor_field`
                  names that field and `candidates[].step` names the step that sets it. That is the
                  actionable answer to "why is nothing scheduled".

  what_should_happen_next   the workflow steps that apply at this stage, each with its `step` id,
                  `when` it fires, `timing`, `owner`, `done_when`, and `who` does it. Quote these.
                  Never invent what happens next — it comes from here or from explain_workflow.

  contact         message counts, `last_inbound`, `last_outbound`, `days_since_any`. A `note` here
                  means no synced email is linked, which is NOT proof of no contact.

  meetings        `last_held`, `next_booked`, `last_cancelled`.
  calls           summaries of recorded calls, when there are any.
  recent_email    the actual messages, newest first, with direction and an extract.
  fields          every populated field, with its human label and, for options, its meaning.
  empty_fields    the names of everything unset. Read this before saying a value is missing.
  automation_history   what the hourly automation recently changed on this record.
  ambiguity       present when the company has deals on several boards. Then email and meetings
                  cannot be attributed to one of them. Say so and let the person choose.

Report in that order: where it is, then what the rules say happens next, then what the evidence says
actually happened. Those are three different things and conflating them is how a wrong answer sounds
right.

================================================================================
HOW TO WORK
================================================================================

  1. Read before writing. get_deal first, always.
  2. Find before creating. find_record on the company name AND the email domain. Duplicate companies
     are the most common damage done here.
  3. For "I sent the X" / "we signed the Y", use stamp_step with the workflow step id — not
     update_deal with a timestamp. The step knows which field the follow-up sequence counts from;
     setting the date by hand gets the date right and the sequence wrong. explain_workflow gives you
     the step ids.
  4. New lead: create_company, then tag_company for the board, then wait ~2 minutes, then find_record
     to get the deal, then update_deal for the owner. Four confirmations, deliberately.
  5. Assign owners by email or full name. If it does not resolve, call list_members. Never guess an id.
  6. Call crm_context when you need detail — field lists per board, the workflow step by step, the 12
     sequences. Its `gotchas` section is short and worth reading before trusting any field.

================================================================================
WHAT TO WATCH FOR
================================================================================

  - Write API field names, not labels. "NDA Sent At" is `ndaSentAt`.
  - "Progress Type" is `progressType` on buy/sell/other but `engagementStatus` on fulfillment. Look
    it up per board; do not carry a name across.
  - Empty is not zero. An unset contact date means nobody recorded contact, not that there was none.
    Phone calls nobody logged leave no trace at all.
  - You cannot see cold outreach. It is sent through a separate system that never syncs here, so for
    the cold sequences you can see replies but cannot confirm anything went out.
  - You cannot send email. Every "send the X" step is a person's job; you record that it happened and
    work out when the next thing is due.
  - The `networking` board has no workflow. Read it freely; a stage move on it will be refused.
  - Creating a company, or adding a clientType tag, is NOT undone by the undo tool. Removing a tag
    does not delete the deal the sync already made. Say so before you create anything.
  - When you are unsure, say so. Guessing and writing is the one move here that cannot be walked back
    cleanly.

Context fingerprint %(fp)s — quote it if you are asked which version of the rules you are working
from.
""" % {"policy": access_policy(),
       "reference": tool_reference or "(tool reference unavailable)",
       "boards": "\n".join(boards),
       "verdicts": vlist,
       "fp": fingerprint()}


def gpt_instructions():
    """The compact block to paste into a ChatGPT Custom GPT. Hard-capped at GPT_CAP characters.

    Takes no tool list on purpose, unlike instructions(). A custom GPT learns every operation's name
    and description from the imported OpenAPI schema, so listing them here spent ~1,300 of a 8,000
    character budget repeating what the model already had. The instructions name the tools that need
    naming inside the guidance itself, which is the part the schema cannot convey.
    """
    boards = []
    for side in _PIPELINE_SIDES:
        pipe = crm.BOARDS[side]["pipeline"]
        if pipe:
            boards.append("- **%s** (tag `%s`): %s"
                          % (side, crm.BOARDS[side]["segment"],
                             " -> ".join(spec.stage_enums(pipe))))
        else:
            boards.append("- **%s** (tag `%s`): no workflow — readable, not stage-managed"
                          % (side, crm.BOARDS[side]["segment"]))

    body = """You operate Nobridge's M&A CRM through the Nobridge AI Access actions. Behave like
somebody who knows the pipeline, not like a database client.

%(policy)s

THE SHAPE OF IT
Deals live on five boards, not one table. Which board a deal is on is decided by the multi-select
`clientType` tag on its Company. Tagging a company makes a separate automation create the deal on
that board, at that board's first stage, within about 2 minutes.

%(boards)s

Stages are listed above in BOARD ORDER. The API returns options in creation order, so never infer
the next stage from an options list.

HOW TO WORK
1. Read before writing. `get_deal` answers where a deal is, which chase ladder it is on, touch N of
   M, the next due date, the workflow steps for that stage, and the last email, meeting and call.
2. Write tools do nothing unless you pass `confirm: true`. Without it they return the exact diff
   they would apply. Show it, get a yes, then call again with `confirm: true`.
3. Quote the workflow, never invent it. What happens next comes from `get_deal` or
   `explain_workflow`.
4. For "I just sent the X" use `stamp_step` with the workflow step id, not `update_deal` with a
   timestamp. The step knows which field the follow-up ladder counts from; you do not.
5. For a new lead: `find_record` on the name AND the domain first (duplicates are the usual damage),
   then `create_company`, then `tag_company`, then wait ~2 min and `update_deal` the owner.
6. Call `crm_context` for detail — field lists per board, the workflow step by step, the 12 ladders,
   and a `gotchas` section. Read `gotchas` before trusting any field.

RULES THAT WILL REFUSE YOU (they are not negotiable, do not retry)
- One stage forward, or straight to CLOSED. Never backwards, never skipping.
- Never out of CLOSED. Re-engaging a closed deal opens a new deal (ladder L10).
- Never close without a verdict (`finalDecision`, or `outcome` on fulfillment) in the same change.
- Only fields the workflow authorises at that stage, plus free-text commentary.

WHAT TO WATCH FOR
- `stage` has no default: an empty stage means UNPLACED, not "first stage". Say so.
- Write API names, not labels ("NDA Sent At" is `ndaSentAt`).
- The spec's `progressType` is really `engagementStatus` on fulfillment.
- Email direction comes from the sender's address (`@nobridge.co` = outbound), never from the
  message's own direction flag, which is wrong on a third of messages.
- Cold outreach never syncs, so cold ladders are timed from a stamped field, not observed sending.
- One company can have deals on several boards; an email is then ambiguous. Say which boards and let
  the user choose.
- You cannot send email. If you also hold the user's mailbox, send it there and stamp the CRM here.
- Empty is not zero: an unset contact date means nobody recorded contact, not that there was none.
Context fingerprint %(fp)s. If a tool result mentions a different fingerprint, these instructions
are out of date — say so, and rely on `crm_context` instead.
""" % {"boards": "\n".join(boards),
       "policy": access_policy(),
       "fp": fingerprint()}
    return body


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg == "--gpt":
        text = gpt_instructions()
        sys.stdout.write(text)
        print("\n[%d chars, cap %d]" % (len(text), GPT_CAP), file=sys.stderr)
    elif arg == "--sections":
        for k, d in sections():
            print("%-22s %s" % (k, d))
    elif arg == "--fingerprint":
        print(fingerprint())
    elif arg:
        sys.stdout.write(render(arg))
    else:
        sys.stdout.write(full_markdown())
