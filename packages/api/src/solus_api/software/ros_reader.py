"""SOLUSDEV-321 P6 — a ROS workspace's nodes and topics, read from its package texts (pure).

`parse_ros_workspace(packages)` takes the texts a connector already holds (the local companion's
bounded scan, `FolderScan.ros`, or the files a code host serves) and returns the nodes its launch
files start, the topics their modules declare, and where each was stated. Nothing it is handed
runs:

- Python (a launch file, a node's module, `setup.py`) is read with `ast.parse` and walked for
  literals, and is never imported, loaded or executed;
- XML (a launch file, `package.xml`) goes through `graph/inference/manifests._xml_root`, which
  refuses a DTD and caps the size;
- YAML (a launch file under `launch/`) is capped at MAX_YAML_BYTES and refused when it holds an
  anchor or an alias, then read with `yaml.safe_load`; `setup.cfg` is read with `configparser`
  and no interpolation.

A malformed or too-deep text yields nothing (`RecursionError` included), never an exception.

Direction comes from the launched executable's own Python module (R133): a `console_scripts`
entry in `setup.py` or `setup.cfg` names it, and its `create_publisher` / `create_subscription`
calls name each topic and its message type. A node whose executable is no Python module of its
package (compiled code) lands with no topics: Empty beats invented. Names resolve as ROS resolves
them: the launch file's remaps first, then the node's namespace (`~/x` is the node's own). A name
that fails `ROS_NAME`, runs past MAX_NAME_CHARS or carries the ingress filter's mask is dropped;
a node named neither by its launch line nor by its module is named by its executable. A launch
line whose package is no ROS package name, or whose executable is no identifier (one `.py` or
`.sh` suffix allowed), starts no node.
"""

from __future__ import annotations

import ast
import configparser
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Final, Literal, NamedTuple
from xml.etree.ElementTree import Element

import yaml

from solus_api.graph.inference.manifests import NAME_RULES, _line_containing, _xml_root

Direction = Literal["publishes", "subscribes"]

#: A ROS graph name as Solus keeps one (R3): absolute or relative, no substitution. The patterns
#: here are strings `re` caches, so no code-building word appears in this package at all.
ROS_NAME: Final = r"^/?[A-Za-z_][A-Za-z0-9_/]*$"
MAX_NAME_CHARS: Final = 256
MAX_NODES: Final = 256
MAX_TOPICS: Final = 512
MAX_YAML_BYTES: Final = 64 * 1024
#: What the cloud's ingress filter leaves of a secret-shaped run (`agent/tools/untrusted.py`).
MASK: Final = "[REDACTED]"
LAUNCH_FUNCTION: Final = "generate_launch_description"
#: The node-API calls that declare a topic, and which way it runs.
TOPIC_CALLS: Final[Mapping[str, Direction]] = {
    "create_publisher": "publishes",
    "create_subscription": "subscribes",
}
_MESSAGE_TYPE: Final = r"^[a-z][a-z0-9_]*/msg/[A-Za-z][A-Za-z0-9_]*$"
_MODULE_NAME: Final = r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"


@dataclass(frozen=True)
class RosSourceFile:
    """One text a connector holds: its folder- or repository-relative path, and the text."""

    path: str
    text: str


@dataclass(frozen=True)
class RosPackageSources:
    """One ROS package's texts: its `package.xml` and the files beneath its directory."""

    manifest: RosSourceFile
    files: tuple[RosSourceFile, ...] = ()


@dataclass(frozen=True)
class RosNode:
    name: str
    package: str
    executable: str
    publishes: tuple[str, ...]
    subscribes: tuple[str, ...]


@dataclass(frozen=True)
class RosTopic:
    name: str
    type: str | None


@dataclass(frozen=True)
class RosWorkspace:
    """What a workspace's texts state, each list ordered by name."""

    nodes: tuple[RosNode, ...] = ()
    topics: tuple[RosTopic, ...] = ()
    #: Node name → `<launch file>:<line>`, the line that starts it (the edges' CONFIG evidence).
    launched_at: Mapping[str, str] = field(default_factory=dict)
    #: (node name, topic name) → `<module>:<line>`, the call that declares the topic.
    declared_at: Mapping[tuple[str, str], str] = field(default_factory=dict)


class _RosLaunch(NamedTuple):
    """One node a launch file starts."""

    package: str
    executable: str
    name: str | None
    namespace: str
    remaps: tuple[tuple[str, str], ...]
    ref: str


