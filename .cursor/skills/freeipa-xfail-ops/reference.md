# FreeIPA Xfail Ops Reference

## MCP server
- Server name: `user-freeipa-xfail-agent`
- Tool descriptors location:
  - `.cursor/projects/.../mcps/user-freeipa-xfail-agent/tools/*.json` in local Cursor state
- Per-user defaults supported via environment:
  - `FREEIPA_XFAIL_REPO_PATH`
  - `FREEIPA_XFAIL_BRANCH`
  - `FREEIPA_XFAIL_EXPECTED_ORIGIN`
  - `FREEIPA_XFAIL_PERSON_NAME`
  - `FREEIPA_XFAIL_PERSON_EMAIL`

## Tool contracts

### `get_runtime_defaults`
Required:
- none

Returns:
- resolved `repo_path`
- resolved `branch`
- resolved `expected_origin`
- resolved sign-off identity (if configured)

### `list_branches`
Required:
- none

Optional:
- `repo_path: string | null`

Returns:
- `repo_path`
- `branches`

### `scan_xfails`
Required:
- none

Optional:
- `repo_path: string | null`
- `branch: string | null` (default from env, else `master`)
- `paths: list[string] | null`
- `expected_origin: string | null`
- `person_name: string | null`
- `person_email: string | null`
- `selection: string` (`all`, `plain-only`, `conditional-only`)
- `selected_keys: list[string] | null`

Returns (key fields):
- `total_xfails`
- `removable_count`
- `remaining_count`
- `planned_files`
- `proposed_commit_message`
- `removable[]` with file/line/reason/tickets

### `plan_xfail_cleanup`
Required:
- none

Optional:
- `repo_path: string | null`
- `branch: string | null` (default from env, else `master`)
- `paths: list[string] | null`
- `expected_origin: string | null`
- `person_name: string | null`
- `person_email: string | null`
- `selection: string` (`all`, `plain-only`, `conditional-only`)
- `selected_keys: list[string] | null`

Returns (key fields):
- `total_xfails`
- `removable_count`
- `remaining_count`
- `planned_files`
- `proposed_commit_message`
- `remaining[]` with file/line/reason/tickets

### `apply_xfail_cleanup`
Required:
- none

Optional:
- `repo_path: string | null`
- `branch: string | null` (default from env, else `master`)
- `paths: list[string] | null`
- `create_branch: string | null`
- `do_commit: bool` (default `false`)
- `commit_strategy: string` (`batch`, `single`)
- `push: bool` (default `false`)
- `expected_origin: string | null`
- `person_name: string | null`
- `person_email: string | null`
- `selection: string` (`all`, `plain-only`, `conditional-only`)
- `selected_keys: list[string] | null`

Returns (key fields):
- `updated_files`
- `planned_files`
- `proposed_commit_message`
- `commit_sha`
- counts for total/removable/remaining

### `analyze_xfail_candidates`
Required:
- none

Optional:
- same planning inputs as `plan_xfail_cleanup`

Returns:
- `candidate_count`, `high_risk_count`, `medium_risk_count`
- `analyses[]` with recommendation, risk score, and rationale

### `explain_conditional_xfails`
Required:
- none

Optional:
- same planning inputs as `plan_xfail_cleanup`

Returns:
- `conditional_count`
- `conditional_details[]` with remove_candidate and ticket state rationale

### `improve_commit_message`
Required:
- none

Optional:
- same planning inputs as `plan_xfail_cleanup`
- `current_message: string | null`

Returns:
- `original_message`
- `suggested_message`
- `improvements[]`

### `generate_review_summary`
Required:
- none

Optional:
- same planning inputs as `plan_xfail_cleanup`

Returns:
- `summary_markdown`
- removable/remaining counts

## Agent operating checklist
1. Read tool schema before any MCP call.
2. Prefer plan/scan for ambiguous requests.
3. Ask confirmation before apply/commit/push.
4. If user asks for "analysis", report:
   - removable vs remaining count
   - reason categories
   - conditional-xfail risk notes
   - improved commit message draft
5. If tracker responses are incomplete or erroring, treat affected candidates as keep/manual-review.

