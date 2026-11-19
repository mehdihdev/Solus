"""MCP fork runtimes — per-fork Python environments in the OS app-data folder
(ADR-031 amendment 2026-11-19, docs/architecture/mcp-fork-runtime.md).

Deliberately import-light: `config.py` imports `runtime.trust` on every
companion start, and the CLI (`runtime.cli`) is only loaded for the
`solus-companion runtime …` subcommand."""
