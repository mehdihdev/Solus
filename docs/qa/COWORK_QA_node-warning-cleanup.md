# Node warning cleanup — SOLUSDEV-261

This is a behavior-preserving refactor of desktop components, hooks, IPC setup
and test helpers. No new user flow or public interface is intended.

## Setup

- Use the complete `SOLUSDEV-261-integration-check` working tree, including all
  uncommitted Node cleanup files; install the locked pnpm dependencies.
- For application checks, start the existing development services with
  `pnpm dev:all`, use the desktop application and a disposable local project.
- Keep live Onshape testing paused at the existing 70% quota threshold. Do not
  reconnect, sync or mutate provider resources for this cleanup. No hardware,
  firmware uploads or connected GitHub repository changes are required.
- Automated results are recorded in `CI_VERIFICATION_SOLUSDEV-261.md`. The manual
  checklist below is a handoff, not a claim of a new live acceptance run.

## Automated regression checks

- [x] Run `pnpm exec eslint . --max-warnings 0`: no errors or warnings.
- [x] Run `pnpm typecheck`: shared-types, desktop main/preload and renderer pass.
- [x] Run `pnpm test`: 279 shared-types, 3,726 desktop and 25 script tests pass.
- [x] Run `pnpm build:desktop`: generated API types and production bundles build.
- [x] Check changed TypeScript files with Prettier and scan the diff with Gitleaks:
  formatting passes and no secrets are detected.

## Local application smoke checklist

- [ ] Open Home, then a disposable project. Expand project activity, open its
  menu and close it. Expected: existing layout, controls and project title remain
  intact; activity/menu clicks do not accidentally activate another project.
- [ ] Open the project switcher and notifications, then dismiss each. Expected:
  focus, close behavior, empty states and menu placement remain unchanged.
- [ ] Open Settings and inspect preferences and panel-link controls. Expected:
  inputs, labels, enabled states and cancellation behave as before. Do not approve
  an unsolicited pairing request.
- [ ] In the desktop local-folder card, open the folder picker and cancel.
  Expected: no link created, no stuck busy state and no error for cancellation.
- [ ] Link a disposable scratch folder, then unlink it. Expected: machine-local
  link appears, scan readiness is shown honestly, and unlink clears the card.
  Repeat while switching projects during a pending selection: the previous
  project's result must not appear in the new project.
- [ ] Open an existing SOL conversation without sending a new provider action.
  Expected: messages, classification indicator, sidebar and any existing terminal
  approval cards render normally; completed cards do not become actionable again.
- [ ] With the API unavailable, revisit Home and local-folder status. Expected:
  existing offline explanations appear and stale project/team data is not shown
  under a different scope. Restore the API afterward.

The automated suites additionally cover OAuth cancellation/state checks, IPC
sender authorization, extension bridge origin/source checks, graph identity,
stale async responses, onboarding, sourcing and preserved test fixture lifetimes.
