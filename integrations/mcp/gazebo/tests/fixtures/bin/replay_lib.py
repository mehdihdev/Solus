"""Shared replay for the `gz8/gz` and `ign6/ign` fixture CLIs.

Every stdout below was RECORDED from Harmonic gz 8.15.0 (`/opt/ros/jazzy/opt/gz_tools_vendor/bin/
gz`) on 2026-11-09 against a headless `gz sim -s -r empty.sdf` the recording script started and
terminated through its own Popen handle; a two-link URDF was converted with `gz sdf -p`, wrapped
with the joint-state-publisher and two joint-position-controller systems and spawned as
`twolink`. The `ign6/ign` fixture replays the same shapes with `ignition.msgs` type names: it is
AUTHORED from these recordings and the documented ignition.msgs schema because the
`solus-gz-fortress` conda server did not start on this host (libabsl version mismatch).

Knob: `GZ_PARTITION=solus-fixture-paused` makes `/world/<w>/stats` report `paused: true` and
freezes the joint_state stamps and positions (recorded shapes 14/15 of the session).
Knob: `GZ_PARTITION=solus-fixture-idle` lists no `/world/...` service or topic at all (AUTHORED:
the listing before any server is up; the recording script only captured the running state).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

WORLD = "empty"
MODEL = "twolink"
PAUSED_PARTITION = "solus-fixture-paused"
IDLE_PARTITION = "solus-fixture-idle"

SERVICE_LIST = """/gazebo/resource_paths/add
/gazebo/resource_paths/get
/gazebo/resource_paths/resolve
/gazebo/worlds
/server_control
/world/empty/control
/world/empty/control/state
/world/empty/create
/world/empty/create/blocking
/world/empty/generate_world_sdf
/world/empty/remove
/world/empty/scene/graph
/world/empty/scene/info
/world/empty/set_pose
/world/empty/state
"""

TOPIC_LIST = """/clock
/gazebo/resource_paths
/stats
/world/empty/clock
/world/empty/dynamic_pose/info
/world/empty/model/twolink/joint_state
/world/empty/pose/info
/world/empty/scene/deletion
/world/empty/scene/info
/world/empty/state
/world/empty/stats
"""

STATS_RUNNING = (
    '{"simTime":{"sec":"8","nsec":127000000},"realTime":{"sec":"9","nsec":793559334},'
    '"iterations":"8127","realTimeFactor":0.996024864764724,"stepSize":{"nsec":1000000}}'
)
STATS_PAUSED = (
    '{"simTime":{"sec":"16","nsec":52000000},"realTime":{"sec":"18","nsec":230430000},'
    '"paused":true,"iterations":"16052","stepSize":{}}'
)

# gz.msgs.Model JSON as the joint-state-publisher prints it; (stamp, shoulder, elbow) triples.
_JOINT_LINE = (
    '{{"header":{{"stamp":{{"sec":"{sec}","nsec":{nsec}}}}},"name":"twolink","id":10,'
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
    {
        "sec": 15,
        "nsec": 838000000,
        "p0": 0.91339023173050071,
        "v0": 0.71177044306127879,
        "p1": 0.013115564070374449,
        "v1": 0.12584293534387486,
    },
    {
        "sec": 15,
        "nsec": 839000000,
        "p0": 0.91410200000000004,
        "v0": 0.71180000000000001,
        "p1": 0.013241999999999999,
        "v1": 0.12590000000000001,
    },
    {
        "sec": 15,
        "nsec": 840000000,
        "p0": 0.91481400000000003,
        "v0": 0.71183000000000003,
        "p1": 0.013367999999999999,
        "v1": 0.12596000000000001,
    },
]
JOINT_PAUSED = {
    "sec": 16,
    "nsec": 52000000,
    "p0": 1.1734078682923965,
    "v0": 0.92023644262235749,
    "p1": 0.058440391614246676,
    "v1": 0.16306660379838775,
}

SCENE_INFO = """ambient {
  r: 0.4
  g: 0.4
  b: 0.4
  a: 1
}
shadows: true
grid: true
model {
  name: "ground_plane"
  id: 4
  pose {
    position {
    }
    orientation {
      w: 1
    }
  }
  link {
    id: 5
    name: "link"
    visual {
      name: "visual"
      id: 6
      parent_id: 5
      geometry {
        type: PLANE
        plane {
          normal {
            z: 1
          }
          size {
            x: 100
            y: 100
          }
        }
      }
    }
  }
}
model {
  name: "twolink"
  id: 10
  pose {
    position {
      x: 1
      z: 0.4999902
    }
    orientation {
      z: 0.24740395925452285
      w: 0.96891242171064484
    }
  }
  link {
    id: 11
    name: "base"
  }
  link {
    id: 14
    name: "arm"
    pose {
      position {
        x: 1.1102230246251565e-16
        z: 0.0500000000000001
      }
    }
  }
  link {
    id: 17
    name: "tip"
  }
}
light {
  name: "sun"
  type: DIRECTIONAL
  cast_shadows: true
  id: 8
  parent_id: 1
}
origin_visual: true

