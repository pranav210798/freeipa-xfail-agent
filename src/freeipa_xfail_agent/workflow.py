from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig
from .git_utils import GitRepo
from .issue_trackers import JiraClient, PagureClient, TrackerGateway
from .models import TicketStatus, XfailBlock, XfailDecision
from .xfail_scanner import scan_xfails


@dataclass
class CleanupResult:
    branch: str
    total_xfails: int
    removable: list[XfailDecision]
    remaining: list[XfailDecision]
    updated_files: list[str]
    planned_files: list[str]
    proposed_commit_message: str
    commit_sha: str | None = None


def _build_gateway(config: AppConfig) -> TrackerGateway:
    jira_client = JiraClient(config.jira) if config.jira else None
    pagure_client = PagureClient(config.pagure)
    return TrackerGateway(jira=jira_client, pagure=pagure_client)


def evaluate_blocks(blocks: list[XfailBlock], gateway: TrackerGateway) -> list[XfailDecision]:
    decisions: list[XfailDecision] = []

    for block in blocks:
        if not block.tickets:
            decisions.append(
                XfailDecision(
                    block=block,
                    statuses=[],
                    should_remove=False,
                    reason="no linked ticket in xfail marker",
                )
            )
            continue

        statuses: list[TicketStatus] = [gateway.get_status(ticket) for ticket in block.tickets]
        has_error = any(status.error for status in statuses)
        all_closed = all(status.is_closed for status in statuses)

        if has_error:
            decisions.append(
                XfailDecision(
                    block=block,
                    statuses=statuses,
                    should_remove=False,
                    reason="ticket status check failed or incomplete",
                )
            )
            continue

        if all_closed:
            decisions.append(
                XfailDecision(
                    block=block,
                    statuses=statuses,
                    should_remove=True,
                    reason="all linked tickets are closed",
                )
            )
        else:
            decisions.append(
                XfailDecision(
                    block=block,
                    statuses=statuses,
                    should_remove=False,
                    reason="at least one linked ticket is still open",
                )
            )

    return decisions


def _remove_block_lines(file_path: Path, blocks: list[XfailBlock]) -> bool:
    raw_lines = file_path.read_text(encoding="utf-8").splitlines()
    to_remove: set[int] = set()
    for block in blocks:
        for line_no in range(block.start_line, block.end_line + 1):
            to_remove.add(line_no)

    if not to_remove:
        return False

    updated = [line for idx, line in enumerate(raw_lines, start=1) if idx not in to_remove]
    file_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    return True


def _group_removals_by_file(removable: list[XfailDecision]) -> dict[Path, list[XfailBlock]]:
    grouped: dict[Path, list[XfailBlock]] = defaultdict(list)
    for decision in removable:
        grouped[decision.block.file_path].append(decision.block)
    return grouped


def build_commit_message(
    removable: list[XfailDecision],
    repo_path: Path,
    person_name: str | None = None,
    person_email: str | None = None,
) -> str:
    lines = [
        "ipatests: Remove xfails for fixed test cases.",
        "The following test cases are linked to closed issues and are now considered fixed, so the xfail markers are removed:",
    ]

    if not removable:
        lines.append("No closed-ticket xfail testcases were found.")
    else:
        for decision in removable:
            ticket_ids = ", ".join(status.ticket.normalized_id for status in decision.statuses) or "no-issue"
            test_name = decision.block.test_name or "unknown_testcase"
            rel_file = str(decision.block.file_path.relative_to(repo_path))
            lines.append(f"{test_name} : {rel_file}: {ticket_ids}")

    if person_name and person_email:
        lines.extend(
            [
                "",
                f"Signed-off-by: {person_name} <{person_email}>",
            ]
        )

    return "\n".join(lines)


def plan_cleanup(
    repo_path: Path,
    branch: str,
    test_paths: list[str],
    config: AppConfig,
    expected_origin: str | None = None,
    person_name: str | None = None,
    person_email: str | None = None,
) -> CleanupResult:
    git = GitRepo(repo_path)
    git.ensure_repo()
    git.assert_origin_contains(expected_origin)
    git.checkout(branch)

    gateway = _build_gateway(config)
    blocks = scan_xfails(repo_path, test_paths)
    decisions = evaluate_blocks(blocks, gateway)

    removable = [item for item in decisions if item.should_remove]
    remaining = [item for item in decisions if not item.should_remove]
    planned_files = sorted({str(item.block.file_path.relative_to(repo_path)) for item in removable})
    commit_message = build_commit_message(
        removable=removable,
        repo_path=repo_path,
        person_name=person_name,
        person_email=person_email,
    )
    return CleanupResult(
        branch=branch,
        total_xfails=len(blocks),
        removable=removable,
        remaining=remaining,
        updated_files=[],
        planned_files=planned_files,
        proposed_commit_message=commit_message,
    )


def apply_cleanup(
    repo_path: Path,
    branch: str,
    test_paths: list[str],
    config: AppConfig,
    create_branch: str | None = None,
    do_commit: bool = False,
    expected_origin: str | None = None,
    person_name: str | None = None,
    person_email: str | None = None,
) -> CleanupResult:
    git = GitRepo(repo_path)
    git.ensure_repo()
    git.assert_origin_contains(expected_origin)

    if create_branch:
        git.create_and_checkout(create_branch, branch)
        active_branch = create_branch
    else:
        git.checkout(branch)
        active_branch = branch

    gateway = _build_gateway(config)
    blocks = scan_xfails(repo_path, test_paths)
    decisions = evaluate_blocks(blocks, gateway)
    removable = [item for item in decisions if item.should_remove]
    remaining = [item for item in decisions if not item.should_remove]

    grouped = _group_removals_by_file(removable)
    updated_files: list[str] = []
    for file_path, file_blocks in grouped.items():
        changed = _remove_block_lines(file_path, file_blocks)
        if changed:
            updated_files.append(str(file_path.relative_to(repo_path)))

    commit_sha = None
    commit_message = build_commit_message(
        removable=removable,
        repo_path=repo_path,
        person_name=person_name,
        person_email=person_email,
    )
    if do_commit and updated_files and git.has_changes():
        commit_sha = git.commit_all(message=commit_message)

    return CleanupResult(
        branch=active_branch,
        total_xfails=len(blocks),
        removable=removable,
        remaining=remaining,
        updated_files=sorted(updated_files),
        planned_files=sorted({str(item.block.file_path.relative_to(repo_path)) for item in removable}),
        proposed_commit_message=commit_message,
        commit_sha=commit_sha,
    )
