"""Cloud side of the local bridge channel (SOLUSDEV-154, BRG-02-impl).

The companion on a user's machine dials OUT to the WS route in
`routers/bridge.py`; this package holds the wire frames, the session registry,
the transport-free channel service, and the `BridgeTool` kind. It relays JSON —
the `mcp` SDK is never imported here (the reasoning layer's import graph stays
MCP-free). Contract: docs/contracts/bridge-protocol.md.
"""
