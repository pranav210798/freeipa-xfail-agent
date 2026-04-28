from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .ai_analysis import (
    analyze_candidates,
    build_review_summary,
    explain_conditional_xfails as build_conditional_explanations,
    improve_commit_message as build_improved_commit_message,
)
from .config import load_config
from .git_utils import GitRepo
from .workflow import CommitStrategy, XfailSelection, apply_cleanup, plan_cleanup

mcp = FastMCP("freeipa-xfail-agent")

DEFAULT_PATHS = ["ipatests/test_integration", "ipatests/test_xmlrpc"]
DEFAULT_BRANCH = "master"


def _env_trimmed(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _resolve_repo_path(repo_path: str | None) -> Path:
    candidate = (repo_path or "").strip() or _env_trimmed("FREEIPA_XFAIL_REPO_PATH")
    path = Path(candidate) if candidate else Path.cwd()
    return path.expanduser().resolve()


def _resolve_branch(branch: str | None) -> str:
    return (branch or "").strip() or _env_trimmed("FREEIPA_XFAIL_BRANCH") or DEFAULT_BRANCH


def _resolve_expected_origin(expected_origin: str | None) -> str | None:
    return (expected_origin or "").strip() or _env_trimmed("FREEIPA_XFAIL_EXPECTED_ORIGIN")


def _resolve_identity(person_name: str | None, person_email: str | None) -> tuple[str | None, str | None]:
    resolved_name = (person_name or "").strip() or _env_trimmed("FREEIPA_XFAIL_PERSON_NAME")
    resolved_email = (person_email or "").strip() or _env_trimmed("FREEIPA_XFAIL_PERSON_EMAIL")
    return resolved_name, resolved_email


def _parse_selection(selection: str) -> XfailSelection:
    try:
        return XfailSelection(selection)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in XfailSelection)
        raise ValueError(f"Invalid selection '{selection}'. Allowed: {allowed}") from exc


def _parse_commit_strategy(strategy: str) -> CommitStrategy:
    try:
        return CommitStrategy(strategy)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in CommitStrategy)
        raise ValueError(f"Invalid commit_strategy '{strategy}'. Allowed: {allowed}") from exc


def _serialize_decision(item) -> dict:
    return {
        "file": str(item.block.file_path),
        "start_line": item.block.start_line,
        "end_line": item.block.end_line,
        "test_name": item.block.test_name,
        "kind": item.block.kind.value,
        "reason": item.reason,
        "tickets": [status.ticket.normalized_id for status in item.statuses],
    }


def _selected_key_set(selected_keys: list[str] | None) -> set[str] | None:
    if selected_keys is None:
        return None
    return {item.strip() for item in selected_keys if item.strip()}


@mcp.tool()
def get_runtime_defaults() -> dict:
    resolved_repo = _resolve_repo_path(None)
    return {
        "repo_path": str(resolved_repo),
        "branch": _resolve_branch(None),
        "expected_origin": _resolve_expected_origin(None),
        "person_name": _env_trimmed("FREEIPA_XFAIL_PERSON_NAME"),
        "person_email": _env_trimmed("FREEIPA_XFAIL_PERSON_EMAIL"),
    }


@mcp.tool()
def list_branches(repo_path: str | None = None) -> dict:
    resolved_repo = _resolve_repo_path(repo_path)
    repo = GitRepo(resolved_repo)
    branches = repo.list_branches()
    return {"repo_path": str(resolved_repo), "branches": branches}


@mcp.tool()
def scan_xfails(
    repo_path: str | None = None,
    branch: str | None = None,
    paths: list[str] | None = None,
    expected_origin: str | None = None,
    person_name: str | None = None,
    person_email: str | None = None,
    selection: str = "all",
    selected_keys: list[str] | None = None,
) -> dict:
    resolved_repo = _resolve_repo_path(repo_path)
    resolved_branch = _resolve_branch(branch)
    resolved_origin = _resolve_expected_origin(expected_origin)
    resolved_name, resolved_email = _resolve_identity(person_name, person_email)
    result = plan_cleanup(
        repo_path=resolved_repo,
        branch=resolved_branch,
        test_paths=paths or DEFAULT_PATHS,
        config=load_config(),
        expected_origin=resolved_origin,
        person_name=resolved_name,
        person_email=resolved_email,
        selection=_parse_selection(selection),
        selected_keys=_selected_key_set(selected_keys),
    )
    return {
        "branch": result.branch,
        "repo_path": str(resolved_repo),
        "total_xfails": result.total_xfails,
        "removable_count": len(result.removable),
        "remaining_count": len(result.remaining),
        "planned_files": result.planned_files,
        "proposed_commit_message": result.proposed_commit_message,
        "removable": [_serialize_decision(item) for item in result.removable],
    }


