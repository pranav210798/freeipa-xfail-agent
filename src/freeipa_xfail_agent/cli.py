from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, TypeVar

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from .config import load_config
from .git_utils import GitRepo
from .models import XfailDecision, XfailKind
from .workflow import (
    CleanupResult,
    CommitStrategy,
    XfailSelection,
    apply_cleanup,
    decision_key,
    plan_cleanup,
)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _make_console() -> Console:
    """Rich Console tuned for real terminals (Cursor, VS Code, ssh, CI).

    - Honors https://no-color.org/ when ``NO_COLOR`` is set (any value).
    - Enables ANSI styles when stdout is a TTY, or when ``FORCE_COLOR`` / ``CLICOLOR_FORCE`` is set.
    """
    no_color = "NO_COLOR" in os.environ
    force_color = _env_truthy("FORCE_COLOR") or _env_truthy("CLICOLOR_FORCE")
    force_terminal = sys.stdout.isatty() or force_color
    return Console(force_terminal=force_terminal, no_color=no_color, highlight=True)


app = typer.Typer(help="FreeIPA xfail cleanup automation.")
console = _make_console()

DEFAULT_PATHS = ["ipatests/test_integration", "ipatests/test_xmlrpc"]
T = TypeVar("T")


def _collect_person_details(person_name: str | None, person_email: str | None) -> tuple[str, str]:
    name = person_name or typer.prompt("Enter your name for commit sign-off")
    email = person_email or typer.prompt("Enter your email for commit sign-off")
    return name.strip(), email.strip()


def _run_with_progress(description: str, fn: Callable[[], T]) -> T:
    progress = Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40, pulse_style="cyan"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )
    with progress:
        progress.add_task(description=description, total=None)
        return fn()


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
    if len(result.commit_shas) > 1:
        console.print(f"[bold green]Commits created:[/bold green] {len(result.commit_shas)}")


def _print_selected_removals_preview(repo_path: Path, decisions: list[XfailDecision]) -> None:
    """Show what would be removed (used for interactive + dry-run only)."""
    if not decisions:
        return
    table = Table(title="Would remove (dry run — no writes)")
    table.add_column("File")
    table.add_column("Lines")
    table.add_column("Tickets")
    for decision in decisions:
        tickets = ", ".join(status.ticket.normalized_id for status in decision.statuses) or "-"
        table.add_row(
            str(decision.block.file_path.relative_to(repo_path)),
            f"{decision.block.start_line}-{decision.block.end_line}",
            tickets,
        )
    console.print(table)


def _format_decision_choice(decision: XfailDecision, repo_path: Path) -> str:
    rel_file = str(decision.block.file_path.relative_to(repo_path))
    test_name = decision.block.test_name or "unknown_testcase"
    kind = "conditional" if decision.block.kind == XfailKind.CONDITIONAL else "plain"
    tickets = ", ".join(status.ticket.normalized_id for status in decision.statuses) or "no-issue"
    # Avoid "[...]" — questionary uses prompt_toolkit, which treats square brackets as markup.
    return (
        f"{kind}: {test_name} | {rel_file}:{decision.block.start_line}-{decision.block.end_line} | "
        f"{tickets}"
    )


