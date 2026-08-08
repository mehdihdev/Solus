"""The trimming registrar: only allowlisted tools ever reach the real server.

Upstream's `register_*_tools(mcp)` functions register every tool in their
module. This shim sits between them and the real FastMCP instance so that:

* a tool NOT in the allowed set is never registered anywhere — dead
  in-process, not merely hidden from listings (the decorator hands the
  original function back so upstream internals that call a sibling tool
  keep working);
* an allowed tool is registered through a hardened wrapper that (a) strips
  any `ctx` parameter from the advertised surface and pins it to None on the
  call (today's altium roster tools take no ctx — the strip is kept so a
  re-vendor that adds one can never surface it as a model-suppliable input),
  (b) force-pins the `PINNED_PARAMETERS` values — overwriting anything a
  caller smuggles — and removes those parameters from the advertised
  signature/schema, (c) refuses, BEFORE the tool body ever runs, any string
  argument whose name is path-shaped that does not resolve inside the
  workspace (`solus/confinement.py`, the ONE place this check lives for
  every roster tool), (d) applies the data-driven `WRITE_GUARDS` (ALT-7) to
  the confirmation-gated write tools — parameter names shape-checked against
  the IPC wire-format metacharacters, values and stamp batches size-bounded —
  and the data-driven `NUMERIC_BOUNDS` (H4) to the limit-bearing reads —
  refusing BEFORE the tool body ever runs, (e) redirects `print()`
  chatter in upstream tool bodies to stderr, off the MCP stdio protocol
  channel (the stdio transport holds the real stdout stream captured at
  startup, so this swap never touches protocol writes), and (f) strips
  upstream's model-directed result decorations (`STRIPPED_RESULT_KEYS` and
  dunder-shaped keys — the datasheet-guidance / bulk-hint instruction
  channel) from every result before it leaves the wrapper.

Tested by tests/test_overlay_tool_trimming.py and tests/test_overlay_support.py.
"""

import inspect
import re
import sys
import threading
from collections.abc import Callable, Mapping
from typing import Any, Protocol, TypeVar

from .confinement import confinement_refusal

F = TypeVar("F", bound=Callable[..., Any])

#: A write guard inspects ONE argument value and returns a human-readable
#: fault string (refuse before the tool body runs) or None (pass).
WriteGuard = Callable[[Any], "str | None"]

REASON_WRITE_GUARD_REFUSED = "write_guard_refused"

#: ALT-7 write-guard bounds. The IPC wire format for the write tools uses
#: `key=value` pairs joined by `;` and stamps joined by `~~`; the NAME shape
#: check excludes all of those metacharacters (and every control character)
#: outright, while VALUES — which upstream escapes via its shared
#: `payload_safe` sanitiser — are only size-bounded here.
PARAMETER_VALUE_MAX_BYTES = 4096
PARAMETER_NAME_MAX_CHARS = 64
PARAMETER_NAME_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_. \-]*\Z")
STAMPS_MAX_COUNT = 500
#: M2 — the count/per-value bounds above leave two payload dimensions
#: unbounded: how many keys a single stamp may carry, and the batch's TOTAL
#: encoded size (500 stamps * 4 KiB values * many keys each is a multi-MiB
#: IPC frame). Cap both so no single write can flood the file-drop bridge.
STAMP_MAX_KEYS = 32
STAMPS_TOTAL_MAX_BYTES = 1024 * 1024


def _parameter_name_fault(value: Any) -> str | None:
    if not isinstance(value, str):
        return "parameter name must be a string"
    if len(value) > PARAMETER_NAME_MAX_CHARS:
        return f"parameter name exceeds {PARAMETER_NAME_MAX_CHARS} characters"
    if not PARAMETER_NAME_PATTERN.fullmatch(value):
        return "parameter name fails the shape check"
    return None


def _parameter_value_fault(value: Any) -> str | None:
    if not isinstance(value, str):
        return "parameter value must be a string"
    if len(value.encode("utf-8")) > PARAMETER_VALUE_MAX_BYTES:
        return f"parameter value exceeds {PARAMETER_VALUE_MAX_BYTES} bytes"
    return None


def _stamps_fault(value: Any) -> str | None:
    if not isinstance(value, list):
        return "stamps must be a list"
    if len(value) > STAMPS_MAX_COUNT:
        return f"stamps count exceeds {STAMPS_MAX_COUNT}"
    total_bytes = 0
    for stamp in value:
        if not isinstance(stamp, dict):
            return "each stamp must be an object of parameter name/value pairs"
        if len(stamp) > STAMP_MAX_KEYS:
            return f"stamp exceeds {STAMP_MAX_KEYS} keys"
        for name, item in stamp.items():
            fault = _parameter_name_fault(name)
            if fault is not None:
                return fault
            fault = _parameter_value_fault(item)
            if fault is not None:
                return fault
            total_bytes += len(name.encode("utf-8")) + len(item.encode("utf-8"))
            if total_bytes > STAMPS_TOTAL_MAX_BYTES:
                return f"stamp batch exceeds {STAMPS_TOTAL_MAX_BYTES} total bytes"
    return None


