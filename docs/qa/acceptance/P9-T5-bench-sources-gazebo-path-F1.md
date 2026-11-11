# P9-T5 — `/bench/sources` detects Gazebo under `SOLUS_GAZEBO_PATH` (P8 finding F1)

Branch `SOLUSDEV-322-sim-integrations`, HEAD before: `1cc71d4e`. Host: Ubuntu 24.04 aarch64, dev
Postgres/Redis containers DOWN after the reboot (no `packages/api` pytest possible in this task).
No simulator was started; every check below is a file read or a unit test.

## Defect (P8 live run, F1)

`GET /projects/{id}/bench/sources` said `Gazebo is not installed (no gz, ign or gzserver CLI on
PATH)` on an API configured exactly as the handoff prescribes (`SOLUS_GAZEBO_PATH` set, no Gazebo
on PATH): `livebench/src/livebench/local.py::_gazebo_family_on_path` consulted only `shutil.which`.
Plan §0 row 7 / §2: Gazebo binaries resolve through `SOLUS_GAZEBO_PATH`, never PATH alone.

## Fix

- `livebench/src/livebench/sim/gazebo_family.py`: new `family_on_disk(env)` — file-only sibling
  of `detect_family` (runs nothing): per configured dir `gzserver` ⇒ classic, else `ign` ⇒
  ignition, else `gz` ⇒ gz; newest family across dirs wins (`FAMILIES` order). `gzserver` is read
  first because this host's conda classic env holds `gazebo gz gzserver ign` (an `ign` tool shim
  from classic's deps) — the task's first draft (newest exe first) named it "gz", then "ignition".
- `livebench/src/livebench/local.py`: `_gazebo_family_on_path(which)` → `_gazebo_family(which,
  env)`: `family_on_disk(env) or <which fallback>`; `available_simulators(..., env=None)` (default
  `os.environ`); miss reason is now
  `Gazebo is not installed (no `gz`, `ign` or `gzserver` CLI under SOLUS_GAZEBO_PATH or on PATH)`;
  the stale "never from this process's PATH" comment reworded. `gazebo_family.py` imports only
  stdlib, so the listing still imports no simulator (`test_listing_never_imports_heavy_modules`
  still green).
- `docs/api/gazebo-integration.md` (Environment values): one sentence on how `/bench/sources`
  detects the family. `docs/api/bench*.md` does not exist; API.md / API-implementation.md describe
  the row generically ("available / not-installed + reason") and are unchanged.
- `packages/api/src/solus_api/livebench/bench_router.py:448` calls `local.available_simulators`
  with no arguments → the new default (`os.environ`) is what the running API uses; no API change.

## TDD

`livebench/tests/lb_local_test.py` (new):
`test_gazebo_detected_under_solus_gazebo_path_when_absent_from_path`,
`test_solus_gazebo_path_wins_over_path_for_the_family_name` (pinned: configured path is
authoritative — classic dir `gz`+`gzserver` under `SOLUS_GAZEBO_PATH` with `gz` on PATH reads
"classic family"), `test_gazebo_miss_reason_names_both_search_places`; the three existing
which-only tests now pass `env={}` so a host `SOLUS_GAZEBO_PATH` cannot flip them.
`livebench/tests/lb_gazebo_family_test.py` (new): `test_family_on_disk_is_file_only_and_newest_first`
(fixtures `tests/fixtures/bin/{gz8,ign6,classic11}`),
`test_family_on_disk_ignores_tool_shims_beside_classic`.

Red (before the fix):

```
$ uv run pytest -q livebench/tests/lb_local_test.py -k gazebo
E       TypeError: available_simulators() got an unexpected keyword argument 'env'
7 failed, 1 passed, 34 deselected in 0.88s
```

Green:

```
$ uv run pytest -q livebench/tests/lb_local_test.py livebench/tests/lb_gazebo_family_test.py
49 passed in 1.21s
$ uv run pytest -q livebench/tests
803 passed, 1 skipped in 27.62s
$ uv run ruff check livebench && uv run ruff format --check livebench
All checks passed!
174 files already formatted
$ uv run mypy livebench/src livebench/tests/lb_local_test.py livebench/tests/lb_gazebo_family_test.py
Found 6 errors in 1 file (checked 95 source files)   # all 6 in sim/isaac_direct.py
```

The 6 mypy errors are pre-existing `Unused "type: ignore"` lines in `livebench/sim/isaac_direct.py`
(159, 167, …): the same `uv run mypy livebench/src` on the stashed tree (HEAD `1cc71d4e`) reports
`Found 6 errors in 1 file (checked 93 source files)`. Not touched by this task.

## Host probe (file reads only, `which=lambda n: None` so PATH cannot help)

```
$ uv run python - <<'PY'
from livebench.local import available_simulators
...  # SOLUS_GAZEBO_PATH = each env's bin dir, then all three, then unset
PY
harmonic  available=True reason='Gazebo detected (gz family)'        # /opt/ros/jazzy/opt/gz_tools_vendor/bin
fortress  available=True reason='Gazebo detected (ignition family)'  # ~/miniconda3/envs/solus-gz-fortress/bin
classic   available=True reason='Gazebo detected (classic family)'   # ~/miniconda3/envs/solus-gz-classic/bin
all3      available=True reason='Gazebo detected (gz family)'
unset     available=False reason='Gazebo is not installed (no `gz`, `ign` or `gzserver` CLI under SOLUS_GAZEBO_PATH or on PATH)'
```

## Not run (database down)

- `packages/api/tests/test_bench_router.py` (the only API test naming `bench/sources`): it drives
  the route through a `FakeLocal` with its own `available_simulators`, so this change cannot alter
  it; still, not executed — conftest opens Postgres.
- `packages/api/tests/test_vendor_hygiene_api.py`: its `SWEEP_GLOBS` are relative to
  `packages/api/src/solus_api/` (`livebench/*.py` there is the API-side package), so the livebench
  member edited here is outside its sweep; not executed for the same reason.
- No live `GET /bench/sources` against a running API (needs Postgres); the P9 re-run task owes it.

## Verdict

F1 fixed in the livebench member: with `SOLUS_GAZEBO_PATH` set and nothing on PATH the gazebo row
is `available=True` naming the configured family; the configured path beats PATH; the miss reason
names both places. Model calls: 0 scripted, 0 real (no SOL turn in this task).