class _Declared(NamedTuple):
    """One topic a module's call declares, as written."""

    direction: Direction
    topic: str
    type: str | None
    line: int


class _RosModule(NamedTuple):
    node_name: str | None
    declared: tuple[_Declared, ...]


_NO_MODULE: Final = _RosModule(None, ())


@dataclass(frozen=True)
class _RosPackage:
    name: str
    files: Mapping[str, str]
    #: Executable → the path of the module its entry point names.
    executables: Mapping[str, str]


def parse_ros_workspace(packages: Sequence[RosPackageSources]) -> RosWorkspace:
    """The nodes the packages' launch files start and the topics their modules declare."""
    index = _index_packages(packages)
    found = _RosFound()
    modules: dict[str, _RosModule] = {}
    for launch in _launch_nodes(index):
        if len(found.nodes) == MAX_NODES:
            break
        path, module = _node_module(index, launch, modules)
        found.add(launch, path, module)
    return found.workspace()


#: A launch line's executable is an ASCII identifier with at most one `.py` or `.sh` suffix (an
#: ament_cmake-installed script, R141) and its package a ROS package name (`NAME_RULES["ros"]`),
#: each at most MAX_IDENTIFIER_CHARS (m2).
IDENTIFIER: Final = r"^[A-Za-z_][A-Za-z0-9_]*(?:\.(?:py|sh))?$"
MAX_IDENTIFIER_CHARS: Final = 128


def _launchable(launch: _RosLaunch) -> bool:
    return (
        max(len(launch.package), len(launch.executable)) <= MAX_IDENTIFIER_CHARS
        and NAME_RULES["ros"].fullmatch(launch.package) is not None
        and re.fullmatch(IDENTIFIER, launch.executable) is not None
    )


class _RosFound:
    """The nodes, topics and refs one parse accumulates."""

    def __init__(self) -> None:
        self.nodes: dict[str, RosNode] = {}
        self.types: dict[str, str | None] = {}
        self.conflicted: set[str] = set()
        self.launched_at: dict[str, str] = {}
        self.declared_at: dict[tuple[str, str], str] = {}

    def add(self, launch: _RosLaunch, path: str, module: _RosModule) -> None:
        """One launched node: the first launch line of a name wins, and a line whose package or
        executable breaks its rule lands nothing."""
        named = launch.name or module.node_name or launch.executable
        name = _ros_valid(_absolute(named, launch.namespace))
        if name is None or name in self.nodes or not _launchable(launch):
            return
        topics: dict[Direction, set[str]] = {"publishes": set(), "subscribes": set()}
        for item in module.declared:
            topic = _topic_name(item.topic, launch, name)
            if topic is None or (topic not in self.types and len(self.types) == MAX_TOPICS):
                continue
            topics[item.direction].add(topic)
            self._type(topic, item.type)
            self.declared_at[(name, topic)] = f"{path}:{item.line}"
        self.nodes[name] = RosNode(
            name,
            launch.package,
            launch.executable,
            tuple(sorted(topics["publishes"])),
            tuple(sorted(topics["subscribes"])),
        )
        self.launched_at[name] = launch.ref

    def _type(self, topic: str, kind: str | None) -> None:
        """A topic's type: two different ones leave it unknown for good, and an unknown one never
        overrides a known one."""
        if topic not in self.types:
            self.types[topic] = kind
        elif kind is None or topic in self.conflicted or self.types[topic] == kind:
            return
        elif self.types[topic] is None:
            self.types[topic] = kind
        else:
            self.types[topic] = None
            self.conflicted.add(topic)

    def workspace(self) -> RosWorkspace:
        return RosWorkspace(
            nodes=tuple(self.nodes[name] for name in sorted(self.nodes)),
            topics=tuple(RosTopic(name, self.types[name]) for name in sorted(self.types)),
            launched_at=dict(self.launched_at),
            declared_at=dict(self.declared_at),
        )


# ------------------------------------------------------------------ packages and entry points