#: Per-tool, per-argument write guards the hardened wrapper applies BEFORE
#: the tool body (after pinning and path confinement). Data, not code: a new
#: write tool gets a new entry here, never a new wrapper branch. The cloud
#: keeps these tools requires_confirmation: true (allowlist.yaml); this is
#: the fork-side depth behind that gate.
WRITE_GUARDS: Mapping[str, Mapping[str, WriteGuard]] = {
    "proj_set_parameter": {
        "name": _parameter_name_fault,
        "value": _parameter_value_fault,
    },
    "sch_set_components_parameters": {"stamps": _stamps_fault},
}


def _write_guard_refusal(
    guards: Mapping[str, WriteGuard], kwargs: Mapping[str, Any]
) -> dict[str, Any] | None:
    """The structured refusal envelope when any guarded argument faults, else
    None. Only arguments actually supplied are guarded — required arguments
    a caller omits fail schema binding anyway."""
    for parameter, guard in guards.items():
        if parameter not in kwargs:
            continue
        fault = guard(kwargs[parameter])
        if fault is not None:
            return {"error": fault, "reason": REASON_WRITE_GUARD_REFUSED}
    return None


#: H3 result sanitation — upstream decorates component-touching read results
#: with model-directed imperative keys: `tools/datasheet_hints.tag_response`
#: attaches `_datasheet_guidance` (whose value carries `__DATASHEET_FIRST__`
#: and `action_required` MANDATORY-worded text built partly from the
#: schematic's own Manufacturer/MPN/Comment field values — attacker
#: influencable) plus `_datasheet_parts`, and `tools/bulk_hints` attaches
#: `_hint_bulk`. Instructions must never ride the DATA channel into the SOL
#: agent's context, so these keys — and ANY dunder-shaped `__…__` key — are
#: stripped from every tool result before it leaves the wrapper. Data, not
#: code: a new upstream decoration gets a new entry here, never a new wrapper
#: branch. Stripping reaches ONE nesting level (dict values and list-of-dict
#: rows): tag_response only attaches at the top level today; the extra level
#: covers per-part nesting on a re-vendor. Field VALUES are untouched —
#: hostile text stays exactly where the schematic put it, as leaf data.
#: DELIBERATELY NOT stripped (Phase 4 finding L3, accepted residual): the
#: "reason"/"error" keys — upstream's eda.py puts raw exception text there,
#: but the same keys carry Solus's own degraded/refusal envelopes
#: (path_escapes_workspace, write_guard_refused, numeric_bound_refused,
#: netlist_export REASON_* constants); stripping or rewriting them would
#: clobber legitimate results. Recorded in SECURITY_REVIEW.md residuals.
STRIPPED_RESULT_KEYS: frozenset[str] = frozenset(
    {"_datasheet_guidance", "_datasheet_parts", "_hint_bulk"}
)


def _is_instruction_key(key: Any) -> bool:
    return isinstance(key, str) and (
        key in STRIPPED_RESULT_KEYS or (key.startswith("__") and key.endswith("__"))
    )


def _clean_mapping(mapping: Mapping[Any, Any]) -> dict[Any, Any]:
    return {key: value for key, value in mapping.items() if not _is_instruction_key(key)}


def _clean_value(value: Any) -> Any:
    """One nesting level below the top: strip instruction keys from a dict
    value or the dict rows of a list value; everything else passes through."""
    if isinstance(value, dict):
        return _clean_mapping(value)
    if isinstance(value, list):
        return [_clean_mapping(item) if isinstance(item, dict) else item for item in value]
    return value


def sanitize_result(result: Any) -> Any:
    """A NEW result object with upstream's instruction-channel keys stripped
    (top level plus one nesting level); non-container results pass through
    untouched — a plain string is data, not a key."""
    if isinstance(result, dict):
        return {
            key: _clean_value(value)
            for key, value in result.items()
            if not _is_instruction_key(key)
        }
    if isinstance(result, list):
        return [_clean_mapping(item) if isinstance(item, dict) else item for item in result]
    return result


