"""Bring the `fulfillment` object schema to the agreed fulfillment-notifications spec.

Idempotent + safe. For every SELECT change: add new options (keep old) -> migrate
records -> verify none remain on a removed value -> remove old options. Writes a
rollback manifest of current options before any change.

  python migrate_schema.py            # DRY RUN: print current state + plan, no writes
  python migrate_schema.py --apply    # execute

Field/option ids below were captured live on 2026-06-22 via _introspect_ff.py.
"""
import json, sys, time, uuid, tw

FULFILLMENT = "14cded1b-affb-4d3d-bbe3-2c07f4ea47fc"
APPLY = "--apply" in sys.argv

UPDATE_FIELD = "mutation U($input: UpdateOneFieldMetadataInput!){ updateOneField(input:$input){ id name label options } }"
CREATE_FIELD = "mutation C($input: CreateOneFieldMetadataInput!){ createOneField(input:$input){ id name type } }"
UPDATE_FF    = "mutation U($id: UUID!, $data: FulfillmentUpdateInput!){ updateFulfillment(id:$id, data:$data){ id } }"

# ---- live option ids (preserve EXACTLY for kept values so records stay valid) ----
STAGE_FIELD = "27353cc8-c646-4e83-a7d5-528fd3ef4494"
STAGE_LIVE = {
    "REACHED_OUT":       {"id": "1650c4b0-2881-4096-9be1-a0eaf4823ac1", "color": "gray"},
    "TEASER":            {"id": "89b2f2a2-033e-40ae-91a5-2a8bc1a9b181", "color": "blue"},
    "NDA":               {"id": "bb04c842-5f18-4da6-8c9b-387e2033b866", "color": "purple"},
    "DUE_DILIGENCE_VDR": {"id": "f4c1b9c1-a869-4107-b3a0-bf080f88c9e6", "color": "orange"},
    "WAITING_ON_OFFER":  {"id": "0aa83ef9-5b5b-45d7-966c-120b8c9ab019", "color": "green"},
}
# target stage option set (keep kept-value ids; mint new uuids for the 3 meetings)
STAGE_TARGET = [
    {"value": "REACHED_OUT",       "label": "Reached Out / Teaser", "color": "gray",   "id": STAGE_LIVE["REACHED_OUT"]["id"]},
    {"value": "MEETING_1",         "label": "Meeting 1",            "color": "red",    "id": "40404040-0000-4000-8000-000000000001"},
    {"value": "NDA",               "label": "NDA",                  "color": "purple", "id": STAGE_LIVE["NDA"]["id"]},
    {"value": "MEETING_2",         "label": "Meeting 2",            "color": "blue",   "id": "40404040-0000-4000-8000-000000000002"},
    {"value": "DUE_DILIGENCE_VDR", "label": "Due Diligence",        "color": "orange", "id": STAGE_LIVE["DUE_DILIGENCE_VDR"]["id"]},
    {"value": "MEETING_3",         "label": "Meeting 3",            "color": "sky",    "id": "40404040-0000-4000-8000-000000000003"},
    {"value": "WAITING_ON_OFFER",  "label": "Waiting on Offer",     "color": "green",  "id": STAGE_LIVE["WAITING_ON_OFFER"]["id"]},
]
STAGE_RECORD_MAP = {"TEASER": "REACHED_OUT"}          # records to move before dropping TEASER
STAGE_DROP = ["TEASER"]

