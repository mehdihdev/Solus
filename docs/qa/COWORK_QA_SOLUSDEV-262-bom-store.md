# QA — persistent first-party BOM Store listing

## Setup

Use the completed API checkout with its migrated PostgreSQL database and persistent ArtifactStore
(the local verified root is `tmp/solus262-artifacts`). Sign in to the desktop and open a project.
The official BOM 0.1.0 is already published locally. A fresh environment needs an existing staff
publisher configured in both `SOLUS_STAFF_USER_IDS` and `SOLUS_FIRST_PARTY_PUBLISHER_ID`, then
`make store-setup`. Do not put passwords in either setting. Shared deployments require their own
configuration and deployment of this change; local publication does not publish to another API.

## User flows

1. [ ] Open Store. Expect a BOM card by Solus under available extensions. Open it: the overview,
   icon, version, settings definitions and first-party capabilities load with no broken assets.
2. [ ] In a project without CAD/EDA, expect the listing to remain visible with unmet requirements.
   Install is disabled. Connect an authorized EDA or CAD source; return to BOM and expect Install.
3. [ ] Choose Install, inspect the normal permission step and cancel. No workspace installation
   appears. Repeat and grant/install. Expect BOM in the workspace rail and a working BOM page.
4. [ ] Add a disposable purchase row, change its lifecycle and set currency/supplier preferences.
   Reload and restart the API using the same database/storage. Expect the same installed version,
   row and settings. An empty design must never gain invented design parts.
5. [ ] Disable BOM, restart, and verify it stays disabled. Enable it and verify existing data.
   Pin for all projects; another project has a pinned but uninstalled state, not an auto-install.
6. [ ] In a disposable project, uninstall through its confirmation. Expect widget-owned data and
   installation state removed by the existing lifecycle, but the global BOM Store card remains.
7. [ ] Repeat setup twice or start two configured APIs concurrently. Expect one release/version,
   no duplicate assets or installs, and no automatic update to an existing workspace version.

## Failure paths (disposable database/storage only)

- [ ] Missing/non-staff publisher: publication refuses; no account is promoted or created.
- [ ] Foreign slug ownership, same version with different bytes, withdrawn/rejected version:
  setup refuses visibly and preserves prior data. It must not silently resurrect a version.
- [ ] Missing/corrupt bundle, icon or overview, missing asset row or wrong metadata: health fails.
  Shared environment refuses startup. Development without configured provisioning prints remedy.
- [ ] Missing latest-version pointer: health fails despite an approved version row existing.
- [ ] Viewer/team-isolation/team-block cases: existing permission boundaries continue to apply.
- [ ] Source distribution → wheel build from a clean source archive contains all five BOM assets;
  no checkout-only fixture dependency exists.

Visual QA was not completed by the agent: automatic browser approval review rejected access to
the local app. API publication, normal catalog query and persistence checks did complete.
