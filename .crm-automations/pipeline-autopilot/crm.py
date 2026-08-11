"""Board definitions, live field introspection, and the write surface.

The board map here is the THIRD copy of the same segment->board mapping. The other two are
  .crm-automations/clienttype-sync/sync.py:44-50   (segment -> table / create mutation / stage)
  Sales Engine VM/src/callintel/resolve.ts:17-28   (segment -> REST plural / note target field)
Nothing checks the three agree. If a board is added, renamed or split, all three change together.

Field metadata is read live from /metadata and never hardcoded, because the whole point of this
automation is that it notices when the CRM and the spec disagree. Note the query shape: fields come
from the `fields` ROOT query filtered by objectMetadataId. The nested form (objects { fields })
silently returns three fields instead of thirty-three — no error, no pageInfo warning. That cost a
day during the v2 migration; see .crm-migrate-v2/runner.py:34-46.

Writes go through REST PATCH, which is the path the v2 migration actually used in anger
(.crm-migrate-v2/04_map_stages.py:76). Notes go through core GraphQL, which is what Call
Intelligence uses (Sales Engine VM/src/callintel/twentyNotes.ts:43-47).
"""
import json

import twclient as tw

SCHEMA = "workspace_4cukon3ltvwq3m1goqws3p4lv"

# side -> everything needed to read, write and talk about one board.
#   object     metadata nameSingular
#   plural     REST path segment and GraphQL collection name
#   table      physical Postgres table (LEADING UNDERSCORE - the API name has none)
#   segment    Company.clientType value that creates records here
#   pipeline   key in workflow_spec.PIPELINES, or None when the spec does not describe this board
#   note_field noteTarget column for attaching a note to a record here
BOARDS = {
    "buy": {
        "object": "buyOpportunity", "plural": "buyOpportunities", "table": "_buyOpportunity",
        "segment": "BUY_SIDE", "pipeline": "buy", "note_field": "targetBuyOpportunityId",
    },
    "sell": {
        "object": "sellOpportunity", "plural": "sellOpportunities", "table": "_sellOpportunity",
        "segment": "SELL_SIDE", "pipeline": "sell", "note_field": "targetSellOpportunityId",
    },
    "other": {
        "object": "otherOpportunity", "plural": "otherOpportunities", "table": "_otherOpportunity",
        # The spec has no `other` pipeline. Its MIGRATION row says "Follows Buy", and its stage and
        # verdict enums are byte-identical to buy's, so buy's rules drive it.
        "segment": "OTHERS", "pipeline": "buy", "note_field": "targetOtherOpportunityId",
    },
    "fulfillment": {
        "object": "fulfillment", "plural": "fulfillments", "table": "_fulfillment",
        "segment": "FULFILLMENT", "pipeline": "fulfillment",
        "note_field": "targetFulfillmentId",
    },
    "networking": {
        "object": "networking", "plural": "networkings", "table": "_networking",
        # Deliberately None: networking was out of scope for the v2 migration and still carries the
        # pre-v2 stages (REACHED_OUT / INTRO_CALL / ONGOING_DIALOGUE / ACTIVELY_ENGAGED). Nothing
        # in workflow_spec.py describes it, so this board gets derived activity fields and notes
        # only - never a stage move. Giving it stage automation means first adding a `networking`
        # pipeline to the spec, which is a business decision, not a code change.
        "segment": "NETWORK", "pipeline": None, "note_field": "targetNetworkingId",
    },
}

_OBJECT_IDS = None
_FIELDS = {}

_OBJ_Q = 'query{ objects(paging:{first:200}){ edges{ node{ id nameSingular } } } }'
# The ROOT fields query. See the module docstring for why the nested form is unusable.
_FLD_Q = ("query F($f: FieldFilter){ fields(paging:{first:500}, filter:$f){"
          " edges{ node{ id name label type options defaultValue isNullable } }"
          " pageInfo{ hasNextPage } } }")


