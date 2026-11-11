# P9-T2 — the generated URDF is accepted by Gazebo's urdfdom (P8 defect A)

Branch `SOLUSDEV-322-sim-integrations`, HEAD before: `9bb1b108`. Host: Ubuntu 24.04 aarch64,
dev Postgres/Redis containers up (`solus-db-1`, `solus-redis-1`, both healthy at task start).
Harmonic gz 8.15.0 (`/opt/ros/jazzy/opt/gz_tools_vendor/bin/gz`, ROS shell env), Classic 11.15.1
(`~/miniconda3/envs/solus-gz-classic/bin/gz`), MuJoCo 3.11.0 (the `packages/api` venv). No
simulator server was started in this task; every check is the offline converter (`gz sdf -p`) or
the engine's compile child. Zero model calls (no SOL turn ran).

## Defect (docs/qa/acceptance/P8-live-smoke.md §Defects, A)

`simulation/urdf_writer.write_urdf` output (`two_link.urdf`, sha256 `8e23a5e9…`, reproduced
byte-identical by the recreated driver this task) was refused by both families' urdfdom:

1. `<limit lower upper/>` without `effort`/`velocity` → "Could not parse limit element for joint
   [elbow]" (Harmonic rc 255 "Unable to read file"; Classic "limit has no effort").
2. the root link `base` has no `<inertial>` → "urdf2sdf: link[base] has no <inertial> block …
   child joints ignored … A model must have at least one link".

## What was tried first: fixing the massless root to the world (REJECTED by the converters)

Candidate (`scratchpad/p9/probe/candidate/two_link.urdf`): the writer's output plus
`effort="-1" velocity="-1"`, `<link name="world"/>` and
`<joint name="base_to_world" type="fixed"><parent link="world"/><child link="base"/>…`.

```text
$ gz sdf -p two_link.urdf            # Harmonic, ROS env
<sdf version='1.11'><model name='two_link'>
    <joint name='elbow' type='revolute'><pose relative_to='base'>…   ← no <link name='base'>
    <link name='arm'>…
Error Code 26: Msg: relative_to name[base] specified by joint with name[elbow] does not match a
  nested model, link, joint, or frame name in model with name[two_link].
Error Code 21: Msg: parent frame with name[base] specified by joint with name[elbow] not found …
rc=255
$ gz sdf -p two_link.urdf            # Classic
<sdf version='1.7'><model name='two_link'>
    <joint name='elbow' type='revolute'>… <parent>base</parent>   ← no <link name='base'> either
    <link name='arm'>…
rc=0                                  (an SDF whose joint parent does not exist)
```

urdf2sdf reduces a fixed joint by lumping the child into the parent; a massless `base` fixed to
`world` is lumped into the world and disappears, and `elbow` then names a link that is gone. MuJoCo
alone accepted it (`compile_mjcf` → bodies `base`, `arm`; the parser's URDF view gained a `world`
link and a `base_to_world` joint). Two of three refused → fall back per the task.

A second probe (`probe/three/three.urdf`: base(mass) –revolute– mid(no mass) –revolute– tip(mass))
showed the same drop for a massless NON-root link under a non-fixed joint:

```text
Warning … urdf2sdf: link[mid] has no <inertial> block defined … parent joint[j1] ignored.
urdf2sdf: [1] child joints ignored. urdf2sdf: [1] child links ignored. link[mid] is not modeled in sdf.
```

so the placeholder rule is "every root, and every child of a non-fixed joint", not the root alone.
A massless child of a FIXED joint (the `tip` fixture) is lumped into its parent and needs nothing.

## Fix