def _index_packages(packages: Sequence[RosPackageSources]) -> dict[str, _RosPackage]:
    """Each package whose manifest names it, by that name (the first of a name wins), holding
    only the files beneath its own directory."""
    index: dict[str, _RosPackage] = {}
    for package in packages:
        name = package_name(package.manifest.text)
        if name is None or name in index:
            continue
        directory = PurePosixPath(package.manifest.path).parent.as_posix()
        prefix = "" if directory == "." else f"{directory}/"
        files = {
            item.path: item.text
            for item in package.files
            if item.path.startswith(prefix) and MASK not in item.path
        }
        index[name] = _RosPackage(name, files, _executables(prefix, files))
    return index


def package_name(text: str) -> str | None:
    """A `package.xml`'s `<name>` when it is a ROS package name, else None. It also names the
    package's own module directory (`<package>/<name>/`), whose modules a connector reads."""
    root = _xml_element(text)
    if root is None or root.tag != "package":
        return None
    name = (root.findtext("name") or "").strip()
    return name if NAME_RULES["ros"].match(name) and len(name) <= 128 else None


def _executables(prefix: str, files: Mapping[str, str]) -> dict[str, str]:
    """Executable → the module its entry point names, from `setup.cfg` and then `setup.py`."""
    entries = {
        **_cfg_entry_points(files.get(f"{prefix}setup.cfg", "")),
        **_entry_points(files.get(f"{prefix}setup.py", "")),
    }
    found: dict[str, str] = {}
    for executable, module in entries.items():
        base = prefix + module.replace(".", "/")
        path = next((p for p in (f"{base}.py", f"{base}/__init__.py") if p in files), None)
        if path is not None:
            found[executable] = path
    return found


def _entry_points(text: str) -> dict[str, str]:
    """`setup(entry_points={"console_scripts": ["exe = pkg.module:main"]})`, literals only."""
    found: dict[str, str] = {}
    for call in _calls(_parse_python(text)):
        if _callee(call) != "setup":
            continue
        for keyword in call.keywords:
            if keyword.arg == "entry_points" and isinstance(keyword.value, ast.Dict):
                found.update(_console_scripts(keyword.value))
    return found


def _console_scripts(table: ast.Dict) -> dict[str, str]:
    found: dict[str, str] = {}
    for key, value in zip(table.keys, table.values, strict=True):
        if _str_constant(key) != "console_scripts" or not isinstance(value, ast.List | ast.Tuple):
            continue
        for item in value.elts:
            found.update(_console_script(_str_constant(item) or ""))
    return found


def _cfg_entry_points(text: str) -> dict[str, str]:
    """`[options.entry_points]`'s `console_scripts` lines of a `setup.cfg`."""
    if not text:
        return {}
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(text)
        scripts = parser.get("options.entry_points", "console_scripts", fallback="")
    except (configparser.Error, ValueError, RecursionError):
        return {}
    found: dict[str, str] = {}
    for line in scripts.splitlines():
        found.update(_console_script(line))
    return found


def _console_script(spec: str) -> dict[str, str]:
    """`"talker = talker_py.talker:main"` → `{"talker": "talker_py.talker"}`; else `{}`."""
    executable, sep, target = spec.partition("=")
    module = target.strip().partition(":")[0].strip()
    if not sep or not executable.strip() or re.fullmatch(_MODULE_NAME, module) is None:
        return {}
    return {executable.strip(): module}


# ---------------------------------------------------------------------------- launch files


def _launch_nodes(index: Mapping[str, _RosPackage]) -> Iterator[_RosLaunch]:
    """Every node any package's launch files start, in package and then path order."""
    for name in sorted(index):
        files = index[name].files
        for path in sorted(files):
            yield from _launches(path, files[path])


def _launches(path: str, text: str) -> list[_RosLaunch]:
    pure = PurePosixPath(path)
    lowered = pure.name.lower()
    if lowered.endswith(".launch.py"):
        return _py_launches(path, text)
    if lowered.endswith(".launch.xml"):
        return _xml_launches(path, text)
    if lowered.endswith((".yaml", ".yml")) and pure.parent.name == "launch":
        return _yaml_launches(path, text)
    return []


def _py_launches(path: str, text: str) -> list[_RosLaunch]:
    """Each literal `Node(...)` call inside `generate_launch_description`."""
    tree = _parse_python(text)
    functions = [
        node
        for node in (tree.body if tree is not None else [])
        if isinstance(node, ast.FunctionDef) and node.name == LAUNCH_FUNCTION
    ]
    launches = (
        _py_launch(path, call)
        for function in functions
        for call in _calls(function)
        if _callee(call) == "Node"
    )
    return [launch for launch in launches if launch is not None]


