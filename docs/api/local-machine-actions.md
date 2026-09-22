# Local text writes — SOLUSDEV-261

Governing: architecture/local-machine-actions.md, contracts/action-gate.md,
contracts/bridge-protocol.md and the approved central Build execution policy.
This extends the existing built-in machine.write_file; no new HTTP route or process
executor. Scope is the authenticated bridge's linked workspace.

Cloud-owned MachineWriteTool exposes strict {path, content, create_dirs?:false}.
Its complete preview calls the native tool with dry_run:true and retains a single-use,
task-local fingerprint. Execution requires that ticket, rereads the same preview,
and supplies the internally bound expected_fingerprint. Neither internal field is
model-exposed. Runtime replaces the raw bridge entry; central policy decides whether
an otherwise eligible request runs in Build or presents an approval card.

Native arguments add strict dry_run:boolean=false and optional expected_fingerprint.
An actual write requires the fingerprint. Preview is read-only, including missing
parent directories. It shows the canonical relative path, complete before/proposed
UTF-8 text in bounded chunks and the state fingerprint; at most40rows/400characters
per value. Oversized or binary originals, sensitive paths, traversal and symlinks
refuse; no truncation can turn an incomplete preview into an executable plan.

The fingerprint covers workspace/directory/file identity, original bytes, complete
proposed content and parent-creation intent. POSIX no-follow directory descriptors
anchor traversal, creation, publication and readback; unsupported platforms fail
closed. Existing-file identity/content is compared again immediately before atomic
replacement. New files use exclusive publication. This does not claim an atomic
compare-and-swap against independent external writers of an existing file.

Readback verifies the published content and namespace identity. Failures after
publication say the write may have applied and require inspection; never silently
retry. There is no deletion, shell execution, credential-path access or client
controlled automatic-execution flag. Existing raw read behavior is unchanged.

For `machine.write_file` only, the bridge may preserve the exact requested relative
path in its preview/result while redacting other values normally. This display
context is bound to the in-flight call and authenticated bridge session and is
removed on result, cancellation or disconnect. Eligible paths are bounded relative
component paths with no traversal, URL syntax, secret-named or entropy-shaped
components. Secret-named result keys remain redacted even if their value matches
the requested path. This does not authorize writing, exempt arbitrary slash-bearing
text, or alter complete-content/fingerprint verification and native confinement.
