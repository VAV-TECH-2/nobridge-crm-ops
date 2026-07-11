import json, tw
st, r = tw.meta('query{ objects(paging:{first:200}){ edges{ node{ id nameSingular isCustom } } } }')
objs=[e["node"] for e in r["data"]["objects"]["edges"]]
print("custom objects:", sorted(o["nameSingular"] for o in objs if o["isCustom"]))
print("henry/venice objects:", [o["nameSingular"] for o in objs if "henry" in o["nameSingular"].lower() or "venice" in o["nameSingular"].lower()])
# recently created CUSTOM objects (the prior run may have made one)
st,r=tw.meta('query{ objects(paging:{first:200}){ edges{ node{ nameSingular isCustom createdAt } } } }')
rec=sorted([e["node"] for e in r["data"]["objects"]["edges"] if e["node"]["isCustom"]], key=lambda x:x.get("createdAt") or "", reverse=True)[:6]
print("most-recent custom objects:", [(o["nameSingular"], (o.get("createdAt") or "")[:10]) for o in rec])
