"""SOLUSDEV-321 P6 — what a policy produces and what a controller takes, read by structure (pure).

`read_policy(path, text)` returns the module interfaces one file states. Nothing it is handed
runs, and nothing it names is opened:

- Python is read with `ast.parse` and walked for literals: a `Box(..., shape=(n,))` assigned to a
  name ending `action_space` states a policy's outputs, one ending `observation_space` its inputs.
- YAML (JSON too) within the reader's byte cap and with no anchor or alias is read by a
  `yaml.SafeLoader` whose mappings keep the line of each key (`ros_reader._safe_yaml`). A mapping
  states a policy through `action_dim` / `obs_dim`, an `action_space` / `observation_space` with
  a `shape`, or `output_features` / `input_features` whose one feature has a one-dimensional
  `shape`. Each mapping beneath a key that names a controller and holding `input_dim`,
  `command_dim` or a `joints` list states one controller's inputs. A ref is the line of the key
  that states the interface, in the mapping that states it.
- A checkpoint path literal (`.pt`, `.pth`, `.ckpt`, `.onnx`, `.safetensors`) is recorded and
  never opened.

A dimension that is not a literal integer within 1..MAX_DIM is None and named in `ambiguous`:
nothing is guessed, and `module_contract_mismatch` answers `unknown_input` for it. A malformed or
too-deep text states nothing. Structure is the only signal, so no framework is named here.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from typing import Final, Literal, TypeGuard

import yaml
from pydantic import BaseModel, ConfigDict, Field

from solus_api.software.ros_reader import _callee, _keyword, _parse_python, _safe_yaml

Role = Literal["policy", "controller"]

MAX_DIM: Final = 1 << 16
#: The interfaces one file states, at most; the mappings one YAML text is searched through, and
#: how deep.
MAX_INTERFACES: Final = 16
MAX_MAPPINGS: Final = 256
MAX_DEPTH: Final = 8
MAX_REF_CHARS: Final = 1024
CHECKPOINT_SUFFIXES: Final = (".pt", ".pth", ".ckpt", ".onnx", ".safetensors")
CONFIG_SUFFIXES: Final = (".yaml", ".yml", ".json")
#: A space's name suffix (Python) or key (YAML) → the side of the policy it states.
SPACES: Final = {"action_space": "outputs", "observation_space": "inputs"}
POLICY_DIMS: Final = {"action_dim": "outputs", "obs_dim": "inputs"}
FEATURES: Final = {"output_features": "outputs", "input_features": "inputs"}
CONTROLLER_INPUTS: Final = ("input_dim", "command_dim", "joints")
#: The key a policy's `ref` points at: its outputs first.
_ANCHORS: Final = (
    "action_dim",
    "action_space",
    "output_features",
    "obs_dim",
    "observation_space",
    "input_features",
)


class ModuleInterface(BaseModel):
    """What one module states: a policy's inputs (observations) and outputs (actions), or a
    controller's inputs (commands). `ref` is `path:line`; it rides on the file's entity as
    `attrs.module_interfaces` and is validated back by the fact store."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Role
    inputs: int | None = Field(default=None, ge=1, le=MAX_DIM)
    outputs: int | None = Field(default=None, ge=1, le=MAX_DIM)
    ref: str = Field(min_length=1, max_length=MAX_REF_CHARS)
    checkpoint: str | None = Field(default=None, max_length=MAX_REF_CHARS)
    ambiguous: tuple[str, ...] = Field(default=(), max_length=8)


def read_policy(path: str, text: str) -> list[ModuleInterface]:
    """The interfaces `text` states, by its path's suffix; [] for anything else."""
    if path.endswith(".py"):
        return _python_interfaces(path, text)
    if path.endswith(CONFIG_SUFFIXES):
        return _config_interfaces(path, text)[:MAX_INTERFACES]
    return []


# ------------------------------------------------------------------------------- Python


def _python_interfaces(path: str, text: str) -> list[ModuleInterface]:
    tree = _parse_python(text)
    if tree is None:
        return []
    dims: dict[str, int | None] = {}
    ambiguous: list[str] = []
    line = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if _callee(node.value) != "Box":
            continue
        for space, side in _spaces_named(node.targets):
            dims[side] = _box_dim(node.value)
            if dims[side] is None:
                ambiguous.append(f"{space}.shape")
            if side == "outputs" or not line:
                line = node.lineno
    if not dims:
        return []
    return [
        ModuleInterface(
            role="policy",
            inputs=dims.get("inputs"),
            outputs=dims.get("outputs"),
            ref=_ref(path, line),
            checkpoint=_python_checkpoint(tree),
            ambiguous=tuple(dict.fromkeys(ambiguous)),
        )
    ]


def _spaces_named(targets: list[ast.expr]) -> Iterator[tuple[str, str]]:
    """`(space, side)` for each assignment target named like a space (`self.action_space`)."""
    for target in targets:
        name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", None)
        for space, side in SPACES.items():
            if isinstance(name, str) and name.endswith(space):
                yield space, side


def _box_dim(call: ast.Call) -> int | None:
    shape = _keyword(call, "shape") or (call.args[2] if len(call.args) > 2 else None)
    if not isinstance(shape, ast.Tuple | ast.List) or len(shape.elts) != 1:
        return None
    only = shape.elts[0]
    return _dim(only.value) if isinstance(only, ast.Constant) else None


