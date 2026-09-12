# SOLUSDEV-260 Phase 5 preflight

Prepared read-only against incoming `3661e6d`; execute only after Phase 4 passes.
Merge order remains 251 → 252 → 250. This file does not claim 250 is merged.

Reconcile these documents section by section against the settled implementation:
`docs/api/hardware.md`, `docs/architecture/hardware-onboarding.md`,
`docs/architecture/workspace-navigation.md`, `docs/wireflows/hardware-onboarding.md`,
`docs/wireflows/workspace.md`. The incoming QA is
`docs/qa/COWORK_QA_SOLUSDEV-250.md` (33 steps). Its old Alembic head must be updated.

The watcher is actually API-owned (`hardware/device_watch.py`, `graph/live.py`,
`main.py`), publishing full lists locally. Desktop consumption is projectEvents,
useWorkspaceEvents and detectedDevicesStore. Verify coexistence with the real
companion; do not assume the watch loop lives in the companion because the prompt
uses that shorthand.

The existing launcher is `scripts/dev-all.sh`; `scripts/dev-up` exists in neither
input. Fix the actual launcher’s worktree port handling and foreign-PID refusal.
Protected hook edits remain forbidden by the repository instructions; report the
H10 database selection gap without editing or bypassing the hook. The current hook
has a 1000-second timeout, not the historical report’s 600 seconds.

The six pre-existing formatting files, to format in their own commit, are:

- integrations/mcp/altium/tests/test_launch_entrypoint.py
- integrations/mcp/altium/tests/test_write_tool_guard.py
- integrations/mcp/kicad/tests/test_fixture_integrity.py
- integrations/mcp/tools/tests/test_audit_fabricated_tools.py
- livebench/tests/lb_deploy_fs_test.py
- livebench/tests/lb_firmware_test.py

Fresh performance review targets incoming commit `89907b8`: proposal cache/router,
workspace graph caches/events/optimistic state, hardware proposal cards/hooks,
physical robot state, sidebar, navigator/card code and performance marks.

The user approved one console root logging handler. Remaining implementation must
include unified unassigned rows, honest 404/409 errors, serial-less identity copy,
readable Onshape account identity, sidebar → SOL, and asynchronous confirmation
connection state with measured latency. Write exact ownership manifests only after
inspecting the actual merge; shared router/UI seams are sequential before workers.

Fresh-context read-only review of `89907b8` found four cases to reproduce after
the merge:

- A delayed WorkspaceScreen device GET can overwrite a newer full SSE list or
  repopulate state after an account/project remount. Guard seed generations and
  do not apply a seed after an authoritative frame.
- A cached hardware confirmation skips present-device validation. Propose, unplug,
  then confirm within the cache window must still refuse the absent device.
- Graph invalidation suppresses equal versions, but `MAX(updated_at)` is not a
  commit-order revision. Exercise a late commit with an older timestamp and
  unchanged counts; its graph event must still refresh the view.
- Global latency marks conflate simultaneous confirmations and do not reset for
  replug. Correlate confirmations and label receipt-to-render separately from
  physical plug-in latency; verify overlapping actions and repeated appearances.

This review is preflight only; none of these fixes is claimed implemented yet.