#: Per-tool parameters the hardened wrapper pins to a fixed value and REMOVES
#: from the advertised signature/schema. Data, not code: future pins are new
#: entries here, never new wrapper branches. Current pins:
#:
#: * proj_get_nets.force_recompile — upstream's True path SAVES ALL DIRTY
#:   DOCUMENTS before recompiling (Project.pas ForceRecompileIfRequested): a
#:   disk write hidden behind a read-only allowlist entry. Pinned False; the
#:   tool body then never forwards the flag to the IPC bridge at all.
#:
#: * list_nets.backend — upstream's `resolve_backend(backend)` constructs
#:   whichever backend class the ARGUMENT names (tools/eda.py), so a model
#:   argument could switch the call onto the KiCad backend. Pinned to the
#:   one backend this overlay serves (H2).
#: * proj_get_component_info.timeout — forwarded verbatim to the bridge's
#:   `send_command_async(..., timeout=...)`, whose commands all serialize
#:   through a single ThreadPoolExecutor(max_workers=1): a model-chosen
#:   timeout wedges the one bridge worker for every caller. Pinned None so
#:   the bridge's own default poll timeout always applies (H4).
PINNED_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "proj_get_nets": {"force_recompile": False},
    "list_nets": {"backend": "altium"},
    "proj_get_component_info": {"timeout": None},
}

REASON_NUMERIC_BOUND_REFUSED = "numeric_bound_refused"

#: H4 numeric bounds — per-tool, per-argument ceilings on numeric arguments
#: the tool body forwards UNBOUNDED to the single bridge worker. `limit` on
#: proj_get_nets / proj_get_bom is forwarded straight to the IPC query (a
#: caller-supplied 10**12 passes through today), so a runaway value floods
#: the one worker and the response. The ceilings mirror the ones upstream's
#: own netlist exporter already uses (netlist_export.py: 100_000 nets,
#: 20_000 BOM rows). Refusal, not clamp, for auditability — a smuggled
#: over-cap value is a stable, logged refusal rather than a silently altered
#: request. Data, not code: a new bounded argument is a new entry here.
NUMERIC_BOUNDS: Mapping[str, Mapping[str, int]] = {
    "proj_get_nets": {"limit": 100_000},
    "proj_get_bom": {"limit": 20_000},
}


def _numeric_bound_refusal(
    bounds: Mapping[str, int], kwargs: Mapping[str, Any]
) -> dict[str, Any] | None:
    """The structured refusal envelope when any bounded argument exceeds its
    ceiling (or is not a real integer), else None. Only supplied arguments
    are checked; `bool` is rejected outright (it is an int subclass but never
    a valid limit)."""
    for parameter, ceiling in bounds.items():
        if parameter not in kwargs:
            continue
        value = kwargs[parameter]
        if isinstance(value, bool) or not isinstance(value, int):
            return {
                "error": f"{parameter} must be an integer",
                "reason": REASON_NUMERIC_BOUND_REFUSED,
            }
        if value > ceiling:
            return {
                "error": f"{parameter} exceeds the maximum of {ceiling}",
                "reason": REASON_NUMERIC_BOUND_REFUSED,
            }
    return None


# A process-wide, reference-counted stdout diversion. A naive per-call
# `contextlib.redirect_stdout(sys.stderr)` held open across an `await` is
# concurrency-unsafe: if two overlapping async tool calls each enter it and
# the OUTER one's `__exit__` runs (restoring the pre-diversion stdout) while
# an INNER one is still executing, the inner call's remaining prints leak
# onto the real MCP stdio channel — a naive save/restore pair is not safe
# under out-of-order completion. Every diversion redirects to the SAME
# target (stderr), so a depth counter is sufficient: the real stdout is
# captured only on the 0→1 transition and restored only on the 1→0
# transition, regardless of enter/exit interleaving order.
_stdout_lock = threading.Lock()
_stdout_divert_depth = 0
_stdout_before_diversion: Any = None


def _begin_stdout_diversion() -> None:
    global _stdout_divert_depth, _stdout_before_diversion
    with _stdout_lock:
        if _stdout_divert_depth == 0:
            _stdout_before_diversion = sys.stdout
            sys.stdout = sys.stderr
        _stdout_divert_depth += 1


def _end_stdout_diversion() -> None:
    global _stdout_divert_depth
    with _stdout_lock:
        _stdout_divert_depth -= 1
        if _stdout_divert_depth == 0:
            sys.stdout = _stdout_before_diversion


class SupportsToolDecorator(Protocol):
    """The one surface upstream register functions touch on FastMCP."""

    def tool(
        self, *args: Any, **kwargs: Any
    ) -> Callable[[Callable[..., Any]], Any]: ...  # pragma: no cover


