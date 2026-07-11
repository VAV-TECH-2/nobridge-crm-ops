"""Replace the opportunity `stage` 4-option pipeline with the 8-step pipeline, migrating
every existing record. Safe order: add new options (keep old) -> migrate records ->
verify no old value remains -> remove old options. Writes a rollback manifest first.

  python migrate_stages.py            # dry run: writes manifest + prints plan, no changes
  python migrate_stages.py --apply    # execute
"""
import json, sys, tw

STAGE_FIELD = "90838d6a-4990-409d-b46f-93a3ca1802ec"

# Existing 4 options — preserved EXACTLY (ids/values/colors) during the transition.
OLD = [
    {"id": "20202020-8e01-4afd-9c39-d2063097587a", "color": "red",       "label": "Stage 1 : Introduction Meeting + Screening", "value": "STAGE_1_INTRODUCTION_MEETING_SCREENING", "position": 0},
    {"id": "20202020-e685-4671-ac32-26d304dacb6e", "color": "purple",    "label": "Stage 2 : Value Creation",                   "value": "STAGE_2_VALUE_CREATION",                   "position": 1},
    {"id": "20202020-dde9-4acc-b5ca-f6531a8ecb4a", "color": "sky",       "label": "Stage 3 : Service Evaluation + Pitch",       "value": "STAGE_3_SERVICE_EVALUATION_PITCH",         "position": 2},
    {"id": "20202020-696e-4f6b-91bc-f413e9b2f654", "color": "turquoise", "label": "Stage 4 : Awaiting Feedback",                "value": "STAGE_4_AWAITING_FEEDBACK",                "position": 3},
]

# New 8-step pipeline — fixed ids so re-runs are idempotent.
NEW = [
    {"id": "30303030-0000-4000-8000-000000000001", "color": "gray",   "label": "Stage 1 · New Lead",                    "value": "NEW_LEAD",   "position": 0},
    {"id": "30303030-0000-4000-8000-000000000002", "color": "red",    "label": "Stage 2 · Intro Meeting + Screening",   "value": "MEETING_1",  "position": 1},
    {"id": "30303030-0000-4000-8000-000000000003", "color": "purple", "label": "Stage 3 · Strategy / Value Creation",   "value": "STRATEGY",   "position": 2},
    {"id": "30303030-0000-4000-8000-000000000004", "color": "blue",   "label": "Stage 4 · Strategy Review",             "value": "MEETING_2",  "position": 3},
    {"id": "30303030-0000-4000-8000-000000000005", "color": "orange", "label": "Stage 5 · Revamps",                     "value": "REVAMPS",    "position": 4},
    {"id": "30303030-0000-4000-8000-000000000006", "color": "sky",    "label": "Stage 6 · Service Evaluation + Pitch",  "value": "MEETING_3",  "position": 5},
    {"id": "30303030-0000-4000-8000-000000000007", "color": "green",  "label": "Closed Won",                                "value": "CLOSED_WON", "position": 6},
    {"id": "30303030-0000-4000-8000-000000000008", "color": "gray",   "label": "Lost",                                      "value": "LOST",       "position": 7},
]

STAGE_MAP = {
    "STAGE_1_INTRODUCTION_MEETING_SCREENING": "MEETING_1",
    "STAGE_2_VALUE_CREATION": "STRATEGY",
    "STAGE_3_SERVICE_EVALUATION_PITCH": "MEETING_3",
    "STAGE_4_AWAITING_FEEDBACK": "MEETING_3",
}

UPDATE_FIELD = "mutation U($input: UpdateOneFieldMetadataInput!){ updateOneField(input:$input){ id options } }"
UPDATE_OPP = "mutation U($id: UUID!, $data: OpportunityUpdateInput!){ updateOpportunity(id:$id, data:$data){ id stage } }"

def set_options(options):
    return tw.meta(UPDATE_FIELD, {"input": {"id": STAGE_FIELD, "update": {"options": options}}})

def fetch_all():
    out, after = [], None
    while True:
        st, r = tw.gql('query($a:String){ opportunities(first:60, after:$a){ edges{ node{ id name stage finalDecision clientType } } pageInfo{ hasNextPage endCursor } } }', {"a": after})
        conn = r["data"]["opportunities"]
        out += [e["node"] for e in conn["edges"]]
        if conn["pageInfo"]["hasNextPage"]:
            after = conn["pageInfo"]["endCursor"]
        else:
            break
    return out

def new_stage(n):
    fd = n.get("finalDecision")
    if fd == "CLOSED_WON":
        return "CLOSED_WON"
    if fd in ("CLOSED_LOST", "GHOSTED"):
        return "LOST"
    return STAGE_MAP.get(n.get("stage"))

def main():
    apply = "--apply" in sys.argv
    records = fetch_all()
    print(f"fetched {len(records)} opportunities")
    manifest = [{"id": n["id"], "name": n["name"], "oldStage": n["stage"],
                 "finalDecision": n.get("finalDecision"), "clientType": n.get("clientType"),
                 "newStage": new_stage(n)} for n in records]

    plan = {}
    for m in manifest:
        k = f'{m["oldStage"]} -> {m["newStage"]}'
        plan[k] = plan.get(k, 0) + 1
    print("MIGRATION PLAN:")
    for k, v in sorted(plan.items()):
        print(f"   {k} : {v}")

    with open("stage_migration_manifest.json", "w", encoding="utf-8") as f:
        json.dump({"stageFieldId": STAGE_FIELD, "oldOptions": OLD, "newOptions": NEW, "records": manifest}, f, indent=2)
    print("manifest written -> stage_migration_manifest.json")

    if not apply:
        print("\nDRY RUN. Re-run with --apply to execute.")
        return

    # phase 1: add new options, keep old (so existing records stay valid)
    combined = [dict(o) for o in OLD] + [dict(o, position=o["position"] + 4) for o in NEW]
    st, r = set_options(combined)
    print("phase1 (add new options):", st, json.dumps(r)[:150])
    if st != 200:
        print("ABORT — could not add options"); return

    # phase 2: migrate records
    ok = fail = 0
    for m in manifest:
        if not m["newStage"]:
            continue
        st, r = tw.gql(UPDATE_OPP, {"id": m["id"], "data": {"stage": m["newStage"]}})
        if st == 200 and r.get("data", {}).get("updateOpportunity"):
            ok += 1
        else:
            fail += 1
            print("   fail", m["id"], st, json.dumps(r)[:150])
    print(f"phase2 (migrate records): ok={ok} fail={fail}")

    # phase 3: verify, then finalize to new-only options
    remaining = [n for n in fetch_all() if n["stage"] in STAGE_MAP]
    print("records still on an old stage:", len(remaining))
    if remaining:
        print("NOT removing old options — fix the above first."); return
    st, r = set_options([dict(o) for o in NEW])
    print("phase3 (finalize to 8 options):", st, json.dumps(r)[:150])
    print("DONE.")

if __name__ == "__main__":
    main()
