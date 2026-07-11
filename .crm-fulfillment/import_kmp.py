"""Import KMP Tracking Workbook prospects into the `fulfillment` object.

- Matches each prospect to existing Company + Person records (live API); creates only missing ones.
- Creates one fulfillment record per sheet row, linked to company + pointOfContact.
- Resumable via state.json; writes created.json rollback manifest.

Run preview:  DRY=1 python import_kmp.py
Run for real:        python import_kmp.py
"""
import os, re, json, sys, datetime, openpyxl, tw

DRY = os.environ.get("DRY") == "1"
XLSX = r"C:/Users/Vilca/Downloads/KMP Tracking Workbook (3).xlsx"
SHEET = "Form Responses 1"
MANDATE = "KMP"
STATE_PATH = ".crm-fulfillment/state.json"
FREEMAIL = {"gmail.com","hotmail.com","yahoo.com","outlook.com","icloud.com","qq.com","163.com","aol.com","me.com"}

# ---------- normalization (from .crm-migrate/match.py) ----------
def norm_host(s):
    if not s: return ""
    s = s.strip().lower().split("|")[0].split()[0] if s.strip() else ""
    s = re.sub(r"^https?://", "", s).split("/")[0].split("?")[0]
    if s.startswith("www."): s = s[4:]
    return s.strip()
def email_host(e): return norm_host(e.split("@",1)[1]) if e and "@" in e else ""
def valid_email(e):
    e = (e or "").strip()
    return bool(e) and "@" in e and " " not in e and "." in e.split("@",1)[1]
SUFFIX = {"inc","llc","ltd","limited","co","company","group","corp","corporation","holding",
          "holdings","pte","plc","sa","llp","partners","the","tbk","pt"}
def norm_name(s):
    if not s: return ""
    s = s.lower().replace("&"," and ")
    s = re.sub(r"[^a-z0-9 ]"," ",s)
    return " ".join(t for t in s.split() if t and t not in SUFFIX)

# ---------- field mapping ----------
def level_for(t):
    t = (t or "").lower().strip()
    if not t: return ""
    if t in ("vc","cvc","pe") or any(k in t for k in ("private equity","family office","angel","venture","cvc")):
        return "PE_VC"
    if "fmcg" in t: return "LEVEL_2_SUPPORTING_BUSINESS"
    if "dis" in t and "but" in t: return "LEVEL_1_COMPETITOR_DIRECT_RELATION"
    if any(k in t for k in ("cold chain","3pl","holding","manufactur","logistic")): return "LEVEL_3_EXPANSION"
    return ""
ENG = {"not contacted yet":"NOT_CONTACTED_YET","in discussions / scheduled":"IN_DISCUSSIONS_SCHEDULED",
       "awaiting reply":"AWAITING_REPLY","held off (check back in 3 months)":"HELD_OFF",
       "not interested":"NOT_INTERESTED"}
def eng_for(s):
    s = re.sub(r"^\s*\d+\.\s*","",(s or "")).strip().lower()
    return ENG.get(s,"")
def as_date(v):
    if isinstance(v,(datetime.datetime,datetime.date)): return v.strftime("%Y-%m-%d")
    s = str(v).strip() if v is not None else ""
    return s[:10] if re.match(r"\d{4}-\d{2}-\d{2}", s) else ""

# ---------- parse sheet ----------
def parse():
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    ws = wb[SHEET]
    rows = list(ws.iter_rows(values_only=True))
    H = [str(h).strip() if h is not None else "" for h in rows[0]]
    def idx(label):
        for i,h in enumerate(H):
            if h.lower().startswith(label.lower()): return i
        return -1
    cols = {k: idx(v) for k,v in {
        "country":"Country","type":"Type","company":"Company Name","website":"Website",
        "pic":"Main PIC Full Name","title":"Main PIC Job Title","email":"Main PIC Email",
        "secondary":"Secondary PIC","status":"Engagement Status","next":"Next Steps",
        "findings":"Meeting Findings","fathom":"Fathom Link","last":"Last contact","followup":"Follow up"}.items()}
    out = []
    for r in rows[1:]:
        def g(k):
            i = cols[k]
            return "" if i<0 or i>=len(r) or r[i] is None else r[i]
        def gs(k): return str(g(k)).strip().replace("\n"," ")
        if not gs("company"): continue
        out.append({"country":gs("country"),"type":gs("type"),"company":gs("company"),
            "website":gs("website"),"pic":gs("pic"),"title":gs("title"),"email":gs("email"),
            "secondary":gs("secondary"),"status":gs("status"),"next":gs("next"),
            "findings":gs("findings"),"fathom":gs("fathom"),
            "last":as_date(g("last")),"followup":as_date(g("followup"))})
    return out

