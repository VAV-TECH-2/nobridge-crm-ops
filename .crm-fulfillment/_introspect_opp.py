import json, tw
# find opportunity object id
st, r = tw.meta('query{ objects(paging:{first:200}){ edges{ node{ id nameSingular } } } }')
oid = None
for e in r["data"]["objects"]["edges"]:
    if e["node"]["nameSingular"] == "opportunity":
        oid = e["node"]["id"]
print("opportunity object id:", oid)
q = """query($id:UUID!){ object(id:$id){ fieldsList{ id name label type options } } }"""
st, r = tw.meta(q, {"id": oid})
for f in r["data"]["object"]["fieldsList"]:
    if f["name"] in ("prospectType","companyType","stage","engagementStatus","finalDecision","meetingOutcome","clientType"):
        print(f"\n## {f['name']} | label={f['label']} | type={f['type']}")
        for o in (f.get("options") or []):
            print(f"   {o.get('value')}  |  {o.get('label')}  | color={o.get('color')} pos={o.get('position')}")