def _python_checkpoint(tree: ast.Module) -> str | None:
    return next(
        (
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and _checkpoint_like(node.value)
        ),
        None,
    )


# ---------------------------------------------------------------------- YAML and JSON


class _Lined(dict[object, object]):
    """A YAML mapping that keeps the line each of its keys is written on."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: dict[object, int] = {}


class _LinedLoader(yaml.SafeLoader):
    """`yaml.SafeLoader` whose mappings are `_Lined`."""


def _construct_lined(loader: _LinedLoader, node: yaml.MappingNode) -> Iterator[_Lined]:
    mapping = _Lined()
    yield mapping  # the mapping exists before its values are read, as SafeLoader's own does
    mapping.update(loader.construct_mapping(node))
    mapping.lines.update(
        (loader.construct_object(key), key.start_mark.line + 1) for key, _value in node.value
    )


_LinedLoader.add_constructor("tag:yaml.org,2002:map", _construct_lined)


def _config_interfaces(path: str, text: str) -> list[ModuleInterface]:
    found: list[ModuleInterface] = []
    for key, mapping in _mappings(_safe_yaml(text, _LinedLoader)):
        policy = _policy(path, mapping)
        if policy is not None:
            found.append(policy)
        if isinstance(key, str) and "controller" in key.lower():
            found.extend(_controllers(path, mapping))
    return list(dict.fromkeys(found))  # a controller nested under another's key is read once


def _mappings(doc: object) -> Iterator[tuple[object, Mapping[object, object]]]:
    """Each mapping in `doc` with the key it sits under (a list's items share the list's),
    depth-first in document order, at most MAX_MAPPINGS of them and MAX_DEPTH deep."""
    stack: list[tuple[object, object, int]] = [(None, doc, 0)]
    seen = 0
    while stack and seen < MAX_MAPPINGS:
        key, node, depth = stack.pop()
        if isinstance(node, Mapping):
            seen += 1
            yield key, node
            children = list(node.items())
        elif isinstance(node, list):
            children = [(key, item) for item in node]
        else:
            continue
        if depth < MAX_DEPTH:
            stack.extend((k, v, depth + 1) for k, v in reversed(children))


def _policy(path: str, mapping: Mapping[object, object]) -> ModuleInterface | None:
    dims: dict[str, int | None] = {}
    ambiguous: list[str] = []
    for key, side, dim in _policy_sides(mapping):
        if side not in dims:
            dims[side] = dim
            if dim is None:
                ambiguous.append(key)
    if not dims:
        return None
    anchor = next(key for key in _ANCHORS if key in mapping)
    return ModuleInterface(
        role="policy",
        inputs=dims.get("inputs"),
        outputs=dims.get("outputs"),
        ref=_ref(path, _line_of(mapping, anchor)),
        checkpoint=next((v for v in mapping.values() if _checkpoint_like(v)), None),
        ambiguous=tuple(ambiguous),
    )


def _policy_sides(mapping: Mapping[object, object]) -> Iterator[tuple[str, str, int | None]]:
    """`(key, side, dimension)` for each policy statement in one mapping."""
    for key, side in POLICY_DIMS.items():
        if key in mapping:
            yield key, side, _dim(mapping[key])
    for key, side in SPACES.items():
        space = mapping.get(key)
        if isinstance(space, Mapping) and "shape" in space:
            yield f"{key}.shape", side, _shape_dim(space["shape"])
    for key, side in FEATURES.items():
        features = mapping.get(key)
        if isinstance(features, Mapping):
            yield key, side, _feature_dim(features)


def _controllers(path: str, mapping: Mapping[object, object]) -> Iterator[ModuleInterface]:
    """Each controller beneath a key that names one (bounded): every mapping that states its
    inputs, so a source's controllers are all read, each ref the line of the field stating them."""
    for _key, inner in _mappings(mapping):
        field = next((name for name in CONTROLLER_INPUTS if name in inner), None)
        if field is None:
            continue
        value = inner[field]
        inputs = len(value) if field == "joints" and isinstance(value, list) else _dim(value)
        inputs = inputs if inputs is None or 1 <= inputs <= MAX_DIM else None
        yield ModuleInterface(
            role="controller",
            inputs=inputs,
            ref=_ref(path, _line_of(inner, field)),
            ambiguous=() if inputs is not None else (field,),
        )


def _shape_dim(shape: object) -> int | None:
    if not isinstance(shape, list | tuple) or len(shape) != 1:
        return None
    return _dim(shape[0])


def _feature_dim(features: Mapping[object, object]) -> int | None:
    """The width of the one feature a features mapping states, when its shape is 1-D."""
    if len(features) != 1:
        return None
    (only,) = features.values()
    return _shape_dim(only.get("shape")) if isinstance(only, Mapping) else None


# ------------------------------------------------------------------------------- shared


def _dim(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1 <= value <= MAX_DIM else None


def _checkpoint_like(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and len(value) <= MAX_REF_CHARS
        and value.lower().endswith(CHECKPOINT_SUFFIXES)
    )


def _line_of(mapping: Mapping[object, object], key: str) -> int:
    """The line `key` is written on in `mapping`; 1 for a mapping that kept no lines."""
    return mapping.lines.get(key, 1) if isinstance(mapping, _Lined) else 1


def _ref(path: str, line: int) -> str:
    return f"{path[: MAX_REF_CHARS - 12]}:{line}"
