# FreeIPA Xfail Ops Examples

## Example 1: branch and scan
User prompt:
"List branches and scan xfails on master."

Expected behavior:
1. Read MCP schemas.
2. Call `list_branches`.
3. Call `scan_xfails` with `branch="master"`.
4. Return branch list and scan summary.

## Example 1b: org defaulted MCP usage
User prompt:
"Plan cleanup and explain only conditional xfails."

Expected behavior:
1. Use MCP defaults (`FREEIPA_XFAIL_REPO_PATH`, `FREEIPA_XFAIL_BRANCH`) when args are omitted.
2. Call `plan_xfail_cleanup`.
3. Call `explain_conditional_xfails`.
4. Return summary without requiring path in prompt.

## Example 2: conditional-focused analysis
User prompt:
"Plan cleanup and focus on conditional xfails, no apply yet."

Expected behavior:
1. Call `plan_xfail_cleanup`.
2. Analyze removable/remaining and isolate conditional xfail findings.
3. Explain risk and blockers.
4. Wait for confirmation.

## Example 3: improve commit message before apply
User prompt:
"Plan first, then improve commit message quality."

Expected behavior:
1. Call `plan_xfail_cleanup`.
2. Read `proposed_commit_message`.
3. Produce a refined draft that keeps the same facts (tests/files/tickets).
4. Ask whether to apply with commit.

## Example 4: apply after confirmation
User prompt:
"Apply cleanup on master and commit."

Expected behavior:
1. Confirm intent explicitly.
2. Call `apply_xfail_cleanup` with `do_commit=true`.
3. Return updated files and `commit_sha`.

## Example 5: MCP + shell fallback
User prompt:
"Plan cleanup, then show git status and diff stats."

Expected behavior:
1. MCP: `plan_xfail_cleanup`.
2. Shell fallback: repo status/diff stats.
3. Provide combined report.

