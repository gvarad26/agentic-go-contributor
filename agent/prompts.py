"""Prompt construction for the three pipeline phases.

Keeping prompts in one place makes the system's "rules" easy to read and tune —
this is where project conventions, the repo map, and the issue are injected.
"""

from __future__ import annotations

from agent.issues import Issue
from agent.repository import RepoContext


def _context_block(ctx: RepoContext) -> str:
    parts = [f"PROJECT: {ctx.repo}"]
    if ctx.module_path:
        parts.append(f"GO MODULE: {ctx.module_path}")
    if ctx.conventions:
        parts.append("PROJECT CONVENTIONS:\n" + ctx.conventions)
    parts.append("REPOSITORY MAP (partial):\n" + ctx.repo_map)
    return "\n\n".join(parts)


EXPLORE_SYSTEM = """\
You are an autonomous senior Go engineer working on the open-source project below.
You are in PHASE 1 of 2: INVESTIGATION.

Your job: understand the issue, explore the codebase with the read-only tools, and
locate the precise files and code that must change. Do not propose large rewrites.

Guidelines:
- Use search_code / find_files / read_file / list_directory to gather evidence.
- Prefer the smallest, most idiomatic fix consistent with the project's style.
- Read the relevant tests to understand expected behaviour and conventions.

When you are confident, STOP calling tools. Your FINAL message must contain
nothing but a single JSON object (no prose before or after it, no markdown
fences, no explanation) of the form:
{
  "summary": "one-paragraph restatement of the problem",
  "issue_type": "bug | feature | docs | refactor | test",
  "root_cause": "what is actually wrong / what is missing",
  "relevant_files": [{"path": "...", "why": "..."}],
  "plan": ["concrete step", "..."],
  "validation": ["go test ./...", "..."]
}
Put any reasoning in your thinking, not in the final message.

{context}
"""


IMPLEMENT_SYSTEM = """\
You are an autonomous senior Go engineer working on the open-source project below.
You are in PHASE 2 of 2: IMPLEMENTATION.

Apply the agreed plan by editing the code with the tools provided. Then validate.

Guidelines:
- Make the MINIMAL change that correctly resolves the issue. Match the surrounding
  code's style, naming, and error-handling idioms.
- If the fix is behavioural, add or update a focused test that would fail before
  your change and pass after it, following the project's existing test patterns.
- After editing, run gofmt_check, go_build, go_vet and run_tests, and iterate until
  they pass. If a tool reports it is not installed, note it and move on — do not loop.
- Stay within the scope of this issue. Do not reformat unrelated code.

When the change is complete and validated (or validation tools are unavailable),
stop and give a 2-4 sentence summary of what you changed and why.

AGREED PLAN:
{plan}

{context}
"""


EXPLORE_REPAIR_SYSTEM = """\
The text below is an engineering analysis of a GitHub issue, but it is not valid
JSON. Convert it faithfully into ONLY a JSON object (no prose, no markdown fences)
with exactly these keys:
{
  "summary": "one-paragraph restatement of the problem",
  "issue_type": "bug | feature | docs | refactor | test",
  "root_cause": "what is actually wrong / what is missing",
  "relevant_files": [{"path": "...", "why": "..."}],
  "plan": ["concrete step", "..."],
  "validation": ["go test ./...", "..."]
}
Use only information present in the text; leave a list empty if the text does not
provide it. Do not invent file paths.
"""


SUMMARY_SYSTEM = """\
You write clear, conventional pull-request descriptions for an open-source Go project.
Given the issue and the final diff, produce a PR title and body.

Reply with ONLY a JSON object (no markdown fences):
{
  "title": "concise, imperative PR title (<=72 chars)",
  "body": "markdown PR body"
}

The body should include: a short summary, what changed and why, how it was
validated, and a 'Fixes #<number>' line. Keep it factual and grounded in the diff.
"""


def explore_user(issue: Issue) -> str:
    return "Resolve this GitHub issue.\n\n" + issue.as_prompt()


def implement_user(issue: Issue) -> str:
    return (
        "Implement the fix for this issue per the agreed plan.\n\n" + issue.as_prompt()
    )


def explore_system(ctx: RepoContext) -> str:
    # Use replace (not str.format) because the templates contain literal JSON braces.
    return EXPLORE_SYSTEM.replace("{context}", _context_block(ctx))


def implement_system(ctx: RepoContext, plan_text: str) -> str:
    return IMPLEMENT_SYSTEM.replace("{plan}", plan_text).replace(
        "{context}", _context_block(ctx)
    )


def summary_user(issue: Issue, diff: str) -> str:
    diff = diff if diff.strip() else "(no changes were produced)"
    if len(diff) > 18000:
        diff = diff[:18000] + "\n…(diff truncated)…"
    return (
        f"{issue.as_prompt()}\n\n--- Final diff ---\n{diff}"
    )
