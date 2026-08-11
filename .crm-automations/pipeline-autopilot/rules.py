"""Layer 2 — the deterministic engine, and the validator that keeps judgement inside the rules.

Two halves, and the split is the whole safety story:

  derive()    Facts. No model is asked what "last contacted" means; it is computed. Anything the
              activity data determines outright is written from here.
  validate()  Everything Layer 3 proposes passes through this before it can become a write. The
              model may only touch fields some step at the record's current stage authorises via
              `sets`, may only move one stage forward, may not un-close a deal, and must clear a
              confidence bar that is higher for consequential changes.

The `lastContacted` prose is byte-compatible with ~/refresh-last-contacted.sql on the VM ('today',
'1 day ago', 'N days ago', 'No contact logged'), so the autopilot and the incumbent 06:30 cron job
cannot disagree about the same record.
"""
import bizdays
import crm
import spec

# Confidence bars. Higher where being wrong costs more.
MIN_CONF_STAGE = 0.75
MIN_CONF_FIELD = 0.60
MIN_CONF_DNC = 0.90          # Do Not Contact has consequences outside the CRM
DNC = "DO_NOT_CONTACT"

# "Actively speaking" means a two-way exchange this recently.
ACTIVE_DAYS = 14

# COMMENTARY FIELDS bypass the per-stage `sets` allowlist. The allowlist exists to stop judgement
# changing a record's STATE - its stage, its verdict, its owner, its timestamps - to something no
# rule sanctions. These fields are free text that describes what happened; writing prose into them
# cannot put the pipeline into an illegal state, and one of them (`nextSteps`, labelled "Where we
# last left off") is the single most useful thing this automation produces for somebody picking a
# deal up cold. They are still type-checked and still subject to the confidence bar.
COMMENTARY_FIELDS = {
    "nextSteps",           # "Where we last left off" - history
    "actionItem",          # the plan - deliberately a different field from the above
    "screeningNotes",      # why a lead was qualified or disqualified
    "reasonForProgress",
    "meetingFindings",
    "notes",
}

# Stages whose name marks a meeting, used to decide whether meetingOutcome is meaningful here.
def _is_meeting_stage(pipe, stage_enum):
    for name, _note, _new in spec.pipeline(pipe)["stages"]:
        if spec.enum_value(name) != stage_enum:
            continue
        low = name.lower()
        return ("meeting" in low or "review" in low or "pitch" in low
                or low.startswith("intro"))
    return False


# ── derived facts ──────────────────────────────────────────────────────────────────────────────

def contact_prose(days):
    """Exactly what refresh-last-contacted.sql writes, so the two agree."""
    if days is None:
        return "No contact logged"
    if days <= 0:
        return "today"
    if days == 1:
        return "1 day ago"
    return "%d days ago" % days


