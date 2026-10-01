"""Add a `source` SELECT field to the `opportunity` object (idempotent).

Lets us tag where an opportunity came from — website sign-ups get source=SIGN_UPS.
Purely additive: creates one new column, touches no existing data or fields. Safe to
re-run (skips if `source` already exists). Mirrors setup_fields_se.py.

Run:  python setup_field_source.py
"""
import uuid, json, tw

# This dir's tw.py copy still points at the retired heydeal.co host; force the live one.
tw.HOST = "https://app.nobridge.co"

OPP = "fdd0026f-537d-4ec4-81b3-bf240a820d59"  # opportunity object id (see setup_fields_se.py)

# (label, value, color) — value is the stored enum; label is what shows in the UI.
OPTIONS = [
    ("Sign Ups", "SIGN_UPS", "green"),
    ("Outbound", "OUTBOUND", "blue"),
    ("Referral", "REFERRAL", "purple"),
    ("Network",  "NETWORK",  "orange"),
    ("Other",    "OTHER",    "gray"),
]

CREATE = """mutation C($input: CreateOneFieldMetadataInput!){
  createOneField(input:$input){ id name type }
}"""


def existing():
    st, r = tw.meta('query($id:UUID!){ object(id:$id){ fieldsList{ id name type } } }', {"id": OPP})
    if st == 200 and r.get("data", {}).get("object"):
        return {f["name"]: f for f in r["data"]["object"]["fieldsList"]}
    raise RuntimeError("could not read opportunity fields: %s %s" % (st, json.dumps(r)[:400]))


def main():
    have = existing()
    print("existing opp fields:", sorted(have.keys()))
    if "source" in have:
        print("  skip (exists) source")
        return
    field = {
        "objectMetadataId": OPP,
        "name": "source",
        "label": "Source",
        "type": "SELECT",
        "icon": "IconWorldWww",
        "isLabelSyncedWithName": False,
        "options": [
            {"id": str(uuid.uuid4()), "label": lb, "value": v, "color": c, "position": i}
            for i, (lb, v, c) in enumerate(OPTIONS)
        ],
    }
    st, r = tw.meta(CREATE, {"input": {"field": field}})
    ok = st == 200 and r.get("data", {}).get("createOneField")
    print(("  + source" if ok else "  !! FAIL source " + str(st) + " " + json.dumps(r)[:400]))
    print("=== fields now ===", sorted(existing().keys()))


if __name__ == "__main__":
    main()
