"""Error and detail codes — mcp-fork-runtime.md §5/§6. The ONLY vocabulary
that crosses the CLI boundary; every message attached to a code is fixed
Solus-authored text, never subprocess output."""

from typing import Literal, get_args

ErrorCode = Literal[
    "python_not_found",
    "python_unsupported_version",
    "python_not_cpython",
    "python_store_alias",
    "python_probe_failed",
    "python_is_venv",
    "managed_not_installed",
    "venv_failed",
    "venv_copies_unhealthy",
    "pip_failed",
    "network_unreachable",
    "hash_mismatch",
    "wheel_unavailable",
    "managed_download_failed",
    "managed_hash_mismatch",
    "managed_too_large",
    "managed_extract_refused",
    "not_owner_only",
    "disk_full",
    "timeout",
    "cancelled",
    "internal",
]
ERROR_CODES: frozenset[str] = frozenset(get_args(ErrorCode))

DetailCode = Literal[
    "needs_setup:no_env",
    "needs_setup:not_owner_only",
    "needs_setup:stamp_mismatch",
    "needs_setup:base_missing",
]

MESSAGES: dict[ErrorCode, str] = {
    "python_not_found": "No CPython 3.12 or 3.13 was found on this machine.",
    "python_unsupported_version": "This Python version is not supported; use CPython 3.12 or 3.13.",
    "python_not_cpython": "This interpreter is not CPython; use CPython 3.12 or 3.13.",
    "python_store_alias": "Microsoft Store Python is not supported; install it from python.org.",
    "python_probe_failed": "This Python could not be started.",
    "python_is_venv": (
        "This Python is a virtual environment; choose the Python it was created from."
    ),
    "managed_not_installed": "The Solus-managed Python is not installed yet.",
    "venv_failed": "Could not create the Python environment.",
    "venv_copies_unhealthy": (
        "The copied interpreter could not start. This Python build cannot be copied; "
        "use the Solus-managed Python."
    ),
    "pip_failed": "Installing the tool's packages failed.",
    "network_unreachable": "Could not reach pypi.org.",
    "hash_mismatch": "A downloaded package did not match its pinned hash.",
    "wheel_unavailable": "A pinned package has no build for this Python version.",
    "managed_download_failed": "Could not download the Solus-managed Python.",
    "managed_hash_mismatch": "The Solus-managed Python could not be verified.",
    "managed_too_large": "The Solus-managed Python download was larger than expected.",
    "managed_extract_refused": "The Solus-managed Python archive was refused.",
    "not_owner_only": "The tool environment folder is not private to this user.",
    "disk_full": "The disk is full.",
    "timeout": "The step took too long and was stopped.",
    "cancelled": "Setup was cancelled.",
    "internal": "Something went wrong.",
}


class RuntimeSetupError(Exception):
    """A failure with a protocol error code. `message` defaults to the fixed
    text for the code; callers never pass raw subprocess output here."""

    def __init__(self, code: ErrorCode, message: str | None = None) -> None:
        super().__init__(code)
        self.code: ErrorCode = code
        self.message = message or MESSAGES[code]


class Cancelled(BaseException):  # noqa: N818 — a control-flow signal, like KeyboardInterrupt
    """Raised from the SIGINT/SIGTERM/SIGBREAK handler. A BaseException so no
    `except Exception` on the way up can swallow it; every `finally` still runs."""