# ---------- fetch existing (live) ----------
def fetch_all(plural, node_fields):
    q = "query($after:String){ %s(first:60, after:$after){ edges{ node{ %s } } pageInfo{ hasNextPage endCursor } } }" % (plural, node_fields)
    after, acc = None, []
    while True:
        st,r = tw.gql(q, {"after": after})
        if st!=200 or "data" not in r:
            raise RuntimeError("fetch %s failed: %s %s" % (plural, st, json.dumps(r)[:300]))
        conn = r["data"][plural]
        acc += [e["node"] for e in conn["edges"]]
        if not conn["pageInfo"]["hasNextPage"]: break
        after = conn["pageInfo"]["endCursor"]
    return acc

def build_index():
    comps = fetch_all("companies", "id name domainName{ primaryLinkUrl }")
    ppl   = fetch_all("people", "id name{ firstName lastName } emails{ primaryEmail } companyId")
    fuls  = fetch_all("fulfillments", "id companyId mandate")
    by_host, by_cname = {}, {}
    for c in comps:
        h = norm_host((c.get("domainName") or {}).get("primaryLinkUrl") or "")
        if h and h not in FREEMAIL: by_host.setdefault(h, c["id"])
        nn = norm_name(c["name"])
        if nn: by_cname.setdefault(nn, c["id"])
    by_email, by_pname = {}, {}
    for p in ppl:
        em = ((p.get("emails") or {}).get("primaryEmail") or "").strip().lower()
        if em: by_email.setdefault(em, p["id"])
        nm = norm_name(((p.get("name") or {}).get("firstName","") + " " + (p.get("name") or {}).get("lastName","")))
        if nm and p.get("companyId"): by_pname.setdefault(nm + "@" + p["companyId"], p["id"])
    # companies that already have a fulfillment for THIS mandate -> guards against duplicate
    # fulfillment records for the same company (two workbook rows / a re-run / a sync-created row).
    ful_companies = {f["companyId"] for f in fuls
                     if f.get("companyId") and (f.get("mandate") or "") == MANDATE}
    return {"comps":len(comps),"ppl":len(ppl),"by_host":by_host,"by_cname":by_cname,
            "by_email":by_email,"by_pname":by_pname,"ful_companies":ful_companies}

# ---------- state ----------
def load_state():
    try: return json.load(open(STATE_PATH, encoding="utf-8"))
    except Exception: return {"companies":{}, "people":{}, "fulfillments":{}, "created_companies":[], "created_people":[]}
def save_state(s): json.dump(s, open(STATE_PATH,"w",encoding="utf-8"), indent=1, ensure_ascii=False)

def extract(res):
    if not isinstance(res,dict): return None
    if "id" in res: return res
    d = res.get("data")
    if isinstance(d,dict):
        for v in d.values():
            if isinstance(v,dict) and "id" in v: return v
    return None

