#!/usr/bin/env python3
"""Does the workflow spec still describe the CRM that exists? Read-only; writes nothing.

Every run of the autopilot calls this first, and the result is published on the dashboard. It is
the check whose absence broke clienttype-sync on v2 migration day: that script hardcoded the stage
each new record is created at, the v2 migration deleted those options, and creating a record with a
value that no longer exists fails the whole mutation - so tagging a company silently produced
nothing, for a day, with no error anywhere.

Three questions:
  1. Does every stage the spec names exist as a live option on that board, and vice versa?
  2. Does every field a step claims to write exist as a live column on that board?
  3. When a step writes a literal option value, is that value live?

Exit 0 = clean. Exit 1 = at least one BLOCKER (something the autopilot would try and fail to do).
WARN lines are things a human should know but that do not stop a run.

    python3 preflight.py            # human-readable
    python3 preflight.py --json     # machine-readable, for the dashboard
"""
import json
import sys

import crm
import spec

# Derived anchors/stop-signals: facts that live in the activity data rather than on the record.
# The evidence collector supplies each of these; anything else with a `derived:` prefix is a typo.
DERIVED_KEYS = {
    "last_meeting_end",   # end of the most recent held calendar event
    "meeting_booked",     # a future calendar event exists
    "deliverable_sent",   # the stage's own *SentAt field is populated
    "signed",             # the stage's signature/NDA field came back
    "stage_advanced",     # the record moved on - the only evidence of a yes on some boards
}


# Keys every loop and every step must carry. A hand-edit that drops one is otherwise found only
# when workflow_doc.py raises a KeyError halfway through generating WORKFLOWS.md - which is exactly
# how the missing L7 `escalation` surfaced while this file was being written.
LOOP_KEYS = {"id", "at", "at_mode", "name", "touches", "schedule", "entry", "exit", "on_reply",
             "on_exhaust", "escalation", "used", "today", "stops_on"}
STEP_KEYS = {"id", "name", "stage", "trigger", "timing", "condition", "writes", "owner", "exit",
             "escalation", "who", "loop", "new", "sets"}
STEP_OPTIONAL = {"note", "entry", "anchor", "sla_days", "when"}
WHO_VALUES = {"auto", "approve", "hand"}
AT_MODES = {"absolute", "relative"}


def check_shape(report):
    """Every loop and step carries the same keys. Structural, no CRM involved."""
    for lp in spec.loops():
        missing = LOOP_KEYS - set(lp)
        if missing:
            report["blockers"].append(
                "loop %s is missing %s - workflow_doc.py will crash generating WORKFLOWS.md"
                % (lp.get("id", "?"), ", ".join(sorted(missing))))
        if lp.get("at_mode") not in AT_MODES:
            report["blockers"].append(
                "loop %s has at_mode=%r, not one of %s - its touch dates cannot be computed"
                % (lp.get("id", "?"), lp.get("at_mode"), "/".join(sorted(AT_MODES))))
    for pipe_name in spec.pipelines():
        for st in spec.steps(pipe_name):
            missing = STEP_KEYS - set(st)
            if missing:
                report["blockers"].append(
                    "%s step %s is missing %s"
                    % (pipe_name, st.get("id", "?"), ", ".join(sorted(missing))))
            extra = set(st) - STEP_KEYS - STEP_OPTIONAL
            if extra:
                report["warnings"].append(
                    "%s step %s has unexpected key(s) %s - a typo, or a new key that this check "
                    "and the doc generator both need to know about"
                    % (pipe_name, st.get("id", "?"), ", ".join(sorted(extra))))
            if st.get("who") not in WHO_VALUES:
                report["blockers"].append(
                    "%s step %s has who=%r, not one of %s"
                    % (pipe_name, st.get("id", "?"), st.get("who"), "/".join(sorted(WHO_VALUES))))


