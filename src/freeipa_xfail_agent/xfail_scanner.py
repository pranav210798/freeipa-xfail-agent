from __future__ import annotations

import ast
import re
from pathlib import Path

from .models import XfailBlock, XfailKind
from .ticket_parser import extract_ticket_refs

TEST_DEF_RE = re.compile(r"^\s*def\s+(test_[A-Za-z0-9_]+)\s*\(")


def _collect_test_spans(lines: list[str]) -> list[tuple[int, int, str]]:
    source = "\n".join(lines) + "\n"
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    spans: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        start_line = int(getattr(node, "lineno", 0) or 0)
        end_line = int(getattr(node, "end_lineno", start_line) or start_line)
        if node.decorator_list:
            start_line = min(
                start_line,
                min(int(getattr(deco, "lineno", start_line) or start_line) for deco in node.decorator_list),
            )
        spans.append((start_line, end_line, node.name))

    return spans


def _resolve_test_name(
    start_line: int,
    end_line: int,
    lines: list[str],
    test_spans: list[tuple[int, int, str]],
) -> str | None:
    for span_start, span_end, name in test_spans:
        if span_start <= start_line <= span_end or span_start <= end_line <= span_end:
            return name

    # Fallback for uncommon patterns: probe forward to next test def.
    probe_idx = end_line
    total = len(lines)
    while probe_idx < total:
        probe_line = lines[probe_idx]
        match = TEST_DEF_RE.match(probe_line)
        if match:
            return match.group(1)
        if probe_line.strip() and not probe_line.lstrip().startswith("@"):
            break
        probe_idx += 1

    return None


def _iter_python_files(repo_path: Path, relative_paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for rel in relative_paths:
        root = (repo_path / rel).resolve()
        if not root.exists():
            continue
        if root.is_file() and root.suffix == ".py":
            files.append(root)
            continue
        files.extend(sorted(root.rglob("*.py")))
    return files


def _classify_xfail_kind(text: str) -> XfailKind:
    stripped = text.strip()
    expr = stripped[1:].strip() if stripped.startswith("@") else stripped
    if not expr:
        return XfailKind.PLAIN

    try:
        parsed = ast.parse(expr, mode="eval")
    except SyntaxError:
        return XfailKind.PLAIN

    call = parsed.body
    if not isinstance(call, ast.Call):
        return XfailKind.PLAIN

    if any(keyword.arg == "condition" for keyword in call.keywords if keyword.arg):
        return XfailKind.CONDITIONAL

    if not call.args:
        return XfailKind.PLAIN

    first_arg = call.args[0]
    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        return XfailKind.PLAIN

    return XfailKind.CONDITIONAL


def _extract_xfail_blocks(file_path: Path) -> list[XfailBlock]:
    lines = file_path.read_text(encoding="utf-8").splitlines()
    test_spans = _collect_test_spans(lines)
    blocks: list[XfailBlock] = []
    i = 0
    total = len(lines)

    while i < total:
        line = lines[i]
        if "xfail" not in line:
            i += 1
            continue

        # Handle decorator or inline marker with parenthesis balancing.
        start = i
        snippet = [line]
        balance = line.count("(") - line.count(")")
        i += 1

        while i < total and balance > 0:
            snippet.append(lines[i])
            balance += lines[i].count("(") - lines[i].count(")")
            i += 1

        text = "\n".join(snippet)
        if "xfail" in text:
            block_start = start + 1
            block_end = start + len(snippet)
            test_name = _resolve_test_name(
                start_line=block_start,
                end_line=block_end,
                lines=lines,
                test_spans=test_spans,
            )

            block = XfailBlock(
                file_path=file_path,
                start_line=block_start,
                end_line=block_end,
                test_name=test_name,
                text=text,
                kind=_classify_xfail_kind(text),
                tickets=extract_ticket_refs(text),
            )
            blocks.append(block)

    return blocks


def scan_xfails(repo_path: Path, relative_paths: list[str]) -> list[XfailBlock]:
    results: list[XfailBlock] = []
    for py_file in _iter_python_files(repo_path, relative_paths):
        results.extend(_extract_xfail_blocks(py_file))
    return results
