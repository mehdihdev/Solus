"""Post-deploy verification (LB-03): does telemetry come back, on the right devices?

After a flash, the loop is only closed when the robot's stream resumes and its
`device_id`s are the ones the graph knows (`external_ref` seam — resolution itself
happens in LNK-06 at ingest). This helper watches a packet source until every
expected device has spoken or the packet budget runs out, and NAMES what is
missing rather than summarizing it away.
"""

from dataclasses import dataclass

from livebench.telemetry.stream_live import PacketSource


@dataclass(frozen=True)
class PostDeployReport:
    ok: bool
    seen: set[str]
    missing: set[str]


async def await_post_deploy_telemetry(
    source: PacketSource, *, expected_devices: list[str], max_packets: int = 1000
) -> PostDeployReport:
    expected = set(expected_devices)
    seen: set[str] = set()
    count = 0
    # try/finally: a freshly-rebooting robot may refuse the connection, and the
    # source's __aiter__ can raise BEFORE its first yield — the socket must still close.
    try:
        async for packet in source:
            seen.add(packet.device_id)
            count += 1
            if expected <= seen or count >= max_packets:
                break
    finally:
        await source.aclose()
    missing = expected - seen
    return PostDeployReport(ok=not missing, seen=seen & expected, missing=missing)
