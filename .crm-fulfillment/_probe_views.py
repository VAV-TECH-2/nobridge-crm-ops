import json, tw
INTRO = """query{ __schema{ queryType{ fields{ name } } } }"""
for label, fn in [("CORE /graphql", lambda q: tw.gql(q)), ("METADATA", lambda q: tw.meta(q))]:
    st, r = fn(INTRO)
    names = [f["name"] for f in r.get("data",{}).get("__schema",{}).get("queryType",{}).get("fields",[])] if r.get("data") else []
    hits = [n for n in names if "iew" in n.lower()]
    print(f"\n{label}: status={st} view-ish query fields -> {hits}")
# also mutations on core for view groups/fields
MUT = """query{ __schema{ mutationType{ fields{ name } } } }"""
st, r = tw.gql(MUT)
mnames = [f["name"] for f in r.get("data",{}).get("__schema",{}).get("mutationType",{}).get("fields",[])] if r.get("data") else []
print("\nCORE view-ish mutations ->", [n for n in mnames if "iew" in n.lower()])
