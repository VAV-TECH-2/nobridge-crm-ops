"""Create the non-relation fields on the `fulfillment` object (idempotent).

SELECT / TEXT / DATE via the metadata GraphQL API `createOneField`. Relations and
the kanban view are handled separately (setup_relations.py / setup_view.py).
"""
import uuid, json, tw

FULFILLMENT = "14cded1b-affb-4d3d-bbe3-2c07f4ea47fc"

# ---- SELECT fields: name -> (label, icon, [(label, value, color)]) ----
SELECTS = {
    "stage": ("Stage", "IconProgressCheck", [
        ("Reached Out",          "REACHED_OUT",        "gray"),
        ("Teaser",               "TEASER",             "blue"),
        ("NDA",                  "NDA",                "purple"),
        ("Due Diligence (VDR)",  "DUE_DILIGENCE_VDR",  "orange"),
        ("Waiting on Offer",     "WAITING_ON_OFFER",   "green"),
    ]),
    "outcome": ("Outcome", "IconFlag", [
        ("Offer Received", "OFFER_RECEIVED", "turquoise"),
        ("Deal Closed",    "DEAL_CLOSED",    "green"),
        ("Passed",         "PASSED",         "gray"),
        ("Dropped",        "DROPPED",        "red"),
    ]),
    "engagementStatus": ("Engagement Status", "IconMessageDots", [
        ("Not Contacted Yet",                "NOT_CONTACTED_YET",        "gray"),
        ("In Discussions / Scheduled",       "IN_DISCUSSIONS_SCHEDULED", "blue"),
        ("Awaiting Reply",                   "AWAITING_REPLY",           "yellow"),
        ("Held Off (Check Back In 3 Months)","HELD_OFF",                 "orange"),
        ("Not Interested",                   "NOT_INTERESTED",           "red"),
        ("Crash Out (DNC)",                  "CRASH_OUT_DNC",            "pink"),
    ]),
}

# ---- scalar fields: name -> (label, type, icon) ----
SCALARS = {
    "companyType":       ("Company Type",      "TEXT", "IconBuildingStore"),
    "country":           ("Country",           "TEXT", "IconWorld"),
    "nextSteps":         ("Next Steps",        "TEXT", "IconArrowRight"),
    "mandate":           ("Mandate / Client",  "TEXT", "IconBriefcase"),
    "meetingFindings":   ("Meeting Findings",  "TEXT", "IconNotes"),
    "fathomLink":        ("Fathom Link",       "TEXT", "IconLink"),
    "secondaryContacts": ("Secondary Contacts","TEXT", "IconUsers"),
    "lastContact":       ("Last Contact",      "DATE", "IconCalendar"),
    "followUpDate":      ("Follow-up Date",    "DATE", "IconCalendarDue"),
}

CREATE = """mutation C($input: CreateOneFieldMetadataInput!){
  createOneField(input:$input){ id name type }
}"""

def existing_fields():
    q = """query($id:UUID!){ object(id:$id){ fieldsList{ id name type } } }"""
    st, r = tw.meta(q, {"id": FULFILLMENT})
    if st == 200 and r.get("data", {}).get("object"):
        return {f["name"]: f for f in r["data"]["object"]["fieldsList"]}
    # fallback to objects() listing if object(id) shape differs
    q2 = """query{ objects(paging:{first:200}){ edges{ node{ id nameSingular
              fields{ edges{ node{ id name type } } } } } } }"""
    st, r = tw.meta(q2)
    for e in r["data"]["objects"]["edges"]:
        if e["node"]["id"] == FULFILLMENT:
            return {f["node"]["name"]: f["node"] for f in e["node"]["fields"]["edges"]}
    return {}

def make_field(name, label, ftype, icon, options=None):
    field = {"objectMetadataId": FULFILLMENT, "name": name, "label": label,
             "type": ftype, "icon": icon, "isLabelSyncedWithName": False}
    if options:
        field["options"] = [
            {"id": str(uuid.uuid4()), "label": lb, "value": val, "color": col, "position": i}
            for i, (lb, val, col) in enumerate(options)]
    st, r = tw.meta(CREATE, {"input": {"field": field}})
    ok = st == 200 and r.get("data", {}).get("createOneField")
    print(("  + " if ok else "  !! FAIL ") + name,
          "" if ok else (str(st) + " " + json.dumps(r)[:400]))
    return ok

def main():
    have = existing_fields()
    print("existing fulfillment fields:", sorted(have.keys()))
    print("=== SELECT fields ===")
    for name, (label, icon, opts) in SELECTS.items():
        if name in have: print("  skip (exists)", name); continue
        make_field(name, label, "SELECT", icon, opts)
    print("=== SCALAR fields ===")
    for name, (label, ftype, icon) in SCALARS.items():
        if name in have: print("  skip (exists)", name); continue
        make_field(name, label, ftype, icon)
    print("=== DONE ===")
    after = existing_fields()
    print("fields now:", sorted(after.keys()))

if __name__ == "__main__":
    main()
