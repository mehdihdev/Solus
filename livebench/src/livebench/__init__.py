"""Live Bench runtime (SOLUSDEV-66, LANE H).

Pattern-2 streaming telemetry: everything here feeds the LB-06 packet format and
emits through the MCP-02 ``LiveConnection`` seam — never through an MCP tool.
Heavy/hardware dependencies (simulators, serial, bus SDKs) live in this package
so they never become dependencies of the API service.
"""
