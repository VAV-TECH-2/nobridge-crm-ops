"""Verify the exact core-GraphQL query shapes the engine uses (id filter, calendar, messages)."""
import json, tw

OPP_ID = "01665797-fbf6-490b-af72-99cbc4e2c719"  # Anchanto (from introspect)

def show(l, st, r, n=700):
    print(f"--- {l}: HTTP {st}\n{json.dumps(r)[:n]}\n")

# 1) getOpportunity-style filter
show("filter id eq", *tw.gql(
    'query($id:UUID!){ opportunities(filter:{id:{eq:$id}}, first:1){ edges{ node{ id name stage } } } }',
    {"id": OPP_ID}))

# 2) calendar events + participants (with orderBy + nested first)
show("calendarEvents orderBy", *tw.gql(
    'query{ calendarEvents(first:3, orderBy:{startsAt:DescNullsLast}){ edges{ node{ id title startsAt endsAt '
    'calendarEventParticipants(first:10){ edges{ node{ handle responseStatus } } } } } } }'), 900)

# 2b) fallback: no orderBy, nested without first
show("calendarEvents plain", *tw.gql(
    'query{ calendarEvents(first:3){ edges{ node{ id startsAt endsAt '
    'calendarEventParticipants{ edges{ node{ handle } } } } } } }'), 600)

# 3) messages + participants
show("messages orderBy", *tw.gql(
    'query{ messages(first:3, orderBy:{receivedAt:DescNullsLast}){ edges{ node{ id receivedAt subject '
    'messageParticipants(first:10){ edges{ node{ role handle } } } } } } }'), 900)
