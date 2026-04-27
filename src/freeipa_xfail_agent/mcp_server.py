from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .git_utils import GitRepo
from .workflow import apply_cleanup, plan_cleanup

mcp = FastMCP("freeipa-xfail-agent")

DEFAULT_PATHS = ["ipatests/test_integration", "ipatests/test_xmlrpc"]


@mcp.tool()
def list_branches(repo_path: str) -> dict:
    repo = GitRepo(Path(repo_path))
    branches = repo.list_branches()
    return {"repo_path": repo_path, "branches": branches}


@mcp.tool()
def scan_xfails(
    repo_path: str,
    branch: str = "master",
    paths: list[str] | None = None,
    expected_origin: str | None = None,
    person_name: str | None = None,
    person_email: str | None = None,
) -> dict:
    result = plan_cleanup(
        repo_path=Path(repo_path),
        branch=branch,
        test_paths=paths or DEFAULT_PATHS,
        config=load_config(),
        expected_origin=expected_origin,
        person_name=person_name,
        person_email=person_email,
    )
    return {
        "branch": result.branch,
        "total_xfails": result.total_xfails,
        "removable_count": len(result.removable),
        "remaining_count": len(result.remaining),
        "planned_files": result.planned_files,
        "proposed_commit_message": result.proposed_commit_message,
        "removable": [
            {
                "file": str(item.block.file_path),
                "start_line": item.block.start_line,
                "end_line": item.block.end_line,
                "reason": item.reason,
                "tickets": [status.ticket.normalized_id for status in item.statuses],
            }
            for item in result.removable
        ],
    }


@mcp.tool()
def plan_xfail_cleanup(
    repo_path: str,
    branch: str = "master",
    paths: list[str] | None = None,
    expected_origin: str | None = None,
    person_name: str | None = None,
    person_email: str | None = None,
) -> dict:
    result = plan_cleanup(
        repo_path=Path(repo_path),
        branch=branch,
        test_paths=paths or DEFAULT_PATHS,
        config=load_config(),
        expected_origin=expected_origin,
        person_name=person_name,
        person_email=person_email,
    )
    return {
        "branch": result.branch,
        "total_xfails": result.total_xfails,
        "removable_count": len(result.removable),
        "remaining_count": len(result.remaining),
        "planned_files": result.planned_files,
        "proposed_commit_message": result.proposed_commit_message,
        "remaining": [
            {
                "file": str(item.block.file_path),
                "start_line": item.block.start_line,
                "end_line": item.block.end_line,
                "reason": item.reason,
                "tickets": [status.ticket.normalized_id for status in item.statuses],
            }
            for item in result.remaining
        ],
    }


@mcp.tool()
def apply_xfail_cleanup(
    repo_path: str,
    branch: str = "master",
    paths: list[str] | None = None,
    create_branch: str | None = None,
    do_commit: bool = False,
    expected_origin: str | None = None,
    person_name: str | None = None,
    person_email: str | None = None,
) -> dict:
    result = apply_cleanup(
        repo_path=Path(repo_path),
        branch=branch,
        test_paths=paths or DEFAULT_PATHS,
        config=load_config(),
        create_branch=create_branch,
        do_commit=do_commit,
        expected_origin=expected_origin,
        person_name=person_name,
        person_email=person_email,
    )
    return {
        "branch": result.branch,
        "total_xfails": result.total_xfails,
        "removable_count": len(result.removable),
        "remaining_count": len(result.remaining),
        "updated_files": result.updated_files,
        "planned_files": result.planned_files,
        "proposed_commit_message": result.proposed_commit_message,
        "commit_sha": result.commit_sha,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
