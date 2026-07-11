"""Build the consolidated 'what to follow up on' digest from the LIVE CRM.

Read-only: fetches every open buy-side opportunity, derives each deal's current
stage + next action (same logic the engine uses), and renders ONE digest. Prints
a text preview AND writes the Google Chat cardsV2 JSON to digest_card.json.
Does NOT send anything.
"""
import json, tw

FIELDS = """id name stage clientType finalDecision engagementStatus meetingOutcome revampNeeded
outreachSentAt recapSentAt strategySentAt revampSentAt repliedAt escalatedAt updatedAt
pointOfContact{ name{ firstName lastName } emails{ primaryEmail } } company{ name }"""

CRM = "https://heydeal.co/object/opportunity/"


def fetch_all():
    out, after = [], None
    while True:
        st, r = tw.gql('query($a:String){ opportunities(first:60, after:$a){ edges{ node{ %s } } pageInfo{ hasNextPage endCursor } } }' % FIELDS, {"a": after})
        if st != 200:
            print("ERR", json.dumps(r)[:400]); break
        c = r["data"]["opportunities"]
        out += [e["node"] for e in c["edges"]]
        if c["pageInfo"]["hasNextPage"]:
            after = c["pageInfo"]["endCursor"]
        else:
            break
    return out


def derive(o):
    s = o.get("stage"); mo = o.get("meetingOutcome"); fd = o.get("finalDecision"); es = o.get("engagementStatus")
    if fd == "CLOSED_WON" or s == "CLOSED_WON": return ("Won", None, "Deal won — no action.")
    if fd in ("CLOSED_LOST", "GHOSTED") or es == "CRASH_OUT_DNC" or s == "LOST": return ("Lost/closed", None, "Closed — no action.")
    if es == "HELD_OFF" or fd == "HOLD_OFF": return ("On hold", "C01", "Re-engage with a fresh thread (auto ~90 days after hold).")
    if s == "NEW_LEAD": return ("New lead", "B01" if o.get("outreachSentAt") else "A01",
        "Follow up — outreach sent, no booking yet." if o.get("outreachSentAt") else "Send intro + booking link (24h SLA).")
    if s == "STRATEGY": return ("Strategy", "B03" if o.get("strategySentAt") else "A04",
        "Chase to book the strategy-review meeting." if o.get("strategySentAt") else "Produce + send the strategy doc.")
    if s == "REVAMPS": return ("Revamps", "B04" if o.get("revampSentAt") else "A05",
        "Chase to book the pitch meeting." if o.get("revampSentAt") else "Deliver the revamps.")
    if s in ("MEETING_1", "MEETING_2", "MEETING_3"):
        mtg = {"MEETING_1": 1, "MEETING_2": 2, "MEETING_3": 3}[s]
        if mo == "NO_SHOW": return (f"Mtg {mtg} no-show", "B02", f"They no-showed Mtg {mtg} — reschedule, then chase.")
        if mo == "HOSTED": return (f"Mtg {mtg} hosted", "A03", f"Send the recap / summary for Mtg {mtg} (24h SLA).")
        if mo in ("RESCHEDULED", "CANCELLED"): return (f"Mtg {mtg} moved", "D04", f"Re-confirm the rescheduled Mtg {mtg}.")
        return (f"Mtg {mtg} scheduled", "A02", f"Send confirmation + agenda for Mtg {mtg} (24h SLA).")
    return (str(s), None, "No automation mapped.")


def contact_of(o):
    poc = o.get("pointOfContact") or {}
    nm = poc.get("name") or {}
    name = " ".join(filter(None, [nm.get("firstName"), nm.get("lastName")])) or "—"
    email = (poc.get("emails") or {}).get("primaryEmail") or ""
    return name, email


opps = fetch_all()
buy = [o for o in opps if (o.get("clientType") == "BUY_SIDE")]
actionable = []
for o in buy:
    label, auto, todo = derive(o)
    if auto:  # something to do
        name, email = contact_of(o)
        actionable.append({
            "id": o["id"], "deal": o.get("name"),
            "company": (o.get("company") or {}).get("name") or "—",
            "contact": name, "email": email,
            "stage": label, "auto": auto, "todo": todo,
            "crm": CRM + o["id"],
        })

# group by stage label
order = ["New lead", "Mtg 1 scheduled", "Mtg 1 hosted", "Mtg 1 no-show", "Strategy",
         "Mtg 2 scheduled", "Mtg 2 hosted", "Mtg 2 no-show", "Revamps",
         "Mtg 3 scheduled", "Mtg 3 hosted", "Mtg 3 no-show", "On hold"]
def sort_key(x):
    return (order.index(x["stage"]) if x["stage"] in order else 99, x["company"].lower())
actionable.sort(key=sort_key)

# ---- text preview ----
print("=" * 72)
print(f"NOBRIDGE SALES ENGINE — action digest")
print(f"{len(buy)} buy-side deals · {len(actionable)} need action · {len(buy)-len(actionable)} won/lost/no-action")
print("=" * 72)
cur = None
for a in actionable:
    if a["stage"] != cur:
        cur = a["stage"]
        print(f"\n▸ {cur}")
    line = f"   • {a['contact']} ({a['company']}) — {a['todo']}"
    print(line)
    print(f"     {a['crm']}")

# ---- Google Chat cardsV2 (NOT sent) ----
widgets = [{"textParagraph": {"text":
    f"<b>Your buy-side follow-ups.</b> {len(actionable)} deals need action "
    f"(of {len(buy)} open). Grouped by stage. Tap a deal to open it in the CRM."}}]
cur = None
for a in actionable:
    if a["stage"] != cur:
        cur = a["stage"]
        widgets.append({"decoratedText": {"topLabel": "STAGE", "text": f"<b>{cur}</b>"}})
    widgets.append({"decoratedText": {
        "topLabel": f"{a['company']}",
        "text": f"<b>{a['contact']}</b> — {a['todo']}",
        "bottomLabel": a["email"],
        "button": {"text": "CRM", "onClick": {"openLink": {"url": a["crm"]}}},
    }})
card = {"cardsV2": [{"cardId": "se-digest", "card": {
    "header": {"title": "📋 Sales Engine — Daily Action Digest",
               "subtitle": f"{len(actionable)} deals need action"},
    "sections": [{"widgets": widgets}]}}]}
open("digest_card.json", "w", encoding="utf-8").write(json.dumps(card, ensure_ascii=False, indent=1))
print(f"\n[card JSON written to digest_card.json · {len(widgets)} widgets · NOT sent]")
