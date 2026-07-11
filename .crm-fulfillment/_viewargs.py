import json, tw
q = """query{ __schema{ queryType{ fields{ name args{ name type{ name kind ofType{ name kind } } } } } } }"""
st, r = tw.meta(q)
for f in r["data"]["__schema"]["queryType"]["fields"]:
    if f["name"] in ("getViewFields","getViewGroups","getViews","getView"):
        args=[(a["name"], a["type"].get("name") or (a["type"].get("ofType") or {}).get("name"), a["type"]["kind"]) for a in f["args"]]
        print(f["name"], "->", args)
# also the return type fields of getViewField
q2 = """query{ __type(name:"ViewField"){ fields{ name } } }"""
st,r=tw.meta(q2); print("ViewField fields:", [x["name"] for x in (r.get("data",{}).get("__type") or {}).get("fields",[])] if r.get("data",{}).get("__type") else r.get("errors"))
q3 = """query{ __type(name:"Mutation"){ fields{ name } } }"""
st,r=tw.meta(q3); ms=[x["name"] for x in r["data"]["__type"]["fields"]]; print("view mutations:", [m for m in ms if "iew" in m.lower()])
