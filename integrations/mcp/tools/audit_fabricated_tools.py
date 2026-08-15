#!/usr/bin/env python3
"""Fabricated-data audit for a fork target — the vendoring gate, made mechanical.

`integrations/mcp/LICENCE_VERIFICATION.md` requires, before any MIT fork is
vendored: "Every tool that returns plausible-looking data without actually
talking to the CAD application is stripped before vendoring." That check was
prose. This is the check.

WHAT IT LOOKS FOR. Two shapes, both of which make an MCP tool report success for
work that never happened:

  A. **No adapter reference at all.** The function never touches the CAD
     application by any path, yet returns `status: success` with values that
     read like measurements.

  B. **Capability-probe fallback.** The idiom

         if hasattr(adapter, "check_interference"):
             result = await adapter.check_interference(...)
             ...
         return {"status": "success", "interference_found": False}   # <-- nothing ran

     When the live adapter lacks the capability, the caller is told the check
     passed. For Solus this is the worst possible failure: the graph cannot
     distinguish "no interference" from "never checked", and neither can SOL.

Delegating wrappers (`return await other_tool(...)`) and honest text generators
(`generate_vba_*`, which emit VBA source for a human to run and never claim the
CAD application did anything) are classified separately, not counted as lies.

The output is evidence, not a verdict: every hit prints the returned expression
so a human can read it and decide. Run it against a clone at the exact commit
being considered, and paste the result into that fork's PROVENANCE.md.

    python3 integrations/mcp/tools/audit_fabricated_tools.py <path-to-clone>
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: The names a tool may reach the CAD application through. A function touching
#: none of these did not talk to CAD, whatever its docstring claims.
#:
#: This list is per-target and MUST be checked against the tree being audited
#: before the result means anything — a target whose handle is missing here
#: reports a vacuous zero. `adapter.` is SolidworksMCP-python's seam;
#: `_backend(` is Autocad-MCP's.
CAD_HANDLES = (
    "adapter.",
    "_backend(",
    "Dispatch(",
    "win32com",
    "self.app.",
    "self.doc.",
)

TOOL_DECORATOR = re.compile(r"\btool\b")


@dataclass
class Finding:
    tool: str
    file: str
    line: int
    kind: str
    evidence: str


@dataclass
class Report:
    total: int = 0
    delegating: list[str] = field(default_factory=list)
    generators: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


def _is_tool(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(TOOL_DECORATOR.search(ast.unparse(d)) for d in node.decorator_list)


def _touches_cad(node: ast.AST) -> bool:
    return any(h in ast.unparse(node) for h in CAD_HANDLES)


def _is_success_return(stmt: ast.AST) -> bool:
    if not isinstance(stmt, ast.Return) or stmt.value is None:
        return False
    rendered = ast.unparse(stmt.value).replace("'", '"')
    return '"status": "success"' in rendered


def _is_capability_probe(stmt: ast.If) -> bool:
    """`if hasattr(adapter, "...")` — the probe whose else-path is the problem."""
    test = ast.unparse(stmt.test)
    return test.startswith("hasattr(") and "adapter" in test


def _delegates(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """`return await other_tool(...)` — a wrapper, judged by what it calls."""
    return any(
        isinstance(s, ast.Return)
        and isinstance(s.value, ast.Await)
        and isinstance(s.value.value, ast.Call)
        for s in fn.body
    )


def _scan_probe_fallbacks(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Return]:
    """Success returns reached only when a capability probe FAILED.

    Walks each statement list; once a `hasattr(adapter, ...)` probe is seen,
    later siblings are on the not-supported path — unless one of them touches
    CAD itself (the `if/else: result = await adapter.other(...)` shape, which is
    a genuine second attempt, not a fabrication).
    """
    hits: list[ast.Return] = []

    def walk(body: list[ast.stmt]) -> None:
        after_probe = False
        for stmt in body:
            if isinstance(stmt, ast.If) and _is_capability_probe(stmt):
                after_probe = True
                walk(stmt.body)
                walk(stmt.orelse)
                continue
            if after_probe and _touches_cad(stmt):
                after_probe = False  # a real second attempt; not a fallback lie
            if isinstance(stmt, ast.Return) and after_probe and _is_success_return(stmt):
                # A payload built from `result` came from an adapter call that
                # did run — some tools re-probe only to pick a response shape.
                if stmt.value is not None and "result." not in ast.unparse(stmt.value):
                    hits.append(stmt)
                continue
            for attr in ("body", "orelse", "finalbody"):
                sub = getattr(stmt, attr, None)
                if sub:
                    walk(sub)
            for handler in getattr(stmt, "handlers", []):
                walk(handler.body)

    walk(fn.body)
    return hits


def _classify(node: ast.FunctionDef | ast.AsyncFunctionDef, rel: str, report: Report) -> None:
    report.total += 1
    if _delegates(node) and not _touches_cad(node):
        report.delegating.append(node.name)
        return
    if node.name.startswith("generate_"):
        report.generators.append(node.name)
        return
    if not _touches_cad(node):
        first = next(
            (s for s in ast.walk(node) if isinstance(s, ast.Return) and _is_success_return(s)),
            None,
        )
        if first is not None:
            report.findings.append(
                Finding(node.name, rel, first.lineno, "never-touches-cad", _evidence(first))
            )
        return
    for stmt in _scan_probe_fallbacks(node):
        report.findings.append(
            Finding(node.name, rel, stmt.lineno, "probe-fallback", _evidence(stmt))
        )


def _evidence(stmt: ast.Return) -> str:
    assert stmt.value is not None  # every caller filtered on _is_success_return
    return ast.unparse(stmt.value)[:300]


def audit(root: Path) -> Report:
    report = Report()
    for path in sorted(root.rglob("*.py")):
        rel = str(path.relative_to(root))
        if "/tests/" in f"/{rel}" or path.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and _is_tool(node):
                _classify(node, rel, report)
    return report


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    root = Path(argv[1])
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    report = audit(root)
    lying = {f.tool for f in report.findings}
    print(f"# Fabricated-data audit — {root}")
    print(f"# {report.total} MCP tools examined\n")
    print(f"delegating wrappers (judged by their target): {len(report.delegating)}")
    print(f"text generators (emit source, claim nothing): {len(report.generators)}")
    print(f"TOOLS THAT CAN REPORT SUCCESS FOR WORK THAT NEVER HAPPENED: {len(lying)}\n")
    for kind in ("never-touches-cad", "probe-fallback"):
        group = [f for f in report.findings if f.kind == kind]
        print(f"\n## {kind} ({len(group)})")
        for f in sorted(group, key=lambda f: (f.file, f.line)):
            print(f"\n  {f.tool}  ({f.file}:{f.line})")
            print(f"    {f.evidence}")
    return 1 if lying else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
