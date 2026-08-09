"""Add the 16 new fields the v2 workflow writes to. Additive only — nothing existing is touched.

  python3 01_add_fields.py            # dry run: what would be created, and what already exists
  python3 01_add_fields.py --apply    # execute

Idempotent: a field that already exists by name is reported and skipped, so a half-finished run
is resumed simply by running it again.
"""
import json
import schema
import tw
from runner import Run

CREATE = ("mutation C($input: CreateOneFieldMetadataInput!){"
          " createOneField(input:$input){ id name } }")


def main():
    r = Run("01_add_fields", f"{len(schema.NEW_FIELDS)} new fields")
    objs = r.objects(schema.ALL4)
    created = []

    for obj_name in schema.ALL4:
        if obj_name not in objs:
            raise SystemExit(f"object '{obj_name}' not found in the workspace — "
                             f"names are: {', '.join(sorted(objs))}")
        want = [f for f in schema.NEW_FIELDS if obj_name in f[2]]
        print(f"  \033[1m{obj_name}\033[0m  ({len(want)} fields)")
        existing = {v.get("label"): k for k, v in objs[obj_name]["fields"].items()}
        for label, ftype, _objs, note in want:
            if label in existing:
                r.skip(f"{label:22} {ftype:10} exists")
                continue
            payload = {"name": _camel(label), "label": label, "type": ftype,
                       "objectMetadataId": objs[obj_name]["id"],
                       "description": note, "isNullable": True}
            if ftype == "SELECT":
                payload["options"] = schema.SELECT_OPTIONS[label]
            created.append({"object": obj_name, "label": label})
            r.write(f"{label:22} {ftype:10} create",
                    lambda p=payload: tw.meta(CREATE, {"input": {"field": p}}))
        print()

    r.manifest({"created": created})
    r.done()


def _camel(label):
    parts = label.replace("-", " ").split()
    return parts[0].lower() + "".join(p.capitalize() for p in parts[1:])


if __name__ == "__main__":
    main()
