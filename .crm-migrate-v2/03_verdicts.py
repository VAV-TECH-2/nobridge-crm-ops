"""Bring Final Decision to the same eight options on Buy, Sell and Other.

  python3 03_verdicts.py            # dry run
  python3 03_verdicts.py --apply    # execute

Buy has seven today; Sell and Other have three. Do Not Contact is new on all of them, and it is
the reason this script runs BEFORE anything retires Sell's Engagement Status: `Crash Out / DNC`
there is currently the only field in the CRM that can record a company asking not to be
approached again. Retiring it first destroys that, irreversibly, and unlike every other value here
that one has a consequence outside the CRM.
"""
import schema
import tw
from runner import Run

UPDATE = ("mutation U($input: UpdateOneFieldMetadataInput!){"
          " updateOneField(input:$input){ id options } }")


def main():
    r = Run("03_verdicts", f"Final Decision -> {len(schema.VERDICTS)} options")
    objs = r.objects(schema.VERDICT_OBJECTS)

    # Read every board before writing any of them, so a failure on the third still leaves a
    # manifest covering the first two. See the note in 02_stage_options.py — that is not a
    # hypothetical failure mode, it is what happened on 2026-08-09.
    before, plan = {}, []
    for obj_name in schema.VERDICT_OBJECTS:
        fld = objs[obj_name]["fields"].get("finalDecision")
        if not fld:
            raise SystemExit(f"{obj_name} has no `finalDecision` field")
        old = fld.get("options") or []
        before[obj_name] = old
        have = {o["value"] for o in old}
        add = [{"id": f"40404040-1111-4000-8000-{i:012d}", "value": v, "label": l,
                "color": c, "position": len(old) + n}
               for n, (i, (v, l, c)) in enumerate(
                   (i, t) for i, t in enumerate(schema.VERDICTS) if t[0] not in have)]
        print(f"  \033[1m{obj_name}\033[0m  {len(old)} now, {len(add)} to add")
        if not add:
            r.skip("already carries every verdict")
            print()
            continue
        for o in add:
            print(f"      + {o['label']}")
        plan.append((obj_name, fld["id"], add, old + add))
        print()

    r.manifest({"verdicts_before": before})

    for obj_name, fid, add, merged in plan:
        r.write(f"{obj_name}: add {len(add)} verdict(s)",
                lambda i=fid, m=merged:
                    tw.meta(UPDATE, {"input": {"id": i, "update": {"options": m}}}))
    r.done()


if __name__ == "__main__":
    main()