def _py_launch(path: str, call: ast.Call) -> _RosLaunch | None:
    args = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
    package = _str_constant(args.get("package"))
    executable = _str_constant(args.get("executable") or args.get("node_executable"))
    if package is None or executable is None:
        return None
    return _RosLaunch(
        package,
        executable,
        _str_constant(args.get("name") or args.get("node_name")),
        _str_constant(args.get("namespace") or args.get("node_namespace")) or "",
        _py_remaps(args.get("remappings")),
        f"{path}:{call.lineno}",
    )


def _py_remaps(node: ast.expr | None) -> tuple[tuple[str, str], ...]:
    """`remappings=[("from", "to"), …]`, literal pairs only."""
    if not isinstance(node, ast.List | ast.Tuple):
        return ()
    pairs: list[tuple[str, str]] = []
    for item in node.elts:
        if isinstance(item, ast.Tuple) and len(item.elts) == 2:
            source, target = (_str_constant(element) for element in item.elts)
            if source and target:
                pairs.append((source, target))
    return tuple(pairs)


def _xml_launches(path: str, text: str) -> list[_RosLaunch]:
    """Each `<node pkg exec name namespace>` and its `<remap from to>`. The parser keeps no line
    numbers, so each node's line is the next one holding `<node` (ponytail: a `<node` inside a
    comment shifts the ones after it; the evidence ref is a pointer, not a fact)."""
    root = _xml_element(text)
    if root is None or root.tag != "launch":
        return []
    lines, cursor, found = text.splitlines(), 0, []
    for node in root.iter("node"):
        line = _line_containing(lines, "<node", cursor)
        cursor = line or cursor
        package, executable = node.get("pkg"), node.get("exec")
        if not package or not executable:
            continue
        found.append(
            _RosLaunch(
                package,
                executable,
                node.get("name"),
                node.get("namespace") or "",
                _xml_remaps(node),
                f"{path}:{line or 1}",
            )
        )
    return found


def _xml_remaps(node: Element) -> tuple[tuple[str, str], ...]:
    pairs = ((remap.get("from") or "", remap.get("to") or "") for remap in node.iter("remap"))
    return tuple((source, target) for source, target in pairs if source and target)


def _yaml_launches(path: str, text: str) -> list[_RosLaunch]:
    """`launch: [{node: {pkg, exec, name, namespace, remap: [{from, to}]}}]`."""
    data = _safe_yaml(text)
    entries = data.get("launch") if isinstance(data, dict) else None
    lines, cursor, found = text.splitlines(), 0, []
    for entry in entries if isinstance(entries, list) else []:
        node = entry.get("node") if isinstance(entry, dict) else None
        if not isinstance(node, dict):
            continue
        line = _line_containing(lines, "node:", cursor)
        cursor = line or cursor
        launch = _yaml_launch(node, f"{path}:{line or 1}")
        if launch is not None:
            found.append(launch)
    return found


def _yaml_launch(node: dict[object, object], ref: str) -> _RosLaunch | None:
    package, executable, name = (node.get(key) for key in ("pkg", "exec", "name"))
    namespace = node.get("namespace")
    if not isinstance(package, str) or not isinstance(executable, str):
        return None
    remaps = node.get("remap")
    pairs = [
        (item.get("from"), item.get("to"))
        for item in (remaps if isinstance(remaps, list) else [])
        if isinstance(item, dict)
    ]
    return _RosLaunch(
        package,
        executable,
        name if isinstance(name, str) else None,
        namespace if isinstance(namespace, str) else "",
        tuple((s, t) for s, t in pairs if isinstance(s, str) and isinstance(t, str) and s and t),
        ref,
    )


# --------------------------------------------------------------------------- node modules


def _node_module(
    index: Mapping[str, _RosPackage], launch: _RosLaunch, cache: dict[str, _RosModule]
) -> tuple[str, _RosModule]:
    """The launched executable's module (path, what it declares), read once a parse."""
    package = index.get(launch.package)
    path = package.executables.get(launch.executable) if package is not None else None
    if package is None or path is None:
        return "", _NO_MODULE
    if path not in cache:
        cache[path] = _read_module(package.files[path])
    return path, cache[path]