def derive(side, record, act, mtg, now=None):
    """{field: value} that follows from the activity alone. Only fields live on this board."""
    now = now or bizdays.now()
    live = crm.fields(side)
    out = {}

    def put(field, value):
        if field in live:
            out[field] = value

    last_any = bizdays.parse_dt((act or {}).get("last_any"))
    last_in = bizdays.parse_dt((act or {}).get("last_in"))
    last_out = bizdays.parse_dt((act or {}).get("last_out"))

    # CONTACT DATES ONLY EVER MOVE FORWARD. Email is not the only way anyone talks to a client - a
    # call or a meeting logged by hand is real contact this automation cannot see. Overwriting a
    # later stored date with an earlier computed one would delete that knowledge, so the stored value
    # wins whenever it is more recent, and everything else is derived from whichever is later.
    stored_last = max((d for d in (bizdays.parse_dt(record.get("lastContactedAt")),
                                   bizdays.parse_dt(record.get("lastContact")))
                       if d), default=None)
    if stored_last and (not last_any or stored_last > last_any):
        last_any = stored_last

    # Absence of evidence is not evidence of absence. If no mail is attributed to this record, say
    # nothing rather than stamping "No contact logged" over a value somebody or something else knew
    # about - attribution is a join across duplicate people and imperfect address matching, and a
    # record whose mail this misses would otherwise be quietly rewritten as never-contacted.
    days = (now.date() - last_any.date()).days if last_any else None
    if last_any:
        put("lastContacted", contact_prose(days))                   # TEXT, buy/sell/other
        put("lastContactedAt", bizdays.iso(last_any))               # DATE_TIME, buy/sell/other
        put("lastContact", bizdays.iso_date(last_any))              # DATE, fulfillment/networking
        put("daysSinceContact", float(days))
    elif not record.get("lastContacted"):
        # Nothing known, and nothing recorded: saying so is honest and matches the cron job.
        put("lastContacted", contact_prose(None))

    # A reply is a fact, and like the contact dates it only moves forward - a reply logged by hand
    # after a phone call is still a reply.
    stored_replied = bizdays.parse_dt(record.get("repliedAt"))
    if last_in and (not stored_replied or last_in > stored_replied):
        put("repliedAt", bizdays.iso(last_in))

    # A closed deal owes nobody anything: every _close_steps verdict clears the owner and the due
    # date, so deriving them here would fight the rules. Contact fields are still written, because
    # they are informational and the incumbent 06:30 job writes them for closed records too.
    stage = record.get("stage")
    closed = stage == "CLOSED"

    # who owes the next move: whoever did NOT send last
    if not closed:
        if last_in and last_out:
            put("nextOwner", "US" if last_in > last_out else "THEM")
        elif last_in:
            put("nextOwner", "US")
        elif last_out:
            put("nextOwner", "THEM")

    # Meeting outcome, but only where the stage is about a meeting AND the meeting can be tied to
    # THIS stage. A future booked meeting is unambiguous, so SCHEDULED is always safe. HOSTED is not:
    # it needs the meeting to have happened after the record entered its current stage, and
    # stageChangedAt is a v2 field that nothing has written yet - so on most records it is empty and
    # "any past meeting with this company" would be the real test. That is far too loose (the
    # meeting may have been about a different deal at the same company), so where stageChangedAt is
    # missing this is left to judgement instead of guessed. It becomes derivable for itself: once
    # the autopilot moves a record it stamps stageChangedAt, and the next run can bound the meeting.
    if stage and not closed and _is_meeting_stage(crm.BOARDS[side]["pipeline"] or "buy", stage):
        booked = bizdays.parse_dt((mtg or {}).get("next_booked"))
        held = bizdays.parse_dt((mtg or {}).get("last_held_end"))
        stage_at = bizdays.parse_dt(record.get("stageChangedAt"))
        if held and stage_at and held >= stage_at:
            put("meetingOutcome", "HOSTED")
        elif booked:
            put("meetingOutcome", "SCHEDULED")

    # only send what actually changes
    return {k: v for k, v in out.items() if _changed(record.get(k), v)}


def _changed(old, new):
    if old is None:
        return new is not None
    if isinstance(new, float):
        try:
            return abs(float(old) - new) > 1e-9
        except (TypeError, ValueError):
            return True
    a, b = str(old), str(new)
    # Timestamps round-trip through different precisions; compare to the minute.
    if len(a) >= 16 and len(b) >= 16 and a[4] == "-" and b[4] == "-":
        pa, pb = bizdays.parse_dt(a), bizdays.parse_dt(b)
        if pa and pb:
            return abs((pa - pb).total_seconds()) > 60
    return a != b


# ── loop state ─────────────────────────────────────────────────────────────────────────────────

def _signal_met(signal, record, act, mtg):
    """Has a loop's stop signal fired?"""
    if signal.startswith("derived:"):
        key = signal.split(":", 1)[1]
        if key == "meeting_booked":
            return bool((mtg or {}).get("next_booked"))
        if key == "last_meeting_end":
            return bool((mtg or {}).get("last_held_end"))
        if key == "deliverable_sent":
            return any(record.get(f) for f in ("strategySentAt", "revampSentAt"))
        if key == "signed":
            return any(record.get(f) for f in ("contractSignedAt", "ndaSentAt"))
        if key == "stage_advanced":
            return False        # decided by the caller, which knows the previous stage
        return False
    return bool(record.get(signal))


def _when_met(when, record):
    """Evaluate a step's machine-readable entry condition. No `when` means no extra condition."""
    if not when:
        return True
    field = when.get("field")
    if not field:
        return True
    current = record.get(field)
    if "in" in when:
        wanted = {spec.enum_value(v) for v in when["in"]}
        return current is not None and spec.enum_value(current) in wanted
    if when.get("op") == "set":
        return bool(current)
    if when.get("op") == "empty":
        return not current
    return True


