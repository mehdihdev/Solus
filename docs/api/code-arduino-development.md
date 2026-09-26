# Arduino preparation and compilation — SOLUSDEV-261

## Workspace firmware upload follow-up

The tool `code.arduino_upload` is registered on this same owned Code server.

**Current execution limit:** previews are available, but every non-dry-run call
refuses with `device_ownership_unavailable` before device inspection or launch.
An O_PATH device handle and occupancy snapshot cannot reserve the serial driver
for a CLI that reopens the port. Live upload remains unfinished until the uploader
accepts an already-open exclusive descriptor. Use Arduino IDE for a manually
supervised upload in the meantime; no firmware was flashed by this slice.
The requirements below describe the intended execution path, not a passed live
acceptance result.
Strict input: `{sketch,fqbn:"arduino:avr:uno",build_id:UUID,
device_ref:string,dry_run?:false}`. The sketch remains workspace-relative and
unchanged from its retained immutable build. Resolve its deterministic build ID
from the current workspace/source/toolchain; verify the complete manifest and
all artifact bytes. Select exactly its application HEX, never a bootloader image.
Missing, stale, foreign-workspace or ambiguous outputs refuse.

Resolve `device_ref` from current native USB enumeration, never a caller tty path.
Serial identity is preferred; serial-less identity uses the observed USB topology
location and is explicitly labeled port-bound, not a unique board. Refuse missing,
ambiguous or changed identities, occupied ports and incompatible known board
profiles. The Uno FQBN is the explicitly selected profile, not an inference from a
generic USB bridge. The card distinguishes observed USB/board facts from that
selected profile. Prior firmware is explicitly unknown unless verified evidence
exists; never imply a backup or known sketch. No driver-board flashing.

Upload always requires a complete fresh human confirmation and cannot enter the
routine Build allowlist. Preview includes device identity/basis, selected profile,
source/build/manifest/artifact digests, overwrite consequence and full owned argv.
Revalidate device, source, build and toolchain immediately before execution under
the operation lock. Open only the selected verified character device and hold its
identity through the operation; no scan opens or auto-reset probes. The bounded
sandbox grants only that device, verified toolchain and retained build snapshot;
network remains unavailable. Use pinned CLI `upload --verify`, no caller flags,
profiles, programmer or environment. One attempt only; cancellation/timeouts kill
the process group and never retry automatically.

Use `device_state:unchanged|unknown|flashed`: refusal before launch is unchanged,
any uncertain started upload is unknown, only verified success is flashed. Return
bounded command/stdout/stderr evidence and register `files_errors:true`; failures
file once through existing Error logging. Existing authenticated Code execution
output events may carry bounded actual upload output. The card's execution state
shows progress without invented erase/write percentages. No telemetry payloads,
new bridge frame or new generic command executor. After success the existing
hardware watcher/interrogation path must rediscover firmware-declared channels;
no channel is fabricated from the upload request.

This tier-1 supplement extends `code-environment.md`. Governing documents are
ADR-031/032, `docs/architecture/code-environment.md`,
`docs/architecture/local-machine-actions.md`, `docs/contracts/action-gate.md`,
`docs/contracts/bridge-protocol.md` and `docs/contracts/agent-tool.md`.
Execution belongs to the existing owned Code server, never MachineServer or the
cloud. No new route, server, bridge frame or contract enum is introduced.
Human provenance/security sign-offs remain human-owned. The user's installation
exception permits worktree-local `.venv` dependencies; it does not authorize an
agent to operate the product's confirmation card or write unidentified hardware.

## First slice and authority

Implement probe, prepare and compile first. This slice has no device discovery,
serial opening, upload, flash, bootloader or runtime-test operation. A successful
compile is evidence of compilation for the explicit FQBN, not a test of a board
or a running robot. `/dev/ttyACM0` is not evidence of a board model.

Primary references:

