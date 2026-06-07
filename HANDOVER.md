# Session Handover — Agentic AI Contributor for Go

Resume notes for continuing this build in a fresh session.

## What this is

A take-home assignment (PDF in repo root). Goal: build an agentic AI platform
that takes a GitHub issue from one of four approved Go repos and produces a
production-quality code change (inspect repo → understand issue → locate files →
plan → edit → run checks → generate PR title/body). Opening a real PR is optional;
a branch/patch/diff + PR summary is sufficient.

Approved repos: `gin-gonic/gin`, `spf13/cobra`, `go-playground/validator`,
`golangci/golangci-lint`.

## Decisions locked in

- **LLM backend:** Claude API via the Anthropic Python SDK (manual tool loop).
- **Language:** Python.
- **Control flow:** Hybrid — fixed pipeline stages wrapping inner tool-using loops.
- **Default model:** `claude-sonnet-4-6` (user preference), overridable via
  `AGENT_MODEL=claude-opus-4-8`.
- **No mocks / no samples.** All scripted/offline scaffolding was removed (see
  below). Every run is real: real clone, real Claude calls, real Go validation.

## Target issues (both already merged → ground truth for comparison)

- **go-playground/validator #1550** — `uuid` tag rejects uppercase UUIDs.
  Accepted PR #1551. Base commit (pre-fix tree): `b9258bd2b7bbab41c3d99090cac4a659c5f1a60c`.
  Ground-truth fix: `regexes.go` `[0-9a-f]`→`[0-9a-fA-F]` in `uUIDRegexString` + 1 test case.
- **go-playground/validator #1475** — `e164` accepts phone codes starting with `+0`.
  Accepted PR #1476. Base commit (parent of merge): `a2211184ba30847bc99b5984e108f31f6ffc9495`.
  Ground-truth fix: `regexes.go` `^\+[1-9]?[0-9]{7,14}$`→`^\+?[1-9]\d{1,14}$` + a `TestE164` func.

## Status

- Code is clean of mocks/samples; **16 unit tests pass** offline.
- Go 1.26.4 installed (Homebrew). Validator pre-cloned to `.work/`, module cache
  warmed, baseline `go build ./...` + tests green at the #1550 base.
- `gh` authenticated. `anthropic` 0.102.0 installed.
- **Blocked only on `ANTHROPIC_API_KEY`** for the live paid runs.

## What was removed in this session (the "de-mock" pass)

- `MockProvider` class (and its `_FIXED_GO`/`_FIXED_TEST` blobs) from `agent/llm.py`.
- `demo` subcommand and `--mock` flag from `agent/cli.py`; `_make_provider` helper.
- `examples/sample-repo/` (toy `stringutil` module), `examples/sample-issue.json`,
  `examples/sample-output/` (mock-generated artifacts), and stale `.work/`.
- `tests/test_issues.py` no longer reads the deleted sample; it uses an inline
  gh-shaped JSON fixture written to a temp file.
- README rewritten: removed demo/mock sections, Sonnet default, documents the two
  real target issues + a `examples/validator-<n>/` worked-examples layout.

## Architecture

```
issue → ingest → Phase A: explore (read-only) → Phase B: implement+validate → Phase C: summarize → artifacts
```

- Phase A tools: `list_directory`, `find_files`, `search_code` (ripgrep), `read_file`.
- Phase B adds: `write_file`, `edit_file`, `run_tests`, `go_build`, `go_vet`,
  `gofmt_check`, `git_diff`.
- Phase C: PR title/body grounded in the diff.

### File map
```
agent/
  cli.py          # `run` subcommand
  config.py       # env-driven Config (Sonnet default)
  issues.py       # gh fetch + URL/number parse + saved-JSON loader; APPROVED_REPOS
  repository.py   # clone/checkout, repo map, conventions, branch, collect_diff
  tools.py        # Tool dataclass; build_tools(allow_write); sandbox; _guard wrapper
  llm.py          # AnthropicProvider (manual loop, adaptive thinking+effort+fallback)
  prompts.py      # EXPLORE/IMPLEMENT/SUMMARY system prompts (use .replace, not .format!)
  pipeline.py     # run_pipeline() orchestration; RunResult
  pr.py           # write_artifacts()
examples/         # real run artifacts land in examples/validator-<n>/
tests/            # test_issues.py, test_tools.py, test_repository.py
README.md, HANDOVER.md, requirements.txt, .gitignore
```

## Important implementation notes / gotchas

- **Prompts use `str.replace`, NOT `str.format`** — templates contain literal JSON
  braces. Do not reintroduce `.format`.
- **Tool executors are wrapped by `_guard`** so exceptions become tool-result
  strings, never crashes.
- **Anthropic optional params:** thinking + `output_config.effort` are sent via
  `extra_body`; on first rejection `_optional_features` flips off and retries.
- **Thinking blocks preserved:** loop appends full `resp.content` back to messages.
- **Diff includes new files:** `collect_diff` does `git add -A` then `diff --cached`.
- `.gitignore` excludes `.work/` and `output/`; `examples/` artifacts are committed.

## How to run

```bash
cd agentic-go-contributor
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests          # 16 tests, offline

export ANTHROPIC_API_KEY=sk-ant-...
python3 -m agent run 1550 --repo go-playground/validator \
  --base-commit b9258bd2b7bbab41c3d99090cac4a659c5f1a60c --output examples/validator-1550
python3 -m agent run 1475 --repo go-playground/validator \
  --base-commit a2211184ba30847bc99b5984e108f31f6ffc9495 --output examples/validator-1475
```

## Conventions for working in this repo
- Match existing comment density and style; keep tools small/dedicated/sandboxed.
- Keep the only runtime dep = `anthropic`. Everything else via stdlib + git/gh/rg CLIs.
- Tests must stay offline (no network/API key).
