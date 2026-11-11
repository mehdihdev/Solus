# P9-T4 — World family hint prefers plugin filenames over namespaces (P8 defect E)

Branch `SOLUSDEV-322-sim-integrations`, HEAD before: `979274f4`. Host: Ubuntu 24.04 aarch64, dev
Postgres/Redis containers DOWN after the reboot (no `packages/api` pytest possible in this task).

## Defect (docs/qa/acceptance/P8-live-smoke.md §Defects, E)

Fortress 6.16's own stock worlds load `filename="ignition-gazebo-physics-system"` but name the
plugin `gz::sim::systems::Physics`. `_PLUGIN_HINTS` checked `gz-sim\d*-|gz::sim` before
`ignition-gazebo\d*-|ignition::gazebo`, so the namespace won and the file read as `gz`. With both
families installed and no `family` requested, `open_world` would have picked Harmonic for a
Fortress world.

## Fix (integrations/mcp/gazebo/solus/family_detect.py)

`_PLUGIN_HINTS` is now ordered: `gz-sim\d*-` (gz), `ignition-gazebo\d*-` (ignition),
`ignition::gazebo` (ignition), `gz::sim` (gz), classic `filename="lib*.so"`. Plugin FILENAMES
decide before namespaces; the SDF-version ≥ 1.10 fallback is unchanged. `family_for`,
`worlds._hint_for` and `gazebo_server` all route through `family_hint`, so one change covers
`list_worlds`, `open_world` and the scan hint. `docs/api/gazebo-integration.md` does not describe
the hint order (`grep -i hint` → no match), so it is unchanged.

## TDD (integrations/mcp/gazebo/tests/test_family_detect.py)

Added `test_fortress_stock_world_with_gz_namespace_names_hints_ignition` (snippet shaped like
the Fortress stock `empty.sdf`), `test_harmonic_stock_world_hints_gz`,
`test_garden_style_ignition_namespace_with_gz_filename_hints_gz` (filename wins both ways), and
`test_namespace_alone_still_hints_when_no_filename_decides`.

Red (before the fix):

```text
$ uv run pytest -q integrations/mcp/gazebo/tests/test_family_detect.py -k "fortress_stock or harmonic_stock or garden_style or namespace_alone"
F...
E       AssertionError: assert 'gz' == 'ignition'
FAILED ...::test_fortress_stock_world_with_gz_namespace_names_hints_ignition
1 failed, 3 passed, 22 deselected in 0.49s
```

Green (after the fix, whole gazebo fork suite, one process):

```text
$ uv run pytest -q integrations/mcp/gazebo/tests
282 passed in 11.07s
$ uv run ruff check <both files>            -> All checks passed!
$ uv run ruff format --check <both files>   -> 2 files already formatted
$ uv run mypy --strict <both files>         -> Success: no issues found in 2 source files
```

## Live check against the installed stock worlds (no simulator started, files only)

`family_hint(path.read_bytes())` over every stock world of the three installed families
(Fortress `…/solus-gz-fortress/share/ignition/ignition-gazebo6/worlds/*.sdf`, Harmonic
`/opt/ros/jazzy/opt/gz_sim_vendor/share/gz/gz-sim8/worlds/*.sdf`, Classic
`…/solus-gz-classic/share/gazebo-11/worlds/*.world`):

```text
BEFORE fix (HEAD 979274f4), fortress stock (100 files): {'gz': 63, 'ignition': 27, None: 10}
BEFORE fix, fortress empty.sdf -> gz

AFTER fix,  fortress 100 {'ignition': 89, None: 10, 'gz': 1}
AFTER fix,  harmonic 125 {'gz': 113, None: 12}
AFTER fix,  classic  122 {None: 66, 'classic': 56}
empty.sdf fortress -> ignition
empty.sdf harmonic -> gz
```

- The `None` worlds carry no `<plugin filename=…>` at all (e.g. `default.sdf`, `shapes.sdf`,
  `heightmap.sdf`) and an SDF version < 1.10, so they stay ambiguous → newest installed family,
  as designed and reported through `family_hint = null`.
- The one Fortress file still hinting `gz` is `resource_spawner.sdf`: upstream ships it with
  `filename="gz-sim-physics-system"` / `gz-sim-sensors-system` / `gz-sim-scene-broadcaster-system`
  (a Garden-style file in the Fortress tree), so by filename it IS a gz world. Correct by the new
  rule; recorded here, not special-cased.

## Not done in this task

- `packages/api` tests (incl. the ratchets) need Postgres; the containers are down and an agent
  must not start them. A later task re-runs them. Nothing under `packages/api` was changed here.
- No `open_world` live run with both families installed: the fix is a pure function covered by
  the unit tests and the file-level sweep above.
- Model-provider calls: 0 (no SOL turn was run in this task).
