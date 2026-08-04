"""The stable refusal-reason vocabulary for `set_symbol_property` (T2b).

Every refusal path in this package raises `RefusalError` with one of these
exact strings — callers (and Cowork/QA) can match on them verbatim. The set
is closed: `RefusalError` rejects any other string at construction time so a
typo can never silently mint a new, undocumented reason.
"""

REASON_REFERENCE_NOT_FOUND = "reference_not_found"
REASON_PROPERTY_NOT_FOUND = "property_not_found"
REASON_AMBIGUOUS_TARGET = "ambiguous_target"
REASON_PATH_ESCAPES_WORKSPACE = "path_escapes_workspace"
REASON_FILE_TOO_LARGE = "file_too_large"
REASON_UNSUPPORTED_VALUE = "unsupported_value"
REASON_GUARD_FAILED = "guard_failed"

STABLE_REASONS: frozenset[str] = frozenset(
    {
        REASON_REFERENCE_NOT_FOUND,
        REASON_PROPERTY_NOT_FOUND,
        REASON_AMBIGUOUS_TARGET,
        REASON_PATH_ESCAPES_WORKSPACE,
        REASON_FILE_TOO_LARGE,
        REASON_UNSUPPORTED_VALUE,
        REASON_GUARD_FAILED,
    }
)


class RefusalError(Exception):
    """Raised whenever `set_symbol_property` must refuse rather than write.

    The original file is guaranteed untouched at the point this is raised —
    every refusal path in this package is checked before any disk write.
    """

    def __init__(self, reason: str) -> None:
        if reason not in STABLE_REASONS:
            raise ValueError(f"not a stable refusal reason: {reason!r}")
        super().__init__(reason)
        self.reason = reason