"""

MODEL_JOINTS = """
Requesting state for world [empty]...

- Joint [20]
  - Name: shoulder
  - Parent: twolink [10]
  - Type: revolute
  - Parent Link: base [11]
  - Child Link: arm [14]
  - Pose [ XYZ (m) ] [ RPY (rad) ]:
    [0.000000 0.000000 0.000000]
    [0.000000 -0.000000 0.000000]
  - Axis unit vector [ XYZ ]:
    [0 1 0]
- Joint [21]
  - Name: elbow
  - Parent: twolink [10]
  - Type: revolute
  - Parent Link: arm [14]
  - Child Link: tip [17]
  - Pose [ XYZ (m) ] [ RPY (rad) ]:
    [0.000000 0.000000 0.000000]
    [0.000000 -0.000000 0.000000]
  - Axis unit vector [ XYZ ]:
    [0 1 0]
"""
MODEL_NO_JOINTS = "\nRequesting state for world [empty]...\n\n"

WORLD_SDF = (
    "data: \"<sdf version=\\'1.10\\'>\\n  <world name=\\'empty\\'>\\n    "
    "<physics name=\\'1ms\\' type=\\'ignored\\'>\\n      <max_step_size>0.001</max_step_size>\\n"
    "    </physics>\\n    <plugin name=\\'gz::sim::systems::Physics\\' "
    "filename=\\'gz-sim-physics-system\\'/>\\n  </world>\\n</sdf>\\n\"\n\n"
)

# `gz sdf -p twolink.urdf` (abridged: inertials and collisions dropped, joints kept verbatim).
SDF_PRINT = """<sdf version='{sdf_version}'>
  <model name='twolink'>
    <link name='base'>
      <visual name='base_visual'>
        <geometry>
          <box>
            <size>0.1 0.1 0.1</size>
          </box>
        </geometry>
      </visual>
    </link>
    <joint name='shoulder' type='revolute'>
      <pose relative_to='base'>0 0 0.05 0 0 0</pose>
      <parent>base</parent>
      <child>arm</child>
      <axis>
        <xyz>0 1 0</xyz>
        <limit>
          <lower>-1.57</lower>
          <upper>1.57</upper>
          <effort>10</effort>
          <velocity>2</velocity>
        </limit>
      </axis>
    </joint>
    <link name='arm'>
      <pose relative_to='shoulder'>0 0 0 0 0 0</pose>
    </link>
    <joint name='elbow' type='revolute'>
      <pose relative_to='arm'>0 0 0.2 0 0 0</pose>
      <parent>arm</parent>
      <child>tip</child>
      <axis>
        <xyz>0 1 0</xyz>
        <limit>
          <lower>-1.57</lower>
          <upper>1.57</upper>
        </limit>
      </axis>
    </joint>
    <link name='tip'>
      <pose relative_to='elbow'>0 0 0 0 0 0</pose>
    </link>
  </model>
