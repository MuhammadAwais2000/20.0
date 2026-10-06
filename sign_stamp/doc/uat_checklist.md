Sign & Stamp — UAT Checklist
============================

Environment
-----------
[ ] Module installed on Odoo 20
[ ] Python packages available: pymupdf, pypdf, reportlab, Pillow
[ ] Browser hard-refreshed after asset updates

Happy path
----------
[ ] Create document, upload PDF, save
[ ] Open Editor shows source PDF preview
[ ] Draw signature -> Use drawing -> click PDF -> mark appears
[ ] Upload stamp -> click PDF -> mark appears and can drag/resize
[ ] Add date -> click PDF -> date appears
[ ] Add text -> enter custom text -> choose color/size -> click PDF -> text appears and can drag/resize
[ ] Reopen draft editor — text content, color and size are restored
[ ] Place stamp near top of page — sealed PDF shows stamp near top (not bottom)
[ ] Place signature near bottom-right — sealed PDF matches that position
[ ] Date/text placed by click appears at the same spot after Apply & Save
[ ] Signature/stamp keep natural aspect after Apply & Save (no stretch/squash)
[ ] Signature/stamp seal with transparent background (no white box)
[ ] Reopen sealed document still shows marks at correct positions


Reopen sealed document (critical)
---------------------------------
[ ] Close editor (Back)
[ ] Form shows status Sealed
[ ] Click Open Editor again
[ ] Preview loads SEALED PDF (signatures/stamps/dates already on the page)
[ ] Sidebar shows sealed/read-only message (no place tools)
[ ] Apply & Save / Reset overlay actions are hidden/disabled
[ ] Page navigation still works for multi-page PDFs

Reset to Draft
--------------
[ ] From form, Reset to Draft
[ ] Status becomes Draft
[ ] Open Editor loads original source PDF again (editable)
[ ] New marks can be placed and sealed again

Negative / QA cases
-------------------
[ ] Apply & Save with no overlays shows warning
[ ] Sealed document cannot be sealed again without reset
[ ] Large stamp image is compressed and still seals
[ ] Encrypted/corrupt PDF shows a clear error (no connection drop)

Automated tests
---------------
Run:
  odoo-bin -c /etc/odoo/odoo.conf -d YOUR_DB -u sign_stamp --test-tags sign_stamp --stop-after-init
