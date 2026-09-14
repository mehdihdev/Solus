"""State-bound Git observations and complete commit/push approval plans."""

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from .git_execution import GitOperationError, Repository, fingerprint


class GitArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GitLogArgs(GitArgs):
    limit: int = Field(default=10, ge=1, le=50)


class GitDiffArgs(GitArgs):
    scope: Literal["staged", "unstaged"]
    paths: list[str] | None = Field(default=None, max_length=32)


class GitCommitArgs(GitArgs):
    message: str = Field(min_length=1, max_length=1000)
    expected_head: str
    expected_index_fingerprint: str = Field(pattern=r"^[0-9a-f]{16}(?::[0-9a-f]{16}){3}$")
    dry_run: StrictBool = False


class GitPushArgs(GitArgs):
    remote: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    branch: str = Field(min_length=1, max_length=200)
    expected_head: str
    expected_remote_head: str | None
    dry_run: StrictBool = False


def _validate(model: type[GitArgs], values: dict[str, Any]) -> GitArgs:
    try:
        return model.model_validate(values)
    except ValidationError as exc:
        raise GitOperationError("invalid_arguments") from exc


def _text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeError as exc:
        raise GitOperationError("unsupported_encoding") from exc


def _paths(root: Path, paths: list[str] | None) -> list[str]:
    for value in paths or []:
        if not value or len(value) > 512 or "\\" in value or any(ord(c) < 32 for c in value):
            raise GitOperationError("invalid_path")
        parts = value.split("/")
        if (
            any(p in ("", ".", "..", ".git") or p.startswith("-") for p in parts)
            or PurePosixPath(value).is_absolute()
        ):
            raise GitOperationError("invalid_path")
        if (root / value).resolve().is_relative_to(root.resolve()) is False:
            raise GitOperationError("invalid_path")
        for i in range(1, len(parts) + 1):
            if root.joinpath(*parts[:i]).is_symlink():
                raise GitOperationError("invalid_path")
    return paths or []


def _diff(repo: Repository, scope: str, paths: list[str] | None = None) -> bytes:
    return repo.run(
        [
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--no-color",
            "--full-index",
            "--binary",
            *(["--cached"] if scope == "staged" else []),
            "--",
            *_paths(repo.root, paths),
        ]
    )


def _status(repo: Repository) -> dict[str, Any]:
    staged, unstaged, untracked, conflicts = [], [], [], []
    data = repo.run(
        ["-c", "status.renames=false", "status", "--porcelain=v1", "-z", "--untracked-files=all"]
    )
    for raw in data.split(b"\0"):
        if not raw:
            continue
        status, path = raw[:2], _text(raw[3:])
        if status == b"??":
            untracked.append(path)
        elif status in (b"DD", b"AU", b"UD", b"UA", b"DU", b"AA", b"UU"):
            conflicts.append(path)
        else:
            if status[:1] != b" ":
                staged.append(path)
            if status[1:] != b" ":
                unstaged.append(path)
    return dict(
        ok=True,
        branch=_text(
            repo.run(["symbolic-ref", "--quiet", "--short", "HEAD"], allow_failure=True)
        ).strip()
        or None,
        head=repo.head(),
        index_fingerprint=repo.index_fingerprint(),
        staged=staged,
        unstaged=unstaged,
        untracked=untracked,
        conflicts=conflicts,
        truncated=False,
    )


def git_status(root: Path) -> dict[str, Any]:
    result = _status(Repository(root))
    while len(json.dumps(result).encode()) > 16 * 1024:
        longest = max(
            ("staged", "unstaged", "untracked", "conflicts"), key=lambda key: len(result[key])
        )
        if not result[longest]:
            raise GitOperationError("output_too_large")
        result[longest].pop()
        result["truncated"] = True
    return result


def git_log(root: Path, limit: int = 10) -> dict[str, Any]:
    _validate(GitLogArgs, {"limit": limit})
    repo = Repository(root)
    rows = repo.run(["log", f"--max-count={limit}", "--format=%H%x00%s%x00%aI%x00"])
    commits = []
    parts = rows.split(b"\0")
    for i in range(0, len(parts) - 2, 3):
        commits.append(
            dict(
                oid=_text(parts[i]).strip(),
                subject=_text(parts[i + 1]),
                authored_at=_text(parts[i + 2]),
            )
        )
    result = dict(ok=True, commits=commits, truncated=False)
    while len(json.dumps(result).encode()) > 16 * 1024:
        commits.pop()
        result["truncated"] = True
    return result


