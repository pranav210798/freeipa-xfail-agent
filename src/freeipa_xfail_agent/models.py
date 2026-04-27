from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class TicketType(str, Enum):
    JIRA = "jira"
    PAGURE = "pagure"


class XfailKind(str, Enum):
    PLAIN = "plain"
    CONDITIONAL = "conditional"


@dataclass(frozen=True)
class TicketRef:
    ticket_type: TicketType
    raw: str
    normalized_id: str


@dataclass
class XfailBlock:
    file_path: Path
    start_line: int
    end_line: int
    test_name: str | None
    text: str
    kind: XfailKind = XfailKind.PLAIN
    tickets: list[TicketRef] = field(default_factory=list)


@dataclass
class TicketStatus:
    ticket: TicketRef
    is_closed: bool
    status_name: str
    source: str
    error: str | None = None


@dataclass
class XfailDecision:
    block: XfailBlock
    statuses: list[TicketStatus]
    should_remove: bool
    reason: str
