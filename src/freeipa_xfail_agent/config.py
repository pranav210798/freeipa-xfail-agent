from __future__ import annotations

from dataclasses import dataclass
from os import getenv

from dotenv import load_dotenv


@dataclass(frozen=True)
class JiraConfig:
    base_url: str
    email: str
    api_token: str
    closed_statuses: frozenset[str]


@dataclass(frozen=True)
class PagureConfig:
    base_url: str
    api_token: str | None
    closed_statuses: frozenset[str]


@dataclass(frozen=True)
class AppConfig:
    jira: JiraConfig | None
    pagure: PagureConfig


def _split_statuses(value: str | None, default: tuple[str, ...]) -> frozenset[str]:
    if not value:
        return frozenset(default)
    return frozenset(part.strip().lower() for part in value.split(",") if part.strip())


def load_config() -> AppConfig:
    load_dotenv()

    jira_base = getenv("JIRA_BASE_URL", "").strip()
    jira_email = getenv("JIRA_EMAIL", "").strip()
    jira_token = getenv("JIRA_API_TOKEN", "").strip()

    jira_cfg: JiraConfig | None = None
    if jira_base and jira_email and jira_token:
        jira_cfg = JiraConfig(
            base_url=jira_base.rstrip("/"),
            email=jira_email,
            api_token=jira_token,
            closed_statuses=_split_statuses(
                getenv("JIRA_CLOSED_STATUSES"),
                ("done", "closed", "resolved"),
            ),
        )

    pagure_cfg = PagureConfig(
        base_url=getenv("PAGURE_BASE_URL", "https://pagure.io").strip().rstrip("/"),
        api_token=getenv("PAGURE_API_TOKEN", None),
        closed_statuses=_split_statuses(getenv("PAGURE_CLOSED_STATUSES"), ("closed",)),
    )

    return AppConfig(jira=jira_cfg, pagure=pagure_cfg)
