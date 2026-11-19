# mcp_runtime golden fixtures (SOLUSDEV-329)

Shared by the companion (emitter) and desktop main (parser) for the
`solus-companion runtime` JSON Lines protocol — `docs/architecture/mcp-fork-runtime.md` §6.

| File                            | Expected reading                                                                                             |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `detect_ok.jsonl`               | 4 candidates (2 supported), `done` ok                                                                         |
| `detect_none.jsonl`             | Store alias refused, `error` python_not_found, `done` failed                                                  |
| `provision_ok.jsonl`            | kicad + code ok, altium skipped, `done` ok                                                                    |
| `provision_partial.jsonl`       | kicad ok, local failed `venv_copies_unhealthy`, `done` partial                                                |
| `provision_network_error.jsonl` | both forks failed `network_unreachable`, `error`, `done` failed                                               |
| `malformed.jsonl`               | 5 lines dropped (oversize > 4096 B, not JSON, unknown type, `v: 2`, missing `v`), then 1 `status` + 1 `done` kept |
| `stamp_v1.json`                 | valid stamp v1 (`lock_sha256` is a placeholder; tests compute the real one for their own lock)                |
| `managed_manifest.example.json` | manifest SHAPE only — placeholder release, all-zero hashes; `_comment` is not part of the schema               |
