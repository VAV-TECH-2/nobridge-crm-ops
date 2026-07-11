import json, tw
FF="14cded1b-affb-4d3d-bbe3-2c07f4ea47fc"
st,r=tw.meta("""query($id:UUID!){ object(id:$id){ fieldsList{ id name label type options } } }""",{"id":FF})
flds={f["name"]:f for f in r["data"]["object"]["fieldsList"]}
for nm in ["stage","engagementStatus","outcome","prospectType","notes","daysSinceContact","repliedAt","escalatedAt","lastContact"]:
    f=flds.get(nm)
    if not f: print("MISSING", nm); continue
    opts=" ; ".join(f"{o['value']}" for o in (f.get("options") or [])) if f.get("options") else f["type"]
    print(f"{nm:18} label='{f['label']}' :: {opts}")
print("\nTABLE visible columns (in order):")
NAME={f["id"]:f["name"] for f in flds.values()}
st,r=tw.meta("""query($v:String!){ getViewFields(viewId:$v){ fieldMetadataId isVisible position } }""",{"v":"08915153-2ce2-424b-acce-2fc0e4e70be0"})
for n in sorted(r["data"]["getViewFields"],key=lambda x:x["position"]):
    flag="" if n["isVisible"] else "  (HIDDEN)"
    print(f"   {NAME.get(n['fieldMetadataId'],'?'):20}{flag}")
