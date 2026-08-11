#!/usr/bin/env python3
"""Pipeline Autopilot — reads email, meetings and calls; keeps the CRM records true.

    python3 autopilot.py                     # DRY RUN: print the whole plan, write nothing
    python3 autopilot.py --apply             # execute
    python3 autopilot.py --board fulfillment --limit 20
    python3 autopilot.py --record <uuid> -v  # one record, with its evidence and raw model reply
    python3 autopilot.py --no-judge          # deterministic layer only, no model calls

PLAN THEN APPLY. Nothing is written until the entire plan is built and the circuit breaker has
looked at it, so a bad ruleset or a bad prompt cannot rewrite a board one record at a time. Same
shape as clienttype-sync (sync.py:176-271), for the same reason.

DRY RUN IS SIDE-EFFECT FREE, WATERMARK INCLUDED. A dry run that moved the watermark would make the
next real run skip everything it had only pretended to do — the mistake Call Intelligence made on
its first deploy and now documents at reconciler.ts:239-240.
"""
import argparse
import concurrent.futures
import json
import os
import sys
import traceback

import bizdays
import crm
import evidence
import preflight
import rules
import spec
import store

# How far behind the stored watermark to re-read. Gmail sync, calendar sync and Call Intelligence
# all land late; a record touched at 10:59 can appear after an 11:00 run.
LOOKBACK_MINUTES = int(os.environ.get("AUTOPILOT_LOOKBACK_MINUTES", "240"))
BACKFILL_DAYS = int(os.environ.get("AUTOPILOT_BACKFILL_DAYS", "14"))
MAX_LLM_CALLS = int(os.environ.get("AUTOPILOT_MAX_LLM_CALLS_PER_RUN", "60"))
# Concurrency for the judgement calls. Each one is an independent read of one record,
# so this is bounded only by the deployment's throughput, not by correctness.
JUDGE_WORKERS = int(os.environ.get("AUTOPILOT_JUDGE_WORKERS", "5"))

# The circuit breaker. A run that would move this much of what it looked at is not doing its job,
# it is having an accident.
BREAKER_PCT = float(os.environ.get("AUTOPILOT_BREAKER_PCT", "0.15"))
BREAKER_ABS = int(os.environ.get("AUTOPILOT_BREAKER_ABS", "25"))
# Below this many records scanned, the percentage test is switched off: a proportion of a
# handful is noise, and it aborted a legitimate single-record run.
BREAKER_MIN_SAMPLE = int(os.environ.get("AUTOPILOT_BREAKER_MIN_SAMPLE", "20"))
# Placing a record that had NO stage is not the same risk as moving one that had a stage,
# so it gets its own, looser cap. There are 72 such records to work through.
BREAKER_PLACEMENT_ABS = int(os.environ.get("AUTOPILOT_BREAKER_PLACEMENT_ABS", "80"))

LOG_PATH = os.environ.get("AUTOPILOT_LOG", "/home/azureuser/pipeline-autopilot.log")


def log_line(text):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError:
        pass          # a laptop dry run has nowhere to write; that is not a failure


