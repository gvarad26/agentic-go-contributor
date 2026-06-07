"""Command-line interface.

    python -m agent run <issue-url|number> [--repo owner/repo] [...]

``run`` resolves a real GitHub issue, clones the target repository, drives Claude
through the staged tool loop to produce a real code change, validates it with the
Go toolchain, and writes the run artifacts (patch + PR summary).
"""

from __future__ import annotations

import argparse
import sys

from agent.config import Config
from agent.issues import (
    APPROVED_REPOS,
    fetch_issue,
    load_issue_file,
    parse_issue_reference,
)
from agent.logging_util import RunLog
from agent.pipeline import run_pipeline


def cmd_run(args: argparse.Namespace) -> int:
    config = Config()
    if args.model:
        config.model = args.model
    if args.max_iterations:
        config.max_iterations = args.max_iterations
    log = RunLog(verbose=not args.quiet)

    # Resolve the issue.
    if args.issue_file:
        issue = load_issue_file(args.issue_file, repo=args.repo)
    else:
        repo, number = parse_issue_reference(args.issue, repo=args.repo)
        log.log(f"Fetching {repo}#{number} via gh …")
        issue = fetch_issue(repo, number)

    if issue.repo not in APPROVED_REPOS:
        log.log(
            f"Note: {issue.repo} is not in the approved list {sorted(APPROVED_REPOS)}; "
            "continuing anyway.",
            level="WARN",
        )

    log.log(f"Issue: {issue.repo}#{issue.number} — {issue.title}")
    from agent.llm import AnthropicProvider
    provider = AnthropicProvider(config, log)

    result = run_pipeline(
        issue,
        provider,
        config,
        log,
        repo_path=args.repo_path,
        base_commit=args.base_commit,
        output_dir=args.output,
    )
    print(f"\nDone. Changes produced: {result.changed}. See {result.output_dir}")
    return 0 if result.changed else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent",
        description="Agentic AI contributor for open-source Go projects.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Resolve a GitHub issue.")
    run.add_argument("issue", nargs="?", help="Issue URL or number (number needs --repo).")
    run.add_argument("--repo", help="owner/repo (required for a bare issue number).")
    run.add_argument("--issue-file", help="Path to a JSON issue file for offline runs.")
    run.add_argument("--repo-path", help="Use an existing local checkout instead of cloning.")
    run.add_argument("--base-commit", help="Check out this commit before working (reproducibility).")
    run.add_argument("--model", help="Override the Claude model id.")
    run.add_argument("--max-iterations", type=int, help="Max tool-loop turns per phase.")
    run.add_argument("--output", help="Output directory for artifacts.")
    run.add_argument("--quiet", action="store_true", help="Suppress streaming log to stderr.")
    run.set_defaults(func=cmd_run)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - top-level user-facing error
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
