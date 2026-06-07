"""High-level orchestration: the hybrid staged pipeline.

    ingest -> [Phase A: explore] -> [Phase B: implement+validate] -> [Phase C: summarize]

Each phase is a thin scaffold around an inner tool-using loop, which gives us the
predictability of a pipeline with the flexibility of an agent where it matters
(locating code and editing/validating it).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from agent import prompts
from agent.config import Config
from agent.issues import Issue
from agent.logging_util import RunLog
from agent.pr import write_artifacts
from agent.repository import RepoContext, collect_diff, prepare_repo
from agent.tools import build_tools


@dataclass
class RunResult:
    output_dir: str
    analysis: dict
    pr: dict
    diff: str
    changed: bool


def _analysis_from_text(provider, final_text: str, log: RunLog) -> dict:
    """Parse the explore phase's final message into the analysis dict.

    The model is asked to end Phase A with a bare JSON object. If it instead
    returns prose (it sometimes "explains" its conclusion), we don't silently
    drop to an empty plan — we ask the model once to reformat that text into the
    required JSON. Only if that also fails do we fall back to a minimal plan.
    """
    from agent.llm import extract_json

    try:
        return extract_json(final_text)
    except Exception:  # noqa: BLE001 - not JSON; attempt a repair
        log.log(
            "Phase A did not return strict JSON; asking the model to reformat it.",
            level="WARN",
        )
    try:
        analysis = provider.complete_json(
            prompts.EXPLORE_REPAIR_SYSTEM, final_text, purpose="repair"
        )
        if not isinstance(analysis, dict):
            raise ValueError("repair did not return a JSON object")
        return analysis
    except Exception as exc:  # noqa: BLE001
        log.log(f"JSON repair failed ({exc}); using a minimal plan.", level="WARN")
        return {"summary": final_text[:500], "relevant_files": [], "plan": []}


def _format_plan(analysis: dict) -> str:
    lines = []
    if analysis.get("root_cause"):
        lines.append(f"Root cause: {analysis['root_cause']}")
    for f in analysis.get("relevant_files", []):
        lines.append(f"- File {f.get('path')}: {f.get('why')}")
    for i, step in enumerate(analysis.get("plan", []), 1):
        lines.append(f"{i}. {step}")
    return "\n".join(lines) or "(no plan produced)"


def run_pipeline(
    issue: Issue,
    provider,
    config: Config,
    log: RunLog,
    *,
    repo_path: Optional[str] = None,
    base_commit: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> RunResult:
    phases: Dict[str, List[Tuple[str, str]]] = {}

    # ----- Ingest --------------------------------------------------------- #
    log.section("Preparing repository")
    ctx: RepoContext = prepare_repo(
        issue.repo,
        workdir=config.workdir,
        issue_number=issue.number,
        repo_path=repo_path,
        base_commit=base_commit,
    )
    log.log(f"Checkout: {ctx.path}")
    log.log(f"Base ref: {ctx.base_ref[:12]}  Branch: {ctx.branch}")
    if ctx.module_path:
        log.log(f"Module: {ctx.module_path}")

    # ----- Phase A: explore (read-only) ----------------------------------- #
    log.section("Phase A — Explore & locate")
    explore_schemas, explore_execs = build_tools(ctx, config, allow_write=False)
    final_text, events = provider.agent_loop(
        prompts.explore_system(ctx),
        prompts.explore_user(issue),
        explore_schemas,
        explore_execs,
    )
    phases["explore"] = events
    analysis = _analysis_from_text(provider, final_text, log)
    log.log("Relevant files: " + ", ".join(
        f.get("path", "?") for f in analysis.get("relevant_files", [])
    ) or "(none identified)")

    # ----- Phase B: implement & validate ---------------------------------- #
    log.section("Phase B — Implement & validate")
    impl_schemas, impl_execs = build_tools(ctx, config, allow_write=True)
    impl_text, impl_events = provider.agent_loop(
        prompts.implement_system(ctx, _format_plan(analysis)),
        prompts.implement_user(issue),
        impl_schemas,
        impl_execs,
    )
    phases["implement"] = impl_events
    if impl_text:
        log.log("Implementer: " + impl_text[:300])

    # ----- Collect diff --------------------------------------------------- #
    diff = collect_diff(ctx, commit_message=f"Fix #{issue.number}: {issue.title}")
    changed = bool(diff.strip())
    log.log(f"Diff: {'changes produced' if changed else 'NO changes produced'} "
            f"({len(diff)} bytes)")

    # ----- Phase C: summarize -------------------------------------------- #
    log.section("Phase C — Summarize (PR)")
    try:
        pr = provider.complete_json(
            prompts.SUMMARY_SYSTEM,
            prompts.summary_user(issue, diff),
            purpose="summary",
        )
    except Exception as exc:  # noqa: BLE001
        log.log(f"PR summarization failed ({exc}); using a fallback.", level="WARN")
        pr = {
            "title": f"Fix #{issue.number}: {issue.title}"[:72],
            "body": (analysis.get("summary", "") + f"\n\nFixes #{issue.number}."),
        }
    log.log("PR title: " + pr.get("title", ""))

    # ----- Write artifacts ----------------------------------------------- #
    if output_dir is None:
        output_dir = os.path.join(
            config.output_root, f"{ctx.name}-{issue.number}"
        )
    write_artifacts(
        output_dir=output_dir,
        issue=issue,
        ctx=ctx,
        analysis=analysis,
        diff=diff,
        pr=pr,
        phases=phases,
        run_log=log.text(),
    )
    log.section("Done")
    log.log(f"Artifacts written to: {output_dir}")
    log.log(f"Working branch '{ctx.branch}' left in {ctx.path}")

    return RunResult(
        output_dir=output_dir, analysis=analysis, pr=pr, diff=diff, changed=changed
    )
