from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .config import load_config
from .git_utils import GitRepo
from .workflow import CleanupResult, apply_cleanup, plan_cleanup

app = typer.Typer(help="FreeIPA xfail cleanup automation.")
console = Console()

DEFAULT_PATHS = ["ipatests/test_integration", "ipatests/test_xmlrpc"]


def _collect_person_details(person_name: str | None, person_email: str | None) -> tuple[str, str]:
    name = person_name or typer.prompt("Enter your name for commit sign-off")
    email = person_email or typer.prompt("Enter your email for commit sign-off")
    return name.strip(), email.strip()


def _print_result(result: CleanupResult) -> None:
    console.print(f"[bold]Branch:[/bold] {result.branch}")
    console.print(f"[bold]Total xfails scanned:[/bold] {result.total_xfails}")
    console.print(f"[bold]Removable:[/bold] {len(result.removable)}")
    console.print(f"[bold]Remaining:[/bold] {len(result.remaining)}")

    if result.removable:
        table = Table(title="Removable xfails")
        table.add_column("File")
        table.add_column("Lines")
        table.add_column("Tickets")
        for decision in result.removable:
            tickets = ", ".join(status.ticket.normalized_id for status in decision.statuses) or "-"
            table.add_row(
                str(decision.block.file_path),
                f"{decision.block.start_line}-{decision.block.end_line}",
                tickets,
            )
        console.print(table)

    if result.remaining:
        table = Table(title="Remaining xfails")
        table.add_column("File")
        table.add_column("Lines")
        table.add_column("Reason")
        for decision in result.remaining:
            error_details = "; ".join(status.error for status in decision.statuses if status.error)
            reason = decision.reason if not error_details else f"{decision.reason}: {error_details}"
            table.add_row(
                str(decision.block.file_path),
                f"{decision.block.start_line}-{decision.block.end_line}",
                reason,
            )
        console.print(table)

    if result.updated_files:
        console.print("[bold]Updated files:[/bold]")
        for file_path in result.updated_files:
            console.print(f"- {file_path}")

    if result.planned_files:
        console.print("[bold]Planned files (dry-run preview):[/bold]")
        for file_path in result.planned_files:
            console.print(f"- {file_path}")

    if result.proposed_commit_message:
        console.print("[bold]Proposed commit message:[/bold]")
        console.print(result.proposed_commit_message)

    if result.commit_sha:
        console.print(f"[bold green]Commit:[/bold green] {result.commit_sha}")


@app.command("branches")
def branches(
    repo_path: Annotated[Path, typer.Option(help="Path to freeipa repository")],
) -> None:
    git = GitRepo(repo_path=repo_path)
    names = git.list_branches()
    if not names:
        console.print("No local branches found.")
        raise typer.Exit(code=0)

    table = Table(title=f"Branches in {repo_path}")
    table.add_column("Branch")
    for name in names:
        table.add_row(name)
    console.print(table)


@app.command("scan")
def scan(
    repo_path: Annotated[Path, typer.Option(help="Path to freeipa repository")],
    branch: Annotated[str, typer.Option(help="Branch to inspect")] = "master",
    path: Annotated[list[str], typer.Option(help="Test paths to scan")] = DEFAULT_PATHS,
    expected_origin: Annotated[
        str | None,
        typer.Option(help="Safety check: origin URL must contain this text"),
    ] = None,
    person_name: Annotated[
        str | None,
        typer.Option(help="Name for Signed-off-by trailer in previewed commit message"),
    ] = None,
    person_email: Annotated[
        str | None,
        typer.Option(help="Email for Signed-off-by trailer in previewed commit message"),
    ] = None,
) -> None:
    name, email = _collect_person_details(person_name, person_email)
    result = plan_cleanup(
        repo_path=repo_path,
        branch=branch,
        test_paths=path or DEFAULT_PATHS,
        config=load_config(),
        expected_origin=expected_origin,
        person_name=name,
        person_email=email,
    )
    _print_result(result)


@app.command("apply")
def apply(
    repo_path: Annotated[Path, typer.Option(help="Path to freeipa repository")],
    branch: Annotated[str, typer.Option(help="Base branch to use")] = "master",
    path: Annotated[list[str], typer.Option(help="Test paths to scan")] = DEFAULT_PATHS,
    create_branch: Annotated[str | None, typer.Option(help="Create/switch to this branch first")] = None,
    commit: Annotated[bool, typer.Option(help="Commit changes automatically")] = False,
    dry_run: Annotated[bool, typer.Option(help="Preview only. Do not modify files")] = False,
    yes: Annotated[bool, typer.Option(help="Skip confirmation prompt")] = False,
    expected_origin: Annotated[
        str | None,
        typer.Option(help="Safety check: origin URL must contain this text"),
    ] = None,
    person_name: Annotated[
        str | None,
        typer.Option(help="Name for Signed-off-by trailer in commit message"),
    ] = None,
    person_email: Annotated[
        str | None,
        typer.Option(help="Email for Signed-off-by trailer in commit message"),
    ] = None,
) -> None:
    name, email = _collect_person_details(person_name, person_email)

    if dry_run:
        result = plan_cleanup(
            repo_path=repo_path,
            branch=branch,
            test_paths=path or DEFAULT_PATHS,
            config=load_config(),
            expected_origin=expected_origin,
            person_name=name,
            person_email=email,
        )
        _print_result(result)
        return

    if not yes:
        proceed = typer.confirm(
            f"Apply xfail cleanup on branch '{create_branch or branch}'?",
            default=False,
        )
        if not proceed:
            console.print("Cancelled.")
            raise typer.Exit(code=0)

    result = apply_cleanup(
        repo_path=repo_path,
        branch=branch,
        test_paths=path or DEFAULT_PATHS,
        config=load_config(),
        create_branch=create_branch,
        do_commit=commit,
        expected_origin=expected_origin,
        person_name=name,
        person_email=email,
    )
    _print_result(result)


if __name__ == "__main__":
    app()
