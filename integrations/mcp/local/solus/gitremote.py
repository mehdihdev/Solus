"""Bounded, never-raising reader of a folder's `.git` identity.

Answers `{remote_url, branch, head}` or None — `head` is the SHORT (12-hex)
commit id: the cloud's ingress redaction masks 40+ char entropic strings, so
a full sha would never arrive. `remote_url` never carries userinfo: a
`https://user:token@host/…` or `oauth2:glpat@host:…` origin is stripped to
the host form before it crosses the bridge (`strip_userinfo`).

Confinement: a `.git` that is a directory is read in place; a `gitdir:`
pointer (worktree form) or a `commondir` redirect may only lead INSIDE the
folder or UNDER the user's home directory (real worktrees live there) —
anything else answers None. Handles the directory form and
the worktree `gitdir:` file form (config/refs live in the COMMON dir named by
`commondir`; HEAD in the worktree dir). Every read is size-bounded; nothing
here shells out to git.
"""

import configparser
import re
from pathlib import Path
from typing import TypedDict

MAX_CONFIG_BYTES = 64 * 1024
MAX_POINTER_BYTES = 4 * 1024
MAX_REF_BYTES = 4 * 1024
MAX_PACKED_REFS_BYTES = 1024 * 1024
MAX_URL_CHARS = 2048
#: `head` is reported in git's short form.
SHORT_SHA_LEN = 12
#: SCP-style userinfo is stripped except the conventional literal git user.
_SCP_STYLE_RE = re.compile(r"^([^@/:]*(?::[^@/]*)?)@([^/:]+:.*)$")

_SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_HEAD_REF_RE = re.compile(r"^ref:\s*(refs/heads/\S+)\s*$")


class GitInfo(TypedDict):
    remote_url: str
    branch: str | None
    head: str | None


def _read_bounded(path: Path, limit: int) -> bytes | None:
    """The file's bytes, or None when missing/unreadable/over `limit`."""
    try:
        if any(part.is_symlink() for part in (path, *path.parents)):
            return None
        if not path.is_file() or path.stat().st_size > limit:
            return None
        with path.open("rb") as handle:
            return handle.read(limit + 1)
    except OSError:
        return None


def _read_text(path: Path, limit: int) -> str | None:
    data = _read_bounded(path, limit)
    if data is None or len(data) > limit:
        return None
    return data.decode("utf-8", errors="replace")


def _git_dirs(root: Path, home: Path | None) -> tuple[Path, Path] | None:
    """`(gitdir, commondir)` for the folder, or None when there is no usable
    `.git` (directory or `gitdir:` pointer file) or a pointer/redirect leads
    outside both the folder and `home`."""
    dot_git = root / ".git"
    if dot_git.is_symlink():
        return None
    if dot_git.is_dir():
        gitdir = dot_git
    else:
        pointer = _read_text(dot_git, MAX_POINTER_BYTES)
        if pointer is None or not pointer.startswith("gitdir:"):
            return None
        target = pointer.split(":", 1)[1].strip()
        if not target:
            return None
        gitdir = (dot_git.parent / target).resolve()
    if not _inside_root_or_home(gitdir, root, home) or not (gitdir / "HEAD").is_file():
        return None
    common_pointer = _read_text(gitdir / "commondir", MAX_POINTER_BYTES)
    commondir = (gitdir / common_pointer.strip()).resolve() if common_pointer else gitdir
    if not _inside_root_or_home(commondir, root, home):
        return None
    return gitdir, commondir


def strip_userinfo(url: str) -> str:
    """The origin URL without credentials. `scheme://` URLs drop everything
    between `://` and the `@` of the authority (only the authority — an `@`
    in the path is untouched); scp-style URLs drop the userinfo only when it
    is anything other than the conventional literal `git` user."""
    if "://" in url:
        scheme, _, rest = url.partition("://")
        authority, slash, path = rest.partition("/")
        if "@" in authority:
            authority = authority.rsplit("@", 1)[1]
        return f"{scheme}://{authority}{slash}{path}"
    match = _SCP_STYLE_RE.match(url)
    if match and match.group(1) != "git":
        return match.group(2)
    return url


def _inside_root_or_home(path: Path, root: Path, home: Path | None) -> bool:
    if path.is_relative_to(root):
        return True
    return home is not None and path.is_relative_to(home)


def _origin_url(commondir: Path, branch: str | None) -> str | None:
    text = _read_text(commondir / "config", MAX_CONFIG_BYTES)
    if text is None:
        return None
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        parser.read_string("\n".join(line.strip() for line in text.splitlines()))
        tracking = parser.get(f'branch "{branch}"', "remote", fallback=None) if branch else None
        url = parser.get(f'remote "{tracking}"', "url", fallback=None) if tracking else None
        if not url:
            url = parser.get('remote "origin"', "url", fallback=None)
    except (configparser.Error, ValueError):
        return None
    if not url:
        return None
    url = strip_userinfo(url.strip().strip('"')).split("?", 1)[0].split("#", 1)[0]
    return url if 0 < len(url) <= MAX_URL_CHARS else None


def _resolve_ref(commondir: Path, ref: str) -> str | None:
    loose = _read_text(commondir / ref, MAX_REF_BYTES)
    if loose is not None:
        candidate = loose.strip()
        return candidate if _SHA_RE.match(candidate) else None
    packed = _read_text(commondir / "packed-refs", MAX_PACKED_REFS_BYTES)
    if packed is None:
        return None
    for line in packed.splitlines():
        if line.startswith(("#", "^")):
            continue
        sha, _, name = line.strip().partition(" ")
        if name == ref and _SHA_RE.match(sha):
            return sha
    return None


def _head(gitdir: Path, commondir: Path) -> tuple[str | None, str | None]:
    """`(branch, sha)` from HEAD: a symbolic ref or a detached sha."""
    text = _read_text(gitdir / "HEAD", MAX_REF_BYTES)
    if text is None:
        return None, None
    line = text.strip()
    match = _HEAD_REF_RE.match(line)
    if match:
        ref = match.group(1)
        if any(part in {"", ".", ".."} for part in ref.split("/")) or "\\" in ref:
            return None, None
        return ref.removeprefix("refs/heads/"), _resolve_ref(commondir, ref)
    return None, (line if _SHA_RE.match(line) else None)


def _default_home() -> Path | None:
    try:
        return Path.home().resolve()
    except (OSError, RuntimeError):
        return None


def git_info(root: Path, *, home: Path | None = None) -> GitInfo | None:
    """`{remote_url, branch, head}` for the folder, or None. Never raises.
    `home` (default `Path.home()`) bounds where a worktree pointer may lead."""
    try:
        resolved_root = root.resolve()
        bound = home.resolve() if home is not None else _default_home()
        dirs = _git_dirs(resolved_root, bound)
        if dirs is None:
            return None
        gitdir, commondir = dirs
        branch, full_sha = _head(gitdir, commondir)
        remote_url = _origin_url(commondir, branch)
        if remote_url is None:
            return None
        head = full_sha[:SHORT_SHA_LEN] if full_sha else None
    except Exception:  # noqa: BLE001 - a scan must never fail on git metadata
        return None
    return {"remote_url": remote_url, "branch": branch, "head": head}
