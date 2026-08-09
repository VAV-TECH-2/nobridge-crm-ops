"""Hash the live CRM's schema + every record's stage. Read-only.

Used to PROVE a dry run changed nothing: snapshot, run every script bare, snapshot again, compare.
"""
import hashlib, json, sys, tw

PLURAL = {"buyOpportunity":"buyOpportunities","sellOpportunity":"sellOpportunities",
          "otherOpportunity":"otherOpportunities","fulfillment":"fulfillments"}

def snap():
    st,r = tw.meta("query{ objects(paging:{first:200}){ edges{ node{ id nameSingular } } } }")
    oids = {e["node"]["nameSingular"]: e["node"]["id"] for e in r["data"]["objects"]["edges"]}
    q=('query F($f: FieldFilter){ fields(paging:{first:500}, filter:$f){'
       ' edges{ node{ name label type options } } } }')
    out={}
    for name in PLURAL:
        st,fr = tw.meta(q, {"f":{"objectMetadataId":{"eq":oids[name]}}})
        out[name] = sorted((e["node"]["name"], e["node"]["type"],
                            json.dumps(e["node"]["options"], sort_keys=True))
                           for e in fr["data"]["fields"]["edges"])
        recs, cur = [], None
        while True:
            st, b = tw.rest("GET", f"/{PLURAL[name]}?limit=200" + (f"&starting_after={cur}" if cur else ""))
            ch = b.get("data",{}).get(PLURAL[name],[])
            recs += [(x["id"], x.get("stage")) for x in ch]
            pi = b.get("pageInfo") or {}
            if not pi.get("hasNextPage") or not ch: break
            cur = pi["endCursor"]
        out[name+"::records"] = sorted(recs)
    return out

if __name__ == "__main__":
    s = snap()
    blob = json.dumps(s, sort_keys=True)
    print(hashlib.sha256(blob.encode()).hexdigest())
    if len(sys.argv) > 1:
        open(sys.argv[1],"w").write(blob)
