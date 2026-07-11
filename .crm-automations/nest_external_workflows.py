"""Nest the 'External Workflows' menu item INSIDE the native 'Workflows' folder
in the CRM left sidebar.

Twenty's sidebar is data-driven via core.navigationMenuItem: 'Workflows' is a FOLDER
and items become children by setting their folderId to the folder's id. This moves the
auto-created externalWorkflow OBJECT nav item under that folder via the metadata API
(the same mutation the UI's drag-to-folder uses, so the metadata cache is handled).

Idempotent: resolves both ids live, re-runnable.
"""
import os, sys, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".crm-fulfillment"))
import tw  # noqa: E402

UPDATE = ("mutation($input:UpdateOneNavigationMenuItemInput!){ "
          "updateNavigationMenuItem(input:$input){ id name folderId position } }")


def vm_psql(sql):
    remote = "sudo docker exec -i twenty-db-1 psql -U postgres -d default -tA -f -"
    out = subprocess.run(["ssh", "-o", "StrictHostKeyChecking=no", tw.VM, remote],
                         input=sql, capture_output=True, text=True, timeout=60)
    return out.stdout.strip()


def main():
    folder_id = vm_psql("SELECT id FROM core.\"navigationMenuItem\" "
                        "WHERE type='FOLDER' AND name='Workflows' LIMIT 1;")
    item_id = vm_psql("SELECT n.id FROM core.\"navigationMenuItem\" n "
                      "JOIN core.\"objectMetadata\" o ON o.id=n.\"targetObjectMetadataId\" "
                      "WHERE o.\"nameSingular\"='externalWorkflow' LIMIT 1;")
    print("Workflows folder id:", folder_id or "(not found)")
    print("externalWorkflow nav item id:", item_id or "(not found)")
    if not folder_id or not item_id:
        print("!! could not resolve ids; aborting"); return

    # position 3 -> after workflow(0), workflowRun(1), workflowVersion(2) inside the folder
    st, r = tw.meta(UPDATE, {"input": {"id": item_id, "update": {"folderId": folder_id, "position": 3}}})
    node = r.get("data", {}).get("updateNavigationMenuItem")
    if node:
        print("OK -> nested:", node)
    else:
        print("!! update failed:", st, str(r)[:400])


if __name__ == "__main__":
    main()