def object_ids():
    global _OBJECT_IDS
    if _OBJECT_IDS is None:
        data = tw.gql_checked(_OBJ_Q, metadata=True)
        _OBJECT_IDS = {n["node"]["nameSingular"]: n["node"]["id"]
                       for n in data["objects"]["edges"]}
    return _OBJECT_IDS


def fields(side):
    """{fieldName: {label, type, options:[values], defaultValue, nullable}} for one board, live."""
    if side in _FIELDS:
        return _FIELDS[side]
    out = fields_for_object(BOARDS[side]["object"])
    _FIELDS[side] = out
    return out


def fields_for_object(obj):
    """Same, for any object by metadata nameSingular - `company` and `person` included.

    Split out from fields() so a caller that is not a board (the AI Access context pack needs
    Company's clientType options and Person's shape) gets the same query rather than writing its own
    and rediscovering the nested-form trap in the module docstring the hard way.
    """
    if obj in _FIELDS:
        return _FIELDS[obj]
    oid = object_ids().get(obj)
    if not oid:
        raise RuntimeError("object %r not found in metadata" % obj)
    data = tw.gql_checked(_FLD_Q, {"f": {"objectMetadataId": {"eq": oid}}}, metadata=True)
    if data["fields"]["pageInfo"].get("hasNextPage"):
        raise RuntimeError("%s has more than 500 fields; paging needed" % obj)
    out = {}
    for edge in data["fields"]["edges"]:
        n = edge["node"]
        opts = n.get("options") or []
        out[n["name"]] = {
            "id": n["id"],
            "label": n.get("label"),
            "type": n.get("type"),
            "options": [o["value"] for o in opts],
            "option_labels": {o["value"]: o.get("label") for o in opts},
            "default": n.get("defaultValue"),
            "nullable": n.get("isNullable"),
        }
    _FIELDS[obj] = out
    return out


def stage_options(side):
    return fields(side).get("stage", {}).get("options", [])


def write_key(side, field):
    """The key PATCH expects for a field. RELATION fields are read as `owner` but written as
    `ownerId` - the metadata name is the relation, the join column is what you set. Verified by
    round-trip against a throwaway record; sending `owner` is silently ignored."""
    meta = fields(side).get(field)
    if meta and meta["type"] == "RELATION" and not field.endswith("Id"):
        return field + "Id"
    return field


# ── reads ──────────────────────────────────────────────────────────────────────────────────────

_MEMBERS = None


def workspace_members():
    """[{id, email, name}] for every workspace member, cached for the process.

    Needed so `owner` can be assigned. The judgement layer can only ever name a person the way the
    email does - "fadil@nobridge.co" or "Fadil Lubis" - and a RELATION field needs a record id, so
    something has to do the lookup. Degrades to an empty list rather than failing a run: an
    unassignable owner is a flag, not a crash.
    """
    global _MEMBERS
    if _MEMBERS is not None:
        return _MEMBERS
    try:
        st, body = tw.rest("GET", "/workspaceMembers?limit=60")
        rows = (body.get("data") or {}).get("workspaceMembers") or [] if st == 200 else []
    except Exception:                                    # noqa: BLE001
        rows = []
    out = []
    for m in rows:
        name = m.get("name") or {}
        full = " ".join(x for x in (name.get("firstName"), name.get("lastName")) if x)
        email = ((m.get("userEmail") or "")
                 or ((m.get("emails") or {}).get("primaryEmail") or ""))
        out.append({"id": m.get("id"), "email": email.lower(), "name": full})
    _MEMBERS = out
    return _MEMBERS


def resolve_member(value):
    """An email, a display name, or 'Name <email>' -> a workspaceMember id, or None."""
    if not value:
        return None
    s = str(value).strip().lower()
    if "<" in s and ">" in s:
        s = s[s.index("<") + 1:s.index(">")].strip()
    for m in workspace_members():
        if m["email"] and m["email"] == s:
            return m["id"]
    for m in workspace_members():
        if m["name"] and m["name"].lower() == s:
            return m["id"]
    # A bare first name is how people actually get referred to in mail.
    for m in workspace_members():
        first = (m["name"] or "").split(" ")[0].lower()
        if first and first == s:
            return m["id"]
    return None