def build_plan(args, since, judge=None):
    """Everything that would change, board by board. Writes nothing."""
    multi = evidence.company_boards()
    plan, counts = [], {"scanned": 0, "llm": 0, "errors": 0}
    sides = [args.board] if args.board else list(crm.BOARDS)

    for side in sides:
        recs = evidence.records(side, record_id=args.record)
        if not recs:
            continue
        act = evidence.activity(side)
        mtg = evidence.meetings(side)
        fresh = evidence.new_activity(side, since) if since else {}
        # Records that get their mail read, and a model call: those with new activity, plus any with
        # no stage at all. A stage-less record is invisible on the kanban and may never receive
        # another email, so waiting for the watermark to notice it would mean waiting for ever - and
        # it needs its history read to be placed anywhere sensible.
        stageless = [r["id"] for r in recs
                     if r.get("stage") is None and crm.BOARDS[side]["pipeline"]]
        rids_read = sorted({r["id"] for r in recs if r["id"] in fresh} | set(stageless))
        th = evidence.threads(side, rids_read) if rids_read else {}
        company_ids = [r["companyId"] for r in recs if r.get("companyId")]
        call_by_company = evidence.calls(company_ids)

        for rec in recs:
            counts["scanned"] += 1
            rid = rec["id"]
            a, m = act.get(rid), mtg.get(rid)
            item = {"side": side, "record": rec, "activity": a, "meetings": m,
                    "new": fresh.get(rid), "threads": th.get(rid, []),
                    "calls": call_by_company.get(rec.get("companyId"), []),
                    "writes": {}, "sources": {}, "rejects": [], "flags": [],
                    "loop": None, "proposal": None, "note": None,
                    "attribution": side}

            # ── deterministic, for every record: this is what replaces the two 06:30 cron jobs
            det = rules.derive(side, rec, a, m)
            for k, v in det.items():
                item["writes"][k] = v
                item["sources"][k] = "deterministic"

            item["loop"] = rules.loop_state(side, rec, a, m)
            lw, lf = rules.loop_writes(side, rec, item["loop"])
            for k, v in lw.items():
                item["writes"][k] = v
                item["sources"][k] = "loop"
            item["flags"].extend(lf)

            item["needs_stage"] = bool(rec.get("stage") is None
                                       and crm.BOARDS[side]["pipeline"])
            if item["needs_stage"]:
                item["flags"].append(
                    "no stage at all - invisible on the kanban until one is set")

            # ── judgement, only where there is something new to judge
            ambiguous = rec.get("companyId") in multi
            if ambiguous:
                item["attribution"] = "ambiguous:" + ",".join(multi[rec["companyId"]])
                item["ambiguous_boards"] = multi[rec["companyId"]]
            plan.append(item)

    # Judgement runs CONCURRENTLY. gpt-5-mini is a reasoning model: a single record takes 30-60s,
    # so judging 60 records one after another takes longer than the hour between runs. The calls are
    # independent - each sees one record - so a small pool is safe, and 429s are already retried
    # inside judge.call().
    todo = [i for i in plan if judge and (i["new"] or i.get("needs_stage"))][:MAX_LLM_CALLS]
    if todo:
        n_stageless = sum(1 for i in todo if i.get("needs_stage"))
        print("judging %d record(s) (%d with new activity, %d with no stage), %d at a time..."
              % (len(todo), len(todo) - n_stageless, n_stageless, JUDGE_WORKERS), flush=True)
        _run_judgement(todo, judge, counts, args)

    # Merge each proposal through the validator, and drop records with nothing to say.
    for item in plan:
        prop = item.get("proposal")
        if prop:
            w, rj, fl = rules.validate(item["side"], item["record"], prop, loop=item["loop"])
            for k, v in w.items():
                # Deterministic facts win over judgement on the same field.
                if item["sources"].get(k) == "deterministic":
                    rj.append((k, v, "deterministic value takes precedence"))
                    continue
                item["writes"][k] = v
                item["sources"][k] = "judge"
            item["rejects"].extend(rj)
            item["flags"].extend(fl)
            if (prop.get("note") or {}).get("should_write"):
                item["note"] = prop["note"]

    return [i for i in plan if i["writes"] or i["flags"] or i["note"]], counts


def _run_judgement(todo, judge, counts, args):
    """Fill in item['proposal'] for each record, in parallel."""
    done = [0]

    def one(item):
        try:
            item["proposal"] = judge.judge(
                item["side"], item["record"], item,
                ambiguous_boards=item.get("ambiguous_boards"))
            counts["llm"] += 1
        except Exception as e:                                # noqa: BLE001
            counts["errors"] += 1
            item["flags"].append("judgement failed: %s" % str(e)[:300])
            if args.verbose:
                traceback.print_exc()
        finally:
            done[0] += 1
            print("   judged %d/%d  %s" % (done[0], len(todo),
                                           (item["record"].get("name") or "")[:40]), flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=JUDGE_WORKERS) as pool:
        list(pool.map(one, todo))


def breaker_tripped(plan, scanned):
    """Is this run about to have an accident? (reason|None, number of stage moves)

    The absolute cap always applies. The PERCENTAGE only applies to a run big enough for a
    proportion to mean anything: `--record <id>` scans one record, and one move out of one is 100%,
    which tripped the breaker on a deliberate single-record run and aborted it. A proportion of a
    sample of one is not a signal.
    """
    staged = [i for i in plan if "stage" in i["writes"]]
    moves = sum(1 for i in staged if i["record"].get("stage"))
    placements = len(staged) - moves
    if moves > BREAKER_ABS:
        return "would move %d records (cap %d)" % (moves, BREAKER_ABS), moves
    if placements > BREAKER_PLACEMENT_ABS:
        return ("would place %d stage-less records at once (cap %d)"
                % (placements, BREAKER_PLACEMENT_ABS), moves)
    if scanned >= BREAKER_MIN_SAMPLE and moves / float(scanned) > BREAKER_PCT:
        return ("would move %d of %d records scanned (%.0f%%, cap %.0f%%)"
                % (moves, scanned, 100.0 * moves / scanned, 100 * BREAKER_PCT), moves)
    return None, moves


