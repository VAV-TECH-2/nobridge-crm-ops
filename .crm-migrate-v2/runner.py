"""Shared harness for the v2 migration scripts — dry run by default, --apply to write.

Every mutation in this folder goes through `Run.write()`. That is deliberate: the safety property
("nothing changes without --apply") is then one function, provable by reading it, rather than a
convention repeated in six scripts and correct in five of them.

A dry run still READS the live CRM — it introspects the schema and counts affected records — so
running one proves the object names, field names and stage values resolve before anything is
applied. That is the whole value of a dry run; a purely offline one only proves the file parses.
"""
import json
import os
import sys
import time

import tw

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST_DIR = os.path.join(HERE, "manifests")


class Run:
    def __init__(self, name, what):
        self.name = name
        self.apply = "--apply" in sys.argv
        self.changes = []
        self.reads = 0
        print(f"\n\033[1m{name}\033[0m — {what}")
        print("\033[33mDRY RUN — no changes will be made\033[0m" if not self.apply
              else "\033[31m*** APPLY — this will modify the live CRM ***\033[0m")
        print()

    # -- reads -------------------------------------------------------------
    # Fields are fetched per object through the `fields` ROOT query, not nested inside `objects`.
    # The nested form silently returns three fields instead of thirty-three — no error, no
    # pageInfo warning — which would have made 01_add_fields cheerfully create sixteen duplicates
    # of columns that already exist. Caught by dry-running against the live schema, which is the
    # entire reason dry runs are allowed to read.
    _OBJ_Q = "query{ objects(paging:{first:200}){ edges{ node{ id nameSingular } } } }"
    # `defaultValue` is selected because removing a SELECT option the field still defaults to is
    # rejected outright: METADATA_VALIDATION_FAILED, "Default value must be one of the option
    # values". 06 hit that on its first apply. It is read here rather than in 06 so the value can
    # be recorded in a manifest before it is changed.
    _FLD_Q = ("query F($f: FieldFilter){ fields(paging:{first:500}, filter:$f){"
              " edges{ node{ id name label type options defaultValue } }"
              " pageInfo{ hasNextPage } } }")

    def objects(self, only=None):
        """nameSingular -> {id, fields{name -> field}}. `only` limits the field fetch."""
        st, r = tw.meta(self._OBJ_Q)
        self.reads += 1
        if st != 200 or "data" not in r:
            raise SystemExit(f"cannot read metadata ({st}): {json.dumps(r)[:400]}")
        out = {e["node"]["nameSingular"]: {"id": e["node"]["id"], "fields": {}}
               for e in r["data"]["objects"]["edges"]}
        for name in (only or out):
            if name not in out:
                continue
            st, fr = tw.meta(self._FLD_Q,
                             {"f": {"objectMetadataId": {"eq": out[name]["id"]}}})
            self.reads += 1
            if st != 200 or "data" not in fr:
                raise SystemExit(f"cannot read fields of {name} ({st}): {json.dumps(fr)[:400]}")
            page = fr["data"]["fields"]
            if page["pageInfo"]["hasNextPage"]:
                raise SystemExit(f"{name} has more than 500 fields — paginate before trusting this")
            out[name]["fields"] = {e["node"]["name"]: e["node"] for e in page["edges"]}
        return out

    def count(self, plural, where=""):
        st, r = tw.rest("GET", f"/{plural}?limit=1{where}")
        self.reads += 1
        if st != 200:
            return None
        return r.get("totalCount", r.get("pageInfo", {}).get("totalCount"))

    # -- writes ------------------------------------------------------------
    def write(self, label, fn):
        """The ONLY mutation path. In a dry run it records the intent and calls nothing."""
        self.changes.append(label)
        if not self.apply:
            print(f"    \033[33mwould\033[0m  {label}")
            return None
        print(f"    \033[32mdoing\033[0m {label}")
        st, r = fn()
        if st != 200 or "errors" in r:
            raise SystemExit(f"FAILED on '{label}' ({st}): {json.dumps(r)[:600]}")
        return r

    def skip(self, label):
        print(f"    \033[90mok\033[0m    {label}")

    # -- manifest ----------------------------------------------------------
    def manifest(self, payload):
        """Written BEFORE any mutation, so rollback.py always has something to restore from.
        Never written on a dry run — a manifest for changes that did not happen would be a lie
        rollback would act on."""
        if not self.apply:
            print(f"\n  (a manifest would be written to manifests/{self.name}-*.json)")
            return
        os.makedirs(MANIFEST_DIR, exist_ok=True)
        path = os.path.join(MANIFEST_DIR, f"{self.name}-{time.strftime('%Y%m%d-%H%M%S')}.json")
        with open(path, "w") as f:
            json.dump(payload, f, indent=1)
        print(f"\n  manifest: {path}")

    def done(self):
        print()
        if not self.changes:
            print("  nothing to do — already in the target state")
        elif self.apply:
            print(f"  \033[32m{len(self.changes)} change(s) applied\033[0m")
        else:
            print(f"  \033[33m{len(self.changes)} change(s) would be made\033[0m "
                  f"({self.reads} reads, 0 writes)")
            print("  Run with --apply to execute.")
        print()