def main():
    rows = parse()
    idx = build_index()
    print("sheet rows=%d | existing companies=%d people=%d" % (len(rows), idx["comps"], idx["ppl"]))
    state = load_state()
    stats = {"co_match":0,"co_new":0,"p_match":0,"p_new":0,"p_none":0,"ful_new":0,"ful_skip":0,"fail":0}
    fails = 0
    for n, row in enumerate(rows):
        rk = "%d::%s" % (n, row["company"])
        if rk in state["fulfillments"]:
            stats["ful_skip"] += 1; continue
        # ----- resolve company -----
        wh = norm_host(row["website"]) if row["website"] and row["website"] != "-" else ""
        eh = email_host(row["email"]) if valid_email(row["email"]) else ""
        dom = wh or (eh if eh and eh not in FREEMAIL else "")
        cid = None
        for h in [x for x in (wh,eh) if x and x not in FREEMAIL]:
            if h in idx["by_host"]: cid = idx["by_host"][h]; break
        if not cid and norm_name(row["company"]) in idx["by_cname"]:
            cid = idx["by_cname"][norm_name(row["company"])]
        if cid: stats["co_match"] += 1
        else:
            valid_dom = dom if re.match(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$", dom or "") else ""
            body = {"name": row["company"]}
            if valid_dom: body["domainName"] = {"primaryLinkUrl":"https://"+valid_dom, "primaryLinkLabel":valid_dom}
            if DRY: cid = "DRY_CO_%d" % n
            else:
                st,res = tw.rest("POST","/companies",body); rec = extract(res)
                if not rec and "domainName" in body:   # retry without the (rejected) URL
                    st,res = tw.rest("POST","/companies",{"name":row["company"]}); rec = extract(res)
                if not rec: stats["fail"]+=1; fails+=1; print("  !! company FAIL", row["company"], st, json.dumps(res)[:200])
                else:
                    cid = rec["id"]; state["created_companies"].append(cid)
                    if valid_dom: idx["by_host"][valid_dom]=cid
                    idx["by_cname"][norm_name(row["company"])]=cid
            stats["co_new"] += 1
            if fails>=3: print("ABORT: 3 consecutive failures"); break
            fails = 0 if cid else fails
        # ----- resolve person (main PIC) -----
        pid = None
        pic = row["pic"].strip()
        em = row["email"].strip().lower() if valid_email(row["email"]) else ""
        if em and em in idx["by_email"]: pid = idx["by_email"][em]; stats["p_match"]+=1
        elif pic and cid and not str(cid).startswith("DRY") and (norm_name(pic)+"@"+cid) in idx["by_pname"]:
            pid = idx["by_pname"][norm_name(pic)+"@"+cid]; stats["p_match"]+=1
        elif pic:
            parts = pic.split()
            body = {"name":{"firstName":parts[0], "lastName":" ".join(parts[1:])}, "companyId":cid}
            if em: body["emails"] = {"primaryEmail": row["email"].strip()}
            if row["title"] and row["title"].upper()!="TBD": body["jobTitle"] = row["title"]
            if DRY: pid = "DRY_P_%d" % n
            else:
                st,res = tw.rest("POST","/people",body); rec = extract(res)
                if rec:
                    pid = rec["id"]; state["created_people"].append(pid)
                    if em: idx["by_email"][em]=pid
                else: print("  !! person FAIL", pic, st, json.dumps(res)[:200])
            stats["p_new"] += 1
        else:
            stats["p_none"] += 1
        # ----- dedup: skip if this company already has a fulfillment for this mandate -----
        if cid and not str(cid).startswith("DRY") and cid in idx["ful_companies"]:
            state["fulfillments"][rk] = "SKIP_DUP_COMPANY:%s" % cid
            stats["ful_skip"] += 1
            print("  ~~ skip dup fulfillment (company already has one):", row["company"])
            continue
        # ----- create fulfillment -----
        body = {"name": row["company"], "stage":"REACHED_OUT", "mandate": MANDATE}
        lv = level_for(row["type"])
        if lv: body["prospectType"] = lv
        if row["type"]: body["companyType"] = row["type"]
        if row["country"]: body["country"] = "Singapore" if row["country"].lower()=="singapore" else row["country"]
        ev = eng_for(row["status"])
        if ev: body["engagementStatus"] = ev
        if row["next"]: body["nextSteps"] = row["next"]
        if row["findings"]: body["meetingFindings"] = row["findings"]
        if row["fathom"]: body["fathomLink"] = row["fathom"]
        if row["secondary"]: body["secondaryContacts"] = row["secondary"]
        if row["last"]: body["lastContact"] = row["last"]
        if row["followup"]: body["followUpDate"] = row["followup"]
        if cid and not str(cid).startswith("DRY"): body["companyId"] = cid
        if pid and not str(pid).startswith("DRY"): body["pointOfContactId"] = pid
        if DRY:
            stats["ful_new"]+=1; continue
        st,res = tw.rest("POST","/fulfillments",body); rec = extract(res)
        if rec:
            state["fulfillments"][rk] = rec["id"]; stats["ful_new"]+=1; fails=0
            if cid and not str(cid).startswith("DRY"): idx["ful_companies"].add(cid)
            if stats["ful_new"] % 25 == 0:
                save_state(state); print("  ... %d created" % stats["ful_new"])
        else:
            stats["fail"]+=1; fails+=1
            print("  !! fulfillment FAIL", row["company"], st, json.dumps(res)[:300])
            if fails>=3: print("ABORT: 3 consecutive failures"); break
    if not DRY: save_state(state)
    print("STATS:", json.dumps(stats))
    if not DRY:
        json.dump(state, open(".crm-fulfillment/created.json","w",encoding="utf-8"), indent=1, ensure_ascii=False)
        print("manifest -> .crm-fulfillment/created.json (created %d companies, %d people, %d fulfillments)" % (
            len(state["created_companies"]), len(state["created_people"]), len(state["fulfillments"])))

if __name__ == "__main__":
    main()
