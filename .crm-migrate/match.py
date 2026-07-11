import openpyxl, csv, json, re, io, sys
sys.stdout.reconfigure(encoding='utf-8')

XLSX = r"C:/Users/Vilca/Downloads/Buyer Tracking Workbook.xlsx"
DUMP = ".crm-migrate/dump.txt"

def norm_host(s):
    if not s: return ""
    s = s.strip().lower()
    s = re.sub(r'^https?://', '', s)
    s = s.split('/')[0].split('?')[0]
    if s.startswith('www.'): s = s[4:]
    return s.strip()

def email_host(e):
    if not e or '@' not in e: return ""
    return norm_host(e.split('@', 1)[1])

def valid_email(e):
    if not e: return False
    e = e.strip()
    return '@' in e and ' ' not in e and '.' in e.split('@', 1)[1]

SUFFIX = {'inc','llc','ltd','limited','co','company','group','corp','corporation',
          'holding','holdings','pte','plc','sa','llp','partners','the'}
def norm_name(s):
    if not s: return ""
    s = s.lower().replace('&', ' and ')
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    return ' '.join(t for t in s.split() if t and t not in SUFFIX)

# ---- sheet ----
wb = openpyxl.load_workbook(XLSX, data_only=True)
ws = wb["Form Responses 1"]
rows = list(ws.iter_rows(values_only=True))
H = [str(h).strip() if h is not None else "" for h in rows[0]]
I = {k: H.index(v) for k, v in {
    'company': "Company Name", 'website': "Website", 'pic': "Main PIC Full Name",
    'title': "Main PIC Job Title", 'email': "Main PIC Email Address",
    'status': "Engagement Status", 'next': "Next Steps",
    'pitched': "Pitched Service", 'pitchstatus': "Pitch Status"}.items()}
sheet = []
for r in rows[1:]:
    if not any(c is not None and str(c).strip() for c in r): continue
    def g(k):
        i = I[k]
        return str(r[i]).strip() if i < len(r) and r[i] is not None else ""
    if not g('company'): continue
    sheet.append({k: g(k).replace('�', '-') for k in I})

# ---- dump ----
txt = open(DUMP, encoding='utf-8', errors='replace').read()
def section(name, nxt):
    a = txt.find('===' + name + '===')
    if a < 0: return ""
    a = txt.find('\n', a) + 1
    b = txt.find('===' + nxt + '===') if nxt else len(txt)
    return txt[a:(b if b > 0 else len(txt))]
companies = [c for c in csv.reader(io.StringIO(section('COMPANIES', 'PEOPLE'))) if len(c) >= 3 and c[0]]
people    = [p for p in csv.reader(io.StringIO(section('PEOPLE', 'OPPS')))    if len(p) >= 4 and p[0]]
opps      = [o for o in csv.reader(io.StringIO(section('OPPS', None)))        if len(o) >= 3 and o[0]]

comp_by_host, comp_by_name = {}, {}
for c in companies:
    cid, name, dom = c[0], c[1], c[2]
    ct = c[3] if len(c) > 3 else ''
    if norm_host(dom): comp_by_host.setdefault(norm_host(dom), (cid, name, ct))
    if norm_name(name): comp_by_name.setdefault(norm_name(name), (cid, name, ct))
ppl_by_email = {}
for p in people:
    if p[3]: ppl_by_email.setdefault(p[3].strip().lower(), (p[0], p[1], p[2]))
opp_company_ids = {o[2] for o in opps if o[2]}
opp_names_norm = {norm_name(o[1]): o[1] for o in opps if len(o) > 1 and o[1]}

STATUS_MAP = {
    "in discussions / scheduled": "IN_DISCUSSIONS_SCHEDULED",
    "awaiting reply": "AWAITING_REPLY",
    "held off (check back in 3 months)": "HELD_OFF"}
def stage_for(row):
    ps = (row['pitchstatus'] or '').lower()
    if 'scheduled' in ps or 'pending' in ps: return "STAGE_3_SERVICE_EVALUATION_PITCH"
    if 'awaiting pitch' in ps: return "STAGE_2_VALUE_CREATION"
    return "STAGE_1_INTRODUCTION_MEETING_SCREENING"

resolved = []
for row in sheet:
    wh = norm_host(row['website']) if row['website'] and row['website'] != '-' else ''
    eh = email_host(row['email']) if valid_email(row['email']) else ''
    cmatch, how = None, ''
    for h in [x for x in (wh, eh) if x]:
        if h in comp_by_host: cmatch, how = comp_by_host[h], 'domain'; break
    if not cmatch and norm_name(row['company']) in comp_by_name:
        cmatch, how = comp_by_name[norm_name(row['company'])], 'name'
    pmatch = ppl_by_email.get(row['email'].strip().lower()) if valid_email(row['email']) else None
    sval = STATUS_MAP.get(row['status'].strip().lower(), '')
    final = 'CLOSED_LOST' if sval == 'HELD_OFF' else ''
    isdup, why = False, ''
    if cmatch and cmatch[0] in opp_company_ids: isdup, why = True, 'company already has an opportunity'
    elif norm_name(row['company']) in opp_names_norm: isdup, why = True, 'opp name ~ ' + opp_names_norm[norm_name(row['company'])]
    ct = (cmatch[2] if cmatch and len(cmatch) > 2 and cmatch[2] else '') or 'BUY_SIDE'
    parts = row['pic'].split()
    warn = []
    if not valid_email(row['email']): warn.append('PIC email invalid/missing: ' + repr(row['email']))
    if wh and eh and wh != eh: warn.append('website host %s != email host %s' % (wh, eh))
    resolved.append({
        'company': row['company'], 'website': row['website'], 'domain_norm': wh or eh,
        'company_match': {'id': cmatch[0], 'name': cmatch[1], 'how': how} if cmatch else None,
        'pic_name': row['pic'], 'pic_first': parts[0] if parts else '',
        'pic_last': ' '.join(parts[1:]) if len(parts) > 1 else '',
        'pic_title': row['title'], 'pic_email': row['email'] if valid_email(row['email']) else '',
        'person_match': {'id': pmatch[0]} if pmatch else None,
        'engagement_raw': row['status'], 'engagement_value': sval, 'final_decision': final,
        'stage': stage_for(row), 'client_type': ct, 'next_steps': row['next'],
        'is_dup': isdup, 'dup_why': why, 'warnings': warn})

json.dump(resolved, open('.crm-migrate/resolved.json', 'w', encoding='utf-8'), indent=1, ensure_ascii=False)

print("sheet_rows=%d companies=%d people=%d opps=%d" % (len(sheet), len(companies), len(people), len(opps)))
print("EXISTING OPPS (name | company):")
for o in opps: print("   - %s | %s" % (o[1], o[3] if len(o) > 3 else '?'))
print()
for i, r in enumerate(resolved, 1):
    cm = r['company_match']
    co = ("EXIST(%s):%s" % (cm['how'], cm['name'])) if cm else "NEW"
    dup = "  **DUP: %s**" % r['dup_why'] if r['is_dup'] else ""
    w = "  WARN: " + "; ".join(r['warnings']) if r['warnings'] else ""
    print("%2d %-30s co=%-36s pic=%-4s stage=%s fd=%-11s ct=%s%s%s" % (
        i, r['company'][:30], co[:36], "EXIST" if r['person_match'] else "new",
        r['stage'][6:13], r['final_decision'] or '-', r['client_type'], dup, w))