def get_record(side, record_id):
    plural = BOARDS[side]["plural"]
    st, body = tw.rest("GET", "/%s/%s" % (plural, record_id))
    if st != 200:
        raise RuntimeError("GET %s/%s -> %s %s" % (plural, record_id, st, json.dumps(body)[:400]))
    data = body.get("data") or {}
    # REST returns the record under its singular name.
    return data.get(BOARDS[side]["object"]) or data


def list_records(side, limit=200):
    """Every record on a board, paged. Cursor comes from pageInfo.endCursor - NOT a record id."""
    plural = BOARDS[side]["plural"]
    out, cursor = [], None
    while True:
        q = "/%s?limit=%d" % (plural, limit) + ("&starting_after=%s" % cursor if cursor else "")
        st, body = tw.rest("GET", q)
        if st != 200:
            raise RuntimeError("GET %s -> %s %s" % (q, st, json.dumps(body)[:400]))
        chunk = (body.get("data") or {}).get(plural) or []
        out.extend(chunk)
        info = body.get("pageInfo") or {}
        if not info.get("hasNextPage") or not chunk:
            return out
        cursor = info.get("endCursor")
        if not cursor:
            return out


# ── writes ─────────────────────────────────────────────────────────────────────────────────────

def patch(side, record_id, data):
    """PATCH one record. `data` is {apiFieldName: value}; only send fields that changed.

    Relation names are translated to their join column (owner -> ownerId) so callers can speak in
    the spec's terms throughout.
    """
    plural = BOARDS[side]["plural"]
    data = {write_key(side, k): v for k, v in data.items()}
    st, body = tw.rest("PATCH", "/%s/%s" % (plural, record_id), data)
    if st not in (200, 201):
        raise RuntimeError("PATCH %s/%s %s -> %s %s"
                           % (plural, record_id, json.dumps(data)[:200], st,
                              json.dumps(body)[:600]))
    return body


_CREATE_NOTE = 'mutation N($data: NoteCreateInput!){ createNote(data:$data){ id } }'
_CREATE_NOTE_TARGET = ('mutation T($data: NoteTargetCreateInput!){'
                       ' createNoteTarget(data:$data){ id } }')


def create_note(title, markdown, targets):
    """Create a note and link it to every target. `targets` is [(field, id), ...].

    Partial-success tolerant, like Call Intelligence: a note that lands on the deal but fails to
    link to the company is still worth having, so only a total failure rolls back. Returns
    (noteId, linked, failed).
    """
    if not targets:
        raise ValueError("create_note: refusing to create a note with no targets")
    data = tw.gql_checked(_CREATE_NOTE, {"data": {"title": title[:240],
                                                  "bodyV2": {"markdown": markdown}}})
    note_id = data["createNote"]["id"]
    linked, failed, seen = 0, [], set()
    for field, tid in targets:
        if not tid or (field, tid) in seen:
            continue
        seen.add((field, tid))
        try:
            tw.gql_checked(_CREATE_NOTE_TARGET, {"data": {"noteId": note_id, field: tid}})
            linked += 1
        except Exception as e:  # noqa: BLE001
            failed.append("%s=%s: %s" % (field, tid, e))
    if linked == 0:
        try:
            tw.gql_checked('mutation D($id: UUID!){ deleteNote(id:$id){ id } }', {"id": note_id})
        except Exception:  # noqa: BLE001 - the orphan note is the lesser problem
            pass
        raise RuntimeError("note %s linked to nothing: %s" % (note_id, "; ".join(failed)))
    return note_id, linked, failed


if __name__ == "__main__":
    for side in BOARDS:
        f = fields(side)
        print("%-12s %3d fields | stage: %s"
              % (side, len(f), " ".join(stage_options(side)) or "(none)"))