- `simulation/urdf_writer.py`
  - every non-fixed `<limit>` carries `effort` and `velocity`; unknown → SDF's "not enforced"
    sentinel `-1` (`UNENFORCED`). `GeneratedJoint` gains `effort_nm: float | None = None` and
    `velocity_rad_s: float | None = None` (positive, finite, or `ValueError`); a known value is
    written as given. `model_job` does not populate them yet (no source for actuator limits in the
    graph today).
  - `_kept_massless(model)`: a link without an `<inertial>` that is a root or the child of a
    non-fixed joint gets `<inertial>` mass `PLACEHOLDER_MASS_KG = 1e-3` kg, diagonal inertia
    `1e-6` kg·m², origin at the link frame (`# ponytail:` comment names the ceiling and the upgrade
    path, the report's `<link>.mass` gap).
- `simulation/mjcf_compile.py::_hinted`: MuJoCo reads URDF `effort` as `actuatorfrcrange=±|effort|`
  (probed: `-5`→`"-5 5"`, `10`→`"-10 10"`, `0`→ none), so the sentinel would become an invented
  ±1 N·m clamp in the compiled MJCF. The engine-hint pass (which already rewrites the URDF for the
  engine only) turns a negative `effort` into `0`, the engine's own "no limit". The stored URDF is
  untouched; a known effort still becomes a real range.
- `simulation/model_job.py::MASS_GAP`: the `<link>.mass` gap row (already emitted for every
  massless link, root included) now also says "until set, the URDF gives a root or moving link a
  1 g placeholder so the engines keep it". No properties row was added: the report names the gap,
  which is what was done.

## Tests (TDD: all six written and seen failing first)

`tests/test_urdf_writer.py`: `test_every_limit_carries_effort_and_velocity_sentinels_when_unknown`,
`test_known_actuator_limits_are_written`, `test_a_massless_root_or_moving_link_gets_a_minimal_inertial`,
`test_two_link_urdf_converts_with_gz_sdf_p[harmonic|classic]` (fixed binary paths, skipped when
absent, ROS env obtained from `bash -lc 'source /opt/ros/jazzy/setup.bash; env -0'`, argv lists,
20 s timeouts, never PATH). `tests/test_mjcf_compile.py`:
`test_the_unknown_effort_sentinel_leaves_no_actuator_force_range_in_the_mjcf`.

```text
$ uv run pytest tests/test_urdf_writer.py tests/test_mjcf_compile.py -q      (before the fix)
6 failed, 10 passed in 3.75s
$ uv run pytest tests/test_capability_hygiene.py tests/test_vendor_hygiene_api.py \
    tests/test_urdf_writer.py tests/test_mjcf_compile.py -q                  (after)
30 passed in 4.57s
$ uv run pytest tests/test_sim_generate.py tests/test_model_job.py tests/acceptance/test_sim_acceptance.py \
    tests/test_sol_runtime.py tests/test_model_call_sites.py tests/test_edge_writer_ratchet.py \
    tests/test_hosted_tool_build.py tests/test_kinds.py -q
90 passed in 94.99s (0:01:34)
$ ruff check / ruff format --check / mypy --strict  (the 3 src + 2 test files)
All checks passed! · 5 files already formatted · Success: no issues found in 5 source files
```

One intermediate run tripped `test_capability_hygiene` on the word "Gazebo" in two new
`urdf_writer.py` comments; reworded to "the URDF→SDF importer" (vendor names stay out of shared
code), green afterwards.

## The regenerated live-smoke fixture (P9-T6 spawns this directory)

```text
$ cd packages/api && uv run python $P9/scripts/gen_model.py $P9/model
['meshes/arm.stl', 'meshes/base.stl', 'two_link.urdf']
urdf sha256 eb64f0a43cd05677967d2ab3a168f8fa1f2c8f1f3de078ff27a6c30d2d1e8be2
meshes/arm.stl  55367c485512660a41f855ba757e794e6fb2133666d60bbf22647a28e148232e
meshes/base.stl a7a46b22de22cec41526c17e54df6a5eb67e8da7bee5be9f3cbdbf4e678fcba5
```

`$P9 = /tmp/claude-1000/-home-beeboss-Solus/0cf72a70-f130-49d2-9959-8bce1bad168f/scratchpad/p9`
(the driver `scripts/gen_model.py` was recreated from P8-live-smoke.md §Commands; it reproduced
P8's pre-fix sha `8e23a5e9…` exactly before the writer changed). The URDF now reads:
`base` with `<mass value="0.001" />` and `ixx="1e-06" iyy="1e-06" izz="1e-06"`, `arm` unchanged
(mass 0.42), `<limit lower="-1.57" upper="1.57" effort="-1" velocity="-1" />`.

Real converters on that directory:

```text
$ gz sdf -p two_link.urdf | grep -E "sdf version|link name|joint name|effort|velocity|mass>|Error|Warning"
# Harmonic (ROS env):                       # Classic (conda lib on LD_LIBRARY_PATH):
<sdf version='1.11'>                        <sdf version='1.7'>
    <link name='base'>                          <link name='base'>
        <mass>0.001</mass>                          <mass>0.001</mass>
    <joint name='elbow' type='revolute'>        <joint name='elbow' type='revolute'>
          <effort>-1</effort>                         <effort>-1</effort>
          <velocity>-1</velocity>                     <velocity>-1</velocity>
    <link name='arm'>                           <link name='arm'>
        <mass>0.41999999999999998</mass>            <mass>0.42</mass>
rc=0                                        rc=0
(no Error or Warning line in either)
```

## Verdict

- Defect A root causes (1) and (2): FIXED in the writer; proven offline by both families' real
  `gz sdf -p` (Harmonic rc 0 with both links and the joint; Classic rc 0, same) and by MuJoCo's
  compile (`compile_mjcf` + `parse_model`, no `actuatorfrcrange`).
- Not proven here: a live spawn and joint command in a running server (P9-T6), and whether a 1 g
  root under a 0.42 kg arm behaves sensibly in DART/ODE when the model is not fixed (P8's amended
  copy used mass 1.0 and spawned; this one has not been spawned yet).
