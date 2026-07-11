import csv, json, re, io, sys
from collections import Counter
sys.stdout.reconfigure(encoding='utf-8')

CSV = r"C:\Users\Vilca\Downloads\Seller Tracking Workbook.xlsx - Form Responses 1.csv"
DUMP = ".crm-migrate-seller/dump.txt"
OUT = ".crm-migrate-seller/resolved.json"

GENERIC = {"instagram.com", "facebook.com", "linkedin.com", "twitter.com", "x.com", "youtube.com", "wa.me"}
def is_generic(h):
    return bool(h) and (h in GENERIC or h.endswith("indonetwork.co.id"))

def norm_host(s):
    if not s: return ""
    s = re.sub(r'^https?://', '', s.strip().lower()).split('/')[0].split('?')[0].split('#')[0]
    if s.startswith('www.'): s = s[4:]
    return s.strip()
def first_email(s):
    if not s: return ""
    for tok in re.split(r'[\s,;]+', s.strip()):
        if '@' in tok and '.' in tok.split('@', 1)[1]:
            return tok.strip()
    return ""
def email_host(e):
    return e.split('@', 1)[1].strip().lower() if e and '@' in e else ""
def valid_email(e):
    e = (e or '').strip()
    return '@' in e and ' ' not in e and '.' in e.split('@', 1)[1] if e else False

SUFFIX = {'inc','llc','ltd','limited','co','company','group','corp','corporation','holding','holdings',
          'pte','plc','sa','llp','partners','the','pt','tbk','persero'}
def norm_name(s):
    if not s: return ""
    s = s.lower().replace('&', ' and ')
    s = re.sub(r'\(.*?\)', '', s)
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    return ' '.join(t for t in s.split() if t and t not in SUFFIX)

rows = list(csv.reader(open(CSV, encoding='utf-8-sig', newline='')))
H = [h.strip() for h in rows[0]]
I = {k: H.index(v) for k, v in {
    'name': "Name", 'website': "Website", 'pic': "Main PIC Full Name", 'title': "Main PIC Job Title",
    'email': "Main PIC Email Address", 'status': "Engagement Status", 'next': "Next Steps",
    'ttc': "Time to Contact", 'pitched': "Pitched Service", 'pitchstatus': "Pitch Status"}.items()}
sheet = []
for r in rows[1:]:
    if not any((c or '').strip() for c in r): continue
    def g(k):
        i = I[k]
        return r[i].strip() if i < len(r) and r[i] else ""
    if not g('name'): continue
    sheet.append({k: g(k) for k in I})

txt = open(DUMP, encoding='utf-8', errors='replace').read()
def section(a, b):
    i = txt.find('===' + a + '===')
    if i < 0: return ""
    i = txt.find('\n', i) + 1
    j = txt.find('===' + b + '===') if b else len(txt)
    return txt[i:(j if j > 0 else len(txt))]
companies = [c for c in csv.reader(io.StringIO(section('COMPANIES', 'PEOPLE'))) if len(c) >= 3 and c[0]]
people    = [p for p in csv.reader(io.StringIO(section('PEOPLE', 'OPPS')))    if len(p) >= 4 and p[0]]
opps      = [o for o in csv.reader(io.StringIO(section('OPPS', None)))        if len(o) >= 3 and o[0]]

comp_by_host, comp_by_name = {}, {}
for c in companies:
    cid, name, dom = c[0], c[1], c[2]; ct = c[3] if len(c) > 3 else ''
    if norm_host(dom): comp_by_host.setdefault(norm_host(dom), (cid, name, ct))
    if norm_name(name): comp_by_name.setdefault(norm_name(name), (cid, name, ct))
ppl_by_email = {}
for p in people:
    if p[3]: ppl_by_email.setdefault(p[3].strip().lower(), (p[0], p[1], p[2]))
opp_company_ids = {o[2] for o in opps if o[2]}
opp_names = {norm_name(o[1]): o[1] for o in opps if len(o) > 1 and o[1]}

STATUS = {"in discussions / scheduled": "IN_DISCUSSIONS_SCHEDULED", "awaiting reply": "AWAITING_REPLY",
          "held off (check back in 3 months)": "HELD_OFF", "crash out (dnc)": "CRASH_OUT_DNC"}