@mcp.tool()
def plan_xfail_cleanup(
    repo_path: str | None = None,
    branch: str | None = None,
    paths: list[str] | None = None,
    expected_origin: str | None = None,
    person_name: str | None = None,
    person_email: str | None = None,
    selection: str = "all",
    selected_keys: list[str] | None = None,
) -> dict:
    resolved_repo = _resolve_repo_path(repo_path)
    resolved_branch = _resolve_branch(branch)
    resolved_origin = _resolve_expected_origin(expected_origin)
    resolved_name, resolved_email = _resolve_identity(person_name, person_email)
    result = plan_cleanup(
        repo_path=resolved_repo,
        branch=resolved_branch,
        test_paths=paths or DEFAULT_PATHS,
        config=load_config(),
        expected_origin=resolved_origin,
        person_name=resolved_name,
        person_email=resolved_email,
        selection=_parse_selection(selection),
        selected_keys=_selected_key_set(selected_keys),
    )
    return {
        "branch": result.branch,
        "repo_path": str(resolved_repo),
        "total_xfails": result.total_xfails,
        "removable_count": len(result.removable),
        "remaining_count": len(result.remaining),
        "planned_files": result.planned_files,
        "proposed_commit_message": result.proposed_commit_message,
        "removable": [_serialize_decision(item) for item in result.removable],
        "remaining": [_serialize_decision(item) for item in result.remaining],
    }


@mcp.tool()
def apply_xfail_cleanup(
    repo_path: str | None = None,
    branch: str | None = None,
    paths: list[str] | None = None,
    create_branch: str | None = None,
    do_commit: bool = False,
    expected_origin: str | None = None,
    person_name: str | None = None,
    person_email: str | None = None,
    commit_strategy: str = "batch",
    push: bool = False,
    selection: str = "all",
    selected_keys: list[str] | None = None,
) -> dict:
    resolved_repo = _resolve_repo_path(repo_path)
    resolved_branch = _resolve_branch(branch)
    resolved_origin = _resolve_expected_origin(expected_origin)
    resolved_name, resolved_email = _resolve_identity(person_name, person_email)
    result = apply_cleanup(
        repo_path=resolved_repo,
        branch=resolved_branch,
        test_paths=paths or DEFAULT_PATHS,
        config=load_config(),
        create_branch=create_branch,
        do_commit=do_commit,
        commit_strategy=_parse_commit_strategy(commit_strategy),
        push=push,
        expected_origin=resolved_origin,
        person_name=resolved_name,
        person_email=resolved_email,
        selection=_parse_selection(selection),
        selected_keys=_selected_key_set(selected_keys),
    )
    return {
        "branch": result.branch,
        "repo_path": str(resolved_repo),
        "total_xfails": result.total_xfails,
        "removable_count": len(result.removable),
        "remaining_count": len(result.remaining),
        "updated_files": result.updated_files,
        "planned_files": result.planned_files,
        "proposed_commit_message": result.proposed_commit_message,
        "commit_sha": result.commit_sha,
        "commit_shas": result.commit_shas,
    }


@mcp.tool()
def analyze_xfail_candidates(
    repo_path: str | None = None,
    branch: str | None = None,
    paths: list[str] | None = None,
    expected_origin: str | None = None,
    person_name: str | None = None,
    person_email: str | None = None,
    selection: str = "all",
    selected_keys: list[str] | None = None,
) -> dict:
    resolved_repo = _resolve_repo_path(repo_path)
    resolved_branch = _resolve_branch(branch)
    resolved_origin = _resolve_expected_origin(expected_origin)
    resolved_name, resolved_email = _resolve_identity(person_name, person_email)
    result = plan_cleanup(
        repo_path=resolved_repo,
        branch=resolved_branch,
        test_paths=paths or DEFAULT_PATHS,
        config=load_config(),
        expected_origin=resolved_origin,
        person_name=resolved_name,
        person_email=resolved_email,
        selection=_parse_selection(selection),
        selected_keys=_selected_key_set(selected_keys),
    )
    analyses = analyze_candidates(
        removable=result.removable,
        remaining=result.remaining,
        repo_path=resolved_repo,
    )
    high_risk = [item for item in analyses if item.risk_level.value == "high"]
    medium_risk = [item for item in analyses if item.risk_level.value == "medium"]
    return {
        "branch": result.branch,
        "repo_path": str(resolved_repo),
        "total_xfails": result.total_xfails,
        "candidate_count": len(analyses),
        "high_risk_count": len(high_risk),
        "medium_risk_count": len(medium_risk),
        "analyses": [
            {
                "key": item.key,
                "file": item.file,
                "test_name": item.test_name,
                "kind": item.kind,
                "tickets": item.tickets,
                "should_remove": item.should_remove,
                "risk_score": item.risk_score,
                "risk_level": item.risk_level.value,
                "recommendation": item.recommendation,
                "rationale": item.rationale,
            }
            for item in analyses
        ],
    }


