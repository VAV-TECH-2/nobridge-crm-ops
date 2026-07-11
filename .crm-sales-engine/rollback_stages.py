"""Roll back the stage migration using stage_migration_manifest.json:
re-add the old options, set every record back to its old stage, then remove the new options.

  python rollback_stages.py --apply
"""
import json, sys, tw

UPDATE_FIELD = "mutation U($input: UpdateOneFieldMetadataInput!){ updateOneField(input:$input){ id options } }"
UPDATE_OPP = "mutation U($id: UUID!, $data: OpportunityUpdateInput!){ updateOpportunity(id:$id, data:$data){ id stage } }"

def set_options(field_id, options):
    return tw.meta(UPDATE_FIELD, {"input": {"id": field_id, "update": {"options": options}}})

def main():
    if "--apply" not in sys.argv:
        print("Add --apply to execute the rollback."); return
    with open("stage_migration_manifest.json", encoding="utf-8") as f:
        man = json.load(f)
    field = man["stageFieldId"]
    old, new, records = man["oldOptions"], man["newOptions"], man["records"]

    # 1) re-add old options alongside new
    combined = [dict(o) for o in new] + [dict(o, position=o["position"] + 8) for o in old]
    st, r = set_options(field, combined)
    print("re-add old options:", st, json.dumps(r)[:150])
    if st != 200:
        print("ABORT"); return

    # 2) set each record back to its old stage
    ok = fail = 0
    for m in records:
        if not m.get("oldStage"):
            continue
        st, r = tw.gql(UPDATE_OPP, {"id": m["id"], "data": {"stage": m["oldStage"]}})
        if st == 200 and r.get("data", {}).get("updateOpportunity"):
            ok += 1
        else:
            fail += 1
            print("   fail", m["id"], st, json.dumps(r)[:150])
    print(f"restored records: ok={ok} fail={fail}")

    # 3) remove the new options (old-only)
    st, r = set_options(field, [dict(o) for o in old])
    print("finalize to old options:", st, json.dumps(r)[:150])
    print("ROLLBACK DONE.")

if __name__ == "__main__":
    main()
