# Architecture — Local machine actions (SOLUSDEV-260 integration)

Local actions use the authenticated project bridge and the central confirmation gate.
The built-in `machine` server owns file reads and writes. The I3 `code` server owns
all environment observation, creation, installation, script execution and tests.
The former `machine` environment implementation and command tools are removed.

Governing references: `docs/contracts/action-gate.md`, `docs/contracts/bridge-protocol.md`,
`docs/api/code-environment.md`, `docs/architecture/code-environment.md`, and the
Solus-owned allowlists in `integrations/mcp/machine/` and `integrations/mcp/code/`.
CODE record shapes and their UI are documented in `docs/api/solus.md`.

## One approval and execution path

```text
SOL proposes a local action
  → ToolRegistry descriptor from the Solus-owned allowlist
  → central confirmation card and approve-time preview check
  → authenticated user/team/project bridge tool_call
  → companion dispatch and Supervisor
      ├─ machine.read_file / write_file → built-in MachineServer
      └─ code.create_environment / install / run / test → I3 code server
  → tool_result and best-effort post-action recording
```

The companion inventory does not decide which tools require confirmation. The
cloud allowlist provides that policy and the consent sentence. `machine.read_file`
requires confirmation because it sends local file contents to Solus; local read
access alone is not authorization to transmit raw bytes. `machine.write_file`
requires confirmation before creating or replacing content. Their argument rows
show the selected path and, for writes, the proposed content through the existing
bounded confirmation presentation.

I3 command previews come from `code.plan`, showing the actual argv and cwd. The
adapter refuses unrenderable plans, includes an exact-plan fingerprint, and requires
a matching one-use preview snapshot before invoking the existing bridge tool.
Named environment observation and CODE recording use the same scoped bridge;
see `code-environment.md` for snapshot and partial-observation semantics.

## Built-in file server

`MachineServer` implements the Supervisor built-in interface and returns MCP
`CallToolResult` values. It has no subprocess or `bin/launch`. Its allowlist declares
`launched_by: builtin`; cloud-owned forks, including Brave, are not launched by the
companion. The only built-in tools are:

| Tool | Confirmation | Behavior |
| --- | --- | --- |
| `machine.read_file` | Required | Read one workspace file, with a 1 MiB size check; return UTF-8 text or base64 for bytes containing NUL. |
| `machine.write_file` | Required | Write UTF-8 content up to 200 KiB; optional parent creation; same-directory temporary file followed by atomic replacement. |

Write failures opt into the project's Error logging; raw-read failures do not.
No environment package installation, generic command execution, conda creation or
Dockerfile creation remains in this server.

## Workspace confinement and unavailable state

The companion obtains its linked workspace from `SOLUS_COMPANION_WORKSPACE` through
`watch.workspace_path()`. An unset or invalid directory leaves the server without a
workspace: it advertises no machine inventory, reports `not_launched`, and refuses
calls with `no project workspace linked`. There is no current-directory fallback.

`actions.confine(workspace, candidate)` resolves the workspace and candidate and
requires the target to remain inside that workspace. Relative paths and absolute
paths inside the workspace are accepted; traversal or symlink resolution outside
it is refused. This is the file server's existing path check; it does not authorize
arbitrary paths for hardware calibration, whose private reader has separate scoped
references and regular-file/race checks.

Every file call validates its arguments with Pydantic and rejects unknown fields.
The API bridge remains scoped to the authenticated user, team and project, and
errors/results pass through the shared bridge and tool result handling.

## Environment records

SOL lists/probes environments through I3 and links a named observed environment
into the project's CODE section through `link_environment`. Successful approved
I3 create/install actions re-probe their exact target and update the same CODE
identity with provenance `sol`. The adapter preserves unknown host/interpreter
facts as null and refuses incomplete package inventories. Failed observation never
changes the action outcome or overwrites an existing record with invented facts.

Conda names and system interpreter summaries are observations only. They do not
imply support for the removed machine executor's conda, docker or arbitrary-command
capabilities. The API, companion and desktop continue to use one confirmation path
and one I3 environment implementation.

## Verification boundary

The earlier SOLUSDEV-252 completion report records historical behavior of the
removed environment implementation. Its machine command and multi-environment
live gates do not establish coverage for this integrated design. Current evidence
belongs in the SOLUSDEV-260 phase report and Cowork QA, distinguishing automated
fixtures, live companion execution and platform-specific checks.
