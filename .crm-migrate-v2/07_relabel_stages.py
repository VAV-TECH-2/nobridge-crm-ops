"""Bring every stage option's label and position into line with the spec.

  python3 07_relabel_stages.py            # dry run
  python3 07_relabel_stages.py --apply    # execute

Values are NOT touched, so no record's stage changes and this cannot orphan anything. It is
presentation only — but two parts of that presentation are load-bearing:

**Position.** `02` appended the v2 options after the old ones and `06` then removed the old ones
out of the middle, so the surviving positions have gaps in the wrong order. Buy renders as
`Strategy · Revamps · Lead · Qualified · …` — the two stages kept from the old set sort to the
front because their positions (2 and 4) predate everything added later. A kanban whose columns run
in the wrong order misrepresents the pipeline to everyone reading it. All four boards are affected,
including fulfillment.

**Label.** `02` only adds options whose *value* is missing, so `STRATEGY` and `REVAMPS` — kept by
v2 — never received their v2 labels and still read `Stage 3 · Strategy / Value Creation` and
`Stage 5 · Revamps` on buy, sell and other.

Everything comes from `schema.stages_for(side)`, matched on value, so this stays correct if the
spec's stage names or order change: regenerate and re-run.
"""
import schema
import tw
from runner import Run

UPDATE = ("mutation U($input: UpdateOneFieldMetadataInput!){"
          " updateOneField(input:$input){ id options } }")


def main():
    r = Run("07_relabel_stages", "stage option labels and positions matched to the spec")
    objs = r.objects([o for v in schema.OBJECTS.values() for o in v])

    before, plan = {}, []
    for side, obj_names in schema.OBJECTS.items():
        want = {o["value"]: o for o in schema.stages_for(side)}
        for obj_name in obj_names:
            fld = objs[obj_name]["fields"]["stage"]
            old = fld.get("options") or []
            before[obj_name] = old

            unknown = [o["value"] for o in old if o["value"] not in want]
            if unknown:
                raise SystemExit(f"{obj_name} carries stage value(s) the spec does not define: "
                                 f"{unknown}. Run 05_verify.py — this should be impossible after 06.")

            # Label and position only. Colour is deliberately left as it is: `WORKFLOWS.md` names
            # the stages and their order and says nothing about colour, and syncing it would
            # recolour seven columns — four of them on fulfillment, whose labels are already
            # correct — for no gain the reader of the board can act on. The consequence, stated so
            # nobody reads it as an oversight: STAGE_COLORS derives colour from position, so after
            # this the palette no longer runs in step with the column order.
            merged, diffs = [], []
            for o in old:
                w = want[o["value"]]
                merged.append(dict(o, label=w["label"], position=w["position"]))
                d = [f"{k} {o.get(k)!r}->{w[k]!r}" for k in ("label", "position")
                     if o.get(k) != w[k]]
                if d:
                    diffs.append(f"{o['value']:18} " + ", ".join(d))

            print(f"  \033[1m{obj_name}\033[0m  {len(diffs)} of {len(old)} options differ")
            for d in diffs:
                print(f"      {d}")
            if not diffs:
                r.skip("already matches the spec")
                print()
                continue
            plan.append((obj_name, fld["id"], len(diffs), merged))
            print()

    r.manifest({"stage_options_before": before})

    for obj_name, fid, n, merged in plan:
        r.write(f"{obj_name}: align {n} option(s)",
                lambda i=fid, m=merged:
                    tw.meta(UPDATE, {"input": {"id": i, "update": {"options": m}}}))
    r.done()


if __name__ == "__main__":
    main()
