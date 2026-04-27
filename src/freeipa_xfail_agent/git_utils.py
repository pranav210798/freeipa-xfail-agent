from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


def _run_git(repo_path: Path, *args: str) -> str:
    cmd = ["git", *args]
    completed = subprocess.run(
        cmd,
        cwd=repo_path,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


@dataclass
class GitRepo:
    repo_path: Path

    def ensure_repo(self) -> None:
        _run_git(self.repo_path, "rev-parse", "--is-inside-work-tree")

    def origin_url(self) -> str:
        return _run_git(self.repo_path, "remote", "get-url", "origin")

    def assert_origin_contains(self, expected_origin: str | None) -> None:
        if not expected_origin:
            return
        origin = self.origin_url()
        if expected_origin not in origin:
            raise ValueError(
                "Refusing to operate on unexpected repository origin. "
                f"Expected origin containing '{expected_origin}', got '{origin}'."
            )

    def current_branch(self) -> str:
        return _run_git(self.repo_path, "rev-parse", "--abbrev-ref", "HEAD")

    def list_branches(self) -> list[str]:
        output = _run_git(self.repo_path, "for-each-ref", "--format=%(refname:short)", "refs/heads")
        return [line.strip() for line in output.splitlines() if line.strip()]

    def checkout(self, branch: str) -> None:
        _run_git(self.repo_path, "checkout", branch)

    def create_and_checkout(self, branch: str, base: str) -> None:
        _run_git(self.repo_path, "checkout", "-B", branch, base)

    def has_changes(self) -> bool:
        output = _run_git(self.repo_path, "status", "--porcelain")
        return bool(output.strip())

    def commit_all(self, message: str, signoff: bool = False) -> str:
        _run_git(self.repo_path, "add", "-A")
        args = ["commit", "-m", message]
        if signoff:
            args.append("--signoff")
        _run_git(self.repo_path, *args)
        return _run_git(self.repo_path, "rev-parse", "HEAD")
