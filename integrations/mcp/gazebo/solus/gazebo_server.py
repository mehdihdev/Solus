"""The `solus-gazebo` stdio MCP server: 13 allowlisted tools over the family adapters.

Mirrors ``integrations/mcp/isaac/solus/server.py``: raw JSON arguments are validated by the
Strict models in :mod:`tool_args` before anything runs, every tool returns a dict and NOTHING
raises across the wire — :class:`Unsupported`, :class:`CliError`, :class:`SessionRefusedError`
and plain ``ValueError`` become ``{ok: false, code, reason}``. Every mutating tool honours
``dry_run`` with ``{ok, dry_run, preview: [{label, before, after}], fingerprint}`` (the card body
the API renders; ``bridge/tool.py:_diff_rows`` is the acceptance). ``probe`` returns the detected
families and the capability-matrix row of the newest one, so the API never copies the matrix.

Security posture (CLAUDE.md §7): binaries only from ``SOLUS_GAZEBO_PATH``; world files only
under ``SOLUS_SIM_ROOTS`` through fd-relative opens; models only from the verified store under
``.solus/sim/models/<sha256>/``; one owned process group, stopped only through its handle;
results carry root-relative paths and path-redacted simulator stderr, never absolute paths.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "solus"

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool
from pydantic import ValidationError

from .adapters import ClassicAdapter, adapter_for
from .adapters.adapter_base import (
    Adapter,
    CliError,
    CliRunner,
    Unsupported,
    WorldPose,
    check_name,
    redact_paths,
    run_argv,
)
from .adapters.classic import _SAVE_WORLD_SENTENCE
from .family_detect import (
    Family,
    FamilyName,
    Runner,
    detect_families,
    family_for,
    family_hint,
    gazebo_search_path,
    newest,
    subprocess_run,
)
from .gazebo_routines import (
    joint_targets_of,
    routine_plan,
    routine_result,
    sample_row,
)
from .model_assets import (
    SPAWN_PREFIX,
    ModelAssets,
    VerifiedModel,
    confined_read_all,
    model_file_of,
)
from .spawn import _parse_guarded, wrap_model  # the one guarded XML parser of this fork
from .tool_args import (
    ARG_MODELS,
    ControlArgs,
    JointStateArgs,
    OpenWorldArgs,
    RunRoutineArgs,
    SaveWorldArgs,
    SetJointTargetsArgs,
    SpawnArgs,
    StrictArgs,
)
from .world_sessions import SessionRefusedError, WorldSession, WorldSessions
from .worlds import confined_open, confined_write, list_world_files, read_confined, sim_roots

MUTATING_TOOLS: Final = (
    "open_world",
    "spawn",
    "set_joint_targets",
    "control",
    "run_routine",
    "stop",
    "save_world",
)
ROUTINE_GRACE_S: Final = 10.0  # run_routine wall time ≤ duration_s + this
MAX_MODEL_JOINTS: Final = 32
WORLD_PREFIX_BYTES: Final = 1 << 20
_WORLD_NAME = re.compile(r"<world\s[^>]*?\bname\s*=\s*[\"']([^\"']+)[\"']")
_MOVABLE = frozenset({"revolute", "continuous", "prismatic", "revolute2", "universal", "ball"})
_DIGEST = re.compile(r"[0-9a-f]{64}")

#: Plan §3 / RECON §3 rows, keyed by family; `probe` returns the newest installed family's row.
CAPABILITIES: Final[dict[str, dict[str, object]]] = {
    "classic": {
        "list_worlds": True,
        "running_worlds": "gz topic -l",
        "list_models": "gz model -w <w> -m <m> -i per model",
        "spawn": "gz model -f (URDF as-is; joint control built into classic physics)",
        "joint_state": "polled gz model -i at ≤ 10 Hz, position only",
        "set_joint_targets": "gz joint --pos-t",
        "control": "gz world -p/-s/-m/-r/-t/-o",
        "save_world": False,
        "telemetry": "gz topic -e (protobuf text format)",
        "gui": "gazebo <file>",
        "python_binding": False,
    },
    "ignition": {
        "list_worlds": True,
        "running_worlds": "ign service -l",
        "list_models": "ign service scene/info + ign model -j",
        "spawn": "ign service create (SDF with joint-state-publisher and position controllers)",
        "joint_state": "ign topic -e --json-output (verify at install; text-format fallback)",
        "set_joint_targets": "ign topic -p on /model/<m>/joint/<j>/0/cmd_pos",
        "control": "ign service control (pause/play/multi_step/reset)",
        "save_world": True,
        "telemetry": "ign topic -e --json-output",
        "gui": "ign gazebo <file>",
        "python_binding": False,
    },
    "gz": {
        "list_worlds": True,
        "running_worlds": "gz service -l",
        "list_models": "gz service scene/info + gz model -j",
        "spawn": "gz service create (SDF with joint-state-publisher and position controllers)",
        "joint_state": "gz topic -e --json-output",
        "set_joint_targets": "gz topic -p on /model/<m>/joint/<j>/0/cmd_pos",
        "control": "gz service control (pause/play/multi_step/reset)",
        "save_world": True,
        "telemetry": "gz topic -e --json-output",
        "gui": "gz sim <file>",
        "python_binding": "gz.transport (system python only)",
    },
}
UNSUPPORTED: Final[dict[tuple[str, str], str]] = {("classic", "save_world"): _SAVE_WORLD_SENTENCE}
_DESCRIPTIONS: Final[dict[str, str]] = {
    "probe": "Which Gazebo families are installed, their capability row, running worlds",
    "list_worlds": "Gazebo world files under the sim roots and the worlds running right now",
    "open_world": "Start one Solus-owned Gazebo server on a world file",
    "attach": "Register a Gazebo world the user started themselves (read-only)",
    "list_models": "Models, links and joints of a registered Gazebo world",
    "spawn": "Insert a verified Solus-generated model into a registered Gazebo world",
    "joint_state": "A bounded window of joint positions and velocities from Gazebo",
    "set_joint_targets": "Set joint position targets inside a registered Gazebo world",
    "control": "Pause, play, step or reset a registered Gazebo world",
    "run_routine": "Run a finite joint routine in Gazebo with readback",
    "stop": "Stop the Gazebo server this companion started",
    "save_world": "Write the running Gazebo world back into the user's own file",
    "put_asset": "Store one chunk of a Solus-generated model for Gazebo, verified by manifest",
}

Result = dict[str, Any]


# --- small shared pieces ---------------------------------------------------------------------


def refused(code: str, reason: str) -> Result:
    """Every refusal reason is path-redacted here as well: no absolute path leaves the fork."""
    return {"ok": False, "code": code, "reason": redact_paths(reason)[:200]}


def digest_of(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def preview_result(rows: Sequence[Mapping[str, str | None]], fingerprint: str) -> Result:
    return {"ok": True, "dry_run": True, "preview": list(rows), "fingerprint": fingerprint}


def row(label: str, before: str | None, after: str | None) -> dict[str, str | None]:
    return {
        "label": label,
        "before": before if before is None else before[:400],
        "after": after if after is None else after[:400],
    }


def validation_reason(error: ValidationError) -> str:
    """Field locations and messages only — never the offending input."""
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}"
        for e in error.errors(include_input=False, include_url=False)[:3]
    )


def world_name_of(data: bytes) -> str:
    match = _WORLD_NAME.search(data.decode("utf-8", "replace"))
    if match is None:
        raise ValueError("the world file names no <world>")
    return check_name(match.group(1))


def movable_joints(model_xml: bytes) -> list[str]:
    """Non-fixed joint names of a URDF/SDF model, in document order, bounded."""
    root = _parse_guarded(model_xml)
    names: list[str] = []
    for joint in root.iter("joint"):
        name = joint.get("name")
        if (joint.get("type") or "fixed") in _MOVABLE and name and name not in names:
            names.append(check_name(name))
    if len(names) > MAX_MODEL_JOINTS:
        raise ValueError(f"model has more than {MAX_MODEL_JOINTS} movable joints")
    return names


def inline_schema_defs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline the closed Pydantic ``$defs`` for the bridge's ref gate (isaac's shape)."""
    definitions = schema.get("$defs", {})

    def expand(value: Any, active: frozenset[str] = frozenset()) -> Any:
        if isinstance(value, list):
            return [expand(item, active) for item in value]
        if not isinstance(value, dict):
            return value
        siblings = {key: item for key, item in value.items() if key not in {"$defs", "$ref"}}
        if "$ref" in value:
            ref = value["$ref"]
            if (
                not isinstance(ref, str)
                or not ref.startswith("#/$defs/")
                or ref in active
                or ref[8:] not in definitions
            ):
                raise ValueError("schema must contain only acyclic local definitions")
            target = expand(definitions[ref[8:]], active | {ref})
            return {**target, **expand(siblings, active)}
        return {key: expand(item, active) for key, item in siblings.items()}

    return dict(expand(schema))


