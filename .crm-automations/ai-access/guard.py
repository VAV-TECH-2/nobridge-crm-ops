"""The write path: preview, validate, apply, record.

Every change this connector makes to a deal goes through here, and here goes through
`rules.validate(..., actor="human")`. Since 2026-10-04 (owner's decision) that actor skips the
pipeline's structural rules — a person's assistant may move a deal backwards, reopen it, close it
without a verdict and write any field. Only what the CRM itself would reject is refused: an unknown
stage or field, or a value that is not a live option. The hourly autopilot keeps every rule.

What this file adds on top:

  NO CONFIRM GATE.  Writes apply on the first call. A caller that wants to look first passes
                    preview=true and gets the exact diff, field by field, old -> new. The old
                    `confirm` argument is accepted and ignored so existing clients keep working.
  ATTRIBUTION.      The run is recorded with source='ai' and the asking person's email, so the audit
                    trail says who, not just what.
  REVERSIBILITY.    Field writes land in the autopilot's `field_writes` with the old value and
                    source='ai', which is what makes `revert.py --run N --apply` undo a chat-driven
                    change with no new tooling.
  PACING.           The autopilot's one-stage-move-per-record-per-day cap does not apply to a
                    person. The move still SPENDS the day's allowance, so the hourly run will not
                    move the same deal again an hour later.

ONE DELIBERATE GAP. Company-level writes (creating a company, changing its clientType tags) are
recorded as decisions but NOT as field_writes, so `revert.py` never sees them. That is not laziness:
revert works by PATCHing a board record back, and a company is not a board record — feeding it one
would break the undo of every other write in the same run. It would not help anyway, because
removing a clientType tag does not delete the deal the sync already created. Creation is undone by
hand, and the tools say so in as many words.
"""
import datetime

import deps  # noqa: F401
import bizdays
import crm
import evidence
import rules
import spec
import store


class Refused(Exception):
    """Nothing was written and nothing will be until the caller changes something."""


def now_iso():
    return bizdays.iso(bizdays.now())


def load(side, record_id):
    """The record as the rules expect to see it — text-cast enums, dates already formatted."""
    recs = evidence.records(side, record_id=record_id)
    if not recs:
        raise Refused("no live record %s on %s. It may be deleted, or the id may belong to another "
                      "board — run find_record again." % (record_id, side))
    return recs[0]


# ── turning a human instruction into the autopilot's proposal shape ────────────────────────────

def proposal(stage=None, fields=None, reason=None):
    """Build the structure `rules.validate` consumes. Confidence is 1.0 throughout: a person said so,
    and the confidence bars are skipped for actor='human' anyway — carrying a number keeps the shape
    identical to the model's so one validator serves both."""
    p = {"field_updates": [], "needs_human": False}
    if stage:
        p["stage_decision"] = {"move": True, "to": spec.enum_value(stage), "confidence": 1.0,
                               "reason": reason}
    for field, value in (fields or {}).items():
        upd = {"field": field, "value": value, "confidence": 1.0}
        # A verdict of Do Not Contact still has to carry the words that asked for it. For the hourly
        # run that is a quote from an email; here it is the reason the person gave.
        if reason:
            upd["quote"] = reason
        p["field_updates"].append(upd)
    return p


