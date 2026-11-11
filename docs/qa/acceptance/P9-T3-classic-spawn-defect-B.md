# P9-T3 — Classic `spawn` fails on an `Error` line and confirms presence (P8 defect B)

Branch `SOLUSDEV-322-sim-integrations`, HEAD before: `dde517af`. Host: Ubuntu 24.04 aarch64, dev
Postgres/Redis containers DOWN after the reboot (no `packages/api` pytest possible in this task).

## Defect (docs/qa/acceptance/P8-live-smoke.md §Defects, B)

Classic `gz model -w <w> -m <m> -f <urdf>` exits 0 and reports a parse failure only on stderr;
`ClassicAdapter._ok` checked the return code alone, so `spawn` returned, the server answered
`{"ok": true, …, "joints": [...]}` and the model was absent.

## Fix (integrations/mcp/gazebo/solus/adapters/classic.py)

- `_ok` raises `CliError` when rc != 0 **or** any stderr line starts with `Error` (reason still
  built by `stderr_detail`: last line, path-redacted, bounded). Every classic CLI call routes
  through `_ok` (`topic -l`, `model -i`, `model -f`, `topic -e`, `joint --pos-t`, `world`).
- `spawn` calls `self._model_info(world, name)` once after the CLI returns; it raises
  `model <name> is not in world <world>` when `gz model -i` answers "Unable to get info".
- gz/ignition adapters untouched.

## Live recording (this task, 2026-11-09, Classic 11.15.1, conda solus-gz-classic)

Fork-style gzserver (own Popen, `start_new_session`, scrubbed env, `GAZEBO_MASTER_URI=http://localhost:11345`,
`lsof -i :11345` empty before and after; stopped with `os.killpg` on the owned handle; never the
`gazebo` GUI). Script: scratchpad `rec/record2.py`; log pasted:

```text
POPEN gzserver pid 207553
alive: None
$ gz joint -w default -m absent -j elbow --pos-t 0.5  -> rc=0 3.318s
  stdout: ''
  stderr: ''
alive: None
$ gz model -w default -m two_link -f $SCRATCH/rec/good.urdf -x 0.0 -y 0.0 -z 0.5 -R 0.0 -P 0.0 -Y 0.0  -> TIMEOUT after 20s
alive: None
$ gz model -w default -m two_link -i  -> TIMEOUT after 15s
$ gz joint -w default -m two_link -j elbow --pos-t 0.5  -> rc=0 3.303s
  stdout: ''
  stderr: ''
$ gz joint -w default -m two_link -j nope --pos-t 0.5  -> rc=0 3.302s
  stdout: ''
  stderr: ''
$ gz joint -w default -m two_link -j elbow --pos-t abc  -> rc=0 0.184s
  stdout: ''
  stderr: 'Invalid arguments\n'
alive: None
$ gz model -w default -m broken -f $SCRATCH/rec/broken.urdf -x 0.0 -y 0.0 -z 0.5 -R 0.0 -P 0.0 -Y 0.0  -> rc=0 0.316s
  stdout: ''
  stderr: 'Error:   joint [elbow]: limit has no effort\n         at line 176 in /home/conda/feedstock_root/build_artifacts/bld/rattler-build_urdfdom_h57aec1e_1793831053/work/urdf_parser/src/joint.cpp\nError:   Could not parse limit element for joint [elbow]\n         at line 600 in /home/conda/feedstock_root/build_artifacts/bld/rattler-build_urdfdom_h57aec1e_1793831053/work/urdf_parser/src/joint.cpp\nError:   joint xml is not initialized correctly\n         at line 243 in /home/conda/feedstock_root/build_artifacts/bld/rattler-build_urdfdom_h57aec1e_1793831053/work/urdf_parser/src/model.cpp\nError: SDF parsing the xml failed\n'
alive: None
$ gz model -w default -m broken -i  -> TIMEOUT after 15s
alive: None
gzserver exited -15
```

What this confirms / does not:
- `gz model -f` on a URDF whose joint limit has no `effort` → rc 0, stdout empty, four `Error:`
  lines on stderr ending `Error: SDF parsing the xml failed` (matches P8-T2). The fixture now
  replays this text verbatim for `-m broken` (md5 of the replayed stderr == md5 of the recorded
  text: `8ec3e0469bb00d4ff30473be5dcce37b`).
- `gz joint … --pos-t` on an ABSENT model or joint → rc 0, **no stderr**, ~3.3 s (as P8 saw).
  `--pos-t abc` → `Invalid arguments`, rc 0. No `Error` line was ever recorded from `gz joint`,
  so `test_set_targets_fails_when_gz_joint_prints_an_error` uses an AUTHORED stderr through a
  scripted runner (labelled so in the test) rather than a fixture line claimed as recorded.
- In this scratch setup the good-model `gz model -f` / `-i` calls TIMED OUT (15–20 s) although
  the same calls succeeded in P8-T2 through the fork's session code; not investigated here
  (outside the task), the recording goals above did not depend on it.

## TDD

RED (tests + fixture first): `uv run pytest -q integrations/mcp/gazebo/tests/test_classic.py`
→ `4 failed, 18 passed` (test_spawn_passes_pose_flags [new presence argv],
test_spawn_fails_when_gz_model_prints_an_error_with_rc_0,
test_spawn_fails_when_the_model_is_absent_after_a_silent_gz_model,
test_set_targets_fails_when_gz_joint_prints_an_error).
GREEN after the adapter change → `22 passed`.

## Verification (one pytest process at a time)

```text
uv run pytest -q integrations/mcp/gazebo/tests      -> 278 passed in 11.51s
uv run pytest -q integrations/mcp/isaac/tests       -> 202 passed in 5.20s
uv run pytest -q livebench/tests                    -> 798 passed, 1 skipped in 28.33s
uv run ruff check <classic.py test_classic.py classic11/gz>   -> All checks passed!
uv run ruff format --check <classic.py test_classic.py>       -> 2 files already formatted
uv run mypy <classic.py test_classic.py> (strict, repo root)  -> Success: no issues found in 2 source files
```

Not run: every `packages/api` test and ratchet (conftest needs Postgres; containers down) — a
later task re-runs them. Model-provider calls in this task: 0 (none made, scripted or real).

## Open

- `gz joint --pos-t` on an absent model/joint stays a silent rc-0 success (no stderr), so
  `set_targets` cannot detect it through `_ok`; a presence check there would cost one
  `gz model -i` per call. Not in this task's scope — human/P9 decision.
- `Invalid arguments` (rc 0) is not an `Error` line and still passes `_ok`; the only known
  producer (`-d 0.3`) was fixed in P8-T2.
