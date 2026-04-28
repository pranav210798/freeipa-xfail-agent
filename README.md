# freeipa-xfail-agent

Agentic workflow to clean up stale `pytest.mark.xfail` markers in FreeIPA tests by checking linked JIRA and Pagure tickets.

The tool:

- scans `ipatests/test_integration` and `ipatests/test_xmlrpc` (or custom paths)
- extracts ticket references from xfail decorators
- checks ticket status through read-only APIs
- removes xfails only when linked tickets are closed
- distinguishes plain vs conditional xfail markers
- supports interactive terminal selection (arrow keys + checkbox)
- supports branch-aware workflows and optional commit preparation
- exposes both a CLI and an MCP server

## Why this exists

In long-lived branches, xfails often remain even after tickets are resolved. This project helps continuously align tests with current tracker state and produce review-ready changes.

## Quick start

1) Install:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

2) Set environment variables (read-only tokens):

```bash
export JIRA_BASE_URL="https://your-jira.example.com"
export JIRA_EMAIL="you@example.com"
export JIRA_API_TOKEN="***"
```

Pagure variables are optional for FreeIPA public issues. The tool defaults to `https://pagure.io` and can use anonymous reads:

```bash
# Optional only:
# export PAGURE_BASE_URL="https://pagure.io"
# export PAGURE_API_TOKEN="***"
```

3) See branches:

```bash
freeipa-xfail branches --repo-path /path/to/freeipa
```

4) Dry-run scan:

```bash
freeipa-xfail scan \
  --repo-path /path/to/freeipa \
  --branch master \
  --expected-origin your-github-username \
  --path ipatests/test_integration \
  --path ipatests/test_xmlrpc
```

The dry-run output includes:

- planned files
- proposed commit message

5) Apply removal for closed tickets:

```bash
freeipa-xfail apply \
  --repo-path /path/to/freeipa \
  --branch master \
  --create-branch xfail-cleanup-master \
  --expected-origin your-github-username \
  --commit
```

For interactive selection with keyboard controls:

```bash
freeipa-xfail apply \
  --repo-path /path/to/freeipa \
  --branch master \
  --interactive \
  --xfail-selection all
```

To **only try the checkbox UI** (up/down, space) with **no file edits and no commit**, combine `--interactive` and `--dry-run`:

```bash
freeipa-xfail apply \
  --repo-path /path/to/freeipa \
  --branch master \
  --interactive \
  --dry-run \
  --xfail-selection all
```

After you confirm the selection, the tool prints what would be removed and exits. It does not ask for apply confirmation and does not touch the working tree.

Options:

- `--interactive`: opens a checkbox selector (up/down arrows to navigate, space to toggle)
- in the same selector, press `v` to preview the currently highlighted testcase snippet and `b`/`Esc` to return
- `--xfail-selection`: choose `all`, `plain-only`, or `conditional-only`
- `--commit-strategy`: choose `batch` (single commit) or `single` (one commit per selected xfail)
- `--push`: push commits to origin automatically

`--expected-origin` is a safety guard. If your repository `origin` URL does not contain the given text, the command stops without making changes.

If you want to use the `apply` command in preview-only mode:

```bash
freeipa-xfail apply \
  --repo-path /path/to/freeipa \
  --branch master \
  --expected-origin your-github-username \
  --dry-run
```

## Terminal colors

The CLI uses [Rich](https://github.com/Textualize/rich) (widely used, maintained) for tables and progress output. It follows common conventions:

- If **`NO_COLOR`** is set (any value), colors are disabled.
- If stdout is not a TTY (pipes, some IDE panels), colors are off unless you set **`FORCE_COLOR=1`** or **`CLICOLOR_FORCE=1`**.
- Interactive checkbox labels avoid `[brackets]` because [questionary](https://github.com/tmbo/questionary) / prompt_toolkit treats `[...]` as markup.

## MCP server

Run the MCP server:

```bash
freeipa-xfail-mcp
```

Provided tools:

- `list_branches`
- `scan_xfails`
- `plan_xfail_cleanup`
- `apply_xfail_cleanup`

## Safety behavior

- xfail removal occurs only when:
  - an xfail block contains a ticket link/key
  - tracker status is recognized as closed
- ambiguous or inaccessible tickets are kept as-is
- conditional xfails can be filtered and reviewed separately before removal
- dry-run mode is default behavior for planning

## Status mapping defaults

- JIRA closed statuses:
  - `done`, `closed`, `resolved`
- Pagure closed statuses:
  - `closed`