def print_plan(plan, verbose=False):
    for i in plan:
        rec = i["record"]
        head = "%-11s %-34s %s" % (i["side"], (rec.get("name") or "")[:34], rec.get("stage") or "-")
        print("\n" + head)
        if i["new"]:
            n = i["new"]
            print("   new mail: %s (%s in, %s out)" % (n["n"], n["n_in"], n["n_out"]))
        if i["loop"]:
            lp = i["loop"]
            print("   loop:     %s %s · touch %s/%s · next %s%s"
                  % (lp["loop"], lp["loop_name"], lp["elapsed"], lp["touches"],
                     (lp["next_due"] or "-")[:16],
                     " · EXHAUSTED" if lp["exhausted"] else ""))
        for field, value in sorted(i["writes"].items()):
            old = rec.get(field)
            print("   write:    %-18s %-24r -> %r  [%s]"
                  % (field, old, value, i["sources"].get(field, "?")))
        if i["note"]:
            print("   note:     %s" % (i["note"].get("title") or "")[:80])
        for f, v, why in i["rejects"]:
            print("   refused:  %-18s %-20r %s" % (f, v, why))
        for f in i["flags"]:
            print("   flag:     %s" % f)
        if verbose and i["proposal"]:
            print("   model:    %s" % json.dumps(i["proposal"], indent=2)[:2000])
        if verbose and i["threads"]:
            for m in i["threads"][:4]:
                print("   mail:     %s %-4s %s" % (m["at"][:16], "OUT" if m["outbound"] else "IN",
                                                   (m["subject"] or "")[:60]))


def apply_plan(plan, run_id, now_iso, today):
    counts = {"changed": 0, "stage_moves": 0, "fields": 0, "notes": 0, "errors": 0, "human": 0}
    for i in plan:
        rec, side = i["record"], i["side"]
        rid = rec["id"]
        writes = dict(i["writes"])

        # One stage move per record per day, however many runs happen in between.
        if "stage" in writes and store.stage_moves_today(rid, today):
            target = writes["stage"]
            i["rejects"].append(("stage", target, "already moved once today"))
            i["flags"].append("stage move held back: this record already moved today")
            writes.pop("stage", None)
            writes.pop("stageChangedAt", None)
            # Anything only legal BECAUSE of the target stage has to go with it. A verdict written
            # onto a record that did not actually close leaves it reading as decided while sitting
            # mid-pipeline - which is worse than either outcome on its own.
            only_there = (set(rules.allowed_fields(side, rec, target_stage=target))
                          - set(rules.allowed_fields(side, rec)))
            for f in sorted(only_there & set(writes)):
                i["rejects"].append((f, writes.pop(f),
                                     "only applies at %s, and the move was held back" % target))

        needs_human = bool(i["flags"]) or bool((i["proposal"] or {}).get("needs_human"))
        decision_id = store.add_decision(
            run_id, now_iso, board=side, record_id=rid, record_name=rec.get("name"),
            stage_before=rec.get("stage"), stage_after=writes.get("stage"),
            loop_id=(i["loop"] or {}).get("loop"),
            loop_touch=None if not i["loop"] else "%s/%s" % ((i["loop"]["elapsed"]),
                                                             i["loop"]["touches"]),
            confidence=((i["proposal"] or {}).get("stage_decision") or {}).get("confidence"),
            reason=((i["proposal"] or {}).get("stage_decision") or {}).get("reason"),
            needs_human=1 if needs_human else 0,
            human_reason=(i["proposal"] or {}).get("human_reason"),
            attribution=i["attribution"],
            evidence_json={"activity": i["activity"], "meetings": i["meetings"],
                           "new": i["new"], "threads": i["threads"], "calls": i["calls"]},
            llm_json=i["proposal"], rejects_json=i["rejects"], flags_json=i["flags"],
            applied=0)
        if needs_human:
            counts["human"] += 1

        if not writes and not i["note"]:
            store.mark_applied(decision_id, applied=True)
            continue

        try:
            if writes:
                crm.patch(side, rid, writes)
                for field, value in writes.items():
                    store.add_field_write(run_id, decision_id, now_iso, side, rid, field,
                                          rec.get(field), value,
                                          i["sources"].get(field, "judge"))
                counts["fields"] += len(writes)
                if "stage" in writes:
                    counts["stage_moves"] += 1
            if i["note"]:
                targets = [(crm.BOARDS[side]["note_field"], rid)]
                if rec.get("companyId"):
                    targets.append(("targetCompanyId", rec["companyId"]))
                if rec.get("pointOfContactId"):
                    targets.append(("targetPersonId", rec["pointOfContactId"]))
                note_id, _linked, _failed = crm.create_note(
                    i["note"].get("title") or "Pipeline Autopilot",
                    i["note"].get("markdown") or "", targets)
                store.con().execute("UPDATE decisions SET note_id=? WHERE id=?",
                                    (note_id, decision_id))
                store.con().commit()
                counts["notes"] += 1
            counts["changed"] += 1
            store.mark_applied(decision_id, applied=True)
        except Exception as e:                                # noqa: BLE001
            counts["errors"] += 1
            store.mark_applied(decision_id, applied=False, error=str(e)[:500])
            print("   ERROR %s %s: %s" % (side, rec.get("name"), str(e)[:300]))
    return counts


