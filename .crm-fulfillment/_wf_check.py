import json, tw
# Twenty workflows feature?
for q in ["query{ workflows(first:50){ edges{ node{ id name } } } }"]:
    st,r=tw.gql(q)
    if r.get("data"):
        wfs=[n["node"]["name"] for n in r["data"]["workflows"]["edges"]]
        print("workflows:", wfs)
        print("henry workflows:", [w for w in wfs if "henry" in (w or "").lower()])
    else:
        print("workflows query:", [e.get("message") for e in r.get("errors",[])][:1])
