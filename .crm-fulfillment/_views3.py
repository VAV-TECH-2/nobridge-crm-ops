import json, tw
VIEWS = {
 "TABLE":  "08915153-2ce2-424b-acce-2fc0e4e70be0",
 "FIELDS_WIDGET": "35554471-d537-44d3-8a52-edb18d554700",
 "KANBAN": "3aad7c27-2757-4db1-9ba0-dd44df299c6e",
}
# field id -> name lookup
st, r = tw.meta("""query($id:UUID!){ object(id:$id){ fieldsList{ id name label } } }""", {"id":"14cded1b-affb-4d3d-bbe3-2c07f4ea47fc"})
NAME = {f["id"]: f["name"] for f in r["data"]["object"]["fieldsList"]}
for label, vid in VIEWS.items():
    print(f"\n# {label} {vid}")
    st, r = tw.meta("""query($v:String!){ getViewFields(viewId:$v){ id fieldMetadataId isVisible position } }""", {"v": vid})
    vfs = r.get("data",{}).get("getViewFields") or []
    for n in sorted(vfs, key=lambda x:x["position"]):
        print(f"   F pos={n['position']:<5} vis={str(n['isVisible']):<5} {NAME.get(n['fieldMetadataId'],'?'):<20} vfid={n['id']}")
    st, r = tw.meta("""query($v:String){ getViewGroups(viewId:$v){ id fieldValue isVisible position } }""", {"v": vid})
    vgs = r.get("data",{}).get("getViewGroups") or []
    if vgs: print("   GROUPS:", [(g["fieldValue"], g["position"], g["isVisible"], g["id"]) for g in sorted(vgs,key=lambda x:x["position"])])
