"""Create the additive sales-engine fields on `opportunity` (idempotent).
All additive (new columns) — does not touch existing data or fields."""
import uuid, json, tw

OPP = "fdd0026f-537d-4ec4-81b3-bf240a820d59"

SELECTS = {
    "meetingOutcome": ("Meeting Outcome", "IconCalendarEvent", [
        ("Scheduled",   "SCHEDULED",   "blue"),
        ("Hosted",      "HOSTED",      "green"),
        ("No-show",     "NO_SHOW",     "red"),
        ("Rescheduled", "RESCHEDULED", "orange"),
        ("Cancelled",   "CANCELLED",   "gray"),
    ]),
}
SCALARS = {
    "outreachSentAt": ("Outreach Sent At", "DATE_TIME", "IconSend"),
    "recapSentAt":    ("Recap Sent At",    "DATE_TIME", "IconNotes"),
    "strategySentAt": ("Strategy Sent At", "DATE_TIME", "IconFileText"),
    "revampSentAt":   ("Revamp Sent At",   "DATE_TIME", "IconRefresh"),
    "repliedAt":      ("Replied At",       "DATE_TIME", "IconMail"),
    "escalatedAt":    ("Escalated At",     "DATE_TIME", "IconAlertTriangle"),
}
BOOLS = {
    "revampNeeded": ("Revamp Needed", "IconRefreshAlert"),
}

CREATE = """mutation C($input: CreateOneFieldMetadataInput!){
  createOneField(input:$input){ id name type }
}"""

def existing():
    st, r = tw.meta('query($id:UUID!){ object(id:$id){ fieldsList{ id name type } } }', {"id": OPP})
    if st == 200 and r.get("data", {}).get("object"):
        return {f["name"]: f for f in r["data"]["object"]["fieldsList"]}
    return {}

def make(name, label, ftype, icon, options=None, default=None):
    field = {"objectMetadataId": OPP, "name": name, "label": label, "type": ftype,
             "icon": icon, "isLabelSyncedWithName": False}
    if options:
        field["options"] = [
            {"id": str(uuid.uuid4()), "label": lb, "value": v, "color": c, "position": i}
            for i, (lb, v, c) in enumerate(options)]
    if default is not None:
        field["defaultValue"] = default
    st, r = tw.meta(CREATE, {"input": {"field": field}})
    ok = st == 200 and r.get("data", {}).get("createOneField")
    print(("  + " if ok else "  !! FAIL ") + name, "" if ok else (str(st) + " " + json.dumps(r)[:400]))
    return ok

def main():
    have = existing()
    print("existing opp fields:", sorted(have.keys()))
    print("=== SELECT ===")
    for name, (label, icon, opts) in SELECTS.items():
        print("  skip (exists)", name) if name in have else make(name, label, "SELECT", icon, opts)
    print("=== DATE_TIME ===")
    for name, (label, ftype, icon) in SCALARS.items():
        print("  skip (exists)", name) if name in have else make(name, label, ftype, icon)
    print("=== BOOLEAN ===")
    for name, (label, icon) in BOOLS.items():
        print("  skip (exists)", name) if name in have else make(name, label, "BOOLEAN", icon, default=False)
    print("=== fields now ===", sorted(existing().keys()))

if __name__ == "__main__":
    main()