@mcp.tool()
def explain_conditional_xfails(
    repo_path: str | None = None,
    branch: str | None = None,
    paths: list[str] | None = None,
    expected_origin: str | None = None,
    person_name: str | None = None,
    person_email: str | None = None,
    selection: str = "all",
    selected_keys: list[str] | None = None,
) -> dict:
    resolved_repo = _resolve_repo_path(repo_path)
    resolved_branch = _resolve_branch(branch)
    resolved_origin = _resolve_expected_origin(expected_origin)
    resolved_name, resolved_email = _resolve_identity(person_name, person_email)
    result = plan_cleanup(
        repo_path=resolved_repo,
        branch=resolved_branch,
        test_paths=paths or DEFAULT_PATHS,
        config=load_config(),
        expected_origin=resolved_origin,
        person_name=resolved_name,
        person_email=resolved_email,
        selection=_parse_selection(selection),
        selected_keys=_selected_key_set(selected_keys),
    )
    details = build_conditional_explanations(
        removable=result.removable,
        remaining=result.remaining,
        repo_path=resolved_repo,
    )
    return {
        "branch": result.branch,
        "repo_path": str(resolved_repo),
        "conditional_count": len(details),
        "conditional_details": details,
    }


@mcp.tool()
def improve_commit_message(
    repo_path: str | None = None,
    branch: str | None = None,
    paths: list[str] | None = None,
    expected_origin: str | None = None,
    person_name: str | None = None,
    person_email: str | None = None,
    selection: str = "all",
    selected_keys: list[str] | None = None,
    current_message: str | None = None,
) -> dict:
    resolved_repo = _resolve_repo_path(repo_path)
    resolved_branch = _resolve_branch(branch)
    resolved_origin = _resolve_expected_origin(expected_origin)
    resolved_name, resolved_email = _resolve_identity(person_name, person_email)
    result = plan_cleanup(
        repo_path=resolved_repo,
        branch=resolved_branch,
        test_paths=paths or DEFAULT_PATHS,
        config=load_config(),
        expected_origin=resolved_origin,
        person_name=resolved_name,
        person_email=resolved_email,
        selection=_parse_selection(selection),
        selected_keys=_selected_key_set(selected_keys),
    )
    improved = build_improved_commit_message(
        current_message=current_message or result.proposed_commit_message,
        removable=result.removable,
        repo_path=resolved_repo,
    )
    return {
        "branch": result.branch,
        "repo_path": str(resolved_repo),
        "removable_count": len(result.removable),
        **improved,
    }


@mcp.tool()
def generate_review_summary(
    repo_path: str | None = None,
    branch: str | None = None,
    paths: list[str] | None = None,
    expected_origin: str | None = None,
    person_name: str | None = None,
    person_email: str | None = None,
    selection: str = "all",
    selected_keys: list[str] | None = None,
) -> dict:
    resolved_repo = _resolve_repo_path(repo_path)
    resolved_branch = _resolve_branch(branch)
    resolved_origin = _resolve_expected_origin(expected_origin)
    resolved_name, resolved_email = _resolve_identity(person_name, person_email)
    result = plan_cleanup(
        repo_path=resolved_repo,
        branch=resolved_branch,
        test_paths=paths or DEFAULT_PATHS,
        config=load_config(),
        expected_origin=resolved_origin,
        person_name=resolved_name,
        person_email=resolved_email,
        selection=_parse_selection(selection),
        selected_keys=_selected_key_set(selected_keys),
    )
    analyses = analyze_candidates(
        removable=result.removable,
        remaining=result.remaining,
        repo_path=resolved_repo,
    )
    summary = build_review_summary(
        removable=result.removable,
        remaining=result.remaining,
        analyses=analyses,
        proposed_commit_message=result.proposed_commit_message,
    )
    return {
        "branch": result.branch,
        "repo_path": str(resolved_repo),
        "summary_markdown": summary,
        "removable_count": len(result.removable),
        "remaining_count": len(result.remaining),
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
