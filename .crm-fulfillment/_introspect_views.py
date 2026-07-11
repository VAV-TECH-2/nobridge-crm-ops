import json, tw
FULFILLMENT = "14cded1b-affb-4d3d-bbe3-2c07f4ea47fc"
# Views live in core schema; query via /graphql
q = """query{ views(filter:{objectMetadataId:{eq:"%s"}}){ edges{ node{
  id name type
  viewFields{ edges{ node{ id fieldMetadataId isVisible position size } } }
  viewGroups{ edges{ node{ id fieldValue isVisible position } } }
}}}}""" % FULFILLMENT
st, r = tw.gql(q)
if st != 200 or not r.get("data",{}).get("views"):
    # try metadata endpoint
    st, r = tw.meta(q)
print("status", st)
data = r.get("data",{}).get("views")
if not data:
    print(json.dumps(r)[:800]); raise SystemExit
for e in data["edges"]:
    v = e["node"]
    print(f"\n# VIEW {v['name']} type={v['type']} id={v['id']}")
    vgs = v.get("viewGroups",{}).get("edges",[])
    if vgs:
        print("  groups:", [(g['node']['fieldValue'], g['node']['position'], g['node']['isVisible'], g['node']['id']) for g in vgs])
    print("  fields:")
    for vf in sorted(v.get("viewFields",{}).get("edges",[]), key=lambda x: x['node']['position']):
        n=vf['node']; print(f"    pos={n['position']} vis={n['isVisible']} field={n['fieldMetadataId']} id={n['id']}")
