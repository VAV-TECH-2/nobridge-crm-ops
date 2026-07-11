"""Move PE/VC fulfillment records into the Networking object, then soft-delete them
from Fulfillment. Re-links the SAME company/person records. Resumable; writes manifest."""
import json, tw

MANIFEST = ".crm-fulfillment/networking_moved.json"

def load():
    try: return json.load(open(MANIFEST, encoding="utf-8"))
    except Exception: return {"moved": {}}   # fulfillmentId -> networkingId
def save(m): json.dump(m, open(MANIFEST,"w",encoding="utf-8"), indent=1, ensure_ascii=False)

def extract(res):
    d = res.get("data") if isinstance(res,dict) else None
    if isinstance(d,dict):
        for v in d.values():
            if isinstance(v,dict) and "id" in v: return v
    return None

def fetch_pe_vc():
    recs, after = [], None
    while True:
        path = "/fulfillments?filter=prospectType[eq]:PE_VC&limit=60"
        if after: path += "&starting_after=" + after
        st,r = tw.rest("GET", path)
        page = r.get("data",{}).get("fulfillments",[])
        recs += page
        pi = r.get("pageInfo") or {}
        if not pi.get("hasNextPage"): break
        after = pi["endCursor"]
    return recs

def main():
    m = load()
    recs = fetch_pe_vc()
    print("PE/VC fulfillments to move:", len(recs), "| already moved:", len(m["moved"]))
    moved = skipped = fail = 0
    for f in recs:
        fid = f["id"]
        if fid in m["moved"]: skipped += 1; continue
        body = {"name": f["name"], "stage": "REACHED_OUT"}
        if f.get("companyType"): body["investorType"] = f["companyType"]
        for k in ("country","engagementStatus","nextSteps","lastContact","followUpDate"):
            if f.get(k): body[k] = f[k]
        if f.get("companyId"): body["companyId"] = f["companyId"]
        if f.get("pointOfContactId"): body["pointOfContactId"] = f["pointOfContactId"]
        st,res = tw.rest("POST","/networkings", body)
        rec = extract(res)
        if not rec:
            fail += 1; print("  !! create FAIL", f["name"], st, json.dumps(res)[:250]);
            if fail >= 3: print("ABORT after 3 fails"); break
            continue
        nid = rec["id"]
        # soft-delete the source fulfillment
        std,_ = tw.rest("DELETE","/fulfillments/"+fid)
        m["moved"][fid] = nid; moved += 1; fail = 0
        if moved % 20 == 0: save(m); print("  ... moved", moved)
    save(m)
    print("DONE. moved=%d skipped=%d fail=%d | total in manifest=%d" % (moved, skipped, fail, len(m["moved"])))

if __name__ == "__main__":
    main()
