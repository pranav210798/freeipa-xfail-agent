#!/usr/bin/env bash
set -euo pipefail

workspace_root="$(pwd)"
cursor_dir="${workspace_root}/.cursor"
rules_dir="${cursor_dir}/rules"
template_dir="${workspace_root}/cursor-config"
template_mcp="${template_dir}/mcp.json"
template_rule="${template_dir}/rules/xfail.mdc"
target_mcp="${cursor_dir}/mcp.json"
target_rule="${rules_dir}/xfail.mdc"

if [[ ! -f "${template_mcp}" ]]; then
  echo "Template missing: ${template_mcp}"
  exit 1
fi

if [[ ! -f "${template_rule}" ]]; then
  echo "Template missing: ${template_rule}"
  exit 1
fi

mkdir -p "${rules_dir}"

if [[ -f "${target_mcp}" ]]; then
  if rg -n '"freeipa-xfail-agent"' "${target_mcp}" >/dev/null 2>&1; then
    echo "Found existing freeipa-xfail-agent entry in .cursor/mcp.json"
  else
    echo ".cursor/mcp.json already exists. Merge this block into mcpServers manually:"
    echo
    python3 - <<'PY'
import json
from pathlib import Path

template = json.loads(Path("cursor-config/mcp.json").read_text(encoding="utf-8"))
server = template.get("mcpServers", {}).get("freeipa-xfail-agent")
print(json.dumps({"freeipa-xfail-agent": server}, indent=2))
PY
    echo
  fi
else
  cp "${template_mcp}" "${target_mcp}"
  echo "Installed .cursor/mcp.json"
fi

cp "${template_rule}" "${target_rule}"
echo "Installed .cursor/rules/xfail.mdc"
echo
echo "Restart Cursor to reload MCP configuration."
echo "Then open chat and type: /xfail-plan"
