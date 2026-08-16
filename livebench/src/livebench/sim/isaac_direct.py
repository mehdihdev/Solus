"""Live Isaac Sim → Solus, the ROS-free direct path (SOLUSDEV-72).

Run this UNDER ISAAC'S OWN PYTHON — `<isaac>/python.sh isaac_direct.py …` for a
headless run, or paste-adapt into Isaac's Script Editor against the open stage.
It samples every articulation's joint positions/velocities each tick and POSTs
LB-06 wire batches to the existing bench ingest route — the one telemetry sink;
no new API surface, no ROS anywhere.

    SOLUS_TOKEN=<jwt> <isaac>/python.sh isaac_direct.py \
        --project-id <uuid> --scene /path/to/robot.usd [--url http://localhost:8000/api/v1]

Constraints this file lives under:
- At runtime it has ONLY the stdlib and Isaac's bundled modules — it must not
  import livebench or solus_api (Isaac's interpreter has neither). The pure
  helpers below are unit-tested in the Solus venv against the ratified codec.
- The token arrives via the SOLUS_TOKEN environment variable, never argv (argv
  is world-readable in `ps`), and plaintext http is refused off-loopback.
- Empty beats invented: a stage with no articulations streams nothing and says
  so; there is no synthetic fallback data.

Signals ride as `<scene>/<dof_name>` with `qpos`/`qvel` — the same convention as
the MuJoCo source, so graph resolution and the device-recent view work
identically for both.
"""

import argparse
import ipaddress
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

DEFAULT_URL = "http://localhost:8000/api/v1"
DEFAULT_SAMPLE_HZ = 30.0
POST_INTERVAL_SECONDS = 0.5
MAX_BATCH_PACKETS = 500  # mirrors the ingest route's cap


def wire_packet(device_id: str, *, ts_us: int, values: dict[str, float]) -> dict[str, Any]:
    """One LB-06 wire dict (schema v1; `ts_us` is the wire timestamp field)."""
    return {
        "schema_version": 1,
        "device_id": device_id,
        "ts_us": ts_us,
        "values": values,
    }


def _require_safe_url(base_url: str) -> None:
    parts = urlsplit(base_url)
    if parts.scheme == "https":
        return
    if parts.scheme != "http":
        raise ValueError(f"unsupported URL scheme: {parts.scheme!r}")
    host = parts.hostname or ""
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise ValueError("plaintext http is only allowed to loopback — the token rides this request")


def batch_request(
    base_url: str, *, project_id: str, token: str, packets: list[dict[str, Any]]
) -> urllib.request.Request:
    """The authenticated ingest POST. Token in the header, never the URL."""
    _require_safe_url(base_url)
    url = f"{base_url.rstrip('/')}/projects/{project_id}/bench/telemetry"
    body = json.dumps({"packets": packets}).encode()
    return urllib.request.Request(  # noqa: S310 - scheme pinned by _require_safe_url
        url,
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )


def _post(req: urllib.request.Request) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - loopback/https enforced above
            return resp.status, resp.read(4096).decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(4096).decode(errors="replace")


# ── Isaac-side loop (runs only under Isaac's python; exercised by the QA pass) ──


def _find_articulations(scene_name: str) -> list[Any]:
    """Every articulation on the current stage, wrapped for joint-state reads.

    ponytail: import-chain covers Isaac 5/6 module names; anything older is a
    documented non-goal. Validated by the human-run QA pass, not unit tests —
    Isaac's interpreter is not available to the suite."""
    import omni.usd  # type: ignore[import-not-found]
    from pxr import UsdPhysics  # type: ignore[import-not-found]

    try:
        from isaacsim.core.prims import (  # type: ignore[import-not-found]
            SingleArticulation as ArticulationCls,
        )
    except ImportError:  # Isaac 5.x fallback
        from omni.isaac.core.articulations import (  # type: ignore[import-not-found]
            Articulation as ArticulationCls,
        )

    stage = omni.usd.get_context().get_stage()
    handles = []
    for prim in stage.Traverse():
        if prim.HasAPI(UsdPhysics.ArticulationRootAPI):
            handles.append(ArticulationCls(str(prim.GetPath())))
    return handles


def _sample(articulations: list[Any], scene_name: str, ts_us: int) -> list[dict[str, Any]]:
    packets: list[dict[str, Any]] = []
    for articulation in articulations:
        names = list(articulation.dof_names or [])
        positions = articulation.get_joint_positions()
        velocities = articulation.get_joint_velocities()
        if positions is None or velocities is None:
            continue
        for i, name in enumerate(names):
            packets.append(
                wire_packet(
                    f"{scene_name}/{name}",
                    ts_us=ts_us,
                    values={"qpos": float(positions[i]), "qvel": float(velocities[i])},
                )
            )
    return packets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--project-id", required=True)
    parser.add_argument(
        "--scene", default=None, help="USD stage to open (omit to use the current stage)"
    )
    parser.add_argument("--scene-name", default="isaac", help="device_id prefix")
    parser.add_argument("--sample-hz", type=float, default=DEFAULT_SAMPLE_HZ)
    parser.add_argument("--duration", type=float, default=300.0)
    args = parser.parse_args(argv)

    token = os.environ.get("SOLUS_TOKEN")
    if not token:
        print("SOLUS_TOKEN is not set — refusing to run without credentials", file=sys.stderr)
        return 2
    _require_safe_url(args.url)

    from isaacsim import SimulationApp  # type: ignore[import-not-found]  # Isaac's python only

    sim_app = SimulationApp({"headless": True})
    try:
        import omni.usd

        if args.scene:
            omni.usd.get_context().open_stage(args.scene)
        from isaacsim.core.api import World  # type: ignore[import-not-found]

        world = World()
        world.reset()
        articulations = _find_articulations(args.scene_name)
        if not articulations:
            print("no articulations on this stage — nothing to stream", file=sys.stderr)
            return 1
        for articulation in articulations:
            articulation.initialize()

        period = 1.0 / args.sample_hz
        deadline = time.monotonic() + args.duration
        pending: list[dict[str, Any]] = []
        last_post = time.monotonic()
        while time.monotonic() < deadline and sim_app.is_running():
            world.step(render=False)
            ts_us = time.time_ns() // 1_000
            pending.extend(_sample(articulations, args.scene_name, ts_us))
            now = time.monotonic()
            if pending and (
                now - last_post >= POST_INTERVAL_SECONDS or len(pending) >= MAX_BATCH_PACKETS
            ):
                batch, pending = pending[:MAX_BATCH_PACKETS], pending[MAX_BATCH_PACKETS:]
                status, text = _post(
                    batch_request(args.url, project_id=args.project_id, token=token, packets=batch)
                )
                if status != 200:
                    print(f"ingest POST failed ({status}): {text[:200]}", file=sys.stderr)
                last_post = now
            time.sleep(max(0.0, period - (time.monotonic() - now)))
        return 0
    finally:
        sim_app.close()


if __name__ == "__main__":
    raise SystemExit(main())
