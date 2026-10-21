"""Environment profiles for `code.exec` / `code.process_start`
(docs/api/code-command-execution.md §2.4).

A profile is the environment a setup file (ROS `setup.bash`, a workspace
`install/setup.bash`) produces. It is captured by a FIXED Solus script — the setup
file is `$1`, never interpolated — diffed against the base environment, filtered
of secret-shaped and loader-injection names, and stored machine-private under
`~/.solus/code-profiles/<workspace key>/<name>.json` (atomic, 0600 / 0700).
Values never leave this machine: answers carry variable NAMES only. A corrupt or
tampered file refuses; it never raises.
"""

import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .safe_read import read_regular
from .workspace import is_safe_relative, resolve_inside

SCHEMA_VERSION = 1
CAPTURE_SCRIPT = 'source "$1" >/dev/null 2>&1 </dev/null || exit 97; exec /usr/bin/env -0'
CAPTURE_SHELL = "/bin/bash"
CAPTURE_TIMEOUT_SECONDS = 30
SOURCE_FAILED_EXIT = 97
ROS_ROOT = "/opt/ros/"
MAX_SETUP_BYTES = 256 * 1024
MAX_ENV_BYTES = 256 * 1024
MAX_VARIABLES = 256
MAX_VALUE_CHARS = 8192
MAX_PROFILE_BYTES = 4 * 1024 * 1024
MAX_LISTED = 64
MAX_PATH_CHARS = 512
SETUP_SUFFIXES = (".bash", ".sh")

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_VARIABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SECRET = re.compile(r"TOKEN|SECRET|PASSW|KEY|CREDENTIAL|AUTH|COOKIE|SESSION|PRIVATE", re.I)
SECRET_PREFIXES: tuple[str, ...] = (
    "AWS_",
    "GITHUB_",
    "GH_",
    "GITLAB_",
    "NPM_",
    "HF_",
    "OPENAI_",
    "ANTHROPIC_",
)
SECRET_NAMES: frozenset[str] = frozenset({"SSH_AUTH_SOCK"})
#: THE loader / option-injection list (§2.4, §9.8): never stored in a profile and never
#: passed to any child, whatever a profile says. Search paths (PYTHONPATH,
#: LD_LIBRARY_PATH) are kept: a ROS profile needs them.
LOADER_NAMES: frozenset[str] = frozenset(
    {
        "LD_PRELOAD",
        "LD_AUDIT",
        "DYLD_INSERT_LIBRARIES",
        "GCONV_PATH",
        "BASH_ENV",
        "ENV",
        "PROMPT_COMMAND",
        "PYTHONSTARTUP",
        "PYTHONINSPECT",  # drops any python into a REPL after its script
        "PERL5DB",  # replaces the perl debugger with arbitrary code
        "NODE_OPTIONS",
        "PERL5OPT",
        "RUBYOPT",
        "JAVA_TOOL_OPTIONS",
        "_JAVA_OPTIONS",
    }
)
#: Never taken from a profile: Solus sets these for every child.
SOLUS_CONTROLLED: frozenset[str] = frozenset({"HOME", "TMPDIR", "VIRTUAL_ENV"})
#: Bash's own bookkeeping, not something the setup file configured.
SHELL_BOOKKEEPING: frozenset[str] = frozenset({"_", "SHLVL", "PWD", "OLDPWD"})


@dataclass(frozen=True)
class Refusal:
    reason: str


@dataclass(frozen=True)
class Profile:
    name: str
    setup_file: str
    extends: str | None
    captured_at: str
    variables: tuple[tuple[str, str], ...]
    digest: str

    def listing(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "setup_file": self.setup_file,
            "extends": self.extends,
            "captured_at": self.captured_at,
            "variables": sorted(name for name, _ in self.variables),
        }


class CaptureOutcome(Protocol):
    @property
    def exit_code(self) -> int | None: ...

    @property
    def stdout(self) -> bytes: ...

    @property
    def timed_out(self) -> bool: ...


def name_error(name: object) -> str | None:
    if isinstance(name, str) and _NAME.match(name):
        return None
    return "profile name must match ^[a-z0-9][a-z0-9_-]{0,31}$"


def workspace_key(root: Path) -> str:
    return hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:16]


def _home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def store_dir(root: Path) -> Path:
    return _home() / ".solus" / "code-profiles" / workspace_key(root)