def loop_state(side, record, act, mtg, now=None):
    """Which loop applies at this record's stage, where it is, and whether it has run out.

    Returns None when the stage has no loop, or when the loop's anchor is empty - a ladder that
    has not started cannot be timed, and guessing an anchor would invent a due date.
    """
    now = now or bizdays.now()
    pipe = crm.BOARDS[side]["pipeline"]
    stage = record.get("stage")
    if not pipe or not stage:
        return None
    stage_name = _stage_name(pipe, stage)
    if not stage_name:
        return None
    hours = spec.pipeline(pipe)["hours"]

    for step in spec.steps_for_stage(pipe, stage_name):
        lid = step.get("loop")
        anchor_key = step.get("anchor")
        if not lid or not anchor_key:
            continue
        lp = spec.loop(lid)
        if not lp:
            continue

        # A step's `when` is its entry condition. Where a stage holds two loop-bearing steps, this
        # is what separates them - Pitch holds both L4 (recover a missed meeting) and L3 (chase the
        # go-ahead), and picking by anchor alone puts a HOSTED meeting on the no-show ladder.
        if not _when_met(step.get("when"), record):
            continue

        if anchor_key.startswith("derived:"):
            key = anchor_key.split(":", 1)[1]
            anchor = bizdays.parse_dt((mtg or {}).get("last_held_end")) \
                if key == "last_meeting_end" else None
        else:
            anchor = bizdays.parse_dt(record.get(anchor_key))
        if not anchor:
            continue        # the ladder has not started

        stopped = [s for s in lp.get("stops_on", []) if _signal_met(s, record, act, mtg)]
        try:
            nxt = bizdays.next_touch(lp, anchor, hours, at=now,
                                     sla_days=step.get("sla_days"))
            elapsed = bizdays.touches_elapsed(lp, anchor, hours, at=now,
                                              sla_days=step.get("sla_days"))
        except ValueError:
            continue

        return {
            "loop": lid, "loop_name": lp["name"], "step": step["id"],
            "anchor_field": anchor_key, "anchor": bizdays.iso(anchor),
            "touches": len(lp["at"]), "elapsed": elapsed,
            "next_index": nxt[0] if nxt else None,
            "next_label": nxt[1] if nxt else None,
            "next_due": bizdays.iso(nxt[2]) if nxt else None,
            "exhausted": nxt is None,
            "stopped_by": stopped,
            "on_exhaust": lp["on_exhaust"],
        }
    return None


def _stage_name(pipe, stage_enum):
    for name, _n, _new in spec.pipeline(pipe)["stages"]:
        if spec.enum_value(name) == stage_enum:
            return name
    return None


def allowed_fields(side, record, target_stage=None):
    """{field: valueSpec} every step authorises here. The write allowlist.

    `target_stage` matters more than it looks. A deal being moved to Closed has to be given its
    verdict in the same pass, and the verdict steps belong to Closed, not to the stage it is leaving.
    Building the allowlist from the current stage alone let two records close with no Final Decision
    at all - which is precisely the hanging state the v2 migration existed to remove.
    """
    pipe = crm.BOARDS[side]["pipeline"]
    stage = record.get("stage")
    if not pipe:
        # No pipeline (networking): derived activity fields only, never a stage or a verdict.
        return {}
    names = []
    if stage:
        n = _stage_name(pipe, stage)
        if n:
            names.append(n)
    if target_stage:
        n = _stage_name(pipe, target_stage)
        if n and n not in names:
            names.append(n)
    steps = []
    for n in names:
        steps.extend(spec.steps_for_stage(pipe, n))
    if not steps:
        steps = spec.steps(pipe)          # no stage at all: any rule may apply
    out = {}
    for st in steps:
        for field, value in spec.step_sets(st).items():
            out.setdefault(field, value)
    return out


# ── the validator ──────────────────────────────────────────────────────────────────────────────

