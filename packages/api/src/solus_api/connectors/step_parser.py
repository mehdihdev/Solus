"""STEP → CAD IR via OpenCASCADE's XDE/XCAF layer (SOLUS-CAD-00).

`docs/contracts/metadata-extraction.md` §6.1 is unambiguous about how this must
be done, and about the trap:

    Assembly structure comes from OpenCASCADE's XDE/XCAF layer
    (`STEPCAFControl_Reader` → OCAF document → walk `XCAFDoc_ShapeTool` labels
    for the tree, names, colors, `TopLoc_Location` transforms). A naive
    `STEPControl_Reader` **flattens the model and discards the assembly
    hierarchy/part names**.

So we read through XCAF and walk the label tree, never `STEPControl_Reader`.

**OCCT is an OPTIONAL dependency.** The wheel is ~60 MB and its bundled OCCT
kernel is LGPL-2.1-with-exception (the binding itself is Apache-2.0) — a
licensing call W0-08 §6.6 explicitly reserves to a human, and one that was not
yet signed off when this landed. So the import is lazy and its absence is a
clean `ConnectorError`, never an `ImportError` escaping into a request. Install
with the `cad` extra. Everything else in the mechanical family works without it.

**Identity.** `CadNode.key` is the OCCURRENCE PATH — the chain of product names
from the root, with an ordinal suffix when one product is instanced more than
once under the same parent (`Bracket/PegPair/Peg[0]`). It is derived purely from
the file's content, satisfying MCP-04 §2.1 invariant 2, so a byte-identical
export acquired by any route yields identical keys.

`ponytail:` names+ordinal is the strongest content-derived key STEP affords —
the label entries OCCT assigns are allocation-ordered and shift between exports.
If a tool later exposes stable instance UUIDs, key on those instead.
"""

from __future__ import annotations

import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.mechanical import MAX_CAD_EXPORT_BYTES, CadModel, CadNode

#: Guard against a pathological or hand-crafted file nesting far deeper than any
#: real assembly (and against a cyclic reference the reader failed to reject).
MAX_ASSEMBLY_DEPTH = 32

#: Guard against the ASSEMBLY-EXPANSION BOMB, which the depth cap alone does not
#: stop. STEP shares products by reference, and we walk one OCCURRENCE per
#: component instance — so total visits are the PRODUCT of the branching factors
#: along each path, not the number of products in the file. A ~50 KB file nesting
#: 3 components 32 deep implies 3^32 occurrences: it passes the byte cap by six
#: orders of magnitude and would exhaust the worker. A visited-label memo cannot
#: fix this (distinct occurrences are legitimately distinct entities); only a hard
#: cap on emitted occurrences can.
MAX_ASSEMBLY_NODES = 100_000

#: Unnamed products are legal in AP203 (§6.1 warns names are often absent there).
UNNAMED = "Unnamed"


def step_reader_available() -> bool:
    """Whether the optional OCCT stack can be imported in this environment."""
    try:
        import OCP.STEPCAFControl  # noqa: F401
    except ImportError:
        return False
    return True


def _require_occt() -> tuple[Any, ...]:
    """Import the OCCT symbols we need, or fail with a configuration error."""
    try:
        from OCP.IFSelect import IFSelect_ReturnStatus
        from OCP.STEPCAFControl import STEPCAFControl_Reader
        from OCP.TCollection import TCollection_ExtendedString
        from OCP.TDataStd import TDataStd_Name
        from OCP.TDF import TDF_Label, TDF_LabelSequence
        from OCP.TDocStd import TDocStd_Document
        from OCP.XCAFApp import XCAFApp_Application
        from OCP.XCAFDoc import XCAFDoc_DocumentTool
    except ImportError as exc:
        raise ConnectorError(
            "step_reader_unavailable",
            "STEP parsing needs the optional OCCT stack — install the 'cad' extra "
            "(cadquery-ocp-novtk) on the API image",
        ) from exc
    return (
        IFSelect_ReturnStatus,
        STEPCAFControl_Reader,
        TCollection_ExtendedString,
        TDataStd_Name,
        TDF_Label,
        TDF_LabelSequence,
        TDocStd_Document,
        XCAFApp_Application,
        XCAFDoc_DocumentTool,
    )


