"""Move every record onto its v2 stage.

  python3 04_map_stages.py            # dry run: the exact per-stage counts that would move
  python3 04_map_stages.py --apply    # execute

Most of the map is one-to-one. Two stages are conditional and are the only place this migration
reads a record's data rather than just its stage:

  buy   Stage 1        -> Lead if Outreach Sent At is empty, else Qualified
  sell  Stage 1        -> Target / Contacted / Engaged on outreach and reply
  ful   Reached Out    -> Engaged if Replied At is set, else Approach

Nothing lands in Negotiation: it is a forward-only stage, and back-dating records into it would
invent a history nobody lived.
"""
import json
import schema
import tw
from runner import Run

PLURAL = {"buyOpportunity": "buyOpportunities", "sellOpportunity": "sellOpportunities",
          "otherOpportunity": "otherOpportunities", "fulfillment": "fulfillments"}


def main():
    r = Run("04_map_stages", "every record onto its v2 stage")
    moves, before = [], []

    for side, obj_names in schema.OBJECTS.items():
        smap = schema.STAGE_MAP[side]
        for obj_name in obj_names:
            plural = PLURAL[obj_name]
            recs = _all(plural)
            r.reads += 1
            print(f"  \033[1m{obj_name}\033[0m  {len(recs)} records")
            tally = {}
            for rec in recs:
                cur = rec.get("stage")
                if cur is None:
                    k = "(no stage set) -> left alone"
                    tally[k] = tally.get(k, 0) + 1
                    continue
                if cur not in smap:
                    k = f"{cur} -> UNMAPPED, left alone"
                    tally[k] = tally.get(k, 0) + 1
                    continue
                new = smap[cur] or schema.split_rule(side, rec)
                if new == cur:
                    continue
                before.append({"object": obj_name, "id": rec["id"], "stage": cur})
                moves.append((plural, rec["id"], new))
                k = f"{cur} -> {new}"
                tally[k] = tally.get(k, 0) + 1
            for k in sorted(tally):
                print(f"      {tally[k]:4}  {k}")
            if not tally:
                r.skip("nothing to move")
            # A conditional split that produces one outcome has not split anything. It happens
            # here because the clock is empty: Outreach Sent At and Replied At read 0 of 99 on
            # buy, the engine's values having been cleared on 2026-08-07. Worth saying out loud,
            # because the whole point of splitting Stage 1 was to tell those records apart.
            splits = [k for k in tally if k.split(" -> ")[0] in
                      [c for c, v in smap.items() if v is None]]
            if len(splits) == 1:
                got = splits[0].split(" -> ")[1]
                print(f"      \033[33mnote\033[0m  every record went to {got} — the field this "
                      f"split reads is empty on all of them,")
                print(f"            so the new stages are created but nothing is actually "
                      f"distinguished yet.")
            print()

    # The manifest is written before the first mutation, so rollback always has the old stage of
    # every record this touches.
    r.manifest({"records_before": before})
    for plural, rid, new in moves:
        r.write(f"{plural}/{rid} -> {new}",
                lambda p=plural, i=rid, n=new: tw.rest("PATCH", f"/{p}/{i}", {"stage": n}))
    r.done()


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
