"""Probe the metadata updateOneField mutation shape + opportunity total, for the stage migration."""
import json, tw

# metadata mutation args for field ops
st, r = tw.meta('query{ __type(name:"Mutation"){ fields{ name args{ name type{ kind name ofType{ kind name } } } } } }')
if st == 200 and r.get("data", {}).get("__type"):
    for f in r["data"]["__type"]["fields"]:
        if f["name"] in ("updateOneField", "deleteOneField"):
            print("META MUT", f["name"], ":", json.dumps(f["args"]))
else:
    print("meta mutation introspection failed:", st, json.dumps(r)[:300])

# the UpdateOneFieldMetadataInput shape
for tn in ["UpdateOneFieldMetadataInput", "UpdateFieldInput"]:
    st, r = tw.meta('query{ __type(name:"%s"){ inputFields{ name type{ kind name ofType{ kind name } } } } }' % tn)
    fs = r.get("data", {}).get("__type")
    print(tn, ":", [f["name"] for f in fs["inputFields"]] if fs else ("(none) " + str(st)))

# opportunity total + per-stage tally (paginate)
total = 0
tally = {}
after = None
for _ in range(50):
    q = 'query($a:String){ opportunities(first:60, after:$a){ totalCount edges{ node{ stage } } pageInfo{ hasNextPage endCursor } } }'
    st, r = tw.gql(q, {"a": after})
    if st != 200:
        print("count query failed:", st, json.dumps(r)[:300]); break
    conn = r["data"]["opportunities"]
    total = conn.get("totalCount", total)
    for e in conn["edges"]:
        s = e["node"]["stage"]
        tally[s] = tally.get(s, 0) + 1
    if conn["pageInfo"]["hasNextPage"]:
        after = conn["pageInfo"]["endCursor"]
    else:
        break
print("TOTAL opportunities:", total)
print("BY STAGE:", json.dumps(tally, indent=2))