def resolve_sets(side, rec, step, overrides=None, now=None):
    """Turn one workflow step's `sets` into concrete values.

    This is what makes `stamp_step` worth having. The step already knows which timestamp records the
    event, which field the follow-up ladder counts from, and who owns it next — so naming the step
    gets all of that right, where setting a date by hand gets the date right and the ladder wrong.

    Returns (fields, stage, notes). `stage` is separated out because a stage change has to go through
    the one-forward clamp rather than in with the field updates. Anything the spec leaves to
    judgement (`judge`), or marks as belonging to a later event (`allow`), is not invented: it is
    reported in `notes` unless `overrides` supplies it.
    """
    now = now or bizdays.now()
    live = crm.fields(side)
    pipe = crm.BOARDS[side]["pipeline"]
    hours = spec.pipeline(pipe)["hours"] if pipe else "09:00–18:00"
    overrides = overrides or {}
    out, notes = {}, []
    stage = None

    sets = spec.step_sets(step)
    # Two passes, and the order matters: a `loop_next` due date counts from an anchor this very step
    # is usually setting (B74 stamps signatureSentAt and dates the L8 chase from it). Resolving in
    # one alphabetical pass reached nextActionDue before signatureSentAt existed and reported the
    # ladder as un-startable on the exact call that starts it.
    ordered = sorted(sets.items(),
                     key=lambda kv: (spec.value_spec(kv[1])[0] == "loop_next", kv[0]))
    for field, vspec in ordered:
        if field in overrides:
            out[field] = overrides[field]
            continue
        if field == "stage":
            kind, payload = spec.value_spec(vspec)
            stage = spec.enum_value(payload) if kind == "enum" else None
            continue
        if field == "stageChangedAt":
            continue          # stamped automatically whenever the stage is written
        if field not in live:
            notes.append("step %s writes `%s`, which does not exist on %s — skipped"
                         % (step["id"], field, side))
            continue
        kind, payload = spec.value_spec(vspec)
        if kind == "allow":
            # The stage authorises this field but the event that fills it has not happened. B74 lists
            # contractSignedAt because the counterparty signs days after the document goes out;
            # stamping it here would mark the contract signed on the day it was sent.
            notes.append("`%s` is authorised at this stage but step %s does not set it — the spec "
                         "marks it as belonging to a later event (\"%s\"). Not written. Pass it in "
                         "`fields` when that event actually happens."
                         % (field, step["id"], step.get("writes")))
            continue
        if kind == "now":
            dt = now
            out[field] = (bizdays.iso_date(dt) if live[field]["type"] == "DATE"
                          else bizdays.iso(dt))
        elif kind == "enum":
            out[field] = spec.enum_value(payload)
        elif kind == "clear":
            out[field] = None
        elif kind == "offset":
            n, unit = payload
            dt = (bizdays.add_business_days(now, n) if unit == "bd"
                  else bizdays.add_calendar_days(now, n))
            dt = bizdays.clamp_to_hours(dt, hours)
            out[field] = (bizdays.iso_date(dt) if live[field]["type"] == "DATE"
                          else bizdays.iso(dt))
        elif kind == "loop_next":
            due = _next_touch_after(side, rec, step, out, now, hours)
            if due:
                out[field] = (bizdays.iso_date(due) if live[field]["type"] == "DATE"
                              else bizdays.iso(due))
            else:
                notes.append("could not date the next follow-up for `%s`: %s has no anchor to count "
                             "from yet" % (field, step.get("loop") or "the ladder"))
        elif kind == "judge":
            notes.append("step %s leaves `%s` to judgement — pass it in `fields` if you want it set"
                         % (step["id"], field))
        else:
            notes.append("step %s sets `%s` to %r, which is not a value this understands — skipped"
                         % (step["id"], field, vspec))
    return out, stage, notes


def _next_touch_after(side, rec, step, pending, now, hours):
    """When the next ladder touch falls, given the anchor this very write is about to set."""
    lid, anchor_key = step.get("loop"), step.get("anchor")
    if not lid or not anchor_key:
        return None
    lp = spec.loop(lid)
    if not lp:
        return None
    if anchor_key.startswith("derived:"):
        anchor = now                      # the event is happening now
    else:
        anchor = bizdays.parse_dt(pending.get(anchor_key) or rec.get(anchor_key))
    if not anchor:
        return None
    try:
        nxt = bizdays.next_touch(lp, anchor, hours, at=now, sla_days=step.get("sla_days"))
    except ValueError:
        return None
    return nxt[2] if nxt else None


# ── the gate ───────────────────────────────────────────────────────────────────────────────────

def plan(side, rec, stage=None, fields=None, reason=None):
    """Validate an instruction. Returns (writes, rejects, flags) — nothing is written."""
    prop = proposal(stage=stage, fields=fields, reason=reason)
    writes, rejects, flags = rules.validate(side, rec, prop, actor="human")

    return writes, rejects, flags


def diff(side, rec, writes):
    live = crm.fields(side)
    out = []
    for field, new in sorted(writes.items()):
        meta = live.get(field) or {}
        row = {"field": field, "label": meta.get("label"), "from": rec.get(field), "to": new}
        if meta.get("option_labels"):
            row["to_means"] = meta["option_labels"].get(new)
            row["from_means"] = meta["option_labels"].get(rec.get(field))
        out.append(row)
    return out


