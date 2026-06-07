"""Repository preparation and inspection.

Responsibilities:
  * clone (or reuse a local checkout of) the target repo and create a work branch
  * build a compact "repo map" the model can use to orient itself
  * surface project conventions (CONTRIBUTING, go.mod module path, README)
  * stage/commit the agent's changes and produce a patch + diff

All git work is done through the CLI so the only Python dependency stays the
Anthropic SDK.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

# Directories that add noise to a repo map / search and are skipped.
_SKIP_DIRS = {".git", "vendor", "node_modules", "testdata", ".idea", ".vscode", "dist"}
_MAX_MAP_ENTRIES = 400
_CONVENTION_CHARS = 4000


@dataclass
class RepoContext:
    """Everything the rest of the system needs to know about the checkout."""

    repo: str  # owner/repo
    path: str  # absolute path to the working tree
    branch: str
    base_ref: str
    module_path: str = ""
    conventions: str = ""
    repo_map: str = ""

    @property
    def name(self) -> str:
        return self.repo.split("/")[-1]


def _git(path: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", "-C", path, *args], capture_output=True, text=True
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed:\n{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc


def prepare_repo(
    repo: str,
    *,
    workdir: str,
    issue_number: int,
    repo_path: Optional[str] = None,
    base_commit: Optional[str] = None,
) -> RepoContext:
    """Clone or reuse the repo, then create an isolated work branch.

    If ``repo_path`` points at an existing git checkout it is used in place
    (nothing is fetched); otherwise the repo is cloned under ``workdir``.
    """
    if repo_path:
        path = os.path.abspath(repo_path)
        if not os.path.isdir(os.path.join(path, ".git")):
            raise RuntimeError(f"{path} is not a git repository.")
    else:
        os.makedirs(workdir, exist_ok=True)
        path = os.path.abspath(os.path.join(workdir, repo.replace("/", "__")))
        if not os.path.isdir(os.path.join(path, ".git")):
            url = f"https://github.com/{repo}.git"
            # Full clone when we need to check out a specific historical commit
            # (e.g. to reproduce the state an accepted PR branched from),
            # otherwise a shallow clone is enough and much faster.
            args = ["clone", url, path]
            if not base_commit:
                args = ["clone", "--depth", "50", url, path]
            proc = subprocess.run(["git", *args], capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError(f"git clone failed:\n{proc.stderr.strip()}")

    # When reusing a clone from a previous run, discard any leftover changes so
    # checkout/branch recreation is deterministic. Skipped for a user-supplied
    # --repo-path so we never clobber an external working tree.
    if not repo_path:
        _git(path, "reset", "--hard", check=False)
        _git(path, "clean", "-fdq", check=False)

    if base_commit:
        _git(path, "fetch", "--depth", "50", "origin", base_commit, check=False)
        _git(path, "checkout", base_commit)

    base_ref = _git(path, "rev-parse", "HEAD").stdout.strip()
    branch = f"agent/issue-{issue_number}"
    # Recreate the branch from the base ref so reruns are deterministic.
    _git(path, "checkout", "-B", branch, base_ref)

    ctx = RepoContext(repo=repo, path=path, branch=branch, base_ref=base_ref)
    ctx.module_path = _read_module_path(path)
    ctx.conventions = _read_conventions(path)
    ctx.repo_map = build_repo_map(path)
    return ctx


def _read_module_path(path: str) -> str:
    gomod = os.path.join(path, "go.mod")
    if not os.path.isfile(gomod):
        return ""
    with open(gomod, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("module "):
                return line.split(None, 1)[1].strip()
    return ""


def _read_conventions(path: str) -> str:
    """Collect a short conventions blurb from common project files."""
    chunks: List[str] = []
    for candidate in ("CONTRIBUTING.md", "CONTRIBUTING", ".github/CONTRIBUTING.md"):
        fp = os.path.join(path, candidate)
        if os.path.isfile(fp):
            chunks.append(f"### {candidate}\n" + _read_head(fp, _CONVENTION_CHARS))
            break
    readme = os.path.join(path, "README.md")
    if os.path.isfile(readme):
        chunks.append("### README.md (excerpt)\n" + _read_head(readme, 1500))
    return "\n\n".join(chunks).strip()


def _read_head(fp: str, limit: int) -> str:
    with open(fp, "r", encoding="utf-8", errors="replace") as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        data = data[:limit] + "\n…(truncated)…"
    return data


def build_repo_map(path: str, max_depth: int = 3) -> str:
    """Produce an indented listing of the tree (bounded for prompt size)."""
    lines: List[str] = []
    root = os.path.abspath(path)
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        # Prune noisy and too-deep directories in place.
        dirnames[:] = sorted(
            d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")
        )
        if depth >= max_depth:
            dirnames[:] = []
        if rel != ".":
            lines.append("  " * (depth - 1) + os.path.basename(dirpath) + "/")
            count += 1
        for fn in sorted(filenames):
            if fn.endswith((".go", ".mod", ".md", ".yml", ".yaml", ".toml")):
                lines.append("  " * depth + fn)
                count += 1
        if count >= _MAX_MAP_ENTRIES:
            lines.append("…(repo map truncated)…")
            break
    return "\n".join(lines)


def collect_diff(ctx: RepoContext, *, commit_message: Optional[str] = None) -> str:
    """Stage all changes, return the unified diff, and optionally commit.

    Staging with ``add -A`` ensures newly created files appear in the diff.
    """
    _git(ctx.path, "add", "-A")
    diff = _git(ctx.path, "diff", "--cached").stdout
    if diff.strip() and commit_message:
        # Configure an identity locally if the environment lacks one.
        _git(ctx.path, "config", "user.email", "agent@example.com", check=False)
        _git(ctx.path, "config", "user.name", "Agentic Contributor", check=False)
        _git(ctx.path, "commit", "-m", commit_message, check=False)
    return diff