def validate(side, record, proposal, loop=None, now=None, actor="autopilot"):
    """Clamp a proposal into writes that the rules permit.

    Returns (writes, rejects, flags). `writes` is {field: value} ready for crm.patch; `rejects` is
    [(field, value, reason)] for the audit trail; `flags` are reasons a human should look.

    `actor` is "autopilot" for the hourly run and "human" for the AI Access connector, where a person
    has asked for the change in as many words. The ONLY difference is the confidence bars: they exist
    to stop a model acting on a weak inference from a mailbox, and there is nothing to infer when
    somebody has just said what they want. Every structural rule below — one stage forward or
    straight to Closed, never backwards, never out of Closed, never closed without a verdict, only
    fields a step at this stage authorises, and every value coerced against the live options —
    applies identically to both, because those encode what the pipeline MEANS, not how sure we are.
    """
    now = now or bizdays.now()
    human = actor == "human"
    live = crm.fields(side)
    pipe = crm.BOARDS[side]["pipeline"]
    writes, rejects, flags = {}, [], []
    # Where the record is headed, if anywhere: the allowlist needs it (see allowed_fields).
    _sd = proposal.get("stage_decision") or {}
    _target = (_sd.get("to") or "").strip().upper() if _sd.get("move") else None
    allow = allowed_fields(side, record, target_stage=_target)

    if proposal.get("needs_human"):
        flags.append(proposal.get("human_reason") or "the model asked for a human")

    # ── the stage decision ──
    sd = proposal.get("stage_decision") or {}
    if sd.get("move"):
        target = (sd.get("to") or "").strip().upper()
        conf = float(sd.get("confidence") or 0)
        cur = record.get("stage")
        reason = None
        if not pipe:
            reason = "this board has no pipeline in the spec, so no rule can move it"
        elif target not in crm.stage_options(side):
            reason = "%r is not a live option on %s" % (target, side)
        elif target == cur:
            reason = "already at %s" % target
        elif not human and conf < MIN_CONF_STAGE:
            reason = "confidence %.2f below the %.2f bar for a stage move" % (conf, MIN_CONF_STAGE)
        elif cur == "CLOSED":
            # L10 re-engagement creates a NEW deal; it never reopens the closed one.
            reason = ("refusing to move a record out of Closed - re-engagement opens a new deal "
                      "(L10), it does not reopen this one")
        else:
            order = spec.stage_enums(pipe)
            if cur is None:
                # A record with no stage is unambiguously wrong and cannot be "advanced"; placing
                # it is allowed, and it is the only case where any stage is a legal target.
                writes["stage"] = target
                flags.append("record had no stage at all; placed at %s" % target)
            elif cur not in order or target not in order:
                reason = "%s or %s is not in the spec's stage order" % (cur, target)
            else:
                i, j = order.index(cur), order.index(target)
                if j == i + 1 or target == "CLOSED":
                    writes["stage"] = target
                elif j > i + 1:
                    reason = ("refusing to skip %d stages (%s -> %s); one forward or straight to "
                              "Closed only" % (j - i, cur, target))
                else:
                    reason = ("refusing to move backwards (%s -> %s); only L9 does that, on reply"
                              % (cur, target))
        # A CLOSED deal with no verdict is the hanging state the whole v2 migration existed to
        # remove: the board shows it as finished and nothing records how. Closing is therefore only
        # allowed together with a verdict. This is enforced here rather than asked for in the prompt,
        # because "the model usually remembers" is not a guarantee - and it did not, twice.
        if not reason and target == "CLOSED":
            verdict_field = "finalDecision" if "finalDecision" in live else (
                "outcome" if "outcome" in live else None)
            if verdict_field:
                proposed = {(u.get("field") or "") for u in (proposal.get("field_updates") or [])}
                if verdict_field not in proposed and not record.get(verdict_field):
                    reason = ("refusing to close without a verdict - %s must be set in the same "
                              "change, or the deal reads as finished with no record of how"
                              % verdict_field)

        if reason:
            # Take the stage back out. Two branches above set writes["stage"] BEFORE the verdict
            # check runs - the one-forward/to-Closed clamp, and the placement of a stage-less record
            # - so a refusal that arrives afterwards has to undo it. Without this pop, a close with
            # no verdict was rejected in the audit trail and then written anyway, minus its
            # stageChangedAt: the exact hanging state this check exists to prevent, with a log line
            # saying it had been prevented. Found 2026-08-11 while building the AI Access connector.
            writes.pop("stage", None)
            rejects.append(("stage", target, reason))
            flags.append("proposed %s -> %s was refused: %s" % (record.get("stage"), target, reason))
        elif "stage" in writes and "stageChangedAt" in live:
            writes["stageChangedAt"] = bizdays.iso(now)

    # ── field updates ──
    for upd in proposal.get("field_updates") or []:
        field = (upd.get("field") or "").strip()
        value = upd.get("value")
        conf = float(upd.get("confidence") or 0)
        meta = live.get(field)
        if field == "stage":
            rejects.append((field, value, "stage is decided by stage_decision, not field_updates"))
            continue
        if meta is None:
            rejects.append((field, value, "no such field on %s" % side))
            continue
        if field not in allow and field not in COMMENTARY_FIELDS:
            rejects.append((field, value,
                            "no step at stage %s authorises writing %s"
                            % (record.get("stage"), field)))
            continue
        bar = MIN_CONF_DNC if (field == "finalDecision"
                               and str(value).upper() == DNC) else MIN_CONF_FIELD
        if not human and conf < bar:
            rejects.append((field, value, "confidence %.2f below %.2f" % (conf, bar)))
            continue
        if field == "finalDecision" and str(value).upper() == DNC and not upd.get("quote"):
            rejects.append((field, value,
                            "Do Not Contact must quote the sentence that asked for it"))
            continue
        coerced, why = coerce(meta, value)
        if why:
            rejects.append((field, value, why))
            continue
        if _changed(record.get(field), coerced):
            writes[field] = coerced

    return writes, rejects, flags