def _interactive_select_removals(repo_path: Path, removable: list[XfailDecision]) -> set[str]:
    try:
        from prompt_toolkit.application import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.layout.containers import Window
        from prompt_toolkit.styles import Style
    except ImportError as exc:  # pragma: no cover - runtime dependency message
        raise RuntimeError(
            "Interactive selection requires prompt_toolkit. Install dependencies with `pip install -e .`."
        ) from exc

    key_to_decision = {decision_key(item, repo_path): item for item in removable}
    ordered_keys = list(key_to_decision.keys())
    selected: set[str] = {
        key for key in ordered_keys if key_to_decision[key].block.kind != XfailKind.CONDITIONAL
    }
    cursor = 0
    preview_mode = False
    status_message = ""
    snippet_cache: dict[str, str] = {}

    def _current_key() -> str:
        return ordered_keys[cursor]

    def _build_snippet_text(key: str) -> str:
        cached = snippet_cache.get(key)
        if cached is not None:
            return cached

        decision = key_to_decision[key]
        file_path = decision.block.file_path
        test_name = decision.block.test_name or "unknown_testcase"
        rel_file = str(file_path.relative_to(repo_path))
        lines = file_path.read_text(encoding="utf-8").splitlines()
        start_line = max(1, decision.block.start_line - 5)
        end_line = min(len(lines), decision.block.end_line + 15)

        header = [
            f"Preview: {test_name}",
            f"File: {rel_file}",
            f"Range: {decision.block.start_line}-{decision.block.end_line}",
            "",
        ]
        body = [f"{line_no:>5} | {lines[line_no - 1]}" for line_no in range(start_line, end_line + 1)]
        snippet = "\n".join(header + body)
        snippet_cache[key] = snippet
        return snippet

    def _render() -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        if preview_mode:
            fragments.append(("class:title", "XFails selector (preview mode)\n"))
            fragments.append(("class:hint", "Keys: b/esc=back, up/down=next testcase, enter=confirm selection\n\n"))
            snippets = _build_snippet_text(_current_key())
            for line in snippets.splitlines():
                fragments.append(("", line + "\n"))
        else:
            fragments.append(("class:title", "Select xfails to remove\n"))
            fragments.append(
                (
                    "class:hint",
                    "Keys: up/down=move, space=toggle, v=preview snippet, a=toggle all, i=invert, enter=confirm\n\n",
                )
            )
            for idx, key in enumerate(ordered_keys):
                marker = "●" if key in selected else "○"
                pointer = "» " if idx == cursor else "  "
                line = f"{pointer}{marker} {_format_decision_choice(key_to_decision[key], repo_path)}\n"
                style = "class:selected" if idx == cursor else ""
                fragments.append((style, line))
            if status_message:
                fragments.append(("\nclass:error", f"\n{status_message}\n"))
        return fragments

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _move_up(event) -> None:  # type: ignore[no-untyped-def]
        nonlocal cursor
        cursor = (cursor - 1) % len(ordered_keys)

    @kb.add("down")
    @kb.add("j")
    def _move_down(event) -> None:  # type: ignore[no-untyped-def]
        nonlocal cursor
        cursor = (cursor + 1) % len(ordered_keys)

    @kb.add("space")
    def _toggle(event) -> None:  # type: ignore[no-untyped-def]
        nonlocal status_message
        if preview_mode:
            return
        key = _current_key()
        if key in selected:
            selected.remove(key)
        else:
            selected.add(key)
        status_message = ""

    @kb.add("a")
    def _toggle_all(event) -> None:  # type: ignore[no-untyped-def]
        if preview_mode:
            return
        if len(selected) == len(ordered_keys):
            selected.clear()
        else:
            selected.update(ordered_keys)

    @kb.add("i")
    def _invert(event) -> None:  # type: ignore[no-untyped-def]
        if preview_mode:
            return
        inverted = {key for key in ordered_keys if key not in selected}
        selected.clear()
        selected.update(inverted)

    @kb.add("v")
    def _enter_preview(event) -> None:  # type: ignore[no-untyped-def]
        nonlocal preview_mode
        preview_mode = True

    @kb.add("b")
    @kb.add("escape")
    def _exit_preview_or_cancel(event) -> None:  # type: ignore[no-untyped-def]
        nonlocal preview_mode
        if preview_mode:
            preview_mode = False
        else:
            event.app.exit(result=None)

    @kb.add("enter")
    def _confirm(event) -> None:  # type: ignore[no-untyped-def]
        nonlocal status_message, preview_mode
        if preview_mode:
            preview_mode = False
            return
        if not selected:
            status_message = "Select at least one xfail."
            return
        event.app.exit(result=set(selected))

    @kb.add("c-c")
    def _cancel(event) -> None:  # type: ignore[no-untyped-def]
        event.app.exit(result=None)

    control = FormattedTextControl(_render, focusable=True, key_bindings=kb)
    window = Window(content=control, always_hide_cursor=True, wrap_lines=False)
    app = Application(
        layout=Layout(window),
        key_bindings=kb,
        full_screen=True,
        style=Style.from_dict(
            {
            "title": "bold",
            "hint": "fg:#888888",
            "selected": "reverse",
            "error": "fg:ansired",
            }
        ),
    )
    result: set[str] | None = app.run()
    if not result:
        return set()
    return result


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
    xfail_selection: Annotated[
        XfailSelection,
        typer.Option(help="Filter xfails by type (all, plain-only, conditional-only)"),
    ] = XfailSelection.ALL,
) -> None:
    name, email = _collect_person_details(person_name, person_email)
    result = _run_with_progress(
        "Scanning xfails and checking ticket status...",
        lambda: plan_cleanup(
            repo_path=repo_path,
            branch=branch,
            test_paths=path or DEFAULT_PATHS,
            config=load_config(),
            expected_origin=expected_origin,
            person_name=name,
            person_email=email,
            selection=xfail_selection,
        ),
    )
    _print_result(result)