def _label_name(label: Any, name_attr_cls: Any) -> str:
    attr = name_attr_cls()
    if label.FindAttribute(name_attr_cls.GetID_s(), attr):
        text = str(attr.Get().ToExtString()).strip()
        if text:
            return text
    return UNNAMED


#: Characters an occurrence key gives structural meaning to: '/' joins path
#: segments and '[i]' marks a repeated instance. A product NAME containing any of
#: them could otherwise forge a key that collides with a generated one — e.g. a
#: sibling literally named `Peg[0]` alongside a `Peg` instanced twice. Stripping
#: them makes the two alphabets disjoint, so `_ordinal_keys` is collision-free by
#: construction. (Same class of guard as the fingerprint normalizer's separator
#: fix.) Names that collide only AFTER stripping are handled by the ordinal pass
#: below, because counting runs on the stripped names.
_RESERVED_IN_SEGMENT = str.maketrans({"/": "_", "[": "_", "]": "_"})


def _safe_path_segment(name: str) -> str:
    """Neutralise the characters occurrence keys use structurally."""
    return name.translate(_RESERVED_IN_SEGMENT)


def _ordinal_keys(prefix: str, names: list[str]) -> list[str]:
    """Child keys for one parent: bare name when unique among its siblings, and
    `name[i]` when the same product is instanced more than once. Deterministic
    for a given file because OCCT enumerates components in stored order.

    `names` MUST already be `_safe_path_segment`-ed: counting on the sanitised
    name is what makes two names that sanitise alike collide into the ordinal
    branch instead of producing one duplicated key.
    """
    counts: dict[str, int] = defaultdict(int)
    for name in names:
        counts[name] += 1
    used: dict[str, int] = defaultdict(int)
    keys: list[str] = []
    for name in names:
        if counts[name] > 1:
            keys.append(f"{prefix}{name}[{used[name]}]")
            used[name] += 1
        else:
            keys.append(f"{prefix}{name}")
    return keys


class _Budget:
    """Bounds one traversal: total occurrences emitted, and whether either guard
    fired. Truncation notes are FLAGS, not per-branch appends — a wide-at-depth
    file would otherwise grow `warnings` without bound, re-creating in the error
    list the amplification the node cap exists to prevent."""

    def __init__(self, limit: int = MAX_ASSEMBLY_NODES) -> None:
        self._remaining = limit
        self._limit = limit
        self.hit_node_cap = False
        self.hit_depth_cap = False

    def take(self) -> bool:
        """Claim one occurrence slot. False means the traversal must stop."""
        if self._remaining <= 0:
            self.hit_node_cap = True
            return False
        self._remaining -= 1
        return True

    def note_depth(self) -> None:
        self.hit_depth_cap = True

    def warnings(self) -> list[str]:
        notes: list[str] = []
        if self.hit_depth_cap:
            notes.append(f"assembly nesting deeper than {MAX_ASSEMBLY_DEPTH} was truncated")
        if self.hit_node_cap:
            notes.append(
                f"assembly exceeded {self._limit} occurrences and was truncated; "
                "the graph holds a partial tree"
            )
        return notes


def _transfer_document(path: Path, occt: tuple[Any, ...]) -> tuple[Any, Any]:
    """Read the STEP file into an XCAF document; return `(document, shape_tool)`.

    The document MUST be returned and held by the caller: the shape tool is a
    handle into it, and letting the document fall out of scope frees the labels
    underneath — the tree then reads back empty.
    """
    (return_status, reader_cls, ext_string, _n, _l, _ls, document_cls, app_cls, doc_tool_cls) = occt
    app = app_cls.GetApplication_s()
    doc = document_cls(ext_string("MDTV-XCAF"))
    app.InitDocument(doc)

    reader = reader_cls()
    reader.SetNameMode(True)
    try:
        status = reader.ReadFile(str(path))
        transferred = status == return_status.IFSelect_RetDone and reader.Transfer(doc)
    except Exception as exc:  # OCCT raises bare Standard_Failure subclasses
        raise ConnectorError("step_unreadable", "the STEP export could not be read") from exc
    if not transferred:
        raise ConnectorError(
            "step_unreadable", "the content is not a STEP file OpenCASCADE can transfer"
        )
    return doc, doc_tool_cls.ShapeTool_s(doc.Main())


