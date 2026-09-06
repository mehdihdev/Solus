# Fixture Bundle

The first-party fixture for the Store. It exists to prove the whole bundle path end to end:

- a **page** in the rail (this bundle's only view);
- **backend routes** at `/api/v1/projects/{project}/widgets/fixture-bundle/notes`;
- a **graph kind**, `ext:fixture-bundle:note`, written by its tools;
- two **SOL tools** — `fixture-bundle.add_note` and the confirmation-gated `fixture-bundle.clear_notes`;
- the repo's `.solus/project.toml` `[ext.fixture-bundle]` table as team defaults.

Uninstalling it removes every note it added, its settings and its canvas slot.
