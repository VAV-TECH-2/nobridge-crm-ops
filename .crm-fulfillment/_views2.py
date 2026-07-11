import json, tw
FULFILLMENT = "14cded1b-affb-4d3d-bbe3-2c07f4ea47fc"
st, r = tw.meta("""query{ getViews{ id name type objectMetadataId } }""")
views = [v for v in r.get("data",{}).get("getViews",[]) if v["objectMetadataId"]==FULFILLMENT] if r.get("data") else None
if views is None:
    print("getViews shape error:", st, json.dumps(r)[:600]); raise SystemExit
for v in views:
    print(f"\n# VIEW {v['name']} type={v['type']} id={v['id']}")
    st2, r2 = tw.meta("""query($v:UUID!){ getViewFields(viewId:$v){ id fieldMetadataId isVisible position size } }""", {"v": v["id"]})
    vfs = r2.get("data",{}).get("getViewFields",[])
    for n in sorted(vfs, key=lambda x:x["position"]):
        print(f"    F pos={n['position']} vis={n['isVisible']} field={n['fieldMetadataId']} id={n['id']}")
    st3, r3 = tw.meta("""query($v:UUID!){ getViewGroups(viewId:$v){ id fieldValue isVisible position fieldMetadataId } }""", {"v": v["id"]})
    vgs = r3.get("data",{}).get("getViewGroups",[])
    if vgs:
        print("    GROUPS:", [(g["fieldValue"], g["position"], g["isVisible"]) for g in sorted(vgs,key=lambda x:x["position"])])
