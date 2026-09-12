# Approved local code-reader activation

Implementation: packages/companion/src/solus_companion/machine/code_reader.py,
registered by machine/server.py. Cloud wrapper: agent/tools/read_code_file.py.
23 boundary tests pass; fresh security review verified bounded reads and safe
no-follow descriptor traversal. The generic machine.read_file remains gated.

User approved automatic code reads in-session on 2026-09-11. Applied addition to
integrations/mcp/machine/allowlist.yaml:

```yaml
  - name: read_code_file
    requires_confirmation: false
    files_errors: false
    reason: reads bounded UTF-8 source text from the linked folder; refuses credential paths and symlinks; no writes or execution
```

This allows SOL to read saved code without a confirmation card for each file.
The requesting user's project and machine are verified; the graph wrapper proves
repository identity from fresh Git metadata. Maximum source-file read is 128 KiB.
Sensitive path names, symlinks, traversal, binary files and special files are
refused before content can leave the machine. Cloud ingress and model tool-result
redaction remain active. Secure descriptor traversal is supported on POSIX;
unsupported platforms fail closed rather than use an unsafe fallback.

This is a built-in companion capability, not a vendored upstream fork. The
integrations/mcp/CLAUDE.md rule 2 reserves additions to existing allowlists for a
human decision; this document makes that exact activation reviewable.
