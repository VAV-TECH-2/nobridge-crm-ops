"""Remove the retired stage options. RUN LAST, ON ITS OWN, AND NEVER CHAINED.

  python3 06_remove_old.py            # dry run
  python3 06_remove_old.py --apply    # execute

Refuses to run unless 05_verify.py has passed, because an option removed while a record still
points at it takes that record's stage with it and there is no way back. That is why this is a
separate script rather than the tail of 02: the two are separated by a migration and a proof, and
a single script would invite running them together.
"""
import os
import sys

import schema
import tw
from runner import Run

UPDATE = ("mutation U($input: UpdateOneFieldMetadataInput!){"
          " updateOneField(input:$input){ id options } }")


def main():
    if not os.path.exists("VERIFIED"):
        sys.exit("refusing to run: 05_verify.py has not passed. Run it first.")
    r = Run("06_remove_old", "retired stage options removed")
    objs = r.objects([o for v in schema.OBJECTS.values() for o in v])

    # Read pass first, then the manifest, then the mutations — same fix as 02 and 03, and it
    # matters most here: this is the step rollback.py cannot undo, so the manifest is the only
    # surviving record of what the option lists and defaults used to be.
    before, defaults, plan = {}, {}, []
    for side, obj_names in schema.OBJECTS.items():
        keep = {o["value"] for o in schema.stages_for(side)}
        for obj_name in obj_names:
            fld = objs[obj_name]["fields"]["stage"]
            old = fld.get("options") or []
            before[obj_name] = old
            defaults[obj_name] = fld.get("defaultValue")
            drop = [o for o in old if o["value"] not in keep]
            print(f"  \033[1m{obj_name}\033[0m  {len(drop)} to remove of {len(old)}")
            if not drop:
                r.skip("already clean")
                print()
                continue
            for o in drop:
                print(f"      - {o.get('label')}")
            # The field's default has to go in the SAME mutation. It is 'NEW_LEAD' on three of the
            # four boards — a value this script removes — and the server rejects the whole update
            # rather than quietly dropping the default. Cleared rather than repointed at a v2
            # stage: a record created without an explicit stage arrives with none, joining the 27
            # stageless fulfillment records, instead of being silently filed under Lead.
            update = {"options": [o for o in old if o["value"] in keep]}
            if fld.get("defaultValue") is not None:
                update["defaultValue"] = None
                print(f"      default {fld['defaultValue']} -> null")
            plan.append((obj_name, fld["id"], len(drop), update))
            print()

    r.manifest({"stage_options_before": before, "stage_default_before": defaults})

    for obj_name, fid, n_drop, update in plan:
        r.write(f"{obj_name}: remove {n_drop} retired option(s)"
                + (", clear default" if "defaultValue" in update else ""),
                lambda i=fid, u=update:
                    tw.meta(UPDATE, {"input": {"id": i, "update": u}}))
    r.done()


if __name__ == "__main__":
    main()
