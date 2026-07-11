"""Find where Twenty exposes webhook management (core vs metadata, query/mutation/object names)."""
import json, tw

def names(typ, endpoint):
    q = 'query{ __type(name:"%s"){ fields{ name } } }' % typ
    st, r = (tw.meta if endpoint == "meta" else tw.gql)(q)
    t = (r.get("data", {}) or {}).get("__type")
    return [f["name"] for f in t["fields"]] if t else []

for ep in ("core", "meta"):
    fn = tw.gql if ep == "core" else tw.meta
    qf = names("Query", ep)
    mf = names("Mutation", ep)
    print(ep, "Query webhook:", [n for n in qf if "ebhook" in n.lower()])
    print(ep, "Mutation webhook:", [n for n in mf if "ebhook" in n.lower()])

# metadata objects list
st, r = tw.meta('query{ objects(paging:{first:300}){ edges{ node{ nameSingular namePlural isSystem } } } }')
objs = [n["node"] for n in r["data"]["objects"]["edges"]] if st == 200 else []
print("objects matching webhook:", [(o["nameSingular"], o.get("isSystem")) for o in objs if "ebhook" in o["nameSingular"].lower()])