@app.command("apply")
def apply(
    repo_path: Annotated[Path, typer.Option(help="Path to freeipa repository")],
    branch: Annotated[str, typer.Option(help="Base branch to use")] = "master",
    path: Annotated[list[str], typer.Option(help="Test paths to scan")] = DEFAULT_PATHS,
    create_branch: Annotated[str | None, typer.Option(help="Create/switch to this branch first")] = None,
    commit: Annotated[bool, typer.Option(help="Commit changes automatically")] = False,
    commit_strategy: Annotated[
        CommitStrategy,
        typer.Option(help="Commit mode when --commit is used: batch (single commit) or single (one per xfail)"),
    ] = CommitStrategy.BATCH,
    push: Annotated[
        bool,
        typer.Option(help="Push commits to origin after commit(s)"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            help="Preview only, no file changes. With --interactive, runs checkbox UI then exits without applying."
        ),
    ] = False,
    yes: Annotated[bool, typer.Option(help="Skip confirmation prompt")] = False,
    interactive: Annotated[
        bool,
        typer.Option(help="Select removable xfails via terminal checkbox UI"),
    ] = False,
    xfail_selection: Annotated[
        XfailSelection,
        typer.Option(help="Filter xfails by type (all, plain-only, conditional-only)"),
    ] = XfailSelection.ALL,
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

    # Plain dry-run: show full plan, no interactive UI
    if dry_run and not interactive:
        result = _run_with_progress(
            "Preparing dry-run plan...",
            lambda: plan_cleanup(
                repo_path=repo_path,
                branch=branch,
                test_paths=path or DEFAULT_PATHS,
                config=load_config(),
                expected_origin=expected_origin,
                person_name=name,
                person_email=email,
                selection=xfail_selection,
            ),
        )
        _print_result(result)
        return

    selected_keys: set[str] | None = None
    if interactive:
        preview = _run_with_progress(
            "Building interactive xfail selection list...",
            lambda: plan_cleanup(
                repo_path=repo_path,
                branch=branch,
                test_paths=path or DEFAULT_PATHS,
                config=load_config(),
                expected_origin=expected_origin,
                person_name=name,
                person_email=email,
                selection=xfail_selection,
            ),
        )
        if not preview.removable:
            console.print("No removable xfails found for selection.")
            raise typer.Exit(code=0)
        selected_keys = _interactive_select_removals(repo_path, preview.removable)
        if not selected_keys:
            console.print("No xfails selected. Cancelled.")
            raise typer.Exit(code=0)
        chosen = [
            d
            for d in preview.removable
            if decision_key(d, repo_path) in selected_keys
        ]

        if dry_run:
            console.print(
                "[bold yellow]Dry run (interactive):[/bold yellow] "
                "checkbox flow completed; repository was not modified."
            )
            _print_selected_removals_preview(repo_path, chosen)
            console.print(f"[dim]Selected {len(chosen)} removable xfail(s). Run without --dry-run to apply.[/dim]")
            raise typer.Exit(code=0)

    if not yes:
        proceed = typer.confirm(
            f"Apply xfail cleanup on branch '{create_branch or branch}'?",
            default=False,
        )
        if not proceed:
            console.print("Cancelled.")
            raise typer.Exit(code=0)

    result = _run_with_progress(
        "Applying selected xfail cleanup...",
        lambda: apply_cleanup(
            repo_path=repo_path,
            branch=branch,
            test_paths=path or DEFAULT_PATHS,
            config=load_config(),
            create_branch=create_branch,
            do_commit=commit,
            commit_strategy=commit_strategy,
            push=push,
            expected_origin=expected_origin,
            person_name=name,
            person_email=email,
            selection=xfail_selection,
            selected_keys=selected_keys,
        ),
    )
    _print_result(result)


if __name__ == "__main__":
    app()
