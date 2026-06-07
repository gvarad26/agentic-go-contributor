"""Write the run artifacts to disk.

For each run we emit a self-contained directory so the result is easy to review
and compare against an accepted PR:

  analysis.json   structured output of the exploration phase
  change.patch    unified diff of the agent's changes
  pr.md           generated PR title + body
  transcript.md   per-phase tool calls and model messages
  run.log         the full run log
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Tuple

from agent.issues import Issue
from agent.repository import RepoContext


def _render_transcript(phases: Dict[str, List[Tuple[str, str]]]) -> str:
    out: List[str] = ["# Run transcript", ""]
    for phase, events in phases.items():
        out.append(f"## Phase: {phase}")
        out.append("")
        for kind, detail in events:
            if kind == "tool":
                out.append(f"- **tool call** `{detail}`")
            elif kind == "result":
                snippet = detail.replace("\n", " ")[:200]
                out.append(f"  - result: {snippet}")
            elif kind == "thinking":
                out.append(f"- _thinking_: {detail[:300]}")
            elif kind == "text":
                out.append(f"- model: {detail[:600]}")
        out.append("")
    return "\n".join(out)


def write_artifacts(
    *,
    output_dir: str,
    issue: Issue,
    ctx: RepoContext,
    analysis: dict,
    diff: str,
    pr: dict,
    phases: Dict[str, List[Tuple[str, str]]],
    run_log: str,
) -> str:
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "analysis.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {
                "repo": issue.repo,
                "issue_number": issue.number,
                "issue_title": issue.title,
                "base_ref": ctx.base_ref,
                "branch": ctx.branch,
                "analysis": analysis,
            },
            fh,
            indent=2,
        )

    with open(os.path.join(output_dir, "change.patch"), "w", encoding="utf-8") as fh:
        fh.write(diff or "")

    title = pr.get("title", f"Fix issue #{issue.number}")
    body = pr.get("body", "")
    with open(os.path.join(output_dir, "pr.md"), "w", encoding="utf-8") as fh:
        fh.write(f"# {title}\n\n{body}\n")

    with open(os.path.join(output_dir, "transcript.md"), "w", encoding="utf-8") as fh:
        fh.write(_render_transcript(phases))

    with open(os.path.join(output_dir, "run.log"), "w", encoding="utf-8") as fh:
        fh.write(run_log)

    return output_dir
