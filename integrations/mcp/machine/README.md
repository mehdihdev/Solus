# machine — confirmed workspace file access

The companion builtin retains only `machine.read_file` and `machine.write_file`.
Both require the cloud confirmation gate. Reads are bounded at 1 MiB; writes at
200 KiB and use a same-directory temporary file plus atomic replacement. Every
path resolves within the linked workspace; no workspace means no inventory.

All environment probing and command execution is owned by the existing I3
`code` server: `code.probe_environment`, `code.plan`, `code.create_environment`,
`code.install`, `code.run`, and `code.test`. The retired machine command,
installation, environment creation and inventory tools are not advertised or
implemented. Unsupported conda/Docker/npm execution is not redirected to another
executor.

This directory has no third-party code or child launcher. The cloud-owned
allowlist remains the source of confirmation and error-recording flags. Failed
writes use the generic SOL error recorder.