def check():
    report = {"spec": spec.spec_path(), "spec_sha": spec.spec_sha(),
              "blockers": [], "warnings": [], "boards": {}}
    check_shape(report)

    for side, board in crm.BOARDS.items():
        pipe = board["pipeline"]
        live = crm.fields(side)
        live_stages = set(crm.stage_options(side))
        entry = {"pipeline": pipe, "live_stages": sorted(live_stages),
                 "spec_stages": [], "missing_stages": [], "extra_stages": [],
                 "missing_fields": [], "bad_values": [], "automated": bool(pipe)}

        if not pipe:
            report["warnings"].append(
                "%s: no pipeline in the spec - derived activity fields and notes only, never a "
                "stage move. Its stages (%s) are pre-v2 and describe nothing the spec knows about."
                % (side, ", ".join(sorted(live_stages))))
            report["boards"][side] = entry
            continue

        # 1. stages, both directions
        spec_stages = spec.stage_enums(pipe)
        entry["spec_stages"] = spec_stages
        entry["missing_stages"] = [s for s in spec_stages if s not in live_stages]
        entry["extra_stages"] = sorted(live_stages - set(spec_stages))
        for s in entry["missing_stages"]:
            report["blockers"].append(
                "%s: spec stage %s has no live option - a promote to it would fail the whole "
                "request" % (side, s))
        for s in entry["extra_stages"]:
            report["warnings"].append(
                "%s: live option %s is not in the spec - records sitting there will never be "
                "moved by any rule" % (side, s))

        # 2 + 3. fields and literal values
        seen_fields = {}
        for step in spec.steps(pipe):
            for fname, value in spec.step_sets(step).items():
                seen_fields.setdefault(fname, []).append((step["id"], value))

        for fname, uses in sorted(seen_fields.items()):
            meta = live.get(fname)
            if meta is None:
                ids = ", ".join(sorted({sid for sid, _v in uses}))
                entry["missing_fields"].append({"field": fname, "steps": ids})
                report["blockers"].append(
                    "%s: no field %r, written by %s" % (side, fname, ids))
                continue
            for sid, value in uses:
                kind, payload = spec.value_spec(value)
                if kind == "unknown":
                    entry["bad_values"].append(
                        {"field": fname, "value": value, "step": sid, "why": "unknown value spec"})
                    report["blockers"].append(
                        "%s: %s sets %s = %r, which is not one of %s"
                        % (side, sid, fname, value, "/".join(spec.VALUE_KINDS)))
                    continue
                # A literal option must actually exist on THIS board.
                if kind == "enum":
                    ev = spec.enum_value(payload)
                    if ev not in meta["options"]:
                        entry["bad_values"].append(
                            {"field": fname, "value": value, "enum": ev, "step": sid,
                             "why": "not a live option"})
                        report["blockers"].append(
                            "%s: %s sets %s = %r -> %s, not a live option (have: %s)"
                            % (side, sid, fname, payload, ev, " ".join(meta["options"])))
                        continue
                # And the kind must suit the field's type.
                allowed = spec.KIND_TYPES.get(kind)
                if allowed and meta["type"] not in allowed:
                    entry["bad_values"].append(
                        {"field": fname, "value": value, "step": sid,
                         "why": "%s is %s, not %s" % (fname, meta["type"], "/".join(allowed))})
                    report["blockers"].append(
                        "%s: %s sets %s = %r but %s is a %s field, not %s"
                        % (side, sid, fname, value, fname, meta["type"], "/".join(allowed)))

        # 3b. Does each step's `sets` agree with its own prose about what it STAMPS?
        #
        # `sets` does double duty - what a step writes, AND the allowlist for that stage - so a step
        # has to list fields belonging to events that happen LATER in the same stage. Marked "now",
        # such a field reads as "this step stamps it", and something eventually will: B74 "Out for
        # signature" listed contractSignedAt as "now", which meant recording the send marked the
        # contract SIGNED. "allow" is how a field says authorised-but-not-by-me; this is the check
        # that notices the next time somebody reaches for "now" instead.
        #
        # The prose is the tell: a clause with a value ("Signature Sent At = now") is this event, one
        # without ("Contract Signed At on return") is not. It is a WARNING and not a blocker because
        # prose is an incomplete description on purpose - a step's due date is declared in its `owner`
        # column, not in `writes` - so this is gated on "now" only. Widening it to "offset" would fire
        # on five steps whose nextActionDue is perfectly correct.
        for step in spec.steps(pipe):
            claimed = {spec.api_name(lbl) for lbl, val in spec.writes_fields(step)
                       if val is not None}
            for fname, value in spec.step_sets(step).items():
                if fname in ("stage", "stageChangedAt") or fname not in live:
                    continue
                if spec.value_spec(value)[0] != "now" or fname in claimed:
                    continue
                report["warnings"].append(
                    "%s: %s stamps %s = now, but its own description (%r) does not say so - if that "
                    "field belongs to a later event, mark it \"allow\" instead"
                    % (side, step["id"], fname, step.get("writes")))

        # Step anchors: a loop's timing counts from one of these, so a bad one silently mis-times a
        # whole ladder rather than failing loudly.
        for step in spec.steps(pipe):
            anchor = step.get("anchor")
            if not anchor:
                if step.get("loop"):
                    report["warnings"].append(
                        "%s: %s cites loop %s but has no `anchor` - its schedule cannot be timed"
                        % (side, step["id"], step["loop"]))
                continue
            if anchor.startswith("derived:"):
                if anchor.split(":", 1)[1] not in DERIVED_KEYS:
                    report["blockers"].append(
                        "%s: %s anchors on %r, which the evidence collector does not supply "
                        "(known: %s)" % (side, step["id"], anchor,
                                         " ".join(sorted(DERIVED_KEYS))))
            elif anchor not in live:
                report["blockers"].append(
                    "%s: %s anchors on %r, which is not a field on this board"
                    % (side, step["id"], anchor))

        # `when` is a step's entry condition; its field and any literal options must be live.
        for step in spec.steps(pipe):
            when = step.get("when")
            if not when:
                continue
            wf = when.get("field")
            meta = live.get(wf)
            if meta is None:
                report["blockers"].append(
                    "%s: %s has when on %r, which is not a field on this board"
                    % (side, step["id"], wf))
                continue
            for v in when.get("in", []):
                ev = spec.enum_value(v)
                if ev not in meta["options"]:
                    report["blockers"].append(
                        "%s: %s has when %s in %r -> %s, not a live option"
                        % (side, step["id"], wf, v, ev))

        report["boards"][side] = entry

    # Which boards actually cite each loop, derived from the steps rather than trusted from the
    # loop's own `used` list. The spec's header warned that nothing checked these agreed; this is
    # what checks. (It found one: L7 was cited by fulfillment's F61 but declared buy/sell only.)
    cited = {}
    for pipe_name in spec.pipelines():
        for step in spec.steps(pipe_name):
            if step.get("loop"):
                cited.setdefault(step["loop"], set()).add(pipe_name)

    for lp in spec.loops():
        actual = sorted(cited.get(lp["id"], ()))
        declared = sorted(lp.get("used", []))
        if actual != declared:
            report["warnings"].append(
                "loop %s declares used=%s but is cited by %s - the two must agree"
                % (lp["id"], ",".join(declared) or "(none)", ",".join(actual) or "(none)"))

        stops = lp.get("stops_on")
        if not stops:
            report["warnings"].append(
                "loop %s (%s) has no `stops_on` - nothing tells the autopilot when it ends"
                % (lp["id"], lp["name"]))
            continue

        # Boards that genuinely run this loop, by citation, not declaration.
        sides = [s for s, b in crm.BOARDS.items() if b["pipeline"] in actual]
        for signal in stops:
            if signal.startswith("derived:"):
                if signal.split(":", 1)[1] not in DERIVED_KEYS:
                    report["blockers"].append(
                        "loop %s stops on %r, which the evidence collector does not supply"
                        % (lp["id"], signal))
                continue
            # A stop signal is a signal, not a requirement: a board without the column simply
            # cannot raise it (termsAgreedAt ends a negotiation chase on buy/sell; on fulfillment
            # the same loop ends on `outcome`). So it must exist SOMEWHERE it is used - existing
            # nowhere is a typo - and absences are reported so they stay visible.
            present = [s for s in sides if signal in crm.fields(s)]
            if not present:
                report["blockers"].append(
                    "loop %s stops on %r, which exists on none of the boards that use it (%s)"
                    % (lp["id"], signal, ", ".join(sides) or "none"))
            elif len(present) < len(sides):
                absent = [s for s in sides if s not in present]
                report["warnings"].append(
                    "loop %s stops on %r, which %s %s not have - those boards end it another way"
                    % (lp["id"], signal, ", ".join(absent),
                       "does" if len(absent) == 1 else "do"))
    return report