def preview(side, rec, writes, rejects, flags, what, extra=None):
    body = {
        "applied": False,
        "what": what,
        "board": side, "record_id": rec["id"], "name": rec.get("name"),
        "would_write": diff(side, rec, writes),
        "refused": [{"field": f, "value": v, "why": why} for f, v, why in rejects],
        "warnings": flags,
        "preview": "Preview only — nothing has been changed. Call again without preview to apply.",
    }
    if not writes:
        body["preview"] = ("There is nothing to write — either the values already match, or every "
                           "change was refused. Read `refused` before trying again.")
    if extra:
        body.update(extra)
    return body


def apply(side, rec, writes, rejects, flags, principal, what, reason=None, note=None):
    """Write, record, and return what happened."""
    if not writes:
        return preview(side, rec, writes, rejects, flags, what)

    started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    run_id = store.start_run(started, dry_run=False, spec_sha=spec.spec_sha(),
                             watermark_from=None, source="ai",
                             actor=principal.get("email") or "unknown")
    decision_id = store.add_decision(
        run_id, started, board=side, record_id=rec["id"], record_name=rec.get("name"),
        stage_before=rec.get("stage"), stage_after=writes.get("stage"),
        confidence=1.0,
        reason="%s — asked for by %s%s" % (what, principal.get("email"),
                                          (": " + reason) if reason else ""),
        attribution="ai:%s" % principal.get("email"),
        rejects_json=[{"field": f, "value": v, "why": w} for f, v, w in rejects],
        flags_json=flags, applied=0)

    counts = {"scanned": 1, "changed": 1, "stage_moves": 1 if "stage" in writes else 0,
              "fields": len(writes), "notes": 0, "llm": 0, "human": 0, "errors": 0}
    try:
        crm.patch(side, rec["id"], writes)
    except Exception as e:                    # noqa: BLE001
        store.mark_applied(decision_id, False, str(e)[:600])
        counts["errors"] = 1
        counts["changed"] = 0
        store.finish_run(run_id, now_iso(), counts, aborted_reason=str(e)[:300])
        raise Refused("the CRM rejected the change: %s. Nothing was written." % str(e)[:400])

    for field, new in writes.items():
        store.add_field_write(run_id, decision_id, now_iso(), side, rec["id"], field,
                              rec.get(field), new, "ai")
    note_id = None
    if note:
        try:
            note_id, _linked, _failed = crm.create_note(
                note["title"], note["body"], note["targets"])
            counts["notes"] = 1
        except Exception as e:                # noqa: BLE001
            flags.append("the change was written but the note failed: %s" % str(e)[:200])
    store.mark_applied(decision_id, True)
    if note_id:
        store.con().execute("UPDATE decisions SET note_id=? WHERE id=?", (note_id, decision_id))
        store.con().commit()
    store.finish_run(run_id, now_iso(), counts)

    return {
        "applied": True,
        "what": what,
        "board": side, "record_id": rec["id"], "name": rec.get("name"),
        "written": diff(side, rec, writes),
        "refused": [{"field": f, "value": v, "why": why} for f, v, why in rejects],
        "warnings": flags,
        "note_id": note_id,
        "run": run_id,
        "undo": ("This was run %d. To undo it: `revert.py --run %d --apply` on the VM, or ask me to "
                 "with the undo tool." % (run_id, run_id)),
    }


def record_company_change(principal, what, reason, detail):
    """Audit a company-level change. Deliberately not a field_write — see the module docstring."""
    started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    run_id = store.start_run(started, dry_run=False, spec_sha=spec.spec_sha(),
                             watermark_from=None, source="ai",
                             actor=principal.get("email") or "unknown")
    store.add_decision(run_id, started, board="company",
                       record_id=detail.get("company_id") or "(new)",
                       record_name=detail.get("name"),
                       reason="%s — asked for by %s%s" % (what, principal.get("email"),
                                                          (": " + reason) if reason else ""),
                       attribution="ai:%s" % principal.get("email"),
                       flags_json=detail, applied=1, confidence=1.0)
    store.finish_run(run_id, now_iso(), {"scanned": 1, "changed": 1, "fields": 0, "notes": 0,
                                         "stage_moves": 0, "llm": 0, "human": 0, "errors": 0})
    return run_id
