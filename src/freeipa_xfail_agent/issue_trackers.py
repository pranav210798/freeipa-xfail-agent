from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import JiraConfig, PagureConfig
from .models import TicketRef, TicketStatus, TicketType


@dataclass
class JiraClient:
    config: JiraConfig
    timeout_seconds: float = 15.0

    def get_status(self, ticket: TicketRef) -> TicketStatus:
        if ticket.ticket_type is not TicketType.JIRA:
            raise ValueError(f"Unsupported ticket type for JiraClient: {ticket.ticket_type}")

        url = f"{self.config.base_url}/rest/api/2/issue/{ticket.normalized_id}"
        params = {"fields": "status"}

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(
                    url,
                    params=params,
                    auth=(self.config.email, self.config.api_token),
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # noqa: BLE001
            return TicketStatus(
                ticket=ticket,
                is_closed=False,
                status_name="unknown",
                source="jira",
                error=str(exc),
            )

        status_name = str(payload.get("fields", {}).get("status", {}).get("name", "unknown"))
        is_closed = status_name.strip().lower() in self.config.closed_statuses
        return TicketStatus(
            ticket=ticket,
            is_closed=is_closed,
            status_name=status_name,
            source="jira",
        )


@dataclass
class PagureClient:
    config: PagureConfig
    timeout_seconds: float = 15.0

    @staticmethod
    def _is_closed_status(status_name: str, closed_statuses: frozenset[str]) -> bool:
        normalized = status_name.strip().lower()
        if not normalized:
            return False
        if normalized in closed_statuses:
            return True
        # Pagure may return variants like "Closed: fixed".
        return any(normalized.startswith(f"{closed}:") for closed in closed_statuses)

    def _fetch_pagure_issue(
        self,
        url: str,
        headers: dict[str, str],
        trust_env: bool,
    ) -> dict:
        with httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            trust_env=trust_env,
        ) as client:
            response = client.get(url, headers=headers)
            # If token auth fails on public issue, retry without token.
            if response.status_code in (401, 403) and "Authorization" in headers:
                anon_headers = dict(headers)
                anon_headers.pop("Authorization", None)
                response = client.get(url, headers=anon_headers)
            response.raise_for_status()
            return response.json()

    def get_status(self, ticket: TicketRef) -> TicketStatus:
        if ticket.ticket_type is not TicketType.PAGURE:
            raise ValueError(f"Unsupported ticket type for PagureClient: {ticket.ticket_type}")

        try:
            project, issue_id = ticket.normalized_id.split("#", maxsplit=1)
        except ValueError:
            return TicketStatus(
                ticket=ticket,
                is_closed=False,
                status_name="unknown",
                source="pagure",
                error=f"Invalid pagure id format: {ticket.normalized_id}",
            )

        url = f"{self.config.base_url}/api/0/{project}/issue/{issue_id}"
        headers = {}
        headers["Accept"] = "application/json"
        headers["User-Agent"] = "freeipa-xfail-agent/0.1"
        if self.config.api_token:
            headers["Authorization"] = f"token {self.config.api_token}"

        try:
            payload = self._fetch_pagure_issue(url=url, headers=headers, trust_env=True)
        except httpx.ProxyError:
            # Some environments inject proxy variables that reject pagure API calls.
            try:
                payload = self._fetch_pagure_issue(url=url, headers=headers, trust_env=False)
            except Exception as exc:  # noqa: BLE001
                return TicketStatus(
                    ticket=ticket,
                    is_closed=False,
                    status_name="unknown",
                    source="pagure",
                    error=str(exc),
                )
        except Exception as exc:  # noqa: BLE001
            return TicketStatus(
                ticket=ticket,
                is_closed=False,
                status_name="unknown",
                source="pagure",
                error=str(exc),
            )

        issue = payload.get("issue", payload)
        status_name = str(issue.get("status", issue.get("state", "unknown")))
        is_closed = self._is_closed_status(status_name, self.config.closed_statuses)
        return TicketStatus(
            ticket=ticket,
            is_closed=is_closed,
            status_name=status_name,
            source="pagure",
        )


@dataclass
class TrackerGateway:
    jira: JiraClient | None
    pagure: PagureClient

    def get_status(self, ticket: TicketRef) -> TicketStatus:
        if ticket.ticket_type is TicketType.JIRA:
            if self.jira is None:
                return TicketStatus(
                    ticket=ticket,
                    is_closed=False,
                    status_name="unknown",
                    source="jira",
                    error="JIRA config missing. Set JIRA_BASE_URL/JIRA_EMAIL/JIRA_API_TOKEN.",
                )
            return self.jira.get_status(ticket)
        return self.pagure.get_status(ticket)
