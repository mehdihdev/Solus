"""Shared replay for the `gz8/gz` and `ign6/ign` fixture CLIs of the livebench sources.

Every stdout here was RECORDED from Harmonic gz 8.15.0 (`/opt/ros/jazzy/opt/gz_tools_vendor/bin/
gz`) on 2026-11-09 — the same session that recorded integrations/mcp/gazebo/tests/fixtures/bin/
replay_lib.py (a headless `gz sim -s -r empty.sdf`, a two-link URDF spawned as `twolink`). The
`ign6/ign` fixture replays the same shapes under `ignition.msgs` and is AUTHORED from these
recordings plus the documented ignition.msgs schema (the Fortress conda server did not start).

One deliberate difference from the real CLI: an absent topic exits 0 after printing nothing
(the real `gz topic -e` blocks forever), so a unit test never hangs on it.
"""

from __future__ import annotations

import sys

WORLD = "empty"
MODEL = "twolink"

# gz.msgs.Model JSON as the joint-state-publisher prints it; three consecutive recorded lines.
_JOINT_LINE = (
    '{{"header":{{"stamp":{{"sec":"15","nsec":{nsec}}}}},"name":"twolink","id":10,'
    '"pose":{{"position":{{"x":1,"y":5.3948244117610636e-19,"z":0.049999901148174479}},'
    '"orientation":{{"x":-2.0695034398454046e-19,"y":1.7553611087752645e-17,'
    '"z":0.2474039592545228,"w":0.96891242171064484}}}},'
    '"joint":[{{"name":"shoulder","id":20,"parent":"base","child":"arm",'
    '"pose":{{"position":{{}},"orientation":{{"w":1}}}},"axis1":{{"xyz":{{"y":1}},'
    '"limitLower":-1.57,"limitUpper":1.57,"position":{p0},"velocity":{v0}}}}},'
    '{{"name":"elbow","id":21,"parent":"arm","child":"tip",'
    '"pose":{{"position":{{}},"orientation":{{"w":1}}}},"axis1":{{"xyz":{{"y":1}},'
    '"limitLower":-1.57,"limitUpper":1.57,"position":{p1},"velocity":{v1}}}}}]}}'
)
JOINT_RUNNING = [
    {"nsec": 838000000, "p0": 0.91339023173050071, "v0": 0.71177044306127879,
     "p1": 0.013115564070374449, "v1": 0.12584293534387486},
    {"nsec": 839000000, "p0": 0.91410200000000004, "v0": 0.71180000000000001,
     "p1": 0.013241999999999999, "v1": 0.12590000000000001},
    {"nsec": 840000000, "p0": 0.91481400000000003, "v0": 0.71183000000000003,
     "p1": 0.013367999999999999, "v1": 0.12596000000000001},
]  # fmt: skip
STATS_RUNNING = (
    '{"simTime":{"sec":"8","nsec":127000000},"realTime":{"sec":"9","nsec":793559334},'
    '"iterations":"8127","realTimeFactor":0.996024864764724,"stepSize":{"nsec":1000000}}'
)


def main(sub: str, version: str) -> int:
    args = sys.argv[1:]
    if args == [sub, "--versions"]:
        print(version)
        return 0
    if args[:2] == ["topic", "-e"] and "--json-output" in args and "-t" in args:
        topic = args[args.index("-t") + 1]
        if topic == f"/world/{WORLD}/model/{MODEL}/joint_state":
            sys.stdout.write("".join(_JOINT_LINE.format(**row) + "\n" for row in JOINT_RUNNING))
        elif topic == f"/world/{WORLD}/stats":
            sys.stdout.write(STATS_RUNNING + "\n")
        return 0
    sys.stderr.write("unhandled fixture argv: " + " ".join(args) + "\n")
    return 255