def main():
    report = check()
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2))
        return 1 if report["blockers"] else 0

    print("spec: %s" % report["spec"])
    print("sha256: %s\n" % report["spec_sha"][:16])
    for side, e in report["boards"].items():
        head = "%-12s" % side
        if not e["automated"]:
            print("%s  no spec pipeline - fields and notes only" % head)
            continue
        print("%s  %d spec stages, %d live" % (head, len(e["spec_stages"]), len(e["live_stages"])))
        for s in e["missing_stages"]:
            print("               BLOCKER stage %s missing from the CRM" % s)
        for s in e["extra_stages"]:
            print("               warn    live stage %s is in no rule" % s)
        for m in e["missing_fields"]:
            print("               BLOCKER no field %-22s (steps %s)" % (m["field"], m["steps"]))
        for b in e["bad_values"]:
            print("               BLOCKER %s sets %s = %r  (%s)"
                  % (b["step"], b["field"], b["value"], b.get("why", "invalid")))

    other = [w for w in report["warnings"] if not w.startswith(tuple(crm.BOARDS))]
    if other:
        print("")
        for w in other:
            print("warn  %s" % w)

    print("\n%d blocker(s), %d warning(s)" % (len(report["blockers"]), len(report["warnings"])))
    return 1 if report["blockers"] else 0


if __name__ == "__main__":
    sys.exit(main())