PROGRESS_FIELD = "d14c5689-0fcd-43a7-8044-c04b495a2a51"  # engagementStatus, relabel -> Progress Type
PROGRESS_LIVE = {
    "NOT_CONTACTED_YET":        "c30ebe95-553d-4b2d-a8db-c914fce5abf3",
    "IN_DISCUSSIONS_SCHEDULED": "78b60871-29b7-46f6-90ef-ce34ed6cb464",
    "AWAITING_REPLY":           "f600af32-56b0-44be-bd08-21376e3e5d96",
    "HELD_OFF":                 "41216c36-dd17-469d-afdc-3d77ddd0d8f7",
    "NOT_INTERESTED":           "23863fa6-d9bb-47ea-a081-ae03647414b4",
    "CRASH_OUT_DNC":            "b6821d5f-9972-4b9b-afd3-f766b3c8ea6a",
}
PROGRESS_TARGET = [
    {"value": "COMPLETE",          "label": "Complete",          "color": "green",  "id": "41414141-0000-4000-8000-000000000001"},
    {"value": "ACTIVELY_SPEAKING", "label": "Actively Speaking", "color": "blue",   "id": "41414141-0000-4000-8000-000000000002"},
    {"value": "GHOSTED",           "label": "Ghosted",           "color": "red",    "id": "41414141-0000-4000-8000-000000000003"},
]
PROGRESS_RECORD_MAP = {                                # old value -> new value (None = clear)
    "IN_DISCUSSIONS_SCHEDULED": "ACTIVELY_SPEAKING",
    "AWAITING_REPLY":           "ACTIVELY_SPEAKING",
    "HELD_OFF":                 "GHOSTED",
    "NOT_INTERESTED":           "GHOSTED",
    "CRASH_OUT_DNC":            "GHOSTED",
    "NOT_CONTACTED_YET":        None,
}
PROGRESS_DROP = list(PROGRESS_RECORD_MAP.keys())

OUTCOME_FIELD = "cf2681b7-0b69-4aad-b6e3-4355a4c23497"
OUTCOME_LIVE = {
    "OFFER_RECEIVED": {"id": "08620508-e181-448e-9ac1-4c80226f23f0", "color": "turquoise"},
    "DEAL_CLOSED":    {"id": "fd082e8e-f9c0-45ce-a666-7fa9360ec67a", "color": "green"},
    "PASSED":         {"id": "0d309026-ebc9-4a56-ae35-37fb1e3d7b88", "color": "gray"},
    "DROPPED":        {"id": "d897850b-7642-45fb-b760-c99e358d6d2c", "color": "red"},
}
OUTCOME_TARGET = [
    {"value": "OFFER_RECEIVED", "label": "Offer Received", "color": "turquoise", "id": OUTCOME_LIVE["OFFER_RECEIVED"]["id"]},
    {"value": "PASSED",         "label": "Passed",         "color": "gray",      "id": OUTCOME_LIVE["PASSED"]["id"]},
    {"value": "DROPPED",        "label": "Dropped",        "color": "red",       "id": OUTCOME_LIVE["DROPPED"]["id"]},
]
OUTCOME_RECORD_MAP = {"DEAL_CLOSED": "OFFER_RECEIVED"}
OUTCOME_DROP = ["DEAL_CLOSED"]

# ---- additive scalar fields (engine stamps + the user-requested Notes / Days) ----
NEW_SCALARS = {
    "notes":            ("Notes",             "TEXT",      "IconNotes"),
    "daysSinceContact": ("Days Since Contact","NUMBER",    "IconCalendarStats"),
    "repliedAt":        ("Replied At",        "DATE_TIME", "IconMailForward"),
    "escalatedAt":      ("Escalated At",      "DATE_TIME", "IconAlertTriangle"),
}


def opt(o, pos):
    return {"id": o["id"], "value": o["value"], "label": o["label"], "color": o["color"], "position": pos}


def set_options(field_id, options):
    payload = [opt(o, i) for i, o in enumerate(options)]
    return tw.meta(UPDATE_FIELD, {"input": {"id": field_id, "update": {"options": payload}}})


def fetch_all(field):
    out, after = [], None
    while True:
        st, r = tw.gql(
            'query($a:String){ fulfillments(first:60, after:$a){ edges{ node{ id name %s } } pageInfo{ hasNextPage endCursor } } }' % field,
            {"a": after})
        conn = r.get("data", {}).get("fulfillments")
        if not conn:
            print("  !! fetch_all error:", st, json.dumps(r)[:300]); break
        out += [e["node"] for e in conn["edges"]]
        if conn["pageInfo"]["hasNextPage"]:
            after = conn["pageInfo"]["endCursor"]
        else:
            break
    return out


def counts(records, field):
    c = {}
    for n in records:
        c[n.get(field)] = c.get(n.get(field), 0) + 1
    return c