def git_diff(root: Path, scope: str, paths: list[str] | None = None) -> dict[str, Any]:
    _validate(GitDiffArgs, {"scope": scope, "paths": paths})
    raw = _diff(Repository(root), scope, paths)
    return dict(
        ok=True, diff=raw[:15000].decode("utf-8", errors="replace"), truncated=len(raw) > 15000
    )


def _rows(label: str, text: str) -> list[dict[str, Any]]:
    # Fixed chunks preserve all whitespace and characters, including a full long line.
    return [
        dict(
            label=label if i == 0 else label + " (continued)", before=None, after=text[i : i + 400]
        )
        for i in range(0, len(text), 400)
    ]


def _plan(rows: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
    digest = fingerprint(json.dumps(state, sort_keys=True, ensure_ascii=False).encode())
    rows.append(dict(label="Plan fingerprint", before=None, after=digest))
    if len(rows) > 40 or any(
        len(value) > 400 for row in rows for value in row.values() if isinstance(value, str)
    ):
        raise GitOperationError("preview_too_large")
    return dict(ok=True, dry_run=True, preview=rows, fingerprint=digest)


def _commit_plan(
    repo: Repository, message: str, head: str, index: str
) -> tuple[dict[str, Any], bytes]:
    repo.mutation_ready()
    repo.check_oid(head)
    state = _status(repo)
    if state["head"] != head or state["index_fingerprint"] != index:
        raise GitOperationError("stale_state")
    patch = _diff(repo, "staged")
    if not patch:
        raise GitOperationError("nothing_staged")
    rows = [
        dict(label="Branch", before=repo.symbolic_ref(), after=repo.symbolic_ref()),
        dict(label="HEAD", before=head, after="new commit"),
        dict(label="Index fingerprint", before=index, after=index),
    ]
    for path in state["staged"]:
        _paths(repo.root, [path])
        rows.extend(_rows("Staged path", path))
    rows.extend(_rows("Message", message))
    rows.extend(_rows("Complete staged diff", _text(patch)))
    return _plan(
        rows,
        dict(
            identity=repo.state_identity(),
            head=head,
            index=index,
            message=message,
            patch=_text(patch),
            staged=state["staged"],
        ),
    ), patch


def git_commit(
    root: Path,
    message: str,
    expected_head: str,
    expected_index_fingerprint: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    _validate(
        GitCommitArgs,
        dict(
            message=message,
            expected_head=expected_head,
            expected_index_fingerprint=expected_index_fingerprint,
            dry_run=dry_run,
        ),
    )
    if not message.strip() or "\0" in message:
        raise GitOperationError("invalid_arguments")
    repo = Repository(root)
    initial_branch = repo.symbolic_ref()
    plan, _ = _commit_plan(repo, message, expected_head, expected_index_fingerprint)
    if dry_run:
        return plan
    with repo.locked():
        current, patch = _commit_plan(repo, message, expected_head, expected_index_fingerprint)
        if current != plan:
            raise GitOperationError("stale_state")
        if repo.symbolic_ref() != initial_branch:
            raise GitOperationError("stale_state")
        try:
            repo.run(
                ["commit", "--no-verify", "--no-gpg-sign", "--cleanup=verbatim", "-m", message]
            )
            new = repo.head()
            parent = _text(repo.run(["rev-parse", new + "^"])).strip()
            actual_message = repo.run(["cat-file", "commit", new]).split(b"\n\n", 1)[1]
            actual_patch = repo.run(
                [
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--no-renames",
                    "--no-color",
                    "--full-index",
                    "--binary",
                    expected_head,
                    new,
                    "--",
                ]
            )
            if (
                parent != expected_head
                or repo.symbolic_ref() != initial_branch
                or actual_message
                != (message if message.endswith("\n") else message + "\n").encode()
                or actual_patch != patch
            ):
                raise GitOperationError("readback_mismatch")
        except GitOperationError:
            return dict(
                ok=False,
                changed=None,
                exit_code=None,
                output="Commit outcome could not be verified",
                uncertain=True,
            )
    return dict(
        ok=True,
        changed=True,
        exit_code=0,
        output="Commit verified",
        head=new,
        parent=parent,
        uncertain=False,
    )


def _remote(repo: Repository, remote: str) -> tuple[str, str]:
    raw = repo.run(["config", "--local", "--no-includes", "--get-all", "remote." + remote + ".url"])
    urls = _text(raw).splitlines()
    if len(urls) != 1:
        raise GitOperationError("unsupported_transport")
    url = urls[0]
    if url.startswith("https://"):
        raise GitOperationError("authentication_unavailable")
    if url.startswith("ssh://"):
        parsed = urlsplit(url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise GitOperationError("unsupported_transport") from exc
        if (
            parsed.username != "git"
            or parsed.password
            or port not in (None, 22)
            or parsed.query
            or parsed.fragment
        ):
            raise GitOperationError("unsupported_transport")
        host, path = parsed.hostname, parsed.path.lstrip("/")
    else:
        match = re.fullmatch(r"git@([^:]+):(.+)", url)
        if not match:
            raise GitOperationError("unsupported_transport")
        host, path = match.groups()
    if host not in ("github.com", "gitlab.com") or not re.fullmatch(
        r"[A-Za-z0-9_-]+/[A-Za-z0-9_-]+(?:\.git)?", path
    ):
        raise GitOperationError("unsupported_transport")
    return url, host + "/" + path


def _tip(repo: Repository, url: str, branch: str) -> str | None:
    raw = repo.run(["ls-remote", "--refs", "--", url, "refs/heads/" + branch], network=True)
    if not raw:
        return None
    rows = raw.splitlines()
    if len(rows) != 1:
        raise GitOperationError("invalid_remote_state")
    oid, ref = rows[0].split(b"\t", 1)
    value = _text(oid)
    repo.check_oid(value)
    if _text(ref) != "refs/heads/" + branch:
        raise GitOperationError("invalid_remote_state")
    return value


def _push_plan(
    repo: Repository, remote: str, branch: str, head: str, expected_tip: str | None
) -> tuple[dict[str, Any], str]:
    repo.mutation_ready()
    repo.check_oid(head)
    if expected_tip is not None:
        repo.check_oid(expected_tip)
    if repo.head() != head:
        raise GitOperationError("stale_state")
    if branch.startswith("-") or any(ord(c) < 32 for c in branch):
        raise GitOperationError("invalid_branch")
    repo.run(["check-ref-format", "refs/heads/" + branch])
    if _text(repo.run(["rev-parse", "refs/heads/" + branch])).strip() != head:
        raise GitOperationError("stale_state")
    url, destination = _remote(repo, remote)
    if _tip(repo, url, branch) != expected_tip:
        raise GitOperationError("stale_remote")
    if expected_tip:
        # A missing remote object cannot prove ancestry; never fetch implicitly.
        repo.run(["merge-base", "--is-ancestor", expected_tip, head])
    outgoing = repo.run(
        ["log", "--format=%H %s", head, *(["^" + expected_tip] if expected_tip else [])]
    )
    rows = [
        dict(label="Destination", before=None, after=destination),
        dict(label="Branch", before=None, after=branch),
        dict(label="Remote HEAD", before=expected_tip, after=head),
    ]
    rows.extend(_rows("Outgoing commits", _text(outgoing)))
    return _plan(
        rows,
        dict(
            identity=repo.state_identity(),
            head=head,
            remote_head=expected_tip,
            destination=destination,
            branch=branch,
            outgoing=_text(outgoing),
        ),
    ), url


def git_push(
    root: Path,
    remote: str,
    branch: str,
    expected_head: str,
    expected_remote_head: str | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    _validate(
        GitPushArgs,
        dict(
            remote=remote,
            branch=branch,
            expected_head=expected_head,
            expected_remote_head=expected_remote_head,
            dry_run=dry_run,
        ),
    )
    repo = Repository(root)
    plan, _ = _push_plan(repo, remote, branch, expected_head, expected_remote_head)
    if dry_run:
        return plan
    with repo.locked():
        current, url = _push_plan(repo, remote, branch, expected_head, expected_remote_head)
        if current != plan:
            raise GitOperationError("stale_state")
        try:
            repo.run(
                [
                    "push",
                    "--no-verify",
                    "--porcelain",
                    "--",
                    url,
                    expected_head + ":refs/heads/" + branch,
                ],
                network=True,
            )
            if _tip(repo, url, branch) != expected_head:
                raise GitOperationError("readback_mismatch")
        except GitOperationError:
            return dict(
                ok=False,
                changed=None,
                exit_code=None,
                output="Push outcome could not be verified",
                uncertain=True,
            )
    return dict(
        ok=True,
        changed=expected_head != expected_remote_head,
        exit_code=0,
        output="Push verified",
        head=expected_head,
        remote_head=expected_head,
        uncertain=False,
    )
