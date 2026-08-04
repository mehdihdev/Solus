"""The trimming registrar: only allowlisted tools ever reach the real server.

Upstream's `register_*_tools(mcp)` functions register every tool in their
module. This shim sits between them and the real FastMCP instance so that:

* a tool NOT in the allowed set is never registered anywhere — dead
  in-process, not merely hidden from listings (the decorator hands the
  original function back so upstream internals that call a sibling tool
  keep working);
* an allowed tool is registered through a hardened wrapper that (a) strips
  the `ctx` parameter — upstream annotates the MCP SDK's Context against a
  fastmcp 2.x server, so `ctx` would otherwise surface as a model-suppliable
  input; the tools already handle `ctx=None` (upstream PR #33) — (b) refuses,
  BEFORE the tool body ever runs, any string argument whose name is
  path-shaped that does not resolve inside the workspace (H2 —
  `solus/confinement.py`, the ONE place this check lives for every roster
  tool) — and (c) redirects `print()` chatter in upstream tool bodies to
  stderr, off the MCP stdio protocol channel (the stdio transport holds the
  real stdout stream captured at startup, so this swap never touches
  protocol writes).

Tested by tests/test_overlay_tool_trimming.py.
"""

import inspect
import sys
import threading
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from solus.confinement import confinement_refusal

F = TypeVar("F", bound=Callable[..., Any])

# L1: a process-wide, reference-counted stdout diversion. A naive per-call
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


def _copy_metadata(wrapper: Callable[..., Any], fn: Callable[..., Any]) -> None:
    """Copy schema-bearing metadata minus `ctx`. Deliberately NOT
    functools.wraps: `__wrapped__` would let signature introspection tunnel
    back to the original (ctx-bearing) function."""
    wrapper.__name__ = fn.__name__
    wrapper.__qualname__ = fn.__qualname__
    wrapper.__doc__ = fn.__doc__
    wrapper.__annotations__ = {
        key: value for key, value in getattr(fn, "__annotations__", {}).items() if key != "ctx"
    }
    signature = inspect.signature(fn)
    parameters = [param for name, param in signature.parameters.items() if name != "ctx"]
    wrapper_any: Any = wrapper
    wrapper_any.__signature__ = signature.replace(parameters=parameters)


def _harden(fn: Callable[..., Any]) -> Callable[..., Any]:
    """The wrapper actually registered: path arguments confined (H2), ctx
    pinned to None, stdout diverted."""
    has_ctx = "ctx" in inspect.signature(fn).parameters

    if inspect.iscoroutinefunction(fn):

        async def async_wrapper(**kwargs: Any) -> Any:
            refusal = confinement_refusal(kwargs)
            if refusal is not None:
                return refusal
            if has_ctx:
                kwargs["ctx"] = None
            _begin_stdout_diversion()
            try:
                return await fn(**kwargs)
            finally:
                _end_stdout_diversion()

        wrapper: Callable[..., Any] = async_wrapper
    else:

        def sync_wrapper(**kwargs: Any) -> Any:
            refusal = confinement_refusal(kwargs)
            if refusal is not None:
                return refusal
            if has_ctx:
                kwargs["ctx"] = None
            _begin_stdout_diversion()
            try:
                return fn(**kwargs)
            finally:
                _end_stdout_diversion()

        wrapper = sync_wrapper

    _copy_metadata(wrapper, fn)
    return wrapper


class TrimmingRegistrar:
    """Duck-typed FastMCP stand-in handed to upstream register functions."""

    def __init__(self, backing: SupportsToolDecorator, allowed: frozenset[str]) -> None:
        self._backing = backing
        self._allowed = allowed
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
            self._backing.tool(*args, **kwargs)(_harden(fn))
            return fn

        return decorator
