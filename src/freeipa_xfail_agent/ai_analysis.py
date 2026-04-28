from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .models import TicketStatus, XfailDecision, XfailKind


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class CandidateAnalysis:
    key: str
    file: str
    test_name: str
    kind: str
    tickets: list[str]
    should_remove: bool
    risk_score: float
    risk_level: RiskLevel
    recommendation: str
    rationale: str


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _risk_level(score: float) -> RiskLevel:
    if score >= 0.67:
        return RiskLevel.HIGH
    if score >= 0.34:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _has_status_errors(statuses: list[TicketStatus]) -> bool:
    return any(status.error for status in statuses)


def _status_rationale(statuses: list[TicketStatus]) -> str:
    if not statuses:
        return "No linked tickets were detected."
    parts: list[str] = []
    for status in statuses:
        state = "closed" if status.is_closed else "open"
        details = f"{status.ticket.normalized_id}={state}"
        if status.error:
            details = f"{details} (error: {status.error})"
        parts.append(details)
    return "; ".join(parts)


def _candidate_key(decision: XfailDecision, repo_path: Path) -> str:
    rel_file = str(decision.block.file_path.relative_to(repo_path))
    test_name = decision.block.test_name or "unknown_testcase"
    return f"{rel_file}:{decision.block.start_line}:{test_name}"


def analyze_candidates(
    *,
    removable: list[XfailDecision],
    remaining: list[XfailDecision],
    repo_path: Path,
) -> list[CandidateAnalysis]:
    analyses: list[CandidateAnalysis] = []
    for decision in [*removable, *remaining]:
        score = 0.10
        if decision.block.kind == XfailKind.CONDITIONAL:
            score += 0.25
        if len(decision.statuses) > 1:
            score += 0.10
        if not decision.should_remove:
            score += 0.40
        if _has_status_errors(decision.statuses):
            score += 0.35
        if any(not status.is_closed for status in decision.statuses):
            score += 0.20
        score = _clamp(score, 0.0, 1.0)
        level = _risk_level(score)

        test_name = decision.block.test_name or "unknown_testcase"
        rel_file = str(decision.block.file_path.relative_to(repo_path))
        tickets = [status.ticket.normalized_id for status in decision.statuses]
        recommendation = "remove" if decision.should_remove and level != RiskLevel.HIGH else "manual-review"
        if not decision.should_remove:
            recommendation = "keep"

        analyses.append(
            CandidateAnalysis(
                key=_candidate_key(decision, repo_path),
                file=rel_file,
                test_name=test_name,
                kind=decision.block.kind.value,
                tickets=tickets,
                should_remove=decision.should_remove,
                risk_score=round(score, 2),
                risk_level=level,
                recommendation=recommendation,
                rationale=f"{decision.reason} | {_status_rationale(decision.statuses)}",
            )
        )
    return analyses


def explain_conditional_xfails(
    *,
    removable: list[XfailDecision],
    remaining: list[XfailDecision],
    repo_path: Path,
) -> list[dict[str, str | bool]]:
    rows: list[dict[str, str | bool]] = []
    for decision in [*removable, *remaining]:
        if decision.block.kind != XfailKind.CONDITIONAL:
            continue
        rows.append(
            {
                "file": str(decision.block.file_path.relative_to(repo_path)),
                "test_name": decision.block.test_name or "unknown_testcase",
                "remove_candidate": decision.should_remove,
                "reason": decision.reason,
                "ticket_states": _status_rationale(decision.statuses),
            }
        )
    return rows


def improve_commit_message(
    *,
    current_message: str,
    removable: list[XfailDecision],
    repo_path: Path,
) -> dict[str, object]:
    signoff_lines = [line for line in current_message.splitlines() if line.lower().startswith("signed-off-by:")]
    lines = [
        "ipatests: Remove stale xfails for closed issues.",
        "",
        "Remove xfail markers for tests linked only to closed issues:",
    ]
    if not removable:
        lines.append("- no removable xfails were detected in this run")
    else:
        for decision in removable:
            test_name = decision.block.test_name or "unknown_testcase"
            rel_file = str(decision.block.file_path.relative_to(repo_path))
            tickets = ", ".join(status.ticket.normalized_id for status in decision.statuses) or "no-issue"
            lines.append(f"- {test_name} ({rel_file}:{decision.block.start_line}) [{tickets}]")
    if signoff_lines:
        lines.extend(["", *signoff_lines])

    improvements = [
        "Normalized subject for xfail cleanup intent.",
        "Switched list entries to a consistent bullet format.",
        "Preserved Signed-off-by trailers from original message.",
    ]
    return {
        "original_message": current_message,
        "suggested_message": "\n".join(lines),
        "improvements": improvements,
    }


def build_review_summary(
    *,
    removable: list[XfailDecision],
    remaining: list[XfailDecision],
    analyses: list[CandidateAnalysis],
    proposed_commit_message: str,
) -> str:
    high_risk = [item for item in analyses if item.risk_level == RiskLevel.HIGH]
    medium_risk = [item for item in analyses if item.risk_level == RiskLevel.MEDIUM]
    conditional_count = sum(1 for item in analyses if item.kind == XfailKind.CONDITIONAL.value)
    lines = [
        "## Summary",
        f"- Removable xfails: {len(removable)}",
        f"- Remaining xfails: {len(remaining)}",
        f"- Conditional xfails reviewed: {conditional_count}",
        f"- High risk candidates: {len(high_risk)}",
        f"- Medium risk candidates: {len(medium_risk)}",
        "",
        "## Commit message draft",
        "```",
        proposed_commit_message,
        "```",
    ]

    if high_risk:
        lines.extend(["", "## High risk notes"])
        for item in high_risk:
            lines.append(f"- {item.test_name} ({item.file}) -> {item.rationale}")

    if remaining:
        lines.extend(["", "## Remaining blockers"])
        for decision in remaining:
            test_name = decision.block.test_name or "unknown_testcase"
            lines.append(f"- {test_name}: {decision.reason}")
    return "\n".join(lines)
