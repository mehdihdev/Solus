"""The SOL Agent package (ADR-010).

Houses the agent-tool interface (`tools`, W0-04), the reasoning↔systems seam
(`interfaces`/`fake_systems`, W0-07), and the SOL chat plumbing (SOLUSDEV-135):
`conversation` (session/turn persistence), `stream` (the streamed event protocol),
and `runtime` (the reasoning-loop wiring + the mock-and-swap `ScaffoldRunner`). The
model-backed reasoning swaps in behind the `runtime.AgentRunner` seam in later tickets."""
