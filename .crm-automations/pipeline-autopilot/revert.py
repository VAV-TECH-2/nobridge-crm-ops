#!/usr/bin/env python3
"""Undo what a run wrote. This is the promise that makes autonomous writing acceptable.

    python3 revert.py --run 12                 # show what reverting run 12 would do
    python3 revert.py --run 12 --apply         # put every field in run 12 back
    python3 revert.py --decision 481 --apply   # just one record
    python3 revert.py --list                   # recent runs

Every write the autopilot makes is recorded with the value that was there before it, so a revert is
a replay of old values through the same REST path - not a guess, and not a restore from a backup.

Two things it deliberately does NOT undo:
  * notes. A note is a record of what was believed at the time and deleting it destroys history;
    the revert prints which notes a run created so they can be removed by hand if wanted.
  * a field a HUMAN has changed since. If the current value is not what the autopilot wrote, the
    write has been superseded and putting the old value back would overwrite a person's work. Those
    are reported and skipped unless --force.
"""
import argparse
import sys

import bizdays
import crm
import store


def _same(current, wrote):
    """Is the record's value still what the autopilot wrote?

    Deliberately tolerant about representation, because a false "changed since" is not a harmless
    caution - it refuses to undo a write that nobody touched. A NUMBER goes out as '5.0' and comes
    back as 5; a DATE_TIME goes out with milliseconds and comes back with an offset.
    """
    if current is None and wrote in (None, "", "None"):
        return True
    if current is None or wrote is None:
        return False
    a, b = str(current), str(wrote)
    if a == b:
        return True
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        pass
    da, dbv = bizdays.parse_dt(a), bizdays.parse_dt(b)
    if da and dbv:
        return abs((da - dbv).total_seconds()) <= 60
    return False


def plan_revert(rows, force=False):
    """[(row, current, action)] where action is 'revert' | 'skip: ...'"""
    out = []
    by_record = {}
    for r in rows:
        key = (r["board"], r["record_id"])
        if key not in by_record:
            try:
                by_record[key] = crm.get_record(r["board"], r["record_id"])
            except Exception as e:                            # noqa: BLE001
                by_record[key] = {"_error": str(e)}
        rec = by_record[key]
        if "_error" in rec:
            out.append((r, None, "skip: cannot read the record (%s)" % rec["_error"][:80]))
            continue
        current = rec.get(r["field"])
        wrote = r["new_value"]
        same = _same(current, wrote)
        if not same and not force:
            out.append((r, current,
                        "skip: changed since (now %r, autopilot wrote %r)" % (current, wrote)))
            continue
        out.append((r, current, "revert"))
    return out


def main():
    ap = argparse.ArgumentParser(description="Undo a Pipeline Autopilot run.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", type=int)
    g.add_argument("--decision", type=int)
    g.add_argument("--list", action="store_true")
    ap.add_argument("--apply", action="store_true", help="actually write (default: show only)")
    ap.add_argument("--force", action="store_true",
                    help="revert even fields a human has changed since")
    args = ap.parse_args()

    if args.list:
        print("%-5s %-20s %-6s %8s %8s %8s %s"
              % ("run", "started", "mode", "records", "fields", "moves", "note"))
        for r in store.recent_runs(25):
            print("%-5s %-20s %-6s %8s %8s %8s %s"
                  % (r["id"], (r["started_at"] or "")[:19], "dry" if r["dry_run"] else "APPLY",
                     r["records_changed"], r["fields_written"], r["stage_moves"],
                     r["aborted_reason"] or ("%d need a human" % (r["needs_human"] or 0))))
        return 0

    if args.run:
        run = store.run(args.run)
        if not run:
            print("no run #%s" % args.run)
            return 1
        if run["dry_run"]:
            print("run #%s was a dry run - it wrote nothing" % args.run)
            return 0
        rows = store.writes_for_run(args.run)
        notes = [d for d in store.decisions_for_run(args.run) if d["note_id"]]
    else:
        rows = store.writes_for_decision(args.decision)
        notes = []

    if not rows:
        print("nothing to revert (already reverted, or nothing was written)")
        return 0

    plan = plan_revert(rows, force=args.force)
    doable = [(r, c, a) for r, c, a in plan if a == "revert"]
    for r, current, action in plan:
        mark = "revert" if action == "revert" else "SKIP  "
        print("%s %-11s %-30s %-18s %r -> %r%s"
              % (mark, r["board"], (r["record_id"] or "")[:8], r["field"],
                 current, r["old_value"],
                 "" if action == "revert" else "   (%s)" % action.split(": ", 1)[1]))

    if notes:
        print("\n%d note(s) were created by this run and are NOT removed (history):" % len(notes))
        for d in notes:
            print("   note %s on %s" % (d["note_id"], d["record_name"]))

    print("\n%d of %d field(s) revertable" % (len(doable), len(plan)))
    if not args.apply:
        print("Re-run with --apply to write.")
        return 0

    now = bizdays.iso(bizdays.now())
    by_record = {}
    for r, _c, _a in doable:
        by_record.setdefault((r["board"], r["record_id"]), []).append(r)

    ok = fail = 0
    for (board, rid), rs in by_record.items():
        data = {}
        for r in rs:
            old = r["old_value"]
            # An empty old value means the field was NULL before the autopilot filled it.
            data[r["field"]] = None if old in (None, "", "None") else old
        try:
            crm.patch(board, rid, data)
            for r in rs:
                store.mark_reverted(r["id"], now)
            ok += len(rs)
        except Exception as e:                                # noqa: BLE001
            fail += len(rs)
            print("   ERROR %s %s: %s" % (board, rid, str(e)[:200]))
    print("\nreverted %d field(s), %d failed" % (ok, fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
