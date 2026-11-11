"""Per-family wrapping of a Solus model before it is spawned.

gz / ignition: the URDF is converted with the family's ``<exe> sdf -p <file>`` (argv, scrubbed
env, a private temporary copy that is removed afterwards) and the ``<model>`` gains the
joint-state-publisher system plus one joint-position-controller system per joint, listening on
``/model/<name>/joint/<j>/0/cmd_pos`` — the topics :meth:`GzAdapter.set_targets` publishes to.
Classic: the URDF passes through untouched (``gz model -f`` accepts URDF and joint control is
built into classic physics).

The XML is Solus-generated or confined-store content but is still treated as untrusted: a
DOCTYPE or ENTITY declaration is refused before the stdlib parser sees a byte, and the parsed
tree is walked (input and converter output alike) for anything the simulator would load code or
files through — ``<plugin>``, ``<include>``, ``<gazebo>``, ``<transmission>``, ``<script>``,
``<extension>``, XML namespaces, URI schemes, absolute or ``..`` paths. Only ``<mesh><uri>`` with
a relative, confined path survives. Solus adds its own systems after the walk.
"""

from __future__ import annotations

import os
import re
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from .adapters.adapter_base import CliError, CliRunner, check_name, run_argv, stderr_detail
from .family_detect import Family

MAX_MODEL_BYTES: Final = 4 * 1024 * 1024
_DECLARATION = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_ROOT_TAG = re.compile(rb"<\s*(robot|sdf)[\s>]")
_BANNED_TAGS: Final = frozenset(
    {"plugin", "include", "gazebo", "transmission", "script", "extension"}
)
_URI_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:/")
_DOTDOT = re.compile(r"(^|/)\.\.(/|$)")
_SYSTEMS: Final[dict[str, tuple[str, str]]] = {
    "gz": ("gz-sim", "gz::sim::systems"),
    "ignition": ("ignition-gazebo", "ignition::gazebo::systems"),
}
# ponytail: one PID set for every generated joint; per-joint gains when a model needs them.
DEFAULT_GAINS: Final = (1.0, 0.1, 0.01)


def wrap_model(
    urdf_or_sdf: bytes,
    family: Family,
    joints: Sequence[str],
    name: str,
    *,
    run: CliRunner = run_argv,
    gains: tuple[float, float, float] = DEFAULT_GAINS,
) -> bytes:
    check_name(name)
    wanted = [check_name(j) for j in joints]
    source = _parse_guarded(urdf_or_sdf)
    if family.name == "classic":
        return urdf_or_sdf
    if source.tag == "sdf":
        root = source
    elif source.tag == "robot":
        root = _parse_guarded(_urdf_to_sdf(urdf_or_sdf, family, run))
    else:
        raise ValueError("model must be a URDF <robot> or an SDF <sdf> document")
    model = root.find("model")
    if root.tag != "sdf" or model is None:
        raise ValueError("SDF must carry one <model>")
    present = {j.get("name") for j in model.findall("joint")}
    missing = [j for j in wanted if j not in present]
    if missing:
        raise ValueError(f"joints not in the model: {', '.join(missing)}")
    model.set("name", name)
    _add_systems(model, family, wanted, name, gains)
    return ET.tostring(root, encoding="unicode").encode()


def _parse_guarded(data: bytes) -> ET.Element:
    """Size cap, declaration refusal, well-formedness and the element walk, in that order."""
    if len(data) > MAX_MODEL_BYTES:
        raise ValueError("model file too large")
    if _DECLARATION.search(data):
        raise ValueError("model files may not declare a DOCTYPE or entities")
    if _ROOT_TAG.search(data) is None:
        raise ValueError("model must be a URDF <robot> or an SDF <sdf> document")
    try:
        root = ET.fromstring(data)  # noqa: S314 — declarations refused above, bounded size
    except ET.ParseError as error:
        raise ValueError("model XML is not well-formed") from error
    _refuse_loaders(root)
    return root


def _refuse_loaders(root: ET.Element) -> None:
    """Refuse every element, attribute or value through which the simulator loads code or files."""
    for element in root.iter():
        tag = element.tag
        if tag.startswith("{") or any(key.startswith("{") for key in element.attrib):
            raise ValueError("model XML may not use namespaces")
        if tag in _BANNED_TAGS:
            raise ValueError(f"model files may not carry <{tag}> elements")
        for value in (*element.attrib.values(), element.text or ""):
            _check_value(value.strip())
    for parent in root.iter():
        for child in parent:
            if child.tag == "uri" and parent.tag != "mesh":
                raise ValueError("<uri> is only accepted inside <mesh>")


def _check_value(value: str) -> None:
    if _URI_SCHEME.search(value):
        raise ValueError("model files may not reference URIs")
    if value.startswith("/") or _DOTDOT.search(value):
        raise ValueError("model paths must be relative to the model directory")


def _add_systems(
    model: ET.Element,
    family: Family,
    joints: Sequence[str],
    name: str,
    gains: tuple[float, float, float],
) -> None:
    prefix, namespace = _SYSTEMS[family.name]
    ET.SubElement(
        model,
        "plugin",
        filename=f"{prefix}-joint-state-publisher-system",
        name=f"{namespace}::JointStatePublisher",
    )
    for joint in joints:
        plugin = ET.SubElement(
            model,
            "plugin",
            filename=f"{prefix}-joint-position-controller-system",
            name=f"{namespace}::JointPositionController",
        )
        ET.SubElement(plugin, "joint_name").text = joint
        ET.SubElement(plugin, "topic").text = f"/model/{name}/joint/{joint}/0/cmd_pos"
        for tag, gain in zip(("p_gain", "i_gain", "d_gain"), gains, strict=True):
            ET.SubElement(plugin, tag).text = repr(float(gain))


def _urdf_to_sdf(urdf: bytes, family: Family, run: CliRunner) -> bytes:
    """``<exe> sdf -p`` over a private temporary copy; the copy never outlives the call."""
    directory = tempfile.mkdtemp(prefix="solus-sdf-")
    path = Path(directory) / "model.urdf"
    argv = [str(family.exe), "sdf", "-p", str(path)]
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(urdf)
        done = run(argv, 30.0)
    finally:
        path.unlink(missing_ok=True)
        os.rmdir(directory)
    if done.returncode != 0 or not done.stdout.lstrip().startswith("<sdf"):
        detail = stderr_detail(done.stderr, "no SDF produced")
        raise CliError(argv, f"URDF conversion failed: {detail}")
    return done.stdout.encode()
