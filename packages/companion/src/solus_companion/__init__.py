"""Solus bridge companion (SOLUS-BRG-01).

A standalone process on the user's machine: discovers vendored MCP servers
under an integrations root (ADR-031), supervises them as persistent stdio
sessions, and dials OUT to the Solus cloud over one WebSocket speaking the
`{type, data}` bridge frame protocol. It deliberately does NOT depend on
`solus-api` — the few wire shapes it needs are re-declared in `frames.py`.
"""

__version__ = "0.1.0"
