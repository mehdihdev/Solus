# Workspace account document tree — SOLUSDEV-261

Extends sources-connect-wizard.md and workspace.md for Workspace Add → Integrations.
Account expansion reads cached root navigation; a cache miss offers Load documents.
For Onshape, root collections and folders are expandable disclosure buttons using
vendor names. Expanding a folder loads its cached first page, populating it once on
an explicit expansion if absent. Children use the same recursive presentation.
Load more appends the next page; Refresh reloads the visible listing explicitly.
Only document rows invoke existing attachment/selection actions. Folder rows never
create Sources. Loading, empty, error, and retry states remain scoped to the folder.
Collapse/reopen reuses the page cache. Signing out discards client state. Depth and
ancestor-cycle bounds prevent a malformed provider tree from rendering indefinitely.
Other providers retain the existing flat list. Uses existing design tokens and
Guide/Expert setting for explanatory copy.
The account's `document_tree` capability selects this presentation; shared UI code
contains no provider-name condition. Older account responses without it retain the
flat browser.