def capture_argv(setup_file: str) -> list[str]:
    return [
        CAPTURE_SHELL,
        "--noprofile",
        "--norc",
        "-c",
        CAPTURE_SCRIPT,
        "solus-profile",
        setup_file,
    ]


def allowed_variable(name: str) -> bool:
    """A storable profile variable name (the spec's filters)."""
    return bool(
        _VARIABLE.match(name)
        and not _SECRET.search(name)
        and not name.upper().startswith(SECRET_PREFIXES)
        and name not in SECRET_NAMES
        and name not in LOADER_NAMES
        and name not in SOLUS_CONTROLLED
        and name not in SHELL_BOOKKEEPING
    )


def parse_env0(data: bytes) -> dict[str, str] | None:
    result: dict[str, str] = {}
    for entry in data.split(b"\0"):
        if not entry:
            continue
        name, separator, value = entry.decode("utf-8", errors="replace").partition("=")
        if not separator or not name:
            return None
        result[name] = value
    return result


def filter_capture(
    captured: Mapping[str, str], base: Mapping[str, str]
) -> tuple[dict[str, str], list[str]]:
    """New or changed variables that pass the filters, and the names dropped."""
    kept: dict[str, str] = {}
    dropped: list[str] = []
    for name, value in captured.items():
        if base.get(name) == value:
            continue
        if allowed_variable(name) and len(value) <= MAX_VALUE_CHARS:
            kept[name] = value
        else:
            dropped.append(name[:128])
    return kept, sorted(dropped)


def apply(
    base: Mapping[str, str], variables: Sequence[tuple[str, str]], venv_bin: str | None
) -> dict[str, str]:
    """The child environment: `base` overlaid with the profile, Solus names kept."""
    env = dict(base)
    profile = {name: value for name, value in variables if name not in SOLUS_CONTROLLED}
    env.update(profile)
    if venv_bin and "PATH" in profile:
        env["PATH"] = f"{venv_bin}{os.pathsep}{profile['PATH']}"
    return env


def resolve_setup_file(root: Path, value: object) -> str | Refusal:
    """The realpath of an acceptable setup file, or why it is refused."""
    if not isinstance(value, str) or not value or len(value) > MAX_PATH_CHARS:
        return Refusal("setup_file must be a path string")
    if any(char in value for char in ("\0", "\n", "\r")):
        return Refusal("setup_file may not contain NUL or newline characters")
    if os.path.isabs(value):
        real = os.path.realpath(value)
        if not real.startswith(ROS_ROOT):
            return Refusal(f"an absolute setup_file must resolve under {ROS_ROOT}")
    else:
        inside = resolve_inside(value, root) if is_safe_relative(value) else None
        if inside is None:
            return Refusal("setup_file not found inside the linked folder")
        real = str(inside)
    try:
        info = os.stat(real)
    except OSError:
        return Refusal("setup_file not found")
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SETUP_BYTES:
        return Refusal("setup_file must be a regular file of at most 256 KiB")
    if not real.endswith(SETUP_SUFFIXES):
        return Refusal("setup_file must end in .bash or .sh")
    return real


def _private_dir(path: Path) -> None:
    if not path.exists():
        path.mkdir(mode=0o700)
    os.chmod(path, 0o700)


def _profile_path(root: Path, name: str) -> Path:
    return store_dir(root) / f"{name}.json"


def save(
    root: Path,
    name: str,
    setup_file: str,
    extends: str | None,
    variables: Mapping[str, str],
) -> Profile:
    """Write atomically (temp + rename), file 0600, directories 0700."""
    directory = store_dir(root)
    solus = directory.parent.parent
    if not solus.exists():
        solus.mkdir(mode=0o700)
    _private_dir(directory.parent)
    _private_dir(directory)
    record = {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "setup_file": setup_file,
        "extends": extends,
        "captured_at": datetime.now(UTC).isoformat(),
        "vars": dict(variables),
    }
    data = json.dumps(record, sort_keys=True).encode()
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, directory / f"{name}.json")
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return _profile(record, hashlib.sha256(data).hexdigest())


def _profile(record: dict[str, Any], digest: str) -> Profile:
    return Profile(
        name=record["name"],
        setup_file=record["setup_file"],
        extends=record["extends"],
        captured_at=record["captured_at"],
        variables=tuple(sorted(record["vars"].items())),
        digest=digest,
    )


