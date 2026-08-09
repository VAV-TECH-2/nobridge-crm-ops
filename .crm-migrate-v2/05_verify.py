"""Assert every record sits on a v2 stage. Read-only — it has no --apply and cannot write.

  python3 05_verify.py

Exits non-zero if anything is still on a retired value. This is the gate on 06: removing an option
while a record still points at it loses that record's stage with no way back, so 06 refuses to run
unless this has passed.
"""
import json
import sys

import schema
import tw
from runner import Run

PLURAL = {"buyOpportunity": "buyOpportunities", "sellOpportunity": "sellOpportunities",
          "otherOpportunity": "otherOpportunities", "fulfillment": "fulfillments"}


def main():
    r = Run("05_verify", "no record left on a retired stage")
    bad = 0
    for side, obj_names in schema.OBJECTS.items():
        target = {o["value"] for o in schema.stages_for(side)}
        for obj_name in obj_names:
            plural = PLURAL[obj_name]
            recs = _all(plural)
            r.reads += 1
            stale = {}
            for rec in recs:
                # A record with no stage at all is not "stale" — it is unset, which 04 leaves
                # alone deliberately. Sorting it alongside strings is also what blew up here.
                s = rec.get("stage") or "(no stage set)"
                if s != "(no stage set)" and s not in target:
                    stale[s] = stale.get(s, 0) + 1
            if stale:
                bad += sum(stale.values())
                print(f"  \033[31m{obj_name}\033[0m  {sum(stale.values())} still on a retired "
                      f"stage:")
                for k, v in sorted(stale.items()):
                    print(f"      {v:4}  {k}")
            else:
                print(f"  \033[32m{obj_name}\033[0m  all {len(recs)} on v2 stages")
    print()
    if bad:
        print(f"\033[31mFAIL — {bad} record(s) would lose their stage if 06 ran now.\033[0m")
        sys.exit(1)
    print("\033[32mPASS — safe to run 06_remove_old.py\033[0m")
    open("VERIFIED", "w").write("ok")


def _all(plural, page=200):
    """Every record, following the REST cursor.

    `starting_after` takes the opaque `pageInfo.endCursor`, NOT a record id — passing an id gets
    a 400 "Invalid cursor" only once the collection is bigger than one page, so it looks like it
    works on the small boards and fails on the 348-record one.
    """
    out, cursor = [], None
    while True:
        q = f"/{plural}?limit={page}" + (f"&starting_after={cursor}" if cursor else "")
        st, body = tw.rest("GET", q)
        if st != 200:
            raise SystemExit(f"cannot read /{plural} ({st}): {json.dumps(body)[:300]}")
        chunk = body.get("data", {}).get(plural, [])
        out += chunk
        info = body.get("pageInfo") or {}
        if not info.get("hasNextPage") or not chunk:
            return out
        cursor = info["endCursor"]


if __name__ == "__main__":
    main()
