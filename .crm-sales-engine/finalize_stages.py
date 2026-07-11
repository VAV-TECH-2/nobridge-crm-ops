"""Remove the 4 old stage options AND reset the field default to a new value (NEW_LEAD)."""
import json, tw
from migrate_stages import NEW, STAGE_FIELD

UPDATE_FIELD = "mutation U($input: UpdateOneFieldMetadataInput!){ updateOneField(input:$input){ id defaultValue options } }"
st, r = tw.meta(UPDATE_FIELD, {"input": {"id": STAGE_FIELD, "update": {
    "options": [dict(o) for o in NEW],
    "defaultValue": "'NEW_LEAD'",
}}})
print("HTTP", st)
print(json.dumps(r, indent=2)[:1500])