def coerce(meta, value):
    """(value, error). Shape a proposed value for its field type, or explain why it cannot be."""
    t = meta["type"]
    if value is None:
        return None, None
    if t in ("SELECT", "MULTI_SELECT"):
        v = spec.enum_value(value)
        if v not in meta["options"]:
            return None, "%r is not a live option (have: %s)" % (value, " ".join(meta["options"]))
        return v, None
    if t == "BOOLEAN":
        s = str(value).strip().lower()
        if s in ("true", "yes", "1"):
            return True, None
        if s in ("false", "no", "0"):
            return False, None
        return None, "%r is not a boolean" % value
    if t == "NUMBER":
        try:
            return float(value), None
        except (TypeError, ValueError):
            return None, "%r is not a number" % value
    if t == "DATE_TIME":
        dt = bizdays.parse_dt(value)
        return (bizdays.iso(dt), None) if dt else (None, "%r is not a timestamp" % value)
    if t == "DATE":
        dt = bizdays.parse_dt(value)
        return (bizdays.iso_date(dt), None) if dt else (None, "%r is not a date" % value)
    if t == "RELATION":
        s = str(value).strip()
        if len(s) == 36 and s.count("-") == 4:
            return s, None
        # Judgement can only name a person the way the mail does. Resolve it to a member id here
        # rather than making the model guess a uuid it has no way of knowing.
        member = crm.resolve_member(s)
        if member:
            return member, None
        return None, "cannot resolve %r to a workspace member" % value
    return str(value), None


def loop_writes(side, record, loop, now=None):
    """Deterministic writes that follow from loop state: the next due date, and parking a ladder
    that has run out. Separate from derive() because it needs the loop, and separate from the model
    because none of it is a judgement."""
    now = now or bizdays.now()
    live = crm.fields(side)
    out, flags = {}, []
    if not loop:
        return out, flags

    step = None
    pipe = crm.BOARDS[side]["pipeline"]
    for st in spec.steps(pipe):
        if st["id"] == loop["step"]:
            step = st
            break
    sets = spec.step_sets(step) if step else {}

    if loop["stopped_by"]:
        return out, flags     # the ladder is over; nothing to schedule

    if loop["exhausted"]:
        # on_exhaust is prose and varies; the one thing every ladder does is stop being due.
        flags.append("%s exhausted after %d touches - %s"
                     % (loop["loop"], loop["touches"], loop["on_exhaust"]))
        if "progressType" in live and record.get("progressType") != "GHOSTED":
            out["progressType"] = "GHOSTED"
        elif "engagementStatus" in live and record.get("engagementStatus") != "GHOSTED":
            out["engagementStatus"] = "GHOSTED"
        return out, flags

    # The due-date field this step writes: nextActionDue on buy/sell/other, followUpDate on
    # fulfillment. Taken from `sets` rather than assumed.
    for field, vspec in sets.items():
        kind, _payload = spec.value_spec(vspec)
        if kind == "loop_next" and field in live and loop.get("next_due"):
            due = bizdays.parse_dt(loop["next_due"])
            val = bizdays.iso_date(due) if live[field]["type"] == "DATE" else bizdays.iso(due)
            if _changed(record.get(field), val):
                out[field] = val
    return out, flags


if __name__ == "__main__":
    import json

    import evidence
    side = "buy"
    recs = evidence.records(side)
    act = evidence.activity(side)
    mtg = evidence.meetings(side)
    shown = 0
    for r in recs:
        a, m = act.get(r["id"]), mtg.get(r["id"])
        d = derive(side, r, a, m)
        lp = loop_state(side, r, a, m)
        lw, lf = loop_writes(side, r, lp)
        if not d and not lp:
            continue
        print("\n%-34s stage=%-16s" % (r["name"][:34], r.get("stage")))
        if d:
            print("   derived: %s" % json.dumps(d))
        if lp:
            print("   loop:    %s %s touch %s/%s next=%s exhausted=%s stopped=%s"
                  % (lp["loop"], lp["loop_name"], lp["elapsed"], lp["touches"],
                     (lp["next_due"] or "-")[:16], lp["exhausted"], lp["stopped_by"]))
        if lw:
            print("   loopwrt: %s" % json.dumps(lw))
        for f in lf:
            print("   flag:    %s" % f)
        shown += 1
        if shown >= 8:
            break