def _read_module(text: str) -> _RosModule:
    """The node name a module gives itself and the topics its calls declare."""
    tree = _parse_python(text)
    if tree is None:
        return _NO_MODULE
    types = _message_types(tree)
    name: str | None = None
    declared: list[_Declared] = []
    for call in _calls(tree):
        callee = _callee(call)
        if name is None and _names_node(call, callee):
            name = _str_constant(call.args[0] if call.args else _keyword(call, "node_name"))
        elif callee is not None and callee in TOPIC_CALLS:
            item = _topic_call(call, TOPIC_CALLS[callee], types)
            if item is not None:
                declared.append(item)
    return _RosModule(name, tuple(declared))


def _names_node(call: ast.Call, callee: str | None) -> bool:
    """`super().__init__("talker")` in a node class, or `create_node("talker")`."""
    if callee == "create_node":
        return True
    func = call.func
    return (
        callee == "__init__"
        and isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Call)
        and _callee(func.value) == "super"
    )


def _topic_call(call: ast.Call, direction: Direction, types: Mapping[str, str]) -> _Declared | None:
    """`create_publisher(<Type>, "<topic>", …)`: the topic as written, and its type when the
    module's imports name it."""
    message = call.args[0] if call.args else _keyword(call, "msg_type")
    written = call.args[1] if len(call.args) > 1 else _keyword(call, "topic")
    topic = _str_constant(written)
    if topic is None:
        return None
    kind = types.get(message.id) if isinstance(message, ast.Name) else None
    return _Declared(direction, topic, kind, call.lineno)


def _message_types(tree: ast.Module) -> dict[str, str]:
    """`from <package>.msg import <Type> [as <alias>]` → alias → `<package>/msg/<Type>`."""
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
            continue
        package, _, tail = node.module.partition(".")
        for alias in node.names if tail == "msg" else []:
            kind = f"{package}/msg/{alias.name}"
            if re.fullmatch(_MESSAGE_TYPE, kind):
                found[alias.asname or alias.name] = kind
    return found


# ------------------------------------------------------------------------------ the names


def _absolute(name: str, namespace: str) -> str:
    """`name` made absolute in `namespace` (`chatter` in `/robot` is `/robot/chatter`), with no
    empty segment."""
    full = name if name.startswith("/") else f"/{namespace.strip('/')}/{name}"
    return "/" + "/".join(part for part in full.split("/") if part)


def _topic_name(written: str, launch: _RosLaunch, node: str) -> str | None:
    """A declared topic as ROS resolves it: the launch file's remap (matched as written or as
    resolved), then the node's namespace; `~/x` is the node's own."""
    private = written.startswith("~/")
    resolved = f"{node}/{written[2:]}" if private else _absolute(written, launch.namespace)
    for source, target in launch.remaps:
        if source == written or _absolute(source, launch.namespace) == resolved:
            resolved = _absolute(target, launch.namespace)
            break
    return _ros_valid(resolved)


def _ros_valid(name: str) -> str | None:
    """`name` when Solus keeps it: the grammar, the length, and no ingress mask."""
    if len(name) > MAX_NAME_CHARS or MASK in name or re.fullmatch(ROS_NAME, name) is None:
        return None
    return name


# ------------------------------------------------------------------------------- parsing


def _parse_python(text: str) -> ast.Module | None:
    """The text's syntax tree, read and never run; None when it does not read."""
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None


def _xml_element(text: str) -> Element | None:
    try:
        root = _xml_root(text)
    except Exception:  # a hostile or broken text yields nothing, never a crash
        return None
    return root if isinstance(root, Element) else None


def _safe_yaml(text: str, loader: type[yaml.SafeLoader] = yaml.SafeLoader) -> object:
    """A text within MAX_YAML_BYTES that holds no anchor and no alias (so no reference ever
    expands), read by `loader`, a `yaml.SafeLoader` (`yaml.safe_load` by default); None for
    anything else."""
    if len(text.encode("utf-8")) > MAX_YAML_BYTES:
        return None
    try:
        for event in yaml.parse(text, Loader=yaml.SafeLoader):
            if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None) is not None:
                return None
        return loader(text).get_single_data()  # what `yaml.safe_load` does, with `loader`
    except Exception:  # a hostile or broken text yields nothing, never a crash
        return None


def _calls(tree: ast.AST | None) -> Iterator[ast.Call]:
    if tree is None:
        return iter(())
    return (node for node in ast.walk(tree) if isinstance(node, ast.Call))


def _callee(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else None


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


def _str_constant(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None