def _copy_metadata(
    wrapper: Callable[..., Any], fn: Callable[..., Any], excluded: frozenset[str]
) -> None:
    """Copy schema-bearing metadata minus the *excluded* parameters (ctx +
    pinned). Deliberately NOT functools.wraps: `__wrapped__` would let
    signature introspection tunnel back to the original function and resurface
    the stripped parameters. Annotations are EVALUATED (`eval_str=True`) in
    the tool's own module: some upstream modules use `from __future__ import
    annotations`, and string annotations would make the MCP SDK's schema
    builder resolve names against THIS module's globals and crash."""
    wrapper.__name__ = fn.__name__
    wrapper.__qualname__ = fn.__qualname__
    wrapper.__doc__ = fn.__doc__
    signature = inspect.signature(fn, eval_str=True)
    parameters = [param for name, param in signature.parameters.items() if name not in excluded]
    annotations = {
        name: param.annotation
        for name, param in signature.parameters.items()
        if name not in excluded and param.annotation is not inspect.Parameter.empty
    }
    if signature.return_annotation is not inspect.Signature.empty:
        annotations["return"] = signature.return_annotation
    wrapper.__annotations__ = annotations
    wrapper_any: Any = wrapper
    wrapper_any.__signature__ = signature.replace(parameters=parameters)


_NO_GUARDS: Mapping[str, WriteGuard] = {}
_NO_BOUNDS: Mapping[str, int] = {}


def _harden(
    fn: Callable[..., Any],
    pinned: Mapping[str, Any],
    guards: Mapping[str, WriteGuard] = _NO_GUARDS,
    bounds: Mapping[str, int] = _NO_BOUNDS,
) -> Callable[..., Any]:
    """The wrapper actually registered: pinned parameters forced (a smuggled
    value is overwritten, never honoured), path arguments confined, write
    guards and numeric bounds applied, ctx pinned to None, stdout diverted,
    result decorations stripped."""
    has_ctx = "ctx" in inspect.signature(fn).parameters
    pins = dict(pinned)
    guard_map = dict(guards)
    bound_map = dict(bounds)

    def _refuse(hardened: Mapping[str, Any]) -> dict[str, Any] | None:
        return (
            confinement_refusal(hardened)
            or _write_guard_refusal(guard_map, hardened)
            or _numeric_bound_refusal(bound_map, hardened)
        )

    if inspect.iscoroutinefunction(fn):

        async def async_wrapper(**kwargs: Any) -> Any:
            hardened = {**kwargs, **pins}
            refusal = _refuse(hardened)
            if refusal is not None:
                return refusal
            if has_ctx:
                hardened["ctx"] = None
            _begin_stdout_diversion()
            try:
                return sanitize_result(await fn(**hardened))
            finally:
                _end_stdout_diversion()

        wrapper: Callable[..., Any] = async_wrapper
    else:

        def sync_wrapper(**kwargs: Any) -> Any:
            hardened = {**kwargs, **pins}
            refusal = _refuse(hardened)
            if refusal is not None:
                return refusal
            if has_ctx:
                hardened["ctx"] = None
            _begin_stdout_diversion()
            try:
                return sanitize_result(fn(**hardened))
            finally:
                _end_stdout_diversion()

        wrapper = sync_wrapper

    _copy_metadata(wrapper, fn, excluded=frozenset({"ctx", *pins}))
    return wrapper


class TrimmingRegistrar:
    """Duck-typed FastMCP stand-in handed to upstream register functions.

    Deliberately implements ONLY `.tool()`: if a re-vendor makes one of the
    invoked upstream register functions register a resource or prompt, the
    registration crashes loudly (AttributeError) instead of silently widening
    the served surface.
    """

    def __init__(
        self,
        backing: SupportsToolDecorator,
        allowed: frozenset[str],
        pinned: Mapping[str, Mapping[str, Any]] = PINNED_PARAMETERS,
        guards: Mapping[str, Mapping[str, WriteGuard]] = WRITE_GUARDS,
        bounds: Mapping[str, Mapping[str, int]] = NUMERIC_BOUNDS,
    ) -> None:
        self._backing = backing
        self._allowed = allowed
        self._pinned = {name: dict(values) for name, values in pinned.items()}
        self._guards = {name: dict(values) for name, values in guards.items()}
        self._bounds = {name: dict(values) for name, values in bounds.items()}
        self._registered: list[str] = []
        self._blocked: list[str] = []

    @property
    def registered(self) -> tuple[str, ...]:
        return tuple(self._registered)

    @property
    def blocked(self) -> tuple[str, ...]:
        return tuple(self._blocked)

    def tool(self, *args: Any, **kwargs: Any) -> Callable[[F], F]:
        name_override = kwargs.get("name")

        def decorator(fn: F) -> F:
            name = name_override if isinstance(name_override, str) else fn.__name__
            if name not in self._allowed:
                self._blocked.append(name)
                return fn  # never registered anywhere — dead in-process
            self._registered.append(name)
            hardened = _harden(
                fn,
                self._pinned.get(name, {}),
                self._guards.get(name, {}),
                self._bounds.get(name, {}),
            )
            self._backing.tool(*args, **kwargs)(hardened)
            return fn

        return decorator