def chosen_domain(wh, eh):
    if wh and not is_generic(wh): return wh
    return eh or wh or ''

resolved = []
for row in sheet:
    raw = re.sub(r'^\s*\d+\.\s*', '', row['status']).strip()
    sval = STATUS.get(raw.lower(), '')
    wh = norm_host(row['website'])
    em = first_email(row['email'])
    eh = email_host(em) if valid_email(em) else ''
    cdom = chosen_domain(wh, eh)
    cmatch, how = None, ''
    for h in [x for x in (cdom, wh, eh) if x]:
        if h in comp_by_host: cmatch, how = comp_by_host[h], 'domain'; break
    if not cmatch and norm_name(row['name']) in comp_by_name:
        cmatch, how = comp_by_name[norm_name(row['name'])], 'name'
    pmatch = ppl_by_email.get(em.lower()) if valid_email(em) else None
    final = 'CLOSED_LOST' if sval == 'CRASH_OUT_DNC' else ''
    isdup, why = False, ''
    if cmatch and cmatch[0] in opp_company_ids: isdup, why = True, 'company already has an opportunity'
    if not isdup:
        for cand in [norm_name(row['name'])] + [norm_name(s) for s in re.findall(r'\(([^)]+)\)', row['name'])]:
            if cand and cand in opp_names: isdup, why = True, 'opp name ~ ' + opp_names[cand]; break
    parts = row['pic'].split()
    title = '' if row['title'].upper() in ('N/A', 'TBD', '') else row['title']
    ns = row['next']
    if row['ttc']: ns = (ns + '\n' if ns else '') + '· Contact by: ' + row['ttc']
    stage = 'STAGE_3_SERVICE_EVALUATION_PITCH' if row['pitched'] else 'STAGE_1_INTRODUCTION_MEETING_SCREENING'
    warn = []
    if not valid_email(em): warn.append('PIC email invalid/missing: ' + repr(row['email']))
    elif wh and is_generic(wh): warn.append('generic/social website %s -> domain from email (%s)' % (wh, eh or 'none'))
    elif wh and eh and wh != eh: warn.append('website host %s != email host %s' % (wh, eh))
    resolved.append({
        'company': row['name'], 'website': row['website'], 'new_domain': ('' if cmatch else cdom),
        'company_match': {'id': cmatch[0], 'name': cmatch[1], 'how': how} if cmatch else None,
        'pic_name': row['pic'], 'pic_first': parts[0] if parts else '',
        'pic_last': ' '.join(parts[1:]) if len(parts) > 1 else '', 'pic_title': title,
        'pic_email': em if valid_email(em) else '',
        'person_match': {'id': pmatch[0]} if pmatch else None,
        'engagement_raw': raw, 'engagement_value': sval, 'final_decision': final,
        'stage': stage, 'client_type': 'SELL_SIDE', 'next_steps': ns,
        'is_dup': isdup, 'dup_why': why, 'warnings': warn})

json.dump(resolved, open(OUT, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
print("sheet=%d companies=%d people=%d opps=%d" % (len(sheet), len(companies), len(people), len(opps)))
print("status:", dict(Counter(r['engagement_value'] for r in resolved)))
print("dups:", [r['company'] for r in resolved if r['is_dup']])
print("new companies:", sum(1 for r in resolved if not r['company_match'] and not r['is_dup']))
print("new people:", sum(1 for r in resolved if not r['person_match'] and not r['is_dup']))
print()
for i, r in enumerate(resolved, 1):
    cm = r['company_match']
    co = ('EXIST(%s):%s' % (cm['how'], cm['name'])) if cm else ('NEW dom=%s' % (r['new_domain'] or '-'))
    print("%2d %-42s %-30s pic=%-4s %-22s fd=%-11s%s%s" % (
        i, r['company'][:42], co[:30], 'EXIST' if r['person_match'] else 'new',
        r['engagement_value'], r['final_decision'] or '-',
        '  DUP' if r['is_dup'] else '', ('  WARN:' + ';'.join(r['warnings'])) if r['warnings'] else ''))
