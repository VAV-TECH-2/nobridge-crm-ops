"""Restore from a manifest written by 01-04.

  python3 rollback.py manifests/<file>.json            # dry run
  python3 rollback.py manifests/<file>.json --apply    # execute

Handles what each script recorded: stage options as they were, verdict options as they were, and
every record's previous stage. It cannot undo 06 — removing an option destroys it, and the
records that pointed at it are already gone by then. That asymmetry is the reason 06 is gated on
05 rather than trusted to a rollback.
"""
import json
import sys

import tw
from runner import Run

UPDATE = ("mutation U($input: UpdateOneFieldMetadataInput!){"
          " updateOneField(input:$input){ id options } }")
PLURAL = {"buyOpportunity": "buyOpportunities", "sellOpportunity": "sellOpportunities",
          "otherOpportunity": "otherOpportunities", "fulfillment": "fulfillments"}


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith("--"):
        sys.exit(__doc__)
    man = json.load(open(sys.argv[1]))
    r = Run("rollback", f"restore from {sys.argv[1]}")
    objs = r.objects()

    for key, field in (("stage_options_before", "stage"),
                       ("verdicts_before", "finalDecision")):
        for obj_name, opts in (man.get(key) or {}).items():
            fid = objs[obj_name]["fields"][field]["id"]
            r.write(f"{obj_name}.{field} -> {len(opts)} option(s)",
                    lambda i=fid, m=opts:
                        tw.meta(UPDATE, {"input": {"id": i, "update": {"options": m}}}))

    for rec in man.get("records_before") or []:
        plural = PLURAL[rec["object"]]
        r.write(f"{plural}/{rec['id']} -> {rec['stage']}",
                lambda p=plural, i=rec["id"], s=rec["stage"]:
                    tw.rest("PATCH", f"/{p}/{i}", {"stage": s}))

    for c in man.get("created") or []:
        print(f"    \033[90mnote\033[0m  field {c['object']}.{c['label']} was created by 01 — "
              f"delete it in the CRM if you want it gone")
    r.done()


if __name__ == "__main__":
    main()
