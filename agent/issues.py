"""Fetching and parsing GitHub issues.

We use the ``gh`` CLI when available (it handles auth transparently), and fall
back to a local JSON file for offline runs. The four approved repositories are
encoded here only as a convenience for validation/messaging — any ``owner/repo``
is accepted.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

APPROVED_REPOS = {
    "gin-gonic/gin",
    "spf13/cobra",
    "go-playground/validator",
    "golangci/golangci-lint",
}

_ISSUE_URL_RE = re.compile(
    r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)"
)


@dataclass
class Issue:
    """A normalized view of a GitHub issue."""

    repo: str  # "owner/repo"
    number: int
    title: str
    body: str
    url: str
    labels: List[str] = field(default_factory=list)
    comments: List[str] = field(default_factory=list)

    def as_prompt(self) -> str:
        """Render the issue as text for inclusion in a model prompt."""
        parts = [
            f"Repository: {self.repo}",
            f"Issue #{self.number}: {self.title}",
            f"URL: {self.url}",
        ]
        if self.labels:
            parts.append("Labels: " + ", ".join(self.labels))
        parts.append("")
        parts.append("--- Issue body ---")
        parts.append(self.body.strip() or "(no body)")
        if self.comments:
            parts.append("")
            parts.append("--- Discussion (most relevant comments) ---")
            for i, c in enumerate(self.comments[:8], 1):
                parts.append(f"[comment {i}]\n{c.strip()}")
        return "\n".join(parts)


def parse_issue_reference(reference: str, repo: Optional[str] = None):
    """Resolve a URL or bare number into (repo, number).

    ``reference`` may be a full GitHub issue URL or a plain issue number. When a
    bare number is given, ``repo`` must be supplied.
    """
    m = _ISSUE_URL_RE.search(reference)
    if m:
        owner_repo = f"{m.group('owner')}/{m.group('repo')}"
        return owner_repo, int(m.group("number"))

    if reference.isdigit():
        if not repo:
            raise ValueError(
                "A bare issue number requires --repo owner/repo (or pass a full URL)."
            )
        return repo, int(reference)

    raise ValueError(f"Could not parse issue reference: {reference!r}")


def fetch_issue(repo: str, number: int) -> Issue:
    """Fetch an issue via the ``gh`` CLI."""
    if shutil.which("gh") is None:
        raise RuntimeError(
            "The `gh` CLI is required to fetch issues. Install it, run `gh auth login`, "
            "or pass --issue-file to run offline."
        )

    cmd = [
        "gh", "issue", "view", str(number),
        "--repo", repo,
        "--json", "title,body,url,labels,comments,number",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"`gh issue view` failed for {repo}#{number}:\n{proc.stderr.strip()}"
        )
    data = json.loads(proc.stdout)
    return _issue_from_json(repo, data)


def load_issue_file(path: str, repo: Optional[str] = None) -> Issue:
    """Load an issue from a local JSON file (offline mode).

    The JSON shape matches ``gh issue view --json``.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    repo = repo or data.get("repo")
    if not repo:
        raise ValueError("Issue file has no 'repo' field; pass --repo owner/repo.")
    return _issue_from_json(repo, data)


def _issue_from_json(repo: str, data: dict) -> Issue:
    labels = [lbl.get("name", "") for lbl in data.get("labels", []) if isinstance(lbl, dict)]
    comments = []
    for c in data.get("comments", []):
        if isinstance(c, dict):
            author = c.get("author")
            if isinstance(author, dict):
                author = author.get("login", "?")
            comments.append(f"{author or '?'}: {c.get('body', '')}")
        elif isinstance(c, str):
            comments.append(c)
    number = int(data.get("number", 0))
    url = data.get("url") or f"https://github.com/{repo}/issues/{number}"
    return Issue(
        repo=repo,
        number=number,
        title=data.get("title", "").strip(),
        body=data.get("body", "") or "",
        url=url,
        labels=labels,
        comments=comments,
    )
