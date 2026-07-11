import json, tw
q = """query{ __schema{ mutationType{ fields{ name args{ name type{ name kind ofType{ name } } } } } } }"""
st, r = tw.meta(q)
want = {"updateViewField","createViewField","updateViewGroup","deleteViewGroup"}
for f in r["data"]["__schema"]["mutationType"]["fields"]:
    if f["name"] in want:
        print(f["name"], "->", [(a["name"], a["type"].get("name") or (a["type"].get("ofType") or {}).get("name")) for a in f["args"]])
for t in ("UpdateViewFieldInput","CreateViewFieldInput","UpdateViewGroupInput"):
    st,r=tw.meta("""query($n:String!){ __type(name:$n){ inputFields{ name type{ name kind ofType{ name } } } } }""",{"n":t})
    tt=r.get("data",{}).get("__type")
    print(t, "->", [(x["name"], x["type"].get("name") or (x["type"].get("ofType") or {}).get("name")) for x in tt["inputFields"]] if tt else r.get("errors"))
# new field ids
st,r=tw.meta("""query($id:UUID!){ object(id:$id){ fieldsList{ id name } } }""",{"id":"14cded1b-affb-4d3d-bbe3-2c07f4ea47fc"})
ids={f["name"]:f["id"] for f in r["data"]["object"]["fieldsList"]}
print("notes=",ids.get("notes"),"daysSinceContact=",ids.get("daysSinceContact"))