def _valid_record(record: object, name: str) -> bool:
    if not isinstance(record, dict) or record.get("schema_version") != SCHEMA_VERSION:
        return False
    variables = record.get("vars")
    return (
        record.get("name") == name
        and isinstance(record.get("setup_file"), str)
        and (record.get("extends") is None or name_error(record.get("extends")) is None)
        and isinstance(record.get("captured_at"), str)
        and isinstance(variables, dict)
        and len(variables) <= MAX_VARIABLES
        and all(
            isinstance(key, str)
            and allowed_variable(key)
            and isinstance(value, str)
            and len(value) <= MAX_VALUE_CHARS
            for key, value in variables.items()
        )
    )


def _read(path: Path) -> bytes:
    data = read_regular(path, MAX_PROFILE_BYTES + 1)
    if data is None:
        raise OSError("not a regular file")
    return data


def load(root: Path, name: object) -> Profile | str:
    """The stored profile, or a refusal reason (never raises)."""
    if name_error(name) is not None:
        return f"invalid profile name: {str(name)[:64]}"
    assert isinstance(name, str)
    path = _profile_path(root, name)
    if not path.exists() and not path.is_symlink():
        return f"no profile named {name} (capture it first)"
    try:
        data = _read(path)
        record = json.loads(data)
    except (OSError, ValueError):
        return f"profile {name} is unreadable"
    if len(data) > MAX_PROFILE_BYTES or not _valid_record(record, name):
        return f"profile {name} is unreadable"
    return _profile(record, hashlib.sha256(data).hexdigest())


def list_profiles(root: Path) -> list[dict[str, Any]]:
    """Every readable profile's listing (names only; unreadable files are skipped)."""
    directory = store_dir(root)
    try:
        names = sorted(path.stem for path in directory.glob("*.json"))
    except OSError:
        return []
    listed: list[dict[str, Any]] = []
    for name in names[:MAX_LISTED]:
        profile = load(root, name)
        if isinstance(profile, Profile):
            listed.append(profile.listing())
    return listed


def delete(root: Path, name: object) -> dict[str, Any]:
    if name_error(name) is not None:
        return {"ok": False, "name": str(name)[:64], "reason": "invalid profile name"}
    assert isinstance(name, str)
    try:
        _profile_path(root, name).unlink()
    except FileNotFoundError:
        return {"ok": False, "name": name, "reason": f"no profile named {name}"}
    except OSError:
        return {"ok": False, "name": name, "reason": f"profile {name} could not be deleted"}
    return {"ok": True, "name": name, "reason": None}


def capture_refusal(name: str, reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "name": name,
        "variables": [],
        "dropped": [],
        "path_entries": 0,
        "reason": reason,
    }


def _outcome_error(outcome: CaptureOutcome) -> str | None:
    if outcome.timed_out:
        return f"capture timed out after {CAPTURE_TIMEOUT_SECONDS} s"
    if outcome.exit_code == SOURCE_FAILED_EXIT:
        return f"setup file could not be sourced (exit {SOURCE_FAILED_EXIT})"
    if outcome.exit_code != 0:
        return f"capture failed (exit {outcome.exit_code})"
    if len(outcome.stdout) > MAX_ENV_BYTES:
        return "environment output too large (> 256 KiB)"
    return None


def finish_capture(
    root: Path,
    name: str,
    setup_file: str,
    extends: str | None,
    outcome: CaptureOutcome,
    base: Mapping[str, str],
) -> dict[str, Any]:
    """Turn the capture's `env -0` output into a stored profile; names only in the answer."""
    error = _outcome_error(outcome)
    if error is not None:
        return capture_refusal(name, error)
    captured = parse_env0(outcome.stdout)
    if captured is None:
        return capture_refusal(name, "unparseable environment output")
    kept, dropped = filter_capture(captured, base)
    if len(kept) > MAX_VARIABLES:
        return capture_refusal(name, f"the profile has more than {MAX_VARIABLES} variables")
    try:
        save(root, name, setup_file, extends, kept)
    except OSError as exc:
        return capture_refusal(name, f"profile could not be stored: {type(exc).__name__}")
    path = kept.get("PATH", "")
    return {
        "ok": True,
        "name": name,
        "variables": sorted(kept),
        "dropped": dropped,
        "path_entries": len([entry for entry in path.split(os.pathsep) if entry]),
        "reason": None,
    }
