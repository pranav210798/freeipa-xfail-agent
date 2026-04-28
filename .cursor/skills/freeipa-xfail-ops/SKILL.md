---
name: freeipa-xfail-ops
description: Operate FreeIPA xfail cleanup in this repository through MCP tools first, with shell fallback for repo checks. Use when user asks to scan/plan/apply xfail cleanup, filter conditional or plain xfails, review proposed commit messages, or request safer AI analysis before apply.
---

# FreeIPA Xfail Ops

## Scope
Use this skill for this project's xfail maintenance workflow:
- discover branches
- scan and plan xfail cleanup
- analyze plain vs conditional xfails
- improve operator-facing summary and commit message quality
- apply cleanup only after explicit confirmation

## Mandatory execution order
1. Read MCP tool schema from the local MCP descriptor files.
2. Resolve runtime defaults via MCP (`get_runtime_defaults`) when repo/branch are not explicitly provided.
3. Choose MCP-first path for supported operations.
4. Use shell only for tasks outside MCP coverage (for example `git status`).
5. Before apply/commit/push, ask for explicit user confirmation.

## MCP-first command mapping
- Branch listing:
  - MCP: `list_branches(repo_path=...)`
  - CLI equivalent: `freeipa-xfail branches --repo-path ...`
- Scan/preview:
  - MCP: `scan_xfails(...)`
  - CLI equivalent: `freeipa-xfail scan ...`
- Plan without file edits:
  - MCP: `plan_xfail_cleanup(...)`
  - CLI equivalent: `freeipa-xfail apply --dry-run ...`
- Apply changes:
  - MCP: `apply_xfail_cleanup(...)`
  - CLI equivalent: `freeipa-xfail apply ...`

## Analysis policy (AI-assisted, tool-safe)
When user asks for "analysis", "better quality", or "make it safe":
1. Run `plan_xfail_cleanup`.
2. Run `analyze_xfail_candidates` for risk scoring.
3. Run `explain_conditional_xfails` to focus conditional markers.
4. Run `improve_commit_message` to refine the draft.
5. Run `generate_review_summary` when reviewer-ready output is requested.
6. Stop before apply until user confirms.

## Safety gates
- Default to plan/scan when intent is ambiguous.
- Never run apply as an implicit side effect of analysis.
- Keep xfails when tracker status is unknown/error/incomplete.
- Keep `expected_origin` guard when provided by user.

## Output format
Return concise sections:
1. `Plan summary`
2. `Risk notes (especially conditional xfails)`
3. `Commit message draft`
4. `Next action` (wait for confirmation or run apply)

## Validation checkpoints
- Prompt: "scan all xfails on master and show risk notes"
- Prompt: "plan cleanup and explain only conditional xfails"
- Prompt: "improve commit message before apply"
- Prompt: "generate review summary and stop before write"
- Prompt: "apply cleanup with selection plain-only and commit_strategy single"

## Fallback behavior
If a requested action is not covered by MCP tools:
- run shell commands for repo-inspection-only tasks
- keep output concise and actionable
- do not perform destructive git operations without explicit request