def parse_step(text: str) -> CadModel:
    """Parse STEP text into the shared CAD IR, preserving the assembly tree.

    Raises `ConnectorError('step_reader_unavailable')` when the optional OCCT
    extra is absent, and `ConnectorError('step_unreadable')` when the content is
    not a STEP file OCCT can transfer — never a raw OCCT or IO exception, so
    `CadExportConnector.detect_changes` keeps its fail-safe narrow catch.
    """
    occt = _require_occt()
    (
        _return_status,
        _reader_cls,
        _ext_string,
        name_attr_cls,
        label_cls,
        label_seq_cls,
        _document_cls,
        _app_cls,
        _doc_tool_cls,
    ) = occt

    # The size guard lives HERE, not only in `CadExportConnector._read_export`:
    # that method is the documented per-tool override point ("override
    # `_read_export` and nothing else"), so a future connector that forgets to
    # re-apply the bound would hand unbounded text straight to the parser. This
    # is the one place every acquisition path funnels through.
    if len(text.encode("utf-8", "surrogatepass")) > MAX_CAD_EXPORT_BYTES:
        raise ConnectorError(
            "export_too_large",
            f"export exceeds the {MAX_CAD_EXPORT_BYTES // (1024 * 1024)} MiB parse limit",
        )

    nodes: list[CadNode] = []
    budget = _Budget()

    # OCCT reads from a path, not a buffer. The file is ours: a generated name
    # inside a private temp dir, removed on the way out — no user-influenced
    # path ever reaches the reader (CLAUDE.md §7).
    with tempfile.TemporaryDirectory(prefix="solus-step-") as tmpdir:
        path = Path(tmpdir) / "export.step"
        path.write_text(text, encoding="utf-8", errors="surrogatepass")
        # `_document` is never read, but the binding MUST survive the whole walk:
        # `shape_tool` is a handle into that document, and letting it be collected
        # frees the labels underneath so the tree reads back empty.
        _document, shape_tool = _transfer_document(path, occt)

        def walk(
            label: Any,
            parent_key: str | None,
            key: str,
            placement: tuple[float, float, float] | None,
            depth: int,
        ) -> None:
            if not budget.take():
                return
            nodes.append(
                CadNode(
                    key=key,
                    name=_label_name(label, name_attr_cls),
                    is_assembly=bool(shape_tool.IsAssembly_s(label)),
                    parent_key=parent_key,
                    placement=placement,
                )
            )
            if depth >= MAX_ASSEMBLY_DEPTH:
                budget.note_depth()
                return

            components = label_seq_cls()
            shape_tool.GetComponents_s(label, components)

            resolved: list[tuple[Any, str, tuple[float, float, float]]] = []
            for index in range(1, components.Length() + 1):
                component = components.Value(index)
                referred = label_cls()
                if not shape_tool.GetReferredShape_s(component, referred):
                    continue
                translation = shape_tool.GetLocation_s(component).Transformation().TranslationPart()
                resolved.append(
                    (
                        referred,
                        _safe_path_segment(_label_name(referred, name_attr_cls)),
                        (translation.X(), translation.Y(), translation.Z()),
                    )
                )

            child_keys = _ordinal_keys(f"{key}/", [name for _, name, _ in resolved])
            for (referred, _, child_placement), child_key in zip(resolved, child_keys, strict=True):
                walk(referred, key, child_key, child_placement, depth + 1)

        roots = label_seq_cls()
        shape_tool.GetFreeShapes(roots)
        if roots.Length() == 0:
            raise ConnectorError("step_unreadable", "the STEP export contains no shapes")

        root_labels = [roots.Value(i) for i in range(1, roots.Length() + 1)]
        root_keys = _ordinal_keys(
            "", [_safe_path_segment(_label_name(lbl, name_attr_cls)) for lbl in root_labels]
        )
        for root_label, root_key in zip(root_labels, root_keys, strict=True):
            walk(root_label, None, root_key, None, 0)

    return CadModel(nodes=tuple(nodes), warnings=tuple(budget.warnings()))