def gazebo_tool_specs() -> list[Tool]:
    return [
        Tool(
            name=name,
            description=_DESCRIPTIONS[name]
            + ". Arguments are supplied only by the authenticated Solus adapter.",
            inputSchema=inline_schema_defs(model.model_json_schema()),
        )
        for name, model in ARG_MODELS.items()
    ]


def wire_encode(result: Result) -> Result:
    """Chunk declared digest fields so secret redaction downstream keeps them readable."""

    def encode(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {name: encode(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [encode(item) for item in value]
        if (
            key in {"fingerprint", "sha256", "model_sha256"}
            and isinstance(value, str)
            and _DIGEST.fullmatch(value)
        ):
            return ":".join(value[i : i + 16] for i in range(0, 64, 16))
        return value

    return {name: encode(value, name) for name, value in result.items()}


# --- the service -----------------------------------------------------------------------------


class GazeboToolService:
    def __init__(
        self,
        workspace: Path,
        *,
        run: CliRunner = run_argv,
        detect_run: Runner = subprocess_run,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.workspace = workspace.resolve(strict=True)
        self.home = self.workspace / ".solus" / "sim" / "home"
        self.run = run
        self.detect_run = detect_run
        self.clock = clock
        self.sleep = sleep
        self.assets = ModelAssets(self.workspace)
        self.sessions = WorldSessions(clock=clock, sleep=sleep)
        self.lock = threading.RLock()
        self._families: tuple[Family, ...] | None = None
        self._tools: dict[str, Callable[[Any], Result]] = {
            "probe": self._probe,
            "list_worlds": self._list_worlds,
            "open_world": self._open_world,
            "attach": self._attach,
            "list_models": self._list_models,
            "spawn": self._spawn,
            "joint_state": self._joint_state,
            "set_joint_targets": self._set_joint_targets,
            "control": self._control,
            "run_routine": self._run_routine,
            "stop": self._stop,
            "save_world": self._save_world,
            "put_asset": lambda a: self.assets.put_chunk(a),
        }

    # --- dispatch ----------------------------------------------------------------------------

    def call(self, name: str, arguments: dict[str, Any]) -> Result:
        if name not in ARG_MODELS:
            return refused("unknown_tool", "no such tool")
        try:
            args = ARG_MODELS[name].model_validate(arguments)
        except ValidationError as error:
            return refused("invalid_arguments", validation_reason(error))
        with self.lock:
            try:
                return self._tools[name](args)
            except Unsupported as unsupported:
                return unsupported.wire()
            except SessionRefusedError as session:
                return refused(session.code, session.reason)
            except CliError as cli:
                return refused("cli_failed", cli.reason)
            except ValueError as error:
                return refused("refused", str(error) or "refused")
            except (OSError, TimeoutError) as error:
                return refused("io_failed", type(error).__name__)
            except Exception as error:  # the never-raises invariant across the wire
                return refused("internal_error", type(error).__name__)

    def close(self) -> None:
        with self.lock:
            self.sessions.close()

    # --- families and adapters ---------------------------------------------------------------

    def families(self, *, refresh: bool = False) -> tuple[Family, ...]:
        if self._families is None or refresh:
            self._families = detect_families(gazebo_search_path(), self.detect_run)
        return self._families

    def _family_named(self, name: FamilyName) -> Family:
        for family in self.families():
            if family.name == name:
                return family
        raise SessionRefusedError("family_not_installed", f"no {name} install on SOLUS_GAZEBO_PATH")

    def _adapter(self, family: Family) -> Adapter:
        if family.name == "classic":
            return ClassicAdapter(
                family, run=self.run, home=self.home, clock=self.clock, sleep=self.sleep
            )
        return adapter_for(family, run=self.run, home=self.home)

    # --- discovery ---------------------------------------------------------------------------

    def _probe(self, _: StrictArgs) -> Result:
        families = self.families(refresh=True)
        top = newest(families)
        running = self._running(top) if top else []
        return {
            "ok": True,
            "families": [
                {"name": f.name, "version": f.version, "distro": f.distro} for f in families
            ],
            "capabilities": CAPABILITIES[top.name] if top else None,
            "gui_attach": bool(running),
            "running_worlds": running,
            "sessions": [s.summary() for s in self.sessions.all()],
            "roots": len(sim_roots()),
        }

    def _running(self, family: Family) -> list[str]:
        try:
            return self._adapter(family).running_worlds()
        except CliError:
            return []

    def _list_worlds(self, _: StrictArgs) -> Result:
        files = list_world_files(sim_roots())
        running = [
            {"family": family.name, "version": family.version, "world": world}
            for family in self.families()
            for world in self._running(family)
        ]
        return {
            "ok": True,
            "roots": len(sim_roots()),
            "worlds": [{"path": f.path, "family_hint": f.family_hint} for f in files],
            "running": running,
        }

    # --- sessions ----------------------------------------------------------------------------

    def _resolve_world(self, world_ref: str) -> tuple[Path, bytes]:
        """The first sim root holding ``world_ref`` and the file's prefix bytes."""
        for root in sim_roots():
            try:
                return root, read_confined(root, world_ref, WORLD_PREFIX_BYTES, truncate=True)
            except ValueError:
                continue
        raise ValueError(f"no world file {world_ref!r} under the sim roots")

    def _choose_family(self, args: OpenWorldArgs, path: Path, data: bytes) -> tuple[Family, str]:
        families = self.families()
        if not families:
            raise SessionRefusedError("family_not_installed", "no Gazebo on SOLUS_GAZEBO_PATH")
        if args.family is not None:
            return self._family_named(args.family), f"requested {args.family}"
        hint = family_hint(data)
        chosen = family_for(path, families)
        if chosen is None:
            raise SessionRefusedError("family_not_installed", "no Gazebo on SOLUS_GAZEBO_PATH")
        if hint == chosen.name:
            return chosen, f"hinted by the world file ({hint})"
        return chosen, (
            f"newest installed family ({chosen.name} {chosen.version}); the world file carries "
            "no usable family hint"
            if hint is None
            else f"newest installed family ({chosen.name} {chosen.version}); the file hints "
            f"{hint}, which is not installed"
        )

    def _open_world(self, args: OpenWorldArgs) -> Result:
        root, data = self._resolve_world(args.world_ref)
        world = world_name_of(data)
        family, reason = self._choose_family(args, root / args.world_ref, data)
        label = f"{family.name} {family.version}" + (f" ({family.distro})" if family.distro else "")
        if args.dry_run:
            rows = [
                row("Simulator", None, f"Start {label}, owned by Solus"),
                row("World file", None, args.world_ref),
                row("World", None, world),
                row("Mode", None, "GUI" if args.gui else "headless"),
                row("Family choice", None, reason),
                row("Lifetime", None, "Stopped only through gazebo.stop or with the companion"),
            ]
            return preview_result(rows, digest_of(["open_world", args.model_dump(), world, label]))
        session = self.sessions.open_world(
            self._adapter(family),
            root / args.world_ref,
            world=world,
            world_ref=args.world_ref,
            gui=args.gui,
        )
        return {"ok": True, **session.summary(), "family_reason": reason}

    def _attach(self, args: Any) -> Result:
        session = self.sessions.attach(self._adapter(self._family_named(args.family)), args.world)
        return {"ok": True, **session.summary()}

    def _stop(self, args: Any) -> Result:
        session = self.sessions.get(args.session_id)
        if not session.owned:
            raise SessionRefusedError(
                "not_owned",
                "this world was started by you, not by Solus; stop it from where you started it",
            )
        if args.dry_run:
            summary = session.summary()
            rows = [
                row(
                    "Simulator",
                    f"{summary['family']} {summary['version']} running {session.world}",
                    "Stop Solus's own simulator process group",
                )
            ]
            return preview_result(rows, digest_of(["stop", args.session_id, summary]))
        self.sessions.stop(args.session_id)
        return {"ok": True, "session_id": args.session_id, "state": "stopped"}

    # --- scene and state ---------------------------------------------------------------------

    def _list_models(self, args: Any) -> Result:
        session = self.sessions.get(args.session_id)
        scene = session.adapter.scene(session.world)
        return {
            "ok": True,
            "session_id": session.session_id,
            "world": scene.world,
            "models": [
                {
                    "name": m.name,
                    "links": list(m.links),
                    "joints": [
                        {
                            "name": j.name,
                            "type": j.type,
                            "parent_link": j.parent_link,
                            "child_link": j.child_link,
                        }
                        for j in m.joints
                    ],
                }
                for m in scene.models
            ],
        }

    def _joint_state(self, args: JointStateArgs) -> Result:
        session = self.sessions.get(args.session_id)
        samples = session.adapter.joint_state(session.world, args.model, args.joints, args.window_s)
        return {
            "ok": True,
            "session_id": session.session_id,
            "world": session.world,
            "model": args.model,
            "window_s": args.window_s,
            "paused": any(s.paused for s in samples),
            "count": len(samples),
            "samples": [sample_row(s) for s in samples],
        }

    def _current_positions(
        self, session: WorldSession, model: str, joints: Sequence[str]
    ) -> dict[str, float]:
        try:
            samples = session.adapter.joint_state(session.world, model, list(joints), 0.0)
        except (CliError, ValueError):
            return {}
        return {s.joint: s.position for s in samples}

    # --- actions -----------------------------------------------------------------------------

    def _set_joint_targets(self, args: SetJointTargetsArgs) -> Result:
        session = self.sessions.get(args.session_id)
        targets = {t.joint: t.position_rad for t in args.targets}
        if args.dry_run:
            before = self._current_positions(session, args.model, list(targets))
            rows = [
                row(
                    f"{args.model}/{joint}",
                    f"{before[joint]:.4f} rad" if joint in before else None,
                    f"{value:.4f} rad target",
                )
                for joint, value in targets.items()
            ]
            return preview_result(rows, digest_of(["set_joint_targets", args.model_dump()]))
        session.adapter.set_targets(session.world, args.model, targets)
        return {
            "ok": True,
            "session_id": session.session_id,
            "model": args.model,
            "targets": targets,
        }

    def _control(self, args: ControlArgs) -> Result:
        session = self.sessions.get(args.session_id)
        if args.action == "step":
            after = f"step {args.steps} iteration(s) (the world pauses first)"
        elif args.action == "reset":
            after = f"reset {args.reset_scope}"
        else:
            after = args.action
        if args.dry_run:
            rows = [row(f"World {session.world}", None, after)]
            return preview_result(rows, digest_of(["control", args.model_dump()]))
        session.adapter.control(
            session.world, args.action, steps=args.steps, scope=args.reset_scope
        )
        return {
            "ok": True,
            "session_id": session.session_id,
            "action": args.action,
            "steps": args.steps,
            "reset_scope": args.reset_scope,
        }

    def _run_routine(self, args: RunRoutineArgs) -> Result:
        session = self.sessions.get(args.session_id)
        plan = routine_plan(args)
        joints = list(args.joints or joint_targets_of(plan))
        if args.dry_run:
            rows = [
                row("Routine", None, f"{args.routine} on {args.model} in {session.world}"),
                row("Joints", None, ", ".join(joints)),
                row("Targets", None, f"{len(plan)} target set(s) over {args.duration_s:g} s"),
                row("Wall time", None, f"≤ {args.duration_s + ROUTINE_GRACE_S:g} s, then readback"),
            ]
            return preview_result(rows, digest_of(["run_routine", args.model_dump()]))
        started = self.clock()
        deadline = started + args.duration_s + ROUTINE_GRACE_S
        sent = 0
        for t, targets in plan:
            wait = min(started + t, deadline) - self.clock()
            if wait > 0:
                self.sleep(wait)
            if self.clock() >= deadline:
                break
            session.adapter.set_targets(session.world, args.model, targets)
            sent += 1
        settle = min(started + args.duration_s, deadline - 1.0) - self.clock()
        if settle > 0:
            self.sleep(settle)
        window = max(0.0, min(1.0, deadline - self.clock() - 0.5))
        samples = session.adapter.joint_state(session.world, args.model, joints, window)
        family = session.adapter.family
        return routine_result(
            args,
            session.session_id,
            session.world,
            plan,
            sent,
            samples,
            self.clock() - started,
            family=(family.name, family.version),
        )

    # --- models and files --------------------------------------------------------------------

    def _spawn(self, args: SpawnArgs) -> Result:
        session = self.sessions.get(args.session_id)
        with self._verified_model(args.model_sha256) as model:
            model_file = model_file_of(model.manifest)
            source = confined_read_all(model.fd, model_file)
            joints = movable_joints(source)
            family = session.adapter.family
            pose = WorldPose(xyz=_vec3(args.pose.xyz), rpy=_vec3(args.pose.rpy))
            if args.dry_run:
                rows = [
                    row(
                        "Model",
                        None,
                        f"{model_file} ({args.model_sha256[:16]}…, {len(model.manifest)} files)",
                    ),
                    row("Name in world", None, args.name),
                    row("Pose", None, f"xyz={list(pose.xyz)} rpy={list(pose.rpy)}"),
                    row("Joints controlled", None, ", ".join(joints) or "none"),
                    row("World", None, f"{session.world} ({family.name} {family.version})"),
                ]
                return preview_result(rows, digest_of(["spawn", args.model_dump()]))
            wrapped = wrap_model(source, family, joints, args.name, run=self.run)
            suffix = "urdf" if family.name == "classic" and model_file.endswith(".urdf") else "sdf"
            spawn_rel = f"{SPAWN_PREFIX}{args.name}.{suffix}"
            # Beside its meshes (relative <uri>s resolve against the model file's directory),
            # through the verified descriptor: O_NOFOLLOW, atomic via a sibling temp file.
            confined_write(model.fd, spawn_rel, wrapped)
            session.adapter.spawn(session.world, model.path / spawn_rel, args.name, pose)
        return {
            "ok": True,
            "session_id": session.session_id,
            "world": session.world,
            "name": args.name,
            "model_sha256": args.model_sha256,
            "joints": joints,
        }

    @contextlib.contextmanager
    def _verified_model(self, sha256: str) -> Iterator[VerifiedModel]:
        """The verified model directory, or the one code the API wrapper keys its chunk push
        on (`model_not_verified`): absent, unverifiable and tampered all mean "push it again".
        Only acquiring the model is converted: a `with` body's own ValueError (malformed XML,
        an adapter refusal) is thrown back in at the `yield` and must keep its own code."""
        with contextlib.ExitStack() as stack:
            try:
                model = stack.enter_context(self.assets.verified(sha256))
            except ValueError as error:
                raise SessionRefusedError("model_not_verified", str(error)) from error
            yield model

    def _save_world(self, args: SaveWorldArgs) -> Result:
        session = self.sessions.get(args.session_id)
        family = session.adapter.family
        sentence = UNSUPPORTED.get((family.name, "save_world"))
        if sentence is not None:
            raise Unsupported(family.name, family.version, sentence)
        root = self._save_root(session)
        if args.dry_run:
            rows = [
                row("Destination", _file_state(root, args.dest), args.dest),
                row(
                    "Source",
                    None,
                    f"running world {session.world} ({family.name} {family.version})",
                ),
            ]
            return preview_result(rows, digest_of(["save_world", args.model_dump()]))
        session.adapter.save_world(session.world, root, args.dest)
        return {"ok": True, "session_id": session.session_id, "dest": args.dest}

    def _save_root(self, session: WorldSession) -> Path:
        roots = sim_roots()
        if not roots:
            raise ValueError("SOLUS_SIM_ROOTS names no directory to save into")
        if session.world_ref is not None:
            root, _ = self._resolve_world(session.world_ref)
            return root
        return roots[0]


# --- result helpers ---------------------------------------------------------------------------


def _vec3(values: Sequence[float]) -> tuple[float, float, float]:
    x, y, z = values
    return (x, y, z)


def _file_state(root: Path, rel: str) -> str:
    try:
        fd = confined_open(root, rel)
    except ValueError:
        return "absent"
    try:
        return f"exists ({os.fstat(fd).st_size} bytes)"
    finally:
        os.close(fd)


def encode_result(result: Result) -> CallToolResult:
    """The one place a result becomes wire bytes, inside the never-raises guard: a result that
    cannot be serialized (a NaN/inf a simulator printed, …) is an ``internal_error`` result,
    never an ``isError``/raised exception the SDK would surface."""
    try:
        encoded = wire_encode(result)
        text = json.dumps(encoded, allow_nan=False)
    except Exception as error:
        encoded = refused("internal_error", f"result not serializable: {type(error).__name__}")
        text = json.dumps(encoded)
    return CallToolResult(
        content=[TextContent(type="text", text=text)], structuredContent=encoded, isError=False
    )


# --- MCP transport -----------------------------------------------------------------------------


async def serve_gazebo() -> None:
    workspace = os.environ.get("SOLUS_MCP_WORKSPACE", "")
    if not workspace or not Path(workspace).is_absolute():
        raise ValueError("workspace unavailable")
    service = GazeboToolService(Path(workspace))
    server = Server("solus-gazebo")

    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
    async def list_tools() -> list[Tool]:
        return gazebo_tool_specs()

    @server.call_tool(validate_input=False)  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        try:
            result = await asyncio.to_thread(service.call, name, arguments)
        except asyncio.CancelledError:
            # Cancelling an await does not stop its worker thread; close the owned process.
            await asyncio.shield(asyncio.to_thread(service.close))
            raise
        return encode_result(result)

    try:
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())
    finally:
        service.close()


if __name__ == "__main__":
    asyncio.run(serve_gazebo())
