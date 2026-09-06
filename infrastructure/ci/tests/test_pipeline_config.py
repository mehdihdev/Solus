"""Pipeline policy checks; GitLab CI Lint remains the authoritative YAML validator."""

import fnmatch
import re
import shlex
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CONFIG = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text())
PYTHON_JOBS = {"lint:python", "typecheck:python", "test:python"}
NODE_JOBS = {"lint:node", "typecheck:node", "test:node"}
SCAN = {"security:gitleaks"}
DEPLOY = {"build:api-image", "deploy:staging"}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _job(name: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    parents = CONFIG[name].get("extends", [])
    for parent in [parents] if isinstance(parents, str) else parents:
        result = _merge(result, _job(parent))
    return _merge(result, CONFIG[name])


def _included(rules: list[dict[str, Any]], variables: dict[str, str], changes: list[str]) -> bool:
    # Deliberately limited to this file's rules grammar. Unsupported expressions
    # fail loudly instead of pretending to implement GitLab's entire evaluator.
    for rule in rules:
        match = re.fullmatch(r'\$(\w+)(?: == "([^"]*)")?', rule["if"])
        assert match, f"Extend the policy check for this expression: {rule['if']}"
        actual = variables.get(match[1], "")
        if not (actual == match[2] if match[2] is not None else bool(actual)):
            continue
        if "changes" in rule and not any(
            fnmatch.fnmatchcase(path, pattern)
            or fnmatch.fnmatchcase(path, pattern.replace("/**/", "/"))
            for path in changes
            for pattern in rule["changes"]
        ):
            continue
        return rule.get("when") != "never"
    return False


def _jobs(source: str, branch: str = "", tag: str = "", change: str = "") -> set[str]:
    variables = {
        "CI_PIPELINE_SOURCE": source,
        "CI_COMMIT_BRANCH": branch,
        "CI_COMMIT_TAG": tag,
    }
    if not _included(CONFIG["workflow"]["rules"], variables, [change]):
        return set()
    result = set()
    for name in CONFIG:
        if name.startswith(".") or "stage" not in CONFIG[name]:
            continue
        rules = _job(name).get("rules")
        if rules is None:
            included = source != "merge_request_event"
        else:
            included = _included(rules, variables, [change])
        if included:
            result.add(name)
    return result


@pytest.mark.parametrize("source", ["push", "web", "schedule"])
def test_main_contains_only_image_build_and_staging_deploy(source: str) -> None:
    assert _jobs(source, branch="main") == DEPLOY


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ("packages/api/src/solus_api/main.py", PYTHON_JOBS | SCAN),
        ("packages/api/pyproject.toml", PYTHON_JOBS | SCAN),
        ("apps/desktop/src/renderer/main.tsx", NODE_JOBS | SCAN),
        (".gitlab-ci.yml", PYTHON_JOBS | NODE_JOBS | SCAN),
        ("docs/example.md", SCAN),
        ("infrastructure/ci/scan-secrets.sh", PYTHON_JOBS | SCAN),
        (".dockerignore", PYTHON_JOBS | SCAN),
        ("scripts/seed-provider-keys.py", PYTHON_JOBS | NODE_JOBS | SCAN),
        ("vitest.config.ts", NODE_JOBS | SCAN),
    ],
)
def test_merge_requests_keep_relevant_validation(change: str, expected: set[str]) -> None:
    assert _jobs("merge_request_event", change=change) == expected


def test_tags_keep_validation_without_deploying_staging() -> None:
    assert _jobs("push", tag="v1.0.0") == PYTHON_JOBS | NODE_JOBS | SCAN


def test_feature_push_does_not_duplicate_the_merge_request_pipeline() -> None:
    assert _jobs("push", branch="feature") == set()


def test_deployment_requires_a_successful_build_and_is_not_auto_interrupted() -> None:
    deploy = _job("deploy:staging")
    assert deploy["needs"] == ["build:api-image"]
    assert deploy["interruptible"] is False
    assert deploy.get("when", "on_success") == "on_success"


def test_only_one_job_per_toolchain_uploads_dependency_cache() -> None:
    for jobs in [PYTHON_JOBS, NODE_JOBS]:
        writers = [
            name
            for name in jobs
            if _job(name).get("cache", {}).get("policy") in {"push", "pull-push"}
        ]
        assert len(writers) == 1
        for name in jobs - set(writers):
            assert _job(name).get("cache", {}).get("policy", "pull") == "pull"


def test_python_lint_uses_only_the_lockfile_pinned_ruff_image() -> None:
    with (ROOT / "uv.lock").open("rb") as stream:
        lock = tomllib.load(stream)
    version = next(p["version"] for p in lock["package"] if p["name"] == "ruff")
    lint = _job("lint:python")
    assert lint["image"]["name"] == f"ghcr.io/astral-sh/ruff:{version}-alpine"
    assert not lint.get("before_script")


def test_python_installation_is_locked_and_execution_does_not_resync() -> None:
    assert CONFIG[".python-base"]["before_script"] == ["uv sync --all-packages --locked"]
    for name in ["typecheck:python", "test:python"]:
        script = _job(name)["script"]
        for line in [script] if isinstance(script, str) else script:
            if line.startswith("uv run "):
                assert "--no-sync" in shlex.split(line)


def test_python_suite_is_serial_reports_durations_and_excludes_live_providers() -> None:
    script = _job("test:python")["script"]
    command = next(line for line in script if "pytest " in line)
    args = shlex.split(command)
    assert "-n" not in args and "--numprocesses" not in args
    assert args[args.index("-m") + 1] == "not live"
    assert any(arg.startswith("--durations=") for arg in args)
    assert any(arg.startswith("--junitxml=") for arg in args)
    assert _job("test:python")["artifacts"]["when"] == "always"
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)
    assert "infrastructure/ci/tests" in project["tool"]["pytest"]["ini_options"]["testpaths"]


def test_non_durable_settings_are_limited_to_the_disposable_test_database() -> None:
    service = _job("test:python")["services"][0]
    assert service["alias"] == "postgres"
    for setting in ["fsync=off", "synchronous_commit=off", "full_page_writes=off"]:
        assert setting in service["command"]
        for name in DEPLOY:
            assert setting not in str(_job(name))


def test_secret_scan_uses_complete_history_for_range_validation() -> None:
    scan = _job("security:gitleaks")
    assert str(scan["variables"]["GIT_DEPTH"]) == "0"
    assert scan["script"] == "sh infrastructure/ci/scan-secrets.sh"


def test_python_test_image_installs_git_for_the_repository_fixtures() -> None:
    install = next(line for line in _job("test:python")["script"] if "apt-get install" in line)
    assert "git" in shlex.split(install)
