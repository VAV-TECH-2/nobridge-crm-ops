import tw, json
U="mutation U($input:UpdateViewFieldInput!){ updateViewField(input:$input){ id isVisible } }"
# table createdAt viewField id (captured earlier)
for vfid in ["08c86a2c-11a4-4a89-a474-758044034c34"]:
    st,r=tw.meta(U,{"input":{"id":vfid,"update":{"isVisible":False}}})
    print("hide createdAt(table):", st, "ok" if r.get("data",{}).get("updateViewField") else json.dumps(r)[:200])
