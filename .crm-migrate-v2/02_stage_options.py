"""Add the v2 stage options to each board, KEEPING the old ones.

  python3 02_stage_options.py            # dry run
  python3 02_stage_options.py --apply    # execute

Old and new co-exist until 04 has moved every record and 05 has verified it. 06 removes the old
ones, and only 06 — the same order .crm-sales-engine/migrate_stages.py used for the last stage
change, and for the same reason: a record pointing at an option that no longer exists is not
recoverable from the CRM.
"""
import json
import schema
import tw
from runner import Run

UPDATE = ("mutation U($input: UpdateOneFieldMetadataInput!){"
          " updateOneField(input:$input){ id options } }")


def main():
    r = Run("02_stage_options", "v2 stage options added alongside the old ones")
    objs = r.objects([o for v in schema.OBJECTS.values() for o in v])

    # Read pass over every board FIRST, so the manifest is complete before anything is written.
    # This used to write the manifest after the mutation loop, which is not what RUNBOOK §8
    # promises and not merely academic: the 2026-08-09 apply aborted on sellOpportunity's
    # malformed option ids having already changed buy and other, and produced no manifest at all.
    # A rollback record that only exists once every board succeeded is no rollback record.
    before, plan = {}, []
    for side, obj_names in schema.OBJECTS.items():
        target = schema.stages_for(side)
        for obj_name in obj_names:
            fld = objs[obj_name]["fields"].get("stage")
            if not fld:
                raise SystemExit(f"{obj_name} has no `stage` field")
            old = fld.get("options") or []
            before[obj_name] = old
            have = {o["value"] for o in old}
            add = [o for o in target if o["value"] not in have]
            print(f"  \033[1m{obj_name}\033[0m  {len(old)} options now, "
                  f"{len(add)} to add, {len(old) + len(add)} after")
            if not add:
                r.skip("already carries every v2 stage")
                print()
                continue
            merged = old + [{k: v for k, v in o.items()}
                            for o in _reposition(add, len(old))]
            plan.append((obj_name, fld["id"], add, merged))
            print()

    r.manifest({"stage_options_before": before})

    for obj_name, fid, add, merged in plan:
        r.write(f"{obj_name}: add {len(add)}: " + ", ".join(o["label"] for o in add),
                lambda i=fid, m=merged:
                    tw.meta(UPDATE, {"input": {"id": i, "update": {"options": m}}}))
    r.done()


def _reposition(opts, offset):
    return [dict(o, position=offset + i) for i, o in enumerate(opts)]


if __name__ == "__main__":
    main()
