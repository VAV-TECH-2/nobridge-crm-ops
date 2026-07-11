"""Create clean MANY_TO_ONE relations on `fulfillment` (company, pointOfContact)
mimicking Opportunity, then remove the miswired empty `client` relation."""
import json, tw

FULFILLMENT = "14cded1b-affb-4d3d-bbe3-2c07f4ea47fc"
COMPANY     = "825f8dff-2de8-4055-bb8a-a23f8c1cee20"
PERSON      = "6160d306-18a8-4d07-9772-4d29e62ca66f"

CREATE = """mutation C($input: CreateOneFieldMetadataInput!){
  createOneField(input:$input){ id name type }
}"""
UPDATE = """mutation U($input: UpdateOneFieldMetadataInput!){
  updateOneField(input:$input){ id name isActive }
}"""
DELETE = """mutation D($input: DeleteOneFieldInput!){
  deleteOneField(input:$input){ id name }
}"""

def fields():
    st, r = tw.meta("""query($id:UUID!){ object(id:$id){ fieldsList{ id name type } } }""",
                    {"id": FULFILLMENT})
    return {f["name"]: f for f in r["data"]["object"]["fieldsList"]}

def make_relation(name, label, icon, target, inverse_label, inverse_icon):
    field = {"objectMetadataId": FULFILLMENT, "name": name, "label": label,
             "type": "RELATION", "icon": icon, "isLabelSyncedWithName": False,
             "relationCreationPayload": {
                 "type": "MANY_TO_ONE", "targetObjectMetadataId": target,
                 "targetFieldLabel": inverse_label, "targetFieldIcon": inverse_icon}}
    st, r = tw.meta(CREATE, {"input": {"field": field}})
    ok = st == 200 and r.get("data", {}).get("createOneField")
    print(("  + " if ok else "  !! FAIL ") + name, "" if ok else (str(st)+" "+json.dumps(r)[:500]))
    return ok

def delete_field(fid, name):
    st, r = tw.meta(DELETE, {"input": {"id": fid}})
    if st == 200 and r.get("data", {}).get("deleteOneField"):
        print("  - deleted", name); return True
    # may need deactivation first
    st2, r2 = tw.meta(UPDATE, {"input": {"id": fid, "update": {"isActive": False}}})
    st3, r3 = tw.meta(DELETE, {"input": {"id": fid}})
    ok = st3 == 200 and r3.get("data", {}).get("deleteOneField")
    print(("  - deleted (after deactivate) " if ok else "  !! FAIL delete ")+name,
          "" if ok else json.dumps({"del1":r,"deact":r2,"del2":r3})[:500])
    return ok

def main():
    have = fields()
    print("=== relations ===")
    if "company" not in have:
        make_relation("company", "Company", "IconBuildingSkyscraper",
                      COMPANY, "Fulfillments", "IconTargetArrow")
    else:
        print("  skip (exists) company")
    if "pointOfContact" not in have:
        make_relation("pointOfContact", "Point of Contact", "IconUserCircle",
                      PERSON, "Fulfillments (POC)", "IconTargetArrow")
    else:
        print("  skip (exists) pointOfContact")
    print("=== remove miswired client relation ===")
    have = fields()
    if "client" in have:
        delete_field(have["client"]["id"], "client")
    else:
        print("  already gone")
    print("fields now:", sorted(fields().keys()))

if __name__ == "__main__":
    main()