</sdf>
"""


def _fixture_paused() -> bool:
    # Only env.allow names cross the adapters' scrubbed child environment, so the test selects
    # the paused replay through the transport partition name.
    return os.environ.get("GZ_PARTITION") == PAUSED_PARTITION


def _listing(recorded: str) -> str:
    if os.environ.get("GZ_PARTITION") != IDLE_PARTITION:
        return recorded
    return "".join(line + "\n" for line in recorded.splitlines() if not line.startswith("/world/"))


def _joint_state_lines(count: int) -> str:
    if _fixture_paused():
        return "".join(_JOINT_LINE.format(**JOINT_PAUSED) + "\n" for _ in range(count))
    return "".join(_JOINT_LINE.format(**JOINT_RUNNING[i % 3]) + "\n" for i in range(count))


def _replay_topic_echo(args: list[str]) -> int:
    topic = args[args.index("-t") + 1]
    count = 1
    if "-d" in args:
        count = max(1, min(40, int(float(args[args.index("-d") + 1]) * 8)))
    if "--json-output" not in args:
        return 255
    if topic == f"/world/{WORLD}/stats":
        line = STATS_PAUSED if _fixture_paused() else STATS_RUNNING
        sys.stdout.write((line + "\n") * count)
        return 0
    if topic == f"/world/{WORLD}/model/{MODEL}/joint_state":
        sys.stdout.write(_joint_state_lines(count))
        return 0
    # Recorded: an absent topic prints nothing; `-n 1` never returns, `-d` returns at the deadline.
    time.sleep(float(args[args.index("-d") + 1]) if "-d" in args else 30)
    return 0


def _replay_service(args: list[str], msgs: str) -> int:
    opts = dict(zip(args[1::2], args[2::2], strict=False))
    service, req = opts.get("-s", ""), opts.get("--req")
    if req is None or "--timeout" not in opts:
        sys.stderr.write("--req requires --reqtype --reptype --service --timeout\n")
        return 255
    types_ok = all(opts.get(k, "").startswith(f"{msgs}.") for k in ("--reqtype", "--reptype"))
    if not types_ok:
        sys.stderr.write("Unable to create request: unknown message type\n")
        return 255
    if not service.startswith(f"/world/{WORLD}/"):
        time.sleep(0.2)
        sys.stderr.write("Service call timed out\n")
        return 0
    name = service.removeprefix(f"/world/{WORLD}/")
    if name == "scene/info":
        sys.stdout.write(SCENE_INFO)
    elif name == "generate_world_sdf":
        sys.stdout.write(WORLD_SDF)
    elif name in ("create", "control"):
        if "nonsense" in req:
            sys.stderr.write(f"Unable to create request of type[{opts['--reqtype']}]\n")
            return 0
        sys.stdout.write("data: true\n\n")
    else:
        time.sleep(0.2)
        sys.stderr.write("Service call timed out\n")
    return 0


def _replay_sdf_print(args: list[str], sdf_version: str) -> int:
    if not Path(args[2]).is_file():
        sys.stderr.write(f"Error: File [{args[2]}] does not exist.\n")
        return 255
    sys.stdout.write(SDF_PRINT.format(sdf_version=sdf_version))
    return 0


def _replay_model(args: list[str]) -> int:
    if args == ["model", "--list"]:
        sys.stdout.write(
            f"\nRequesting state for world [{WORLD}]...\n\nAvailable models:\n"
            f"    - ground_plane\n    - {MODEL}\n"
        )
        return 0
    if args[:2] == ["model", "-m"] and args[3:] == ["-j"]:
        sys.stdout.write(MODEL_JOINTS if args[2] == MODEL else MODEL_NO_JOINTS)
        return 0
    return _unhandled(args)


def _unhandled(args: list[str]) -> int:
    sys.stdout.write(json.dumps({"unhandled_fixture_argv": args}) + "\n")
    return 255


def replay_main(msgs: str, sub: str, version: str, sdf_version: str) -> int:
    args = sys.argv[1:]
    if args[:1] == [sub]:
        if "--versions" in args:
            print(version)
            return 0
        time.sleep(30)  # `<sub> -r <world>`: a server stand-in; adapters never wait on it
        return 0
    if args == ["service", "-l"]:
        sys.stdout.write(_listing(SERVICE_LIST))
        return 0
    if args == ["topic", "-l"]:
        sys.stdout.write(_listing(TOPIC_LIST))
        return 0
    if args[:2] == ["topic", "-e"]:
        return _replay_topic_echo(args)
    if args[:2] == ["topic", "-t"] and "-p" in args:
        return 0 if args[args.index("-m") + 1] == f"{msgs}.Double" else 255
    if args[:1] == ["service"]:
        return _replay_service(args, msgs)
    if args[:2] == ["sdf", "-p"]:
        return _replay_sdf_print(args, sdf_version)
    if args[:1] == ["model"]:
        return _replay_model(args)
    return _unhandled(args)