- [Arduino CLI installation](https://docs.arduino.cc/arduino-cli/installation)
- [CLI configuration](https://docs.arduino.cc/arduino-cli/configuration)
- [Compilation](https://docs.arduino.cc/arduino-cli/commands-reference/arduino-cli_compile)
- [Upload](https://docs.arduino.cc/arduino-cli/commands-reference/arduino-cli_upload)
- [Package index format](https://docs.arduino.cc/arduino-cli/package_index_json-specification)

CLI initialization can install the latest builtin helpers present in its loaded
index, even when the requested core version is pinned. Therefore a full rolling
vendor index is not an executable installation specification.

## Runtime and frozen installation

The reviewed development binary is Arduino CLI **1.5.1**, Linux ARM64, at the
explicitly approved Solus worktree `.venv/bin/arduino-cli`. SHA-256:
`b878632298958d61fd1eb19e70ac5d2e803d83db8930bc72dc6915eee6e8f433`.
The installation root is derived from the trusted application installation, never
from the caller's linked project, inherited PATH or VIRTUAL_ENV. Reject a missing,
nonregular, symlinked or hash-mismatching binary. Do not broaden generic executable
resolution to arbitrary workspace `.venv/bin` programs.

Keep Arduino data, downloads, home, configuration and build jobs beneath a dedicated
directory in that approved `.venv`; no writes to the user's existing Arduino IDE,
global configuration or package caches. Child environment is closed: fixed PATH,
isolated HOME/TMPDIR, fixed locale and explicitly constructed Arduino directories.
Ignore inherited ARDUINO_*, proxy, compiler, Python and Git configuration.

The owned manifest has one exact AVR **1.8.8** platform, its **three** tool
dependencies and the **five** required builtin helpers, each with exact version,
Linux ARM64 host selection, official HTTPS URL, byte length and SHA-256 from the
reviewed official index. Store these records as immutable reviewed constants;
reject missing records, extra dependencies and conflicting host matches. No
caller URLs, additional package indexes, floating versions or library installs.

The reviewed source is `https://downloads.arduino.cc/packages/package_index.json`,
retrieved 2026-09-12T21:04:04Z, SHA-256
`8b1dc76b3cd2420680db6e9f8ecfea6386a86fe16f0a7af47a966649625df50e`.
Exact archive closure:

| Package/tool | Version | Bytes | SHA-256 |
| --- | --- | --- | --- |
| arduino/avr | 1.8.8 | 7162150 | a234c2a43dcd01ce54be665806f183b8e6ec4e966d2e3e0c3358b63023d6390c |
| arduino/arduinoOTA | 1.3.0 | 2472427 | 835ed8f37cffac37e979d1b0f6041559592d3d98be52f0e8611b76c4858e4113 |
| arduino/avr-gcc | 7.3.0-atmel3.6.1-arduino7 | 38045723 | 03d322b9df6da17289e9e7c6233c34a8535d9c645c19efc772ba19e56914f339 |
| arduino/avrdude | 8.0.0-arduino1 | 1565761 | 031f212bdcb77e2ea13895f07ab4a0c254963f8f1bbd3b8797d3363a6a2e95e3 |
| builtin/ctags | 5.8-arduino11 | 100819 | 89b6f8adb7b7124ebe2eb30970ea77c754cd2239e0d8a6b0102ae2a36416c6ef |
| builtin/dfu-discovery | 0.1.2 | 1617881 | 4bda54b9031d5b1fb1af70d1c38bf1b1f8cfd0eb0cd81f6c3a43253c31dea92d |
| builtin/mdns-discovery | 1.1.0 | 2990900 | 19597d8d15aac922813b34064deb870c0e5efc08d7430d15c8501768890f7725 |
| builtin/serial-discovery | 1.5.2 | 1998925 | 489c81d0162e28e9c6602ecbce092e5a4669e7410d95067ed6dd1944e6a3cd34 |
| builtin/serial-monitor | 0.15.0 | 2299956 | bb16cf208befb19cef8710f753272f9e1ddbc1bd851d57be371f6d4b77af6c5e |

Archive body bytes total **58,254,542**, enforced exactly in addition to the
defensive aggregate cap. Full official archive metadata research is in
`/tmp/solus261-arduino-pins.json` during implementation; this temporary file is not
a runtime dependency. The owned immutable manifest must carry the full records.

Before any CLI initialization, materialize the frozen derivative package index
and a valid empty `library_index.json` in the isolated data directory. Never copy
the original detached signature onto the derivative: it does not authenticate
modified bytes. Record the official source index digest and derivative digest
separately. This is an unsigned curated derivative; verify every archive's pinned
digest and length and retain upstream archive-integrity checks. Do not disable
integrity checking to make installation succeed.

Disable metrics and update notifications. Core installation specifies
`--skip-post-install` and `--skip-pre-uninstall`; builtin initialization must retain
its skip-post-install behavior. No discovery/monitor daemon or board-list command.
The implementation must prove the selected CLI initialization path does not start
discovery helpers. Existing unknown files/configuration in the isolated directory
are a refusal, not a reason to delete or silently reuse them.

Use fixed configuration: `directories.data=.venv/arduino/data`, downloads and user
directories as their isolated siblings, `directories.builtin.libraries` pointing
at an empty owned libraries directory, and `build_cache.path=.venv/arduino/cache`.
Set `updater.enable_notification=false`, `metrics.enabled=false`,
`board_manager.additional_urls=[]`, `board_manager.enable_unsafe_install=false`,
`library.enable_unsafe_install=false`,
`network.cloud_api.skip_board_detection_calls=true` and an empty proxy.
Resolve these paths from the approved application installation root.

Use a fresh CLI process per command, never a daemon instance. In CLI 1.5.1 Init
registers discovery helpers without starting them. Explicit-FQBN compilation still
calls port resolution: without a supplied/default address it returns before board
discovery. Therefore pass no port, protocol or upload option, and reject both
`sketch.yaml` and `sketch.yml`, which can supply default ports or profiles.

Installation downloads are limited to manifest archives, 256 MiB total and 128 MiB
per archive. Enforce a 2 GiB installed-tree cap and 100,000 files. Reject extraction
paths escaping the isolated installation and special files. A known vendor archive
requiring a confined internal link must have that exact link target reviewed in
the manifest; do not permit general link following. Preserve a complete verified
installation on preparation failure; publish readiness atomically only after all
required files and versions verify. Never repair a partial installation from an
ungated probe or compile call.

Recovery amendment (2026-09-12): CLI installed metadata may serialize its `tools`
collection in any order. Compare that collection as an exact multiset of complete
canonical records; all other structure, scalar types, versions, hashes, URLs and
cardinalities remain exact. No metadata is rewritten to force verification.

An existing installation with neither `ready.json` nor `ready.pending` may be
finalized only through a fresh `arduino_prepare` approval. Its read-only preview
must first verify the CLI and full installed closure, explicitly name readiness
receipt publication, show the exact receipt and dependency identities, and state
that no downloads, extraction or commands will run. Bind the plan to the held root
device/inode and manifest. At execution, acquire the operation lock, revalidate the
same directory and complete closure, then publish the receipt exclusively without
clobbering either receipt name. Partial, altered, malformed or unknown installations
remain unavailable; probe and compile never finalize readiness themselves.

## Tools and strict inputs

Names below have the `code.` prefix. Inputs are strict Pydantic models with
`extra="forbid"`; reject coerced strings/numbers/booleans at MCP registration too.

| Tool | Input | Policy |
| --- | --- | --- |
| `arduino_probe` | `{}` | Read-only local manifest/file verification, no CLI subprocess |
| `arduino_prepare` | `{dry_run?:false}` | Confirmation required; installs the single frozen manifest |
| `arduino_compile` | `{sketch:string,fqbn:"arduino:avr:uno",dry_run?:false}` | Confirmation required; compiles an explicit Uno target without identifying or touching a board |

The first compile target is deliberately one frozen FQBN. Additional AVR board
options require an additive reviewed manifest/API amendment and tests, never a
free-form build-property override. `sketch` is a canonical relative POSIX directory
inside the linked workspace, at most 512 characters; reject absolute paths,
empty/dot/dot-dot/option-prefixed segments, backslashes, NUL/control characters,
`.git`, symlinks and special files. Its primary `.ino` has the directory's name.
Refuse `sketch.yaml` and `sketch.yml`: profiles can trigger implicit dependency installation.

Compile takes a bounded snapshot of the entire selected sketch directory, including
its local headers/sources: at most 1,000 regular files, 2 MiB per file, 16 MiB total.
Reject nested repository metadata and executable scripts. Only `.ino`, `.c`, `.cpp`,
`.h`, `.hpp`, `.S`, `.s` and ordinary non-executable data/documentation are eligible;
never execute or interpret project build configuration. The tool uses only the
frozen platform recipes and dependencies, no custom libraries, programmer, profile,
additional flags, build properties or caller environment. Compilation must be
offline after preparation; missing dependencies refuse instead of downloading.

Run compilation inside the installed `/usr/bin/bwrap` with fixed namespace and
mount arguments. A closed environment alone does not stop C/C++ includes or
assembly incbin directives from reading unrelated host files. Unshare network,
use a minimal private device filesystem, and expose only required system runtime
libraries and the verified Arduino toolchain read-only. The isolated job is the
only writable persistent mount; host home, the original project and real devices
must not be mounted. No caller-selected mounts, environment or wrapper flags.
The complete preview includes the outer sandbox argv and its read/write mounts.
Use Bubblewrap’s `--bind-fd` / `--ro-bind-fd` options (present in the verified
local Bubblewrap 0.9.0) for held sources; descriptor paths are not a substitute for
these APIs. Mount sources use held, validated directory descriptors so a replaced pathname
cannot redirect execution. The write-free preview may show the explicit logical
handles `<verified-cli-fd>`, `<held-job-fd>` and `<verified-packages-fd>`
in place of OS-assigned numbers;
execution substitutes only internally acquired descriptors after inode/content
validation. All other arguments, mount destinations and logical source identities
remain exactly bound to the approved plan. No caller can supply descriptors,
substitutions or extra flags. CLI execution uses a sealed in-memory image of the
verified bytes; later replacement of its on-disk pathname cannot alter executed code.
Refuse a missing or unusable sandbox accurately; do not describe that setup
failure as OS-wide Arduino incompatibility. A host namespace check on 2026-09-12
succeeded here. This is an execution detail within the existing Code server,
not a new dispatcher or permission path.

## Plans, state binding and execution

Both gated tools accept `dry_run:true`, returning exactly:
`{ok:true,dry_run:true,preview:DiffRow[],fingerprint:string}`. Planning writes no
files and starts no install/compile process. A prepare plan lists exact dependency
versions, archive sizes/digests, installation destination and owned argv. A compile
plan lists workspace/sketch identity, source digest, FQBN, CLI/toolchain digests,
output destination and the complete argv. Respect the existing maximum 40 rows,
400 characters per field; an unrenderable plan refuses, never truncates consent.

Fingerprints use SHA-256 over a canonical serialization of the whole plan and
relevant observed state. Recompute at approval and immediately before execution.
Register both names in the cloud-owned complete-preview policy: absent/malformed
plans cannot park or fall back to argument-only approval. Serialize owned install
and compile operations; refuse busy state. Revalidate source identity/content while
copying the snapshot and verify the final snapshot digest. Compiler reads the
snapshot, not changing user files. Do not modify the linked sketch.

Use argv lists, closed stdin, pinned binaries, bounded output and process-group
termination. No shell. Prepare wall-clock deadline is 600 seconds, compile 120
seconds; these include downloads, subprocesses and verification, not per-command
budgets that can multiply. Each stream is captured with a hard 1 MiB read cap and
returned as a maximum 16 KiB tail with explicit truncation flags. Exceeding the
hard cap terminates the process. Validate the complete compiler JSON report
within that existing 1 MiB stdout bound before reducing it to a returned tail;
a tail is not a complete report. Never return the full internal report buffer.
Cloud tool deadlines include a small bounded
cleanup margin: prepare 630 seconds, compile 150 seconds; probe 15 seconds.
Cancellation/disconnect terminates owned work best-effort and never resumes or
retries it automatically under a new session.

## Results and refusal semantics

Probe returns `{ok:true,platform,cli,toolchain}`. `platform` contains OS,
architecture and `supported:bool`; `cli` contains `available`, expected version,
observed digest or null and a stable reason or null; `toolchain` contains `ready`,
manifest digest or null and missing dependency IDs. Unknown facts remain null.
An unsupported host is presented as "Arduino toolchain not available on <OS>/<arch>".
Probe does not declare readiness from directory existence or version text alone.

Successful prepare returns `{ok:true,changed:boolean,manifest_sha256,dependencies}`,
where dependency entries contain only ID, exact version and verified digest.
Already-ready preparation is a truthful no-op (`changed:false`). Successful compile
returns `{ok:true,started:true,exit_code:0,stdout_tail,stderr_tail,stdout_truncated,
stderr_truncated,artifact_summary,artifact_manifest}`. No artifact manifest is returned on failure.

A launched compile failure returns `{ok:false,started:true,exit_code:int|null,reason,
stdout_tail,stderr_tail,stdout_truncated,stderr_truncated,timed_out:boolean}`;
null exit after timeout is not described as "refused to run". Successful preparation
is never relabeled failed because optional graph/error recording failed.
Boundary refusals raise stable sanitized MCP errors, never a successful tool
dictionary: `workspace_unavailable`, `platform_unavailable`, `cli_unavailable`,
`integrity_mismatch`, `toolchain_unavailable`, `invalid_arguments`, `invalid_sketch`,
`profile_unsupported`, `resource_limit`, `preview_too_large`, `stale_state`,
`operation_busy`, `installation_failed`. Never expose credentials, full config or
unbounded compiler output. Existing error filing records failed approved actions;
tests must cover these new result shapes rather than assume legacy compatibility.

## Artifact manifest and following flash slice

An artifact manifest is a strict version-1 object:
`{schema_version:1,build_id,source_sha256,fqbn,cli_sha256,toolchain_sha256,
artifacts:[{path,size_bytes,sha256,kind}],manifest_sha256}`. Paths are relative to
the owned build directory, never arbitrary filesystem paths. SHA-256 fields are
64 lowercase hex characters; `build_id` is a deterministic UUID derived from the
workspace identity, source digest, FQBN and toolchain digest under an owned fixed
namespace. This makes the exact output path stable across preview rechecks. Maximum eight
regular artifacts and 32 MiB total. `kind` is `hex`, `elf` or `bin`; include only
actual compiler outputs after confinement, length and digest verification.
`manifest_sha256` hashes canonical content excluding itself. The tool response puts
a compact `artifact_summary` before output tails and the canonical manifest, with
the build ID, FQBN, source/toolchain/manifest identities and artifact entries. Public
digests in this display summary use four colon-separated 16-character chunks so
the central secret redactor preserves them; canonical disk manifests retain the
original 64-character digests. Test the summary through actual prompt containment
so long compiler logs cannot hide the build identity. Publish immutable
manifest/artifacts atomically after successful compilation; never overwrite a
published build. An already-published matching build is returned only after full
digest verification as a no-op; conflicting output at the derived path refuses.

Flashing is a separate following slice and is not registered here. It must select
an existing immutable artifact manifest plus an explicitly identified device and
matching FQBN, and show device identity and full artifact digest on a fresh concrete
human card. Never infer the board from a tty name or compile success. Revalidate
artifact and device immediately before the one upload. Request CLI verification
explicitly. Pre-upload refusal means `device_state:"unchanged"`; an uncertain
started upload means `"unknown"`; only verified success means `"flashed"`.
No automatic retry. Existing LB-03 runner/orchestration are references for this
tri-state seam, not proof of a safe bounded executor or genuine progress stages.

Use existing final tool-result logs and confirmation events. They are not streamed
compiler output. Incremental output requires a separately reviewed transport plan;
never put build logs on telemetry or invent a generic bridge command frame.

## Test-first verification and ownership

Write failing tests before implementation. Toolchain tests prove missing/replaced
CLI refusal; exact nine-archive closure; unexpected helper rejection; frozen index
and empty library index materialized before CLI Init; no detached signature misuse;
no discovery, metrics, updates or post-install execution; bounded downloads and
extraction; failed preparation preserves prior verified readiness; probe changes
nothing and launches nothing.

Compiler tests cover malformed inputs and MCP coercion, profile/config refusal,
symlink/traversal and source-race refusal, missing dependencies without network,
timeout/output caps and process cleanup, immutable source snapshot, complete
preview changes, changed-toolchain refusal, failed build without manifest, and
manifest/artifact digest readback. A real sample compile proves Linux ARM64 toolchain
execution for the explicit Uno FQBN; it proves nothing about the attached device.

Worker implementation ownership: `integrations/mcp/code/solus/arduino_toolchain.py`,
`arduino_compile.py`, an owned immutable dependency manifest module, and corresponding
`integrations/mcp/code/tests/test_arduino_*.py`. Parent owns registration, allowlists,
preview/outcome integration and provenance documentation; human signature fields
remain untouched. Freeze the dependency and artifact interfaces before parallel
work. Independent Python/code/security review precedes live preparation/compilation.
