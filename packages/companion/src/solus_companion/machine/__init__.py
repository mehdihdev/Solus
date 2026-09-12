"""The built-in `machine` server (SOLUSDEV-252 S5): commands, packages, files,
environments on the customer's machine, confined to the linked workspace.

Every action is destructive on the cloud side (allowlist `requires_confirmation`);
nothing here runs until a human approved the exact plan the `dry_run` preview
showed. docs/architecture/local-machine-actions.md is the design."""