def migrate_select(name, field_id, live_ids, target, record_map, drop, label=None):
    """add-new -> migrate-records -> verify -> remove-old, for one SELECT field."""
    print(f"\n=== {name} ({field_id}) ===")
    recs = fetch_all(name)
    print("  current record counts:", counts(recs, name))
    print("  target options:", [t["value"] for t in target], "| relabel field:", label or "(no)")
    print("  record remap:", record_map, "| drop options:", drop)
    if not APPLY:
        return

    # rollback manifest
    with open(f"rollback_{name}.json", "w", encoding="utf-8") as f:
        json.dump({"field": field_id, "name": name,
                   "records": [{"id": n["id"], "old": n.get(name)} for n in recs]}, f, indent=2)

    # phase 1: union of (target + dropped-but-still-present) so existing records stay valid
    union = list(target)
    present = {n.get(name) for n in recs if n.get(name)}
    for v in drop:
        if v in present and v not in [t["value"] for t in union]:
            lid = live_ids[v]["id"] if isinstance(live_ids.get(v), dict) else live_ids.get(v)
            union.append({"value": v, "label": v.title(), "color": "gray", "id": lid})
    upd = {"options": [opt(o, i) for i, o in enumerate(union)]}
    if label:
        upd["label"] = label
        upd["isLabelSyncedWithName"] = False
    st, r = tw.meta(UPDATE_FIELD, {"input": {"id": field_id, "update": upd}})
    print("  phase1 add/relabel:", st, "ok" if st == 200 and r.get("data", {}).get("updateOneField") else json.dumps(r)[:300])
    if st != 200:
        print("  ABORT"); return

    # phase 2: migrate records off dropped values
    ok = fail = 0
    for n in recs:
        old = n.get(name)
        if old not in record_map:
            continue
        new = record_map[old]
        st, r = tw.gql(UPDATE_FF, {"id": n["id"], "data": {name: new}})
        if st == 200 and r.get("data", {}).get("updateFulfillment"):
            ok += 1
        else:
            fail += 1
            print("    fail", n["id"], old, "->", new, st, json.dumps(r)[:200])
    print(f"  phase2 migrate records: ok={ok} fail={fail}")

    # phase 3: verify + finalize to target-only
    recs2 = fetch_all(name)
    remaining = [n for n in recs2 if n.get(name) in drop]
    print("  records still on a dropped value:", len(remaining))
    if remaining:
        print("  NOT removing old options — resolve the above first."); return
    st, r = set_options(field_id, target)
    print("  phase3 finalize:", st, "ok" if st == 200 and r.get("data", {}).get("updateOneField") else json.dumps(r)[:300])


def add_scalars():
    print("\n=== additive scalar fields ===")
    q = """query($id:UUID!){ object(id:$id){ fieldsList{ name } } }"""
    st, r = tw.meta(q, {"id": FULFILLMENT})
    have = {f["name"] for f in r["data"]["object"]["fieldsList"]}
    for nm, (label, ftype, icon) in NEW_SCALARS.items():
        if nm in have:
            print("  skip (exists)", nm); continue
        if not APPLY:
            print("  would create", nm, ftype); continue
        field = {"objectMetadataId": FULFILLMENT, "name": nm, "label": label,
                 "type": ftype, "icon": icon, "isLabelSyncedWithName": False}
        st, r = tw.meta(CREATE_FIELD, {"input": {"field": field}})
        print(("  + " if st == 200 and r.get("data", {}).get("createOneField") else "  !! FAIL ") + nm,
              "" if st == 200 else json.dumps(r)[:300])


def main():
    print("MODE:", "APPLY" if APPLY else "DRY RUN")
    migrate_select("stage", STAGE_FIELD, STAGE_LIVE, STAGE_TARGET, STAGE_RECORD_MAP, STAGE_DROP)
    migrate_select("engagementStatus", PROGRESS_FIELD, PROGRESS_LIVE, PROGRESS_TARGET,
                   PROGRESS_RECORD_MAP, PROGRESS_DROP, label="Progress Type")
    migrate_select("outcome", OUTCOME_FIELD, OUTCOME_LIVE, OUTCOME_TARGET, OUTCOME_RECORD_MAP, OUTCOME_DROP)
    add_scalars()
    print("\nDONE." if APPLY else "\nDRY RUN complete. Re-run with --apply to execute.")


if __name__ == "__main__":
    main()