def main():
    ap = argparse.ArgumentParser(description="Keep the CRM's records true to its workflow.")
    ap.add_argument("--apply", action="store_true", help="write to the CRM (default is a dry run)")
    ap.add_argument("--board", choices=list(crm.BOARDS), help="one board only")
    ap.add_argument("--record", help="one record id only")
    ap.add_argument("--limit", type=int, help="stop after N planned changes (dry runs)")
    ap.add_argument("--since", help="override the watermark, e.g. 2026-08-01")
    ap.add_argument("--all", action="store_true",
                    help="treat every record as fresh, not just those with new activity")
    ap.add_argument("--no-judge", action="store_true", help="deterministic layer only")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    dry = not args.apply

    # 1. Does the spec still describe the CRM? A blocker means a write would fail anyway.
    report = preflight.check()
    if report["blockers"]:
        print("PREFLIGHT FAILED - refusing to run:")
        for b in report["blockers"]:
            print("  BLOCKER", b)
        log_line("[%s] preflight failed: %d blockers"
                 % (bizdays.iso(bizdays.now()), len(report["blockers"])))
        return 1
    for w in report["warnings"]:
        if args.verbose:
            print("warn:", w)

    now = bizdays.now()
    now_iso = bizdays.iso(now)
    stored = store.get(store.WATERMARK)
    if args.since:
        since = bizdays.parse_dt(args.since)
    elif args.all:
        since = None
    elif stored:
        since = bizdays.parse_dt(stored) - bizdays.timedelta(minutes=LOOKBACK_MINUTES)
    else:
        since = now - bizdays.timedelta(days=BACKFILL_DAYS)

    judge = None
    if not args.no_judge:
        try:
            import judge as judge_mod
            judge = judge_mod
        except Exception as e:                                # noqa: BLE001
            print("judgement layer unavailable (%s); deterministic only" % e)

    run_id = store.start_run(now_iso, dry, report["spec_sha"], stored)
    print("run #%d %s | spec %s | since %s"
          % (run_id, "DRY RUN" if dry else "APPLY", report["spec_sha"][:12],
             bizdays.iso(since)[:16] if since else "(everything)"))

    plan, counts = build_plan(args, since if not args.all else None, judge=judge)
    if args.limit:
        plan = plan[:args.limit]

    reason, moves = breaker_tripped(plan, counts["scanned"])
    print_plan(plan, verbose=args.verbose)

    placements = sum(1 for i in plan
                     if "stage" in i["writes"] and not i["record"].get("stage"))
    print("\n%d records scanned · %d with changes · %d stage moves · %d placed (had no stage) · "
          "%d model calls · %d errors"
          % (counts["scanned"], len(plan), moves, placements, counts["llm"], counts["errors"]))

    if reason:
        print("\nCIRCUIT BREAKER: %s\nNothing was written. Investigate before re-running." % reason)
        store.finish_run(run_id, bizdays.iso(bizdays.now()), counts, aborted_reason=reason)
        log_line("[%s] run %d ABORTED: %s" % (now_iso, run_id, reason))
        return 1

    if dry:
        print("\nDRY RUN - nothing written, watermark not advanced.")
        store.finish_run(run_id, bizdays.iso(bizdays.now()), counts)
        return 0

    applied = apply_plan(plan, run_id, now_iso, now.date().isoformat())
    counts.update(applied)
    # The watermark advances only on a clean pass: a record that errored was never recorded, so it
    # is retried next run - but only while it is still inside the query window.
    watermark_to = now_iso if counts["errors"] == 0 else None
    if watermark_to:
        store.put(store.WATERMARK, watermark_to)
    store.finish_run(run_id, bizdays.iso(bizdays.now()), counts, watermark_to=watermark_to)

    summary = ("[%s] run %d applied: %d records, %d fields, %d stage moves, %d notes, "
               "%d need a human, %d errors%s"
               % (now_iso, run_id, counts["changed"], counts["fields"], counts["stage_moves"],
                  counts["notes"], counts["human"], counts["errors"],
                  "" if watermark_to else " (watermark HELD)"))
    print("\n" + summary)
    log_line(summary)
    return 1 if counts["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
