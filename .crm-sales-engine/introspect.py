"""Read-only introspection to verify the live v2.7.3 schema before any changes:
opportunity object/fields/stage-options, the updateOpportunity mutation shape, and the
calendar/message types used for booking + reply detection."""
import json, tw

def show(label, st, r, n=700):
    print(f"--- {label}: HTTP {st}\n{json.dumps(r)[:n]}\n")

def main():
    st, r = tw.meta('query{ objects(paging:{first:200}){ edges{ node{ id nameSingular } } } }')
    objs = {n["node"]["nameSingular"]: n["node"]["id"] for n in r["data"]["objects"]["edges"]} if st == 200 else {}
    opp = objs.get("opportunity")
    print("OPP OBJECT ID:", opp)

    # opp fields
    st, r = tw.meta('query($id:UUID!){ object(id:$id){ fieldsList{ id name type } } }', {"id": opp})
    flds = {}
    if st == 200 and r.get("data", {}).get("object"):
        flds = {f["name"]: f for f in r["data"]["object"]["fieldsList"]}
    if not flds:
        st, r = tw.meta('query{ objects(paging:{first:200}){ edges{ node{ id fields{ edges{ node{ id name type } } } } } } }')
        for e in r["data"]["objects"]["edges"]:
            if e["node"]["id"] == opp:
                flds = {f["node"]["name"]: f["node"] for f in e["node"]["fields"]["edges"]}
    print("OPP FIELDS:", sorted(flds.keys()))
    print("STAGE FIELD ID:", flds.get("stage", {}).get("id"))
    for fn in ["meetingOutcome", "outreachSentAt", "recapSentAt", "strategySentAt",
               "revampSentAt", "revampNeeded", "repliedAt", "escalatedAt"]:
        print("  exists", fn, ":", fn in flds)

    # SELECT options
    try:
        st, r = tw.meta('query($id:UUID!){ object(id:$id){ fieldsList{ name options } } }', {"id": opp})
        if st == 200 and r.get("data", {}).get("object"):
            for f in r["data"]["object"]["fieldsList"]:
                if f["name"] in ("stage", "clientType", "finalDecision", "engagementStatus"):
                    print("OPTIONS", f["name"], ":", json.dumps(f.get("options")))
        else:
            show("options query", st, r)
    except Exception as e:
        print("options exception:", repr(e))

    # core smoke
    st, r = tw.gql('query{ opportunities(first:1){ edges{ node{ id name stage clientType } } } }')
    show("CORE opportunities(first:1)", st, r, 300)

    # mutation args
    st, r = tw.gql('query{ __type(name:"Mutation"){ fields{ name args{ name type{ kind name ofType{ kind name } } } } } }')
    if st == 200 and r.get("data", {}).get("__type"):
        for f in r["data"]["__type"]["fields"]:
            if f["name"] in ("updateOpportunity", "createWebhook"):
                print("MUT", f["name"], ":", json.dumps(f["args"]))
    else:
        show("mutation introspection", st, r)

    # query fields (cal/msg names)
    st, r = tw.gql('query{ __type(name:"Query"){ fields{ name } } }')
    if st == 200 and r.get("data", {}).get("__type"):
        ns = [f["name"] for f in r["data"]["__type"]["fields"]]
        print("QUERY cal/msg fields:", [n for n in ns if "alendar" in n or "essage" in n])

    # cal/msg types
    for t in ["CalendarEvent", "CalendarEventParticipant", "Message", "MessageParticipant"]:
        st, r = tw.gql('query{ __type(name:"%s"){ fields{ name } } }' % t)
        fs = r.get("data", {}).get("__type") if st == 200 else None
        print("TYPE", t, ":", [f["name"] for f in fs["fields"]] if fs else ("FAIL " + str(st)))

if __name__ == "__main__":
    main()
