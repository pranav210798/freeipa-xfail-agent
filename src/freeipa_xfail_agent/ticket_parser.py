from __future__ import annotations

import re
from collections.abc import Iterable

from .models import TicketRef, TicketType

JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
JIRA_URL_RE = re.compile(r"/browse/([A-Z][A-Z0-9]+-\d+)\b")
PAGURE_URL_RE = re.compile(
    r"https?://(?:\w+\.)?pagure\.io/([^/\s]+)/issue/(\d+)\b", re.IGNORECASE
)


def extract_ticket_refs(text: str) -> list[TicketRef]:
    refs: list[TicketRef] = []
    seen: set[tuple[TicketType, str]] = set()

    for match in JIRA_KEY_RE.finditer(text):
        key = match.group(1).upper()
        marker = (TicketType.JIRA, key)
        if marker not in seen:
            refs.append(TicketRef(ticket_type=TicketType.JIRA, raw=match.group(0), normalized_id=key))
            seen.add(marker)

    for match in JIRA_URL_RE.finditer(text):
        key = match.group(1).upper()
        marker = (TicketType.JIRA, key)
        if marker not in seen:
            refs.append(TicketRef(ticket_type=TicketType.JIRA, raw=match.group(0), normalized_id=key))
            seen.add(marker)

    for match in PAGURE_URL_RE.finditer(text):
        project = match.group(1)
        issue_id = match.group(2)
        normalized = f"{project}#{issue_id}"
        marker = (TicketType.PAGURE, normalized)
        if marker not in seen:
            refs.append(
                TicketRef(
                    ticket_type=TicketType.PAGURE,
                    raw=match.group(0),
                    normalized_id=normalized,
                )
            )
            seen.add(marker)

    return refs


def sort_unique_refs(refs: Iterable[TicketRef]) -> list[TicketRef]:
    keyed = {(ref.ticket_type.value, ref.normalized_id): ref for ref in refs}
    return [keyed[key] for key in sorted(keyed)]
