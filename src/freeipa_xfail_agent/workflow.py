from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .config import AppConfig
from .git_utils import GitRepo
from .issue_trackers import JiraClient, PagureClient, TrackerGateway
from .models import TicketStatus, XfailBlock, XfailDecision, XfailKind
from .xfail_scanner import scan_xfails


class CommitStrategy(str, Enum):
    BATCH = "batch"
    SINGLE = "single"


class XfailSelection(str, Enum):
    ALL = "all"
    PLAIN_ONLY = "plain-only"
    CONDITIONAL_ONLY = "conditional-only"


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
    commit_shas: list[str] = field(default_factory=list)


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


def decision_key(decision: XfailDecision, repo_path: Path) -> str:
    rel_file = str(decision.block.file_path.relative_to(repo_path))
    test_name = decision.block.test_name or "unknown_testcase"
    digest = hashlib.sha1(
        f"{rel_file}|{test_name}|{decision.block.kind.value}|{decision.block.text}".encode("utf-8")
    ).hexdigest()
    return f"{rel_file}:{digest[:12]}"


def _filter_removable(
    removable: list[XfailDecision],
    repo_path: Path,
    selection: XfailSelection,
    selected_keys: set[str] | None,
) -> list[XfailDecision]:
    filtered: list[XfailDecision] = []
    for item in removable:
        is_conditional = item.block.kind == XfailKind.CONDITIONAL
        if selection == XfailSelection.PLAIN_ONLY and is_conditional:
            continue
        if selection == XfailSelection.CONDITIONAL_ONLY and not is_conditional:
            continue
        if selected_keys is not None and decision_key(item, repo_path) not in selected_keys:
            continue
        filtered.append(item)
    return filtered


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


def _remove_block_by_snippet(file_path: Path, block: XfailBlock) -> bool:
    raw_lines = file_path.read_text(encoding="utf-8").splitlines()
    snippet_lines = block.text.splitlines()
    if not snippet_lines:
        return False

    candidates: list[int] = []
    window = len(snippet_lines)
    max_start = len(raw_lines) - window
    for idx in range(max_start + 1):
        if raw_lines[idx : idx + window] == snippet_lines:
            candidates.append(idx)

    if not candidates:
        return False

    # Prefer the candidate closest to original line to disambiguate duplicates.
    chosen = min(candidates, key=lambda idx: abs((idx + 1) - block.start_line))
    updated = raw_lines[:chosen] + raw_lines[chosen + window :]
    file_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    return True


def _group_removals_by_file(removable: list[XfailDecision]) -> dict[Path, list[XfailBlock]]:
    grouped: dict[Path, list[XfailBlock]] = defaultdict(list)
    for decision in removable:
        grouped[decision.block.file_path].append(decision.block)
    for file_path, blocks in grouped.items():
        grouped[file_path] = sorted(blocks, key=lambda block: block.start_line, reverse=True)
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
    selection: XfailSelection = XfailSelection.ALL,
    selected_keys: set[str] | None = None,
) -> CleanupResult:
    git = GitRepo(repo_path)
    git.ensure_repo()
    git.assert_origin_contains(expected_origin)
    git.checkout(branch)

    gateway = _build_gateway(config)
    blocks = scan_xfails(repo_path, test_paths)
    decisions = evaluate_blocks(blocks, gateway)

    removable = [item for item in decisions if item.should_remove]
    removable = _filter_removable(removable, repo_path, selection, selected_keys)
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
    commit_strategy: CommitStrategy = CommitStrategy.BATCH,
    push: bool = False,
    expected_origin: str | None = None,
    person_name: str | None = None,
    person_email: str | None = None,
    selection: XfailSelection = XfailSelection.ALL,
    selected_keys: set[str] | None = None,
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
    removable = _filter_removable(removable, repo_path, selection, selected_keys)
    remaining = [item for item in decisions if not item.should_remove]

    updated_files: list[str] = []
    commit_shas: list[str] = []
    commit_message = build_commit_message(
        removable=removable,
        repo_path=repo_path,
        person_name=person_name,
        person_email=person_email,
    )

    if commit_strategy == CommitStrategy.SINGLE:
        for decision in removable:
            changed = _remove_block_by_snippet(decision.block.file_path, decision.block)
            if not changed:
                continue
            rel_file = str(decision.block.file_path.relative_to(repo_path))
            if rel_file not in updated_files:
                updated_files.append(rel_file)
            if do_commit and git.has_changes():
                single_message = build_commit_message(
                    removable=[decision],
                    repo_path=repo_path,
                    person_name=person_name,
                    person_email=person_email,
                )
                commit_shas.append(git.commit_all(message=single_message))
                if push:
                    git.push_current_branch()
    else:
        grouped = _group_removals_by_file(removable)
        for file_path, file_blocks in grouped.items():
            changed = _remove_block_lines(file_path, file_blocks)
            if changed:
                updated_files.append(str(file_path.relative_to(repo_path)))
        if do_commit and updated_files and git.has_changes():
            commit_shas.append(git.commit_all(message=commit_message))
            if push:
                git.push_current_branch()

    commit_sha = commit_shas[-1] if commit_shas else None

    return CleanupResult(
        branch=active_branch,
        total_xfails=len(blocks),
        removable=removable,
        remaining=remaining,
        updated_files=sorted(updated_files),
        planned_files=sorted({str(item.block.file_path.relative_to(repo_path)) for item in removable}),
        proposed_commit_message=commit_message,
        commit_sha=commit_sha,
        commit_shas=commit_shas,
    )
