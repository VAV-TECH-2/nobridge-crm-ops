import os, json, re, sys, urllib.request, urllib.error
sys.stdout.reconfigure(encoding='utf-8')

BASE = "https://heydeal.co/rest"
TOKEN = os.environ["TWENTY_KEY"]
OWNER = os.environ.get("OWNER_ID") or None
ONLY = os.environ.get("ONLY_COMPANY")          # restrict to one company (testing)
DATA_DIR = os.environ.get("DATA_DIR", ".crm-migrate")
STATE_PATH = os.path.join(DATA_DIR, "created.json")
FREEMAIL = {"gmail.com","hotmail.com","yahoo.com","outlook.com","icloud.com","qq.com","163.com","aol.com","me.com"}

def norm_host(s):
    if not s: return ""
    s = re.sub(r'^https?://', '', s.strip().lower()).split('/')[0].split('?')[0]
    for p in ("www.", "resources."):
        if s.startswith(p): s = s[len(p):]
    return s.strip()
def email_host(e):
    return e.split('@',1)[1].strip().lower() if e and '@' in e else ""
def valid_email(e):
    e = (e or "").strip()
    return '@' in e and ' ' not in e and '.' in e.split('@',1)[1] if e else False

def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {"_error": e.read().decode()[:1000]}
    except Exception as e:
        return 0, {"_error": repr(e)}

def extract(res):
    if not isinstance(res, dict): return None
    if 'id' in res: return res
    d = res.get('data')
    if isinstance(d, dict):
        for v in d.values():
            if isinstance(v, dict) and 'id' in v: return v
    return None

def load_state():
    try: return json.load(open(STATE_PATH, encoding='utf-8'))
    except Exception: return {"companies": {}, "people": {}, "opportunities": {}}
def save_state(s): json.dump(s, open(STATE_PATH, 'w', encoding='utf-8'), indent=1)

rows = json.load(open(os.path.join(DATA_DIR, "resolved.json"), encoding='utf-8'))
last = {}
for ln in open(os.path.join(DATA_DIR, "lastcontact.txt"), encoding='utf-8'):
    p = ln.rstrip("\n").split("|")
    if len(p) >= 4 and "@" in p[0]:
        last[p[0].strip().lower()] = {"date": p[1], "msgs": p[3]}

state = load_state()
work = [r for r in rows if not r['is_dup']]
if ONLY: work = [r for r in work if r['company'].lower() == ONLY.lower()]

def co_domain(r):
    wh = norm_host(r['website']) if r['website'] and r['website'] != '-' else ''
    eh = email_host(r['pic_email']) if valid_email(r['pic_email']) else ''
    d = wh or (eh if eh not in FREEMAIL else '')
    return '' if d in FREEMAIL else d

print("=== COMPANIES (creating missing) ===")
first = True
for r in work:
    if r['company_match']:
        r['_cid'] = r['company_match']['id']; continue
    dom = r.get('new_domain') or co_domain(r)
    key = dom or ("name::" + r['company'].lower())
    if key in state["companies"]:
        r['_cid'] = state["companies"][key]; print("  skip", r['company']); continue
    body = {"name": r['company']}
    if dom: body["domainName"] = {"primaryLinkUrl": "https://" + dom, "primaryLinkLabel": dom}
    st, res = api("POST", "/companies", body)
    if first: print("  [first raw]", st, json.dumps(res)[:500]); first = False
    rec = extract(res)
    if rec:
        r['_cid'] = rec['id']; state["companies"][key] = rec['id']; save_state(state)
        print("  +", r['company'], "->", rec['id'])
    else:
        r['_cid'] = None; print("  !! FAIL", r['company'], st, json.dumps(res)[:300])

print("=== PEOPLE (creating missing) ===")
first = True
for r in work:
    if r['person_match']:
        r['_pid'] = r['person_match']['id']; continue
    em = r['pic_email'].strip().lower() if valid_email(r['pic_email']) else ""
    key = em or ("name::" + r['pic_name'].lower() + "@" + r['company'].lower())
    if key in state["people"]:
        r['_pid'] = state["people"][key]; print("  skip", r['pic_name']); continue
    if not r.get('_cid'):
        r['_pid'] = None; print("  ?? no company for", r['pic_name'], "- skipping person"); continue
    body = {"name": {"firstName": r['pic_first'], "lastName": r['pic_last']}, "companyId": r['_cid']}
    if em: body["emails"] = {"primaryEmail": r['pic_email'].strip()}
    if r['pic_title'] and r['pic_title'].upper() != "TBD": body["jobTitle"] = r['pic_title']
    st, res = api("POST", "/people", body)
    if first: print("  [first raw]", st, json.dumps(res)[:500]); first = False
    rec = extract(res)
    if rec:
        r['_pid'] = rec['id']; state["people"][key] = rec['id']; save_state(state)
        print("  +", r['pic_name'], "->", rec['id'])
    else:
        r['_pid'] = None; print("  !! FAIL", r['pic_name'], st, json.dumps(res)[:300])

print("=== OPPORTUNITIES ===")
fails = 0
for r in work:
    if r['company'] in state["opportunities"]:
        print("  skip", r['company']); continue
    ns = r['next_steps'] or ''
    em = r['pic_email'].strip().lower() if valid_email(r['pic_email']) else ''
    lc = last.get(em)
    if lc and lc['date']:
        ann = "Last email %s (%s msgs)" % (lc['date'], lc['msgs'])
        ns = (ns + " · " + ann) if ns else ann
    body = {"name": r['company'], "stage": r['stage'], "clientType": r['client_type']}
    if r['final_decision']: body["finalDecision"] = r['final_decision']
    if r['engagement_value']: body["engagementStatus"] = r['engagement_value']
    if ns: body["nextSteps"] = ns
    if r.get('_cid'): body["companyId"] = r['_cid']
    if r.get('_pid'): body["pointOfContactId"] = r['_pid']
    if OWNER: body["ownerId"] = OWNER
    st, res = api("POST", "/opportunities", body)
    rec = extract(res)
    if rec:
        state["opportunities"][r['company']] = rec['id']; save_state(state)
        print("  +", r['company'], "->", rec['id'])
        fails = 0
    else:
        fails += 1
        print("  !! FAIL", r['company'], st, json.dumps(res)[:400])
        if fails >= 2:
            print("ABORTING opportunities after 2 consecutive failures."); break

print("=== DONE === companies:%d people:%d opportunities:%d" % (
    len(state["companies"]), len(state["people"]), len(state["opportunities"])))
