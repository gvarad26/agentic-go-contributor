# Agentic AI Contributor for Open-Source Go Projects

A small, reviewable framework that takes a **real GitHub issue** from an approved
Go project and produces a **code change** for it: it inspects the repository,
locates the relevant files, plans a fix, edits the code, runs the Go toolchain to
validate, and generates a pull-request title and body — emitting a working branch
plus a patch and a set of review artifacts.

It is built around the **Claude API** (Anthropic SDK) with a *hybrid* design:
fixed pipeline stages wrapping inner, tool-using agent loops. There are **no
mocks and no canned outputs** — every run clones a real repo, calls the real
model, and runs real `go test`/`go vet`/`gofmt`.

---

## How it works

```
issue → [ingest] → [Phase A: explore] → [Phase B: implement+validate] → [Phase C: summarize] → artifacts
```

| Stage | What happens | Tools available |
|-------|--------------|-----------------|
| **Ingest** | Fetch the issue (`gh`), clone/checkout the repo, create a work branch, build a repo map, load conventions (`CONTRIBUTING`, `go.mod`, `README`). | — |
| **Phase A — Explore** | A **read-only** agent loop investigates the codebase and returns structured JSON: root cause, ranked relevant files, a plan, and validation commands. | `list_directory`, `find_files`, `search_code` (ripgrep), `read_file` |
| **Phase B — Implement** | A full agent loop applies the plan with minimal, idiomatic edits, then validates and iterates. | the read tools **plus** `write_file`, `edit_file`, `run_tests`, `go_build`, `go_vet`, `gofmt_check`, `git_diff` |
| **Phase C — Summarize** | Generates the PR title and body grounded in the final diff. | — |

**Why hybrid?** The staged scaffold gives predictable, inspectable structure
(explore → plan → implement → validate → summarize), while the inner loops give
the model genuine agency where it's actually needed: finding the right code and
editing/validating it. Phase A is read-only so exploration can never mutate the
tree before there's a plan.

### Design choices worth noting

- **Dedicated tools, not raw bash.** Every action has a typed schema, file paths
  are sandboxed to the repository, and command tools are limited to the Go
  toolchain. This keeps the harness in control (auditable, safe, gradeable).
- **Real validation.** Phase B runs `gofmt`, `go build`, `go vet`, and `go test`
  against the cloned module and feeds the results back to the model so it can
  iterate until they pass.
- **Adaptive thinking + effort**, with automatic fallback for models/SDKs that
  don't accept them.
- **Extensible.** Add a capability by adding one `Tool` in `agent/tools.py`; the
  model picks it up automatically. The provider is abstracted (`agent/llm.py`).
- **Reproducible.** `--base-commit <sha>` checks out the exact state an accepted
  PR branched from, which is ideal for comparing the agent's change to the real PR.

---

## Setup

Requirements: **Python 3.9+**, **git**, the **`gh` CLI** (authenticated), the
**Go toolchain** (for real validation), and (recommended) **ripgrep**.

```bash
cd agentic-go-contributor
python3 -m pip install -r requirements.txt      # installs the anthropic SDK

gh auth login                                   # so issues can be fetched
go version                                       # 1.21+ recommended
```

Provide your Anthropic key either via the environment **or a `.env` file** in the
project root (loaded automatically, stdlib-only — real env vars take precedence):

```bash
export ANTHROPIC_API_KEY=sk-ant-...             # option A: environment
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env      # option B: .env (gitignored)
```

Any `AGENT_*` setting (see below) can also live in `.env`.

---

## Running on a real issue

```bash
# By URL:
python3 -m agent run https://github.com/go-playground/validator/issues/1550

# By number + repo:
python3 -m agent run 1550 --repo go-playground/validator

# Reproduce the exact state the accepted PR branched from, for comparison:
python3 -m agent run 1550 --repo go-playground/validator --base-commit <sha>
```

Approved projects: `gin-gonic/gin`, `spf13/cobra`, `go-playground/validator`,
`golangci/golangci-lint` (any `owner/repo` is accepted; a note is logged for
others).

### Useful flags

| Flag | Purpose |
|------|---------|
| `--repo owner/repo` | Required when passing a bare issue number. |
| `--issue-file path.json` | Run from a saved real-issue JSON (matches `gh issue view --json title,body,url,labels,comments,number`). Useful without `gh` auth. |
| `--repo-path path` | Use an existing local checkout instead of cloning. |
| `--base-commit sha` | Check out a specific commit first (reproducibility). |
| `--model id` | Override the model (e.g. `claude-opus-4-8`). |
| `--max-iterations n` | Cap tool-loop turns per phase (default 40). |
| `--output dir` | Where to write artifacts. |

### Environment variables

`AGENT_MODEL` (default `claude-sonnet-4-6`), `AGENT_EFFORT` (`high`),
`AGENT_THINKING` (`1`), `AGENT_MAX_ITERATIONS` (`40`), `AGENT_MAX_TOKENS`
(`16000`), `AGENT_COMMAND_TIMEOUT` (`600`), `AGENT_WORKDIR` (`.work`),
`AGENT_OUTPUT` (`output`).

> The default model is **Sonnet** for fast, cost-effective runs. For the most
> capable (slower/pricier) runs set `AGENT_MODEL=claude-opus-4-8`.

---

## Worked examples (real issues, real PRs)

`examples/` contains the artifacts from running the agent against two real,
already-merged `go-playground/validator` issues, so its output can be compared
directly to the maintainers' accepted PRs:

| Issue | Bug | Accepted PR | Agent artifacts |
|-------|-----|-------------|-----------------|
| [#1550](https://github.com/go-playground/validator/issues/1550) | `uuid` tag rejects uppercase UUIDs | [#1551](https://github.com/go-playground/validator/pull/1551) | `examples/validator-1550/` |
| [#1475](https://github.com/go-playground/validator/issues/1475) | `e164` accepts phone codes starting with `+0` | [#1476](https://github.com/go-playground/validator/pull/1476) | `examples/validator-1475/` |

Each folder holds the full artifact set (`change.patch`, `pr.md`,
`analysis.json`, `transcript.md`, `run.log`) plus a `COMPARISON.md` noting how the
agent's change lines up with the accepted PR. Reproduce a run with:

```bash
python3 -m agent run 1550 --repo go-playground/validator \
  --base-commit <base-sha> --output examples/validator-1550
```

---

## Output

Each run writes a self-contained directory (`output/<repo>-<issue>/` by default):

| File | Contents |
|------|----------|
| `analysis.json` | Phase A structured output: root cause, relevant files, plan, validation. |
| `change.patch` | Unified diff of the agent's change (also committed on the work branch). |
| `pr.md` | Generated PR title + body. |
| `transcript.md` | Per-phase tool calls and model messages. |
| `run.log` | The full run log. |

The working branch `agent/issue-<n>` is left in the checkout with the change
committed, so you can `git diff`, push, or open a PR manually.

### Mapping to the evaluation criteria

| Criterion | Where it shows up |
|-----------|-------------------|
| Identifies the right files | `analysis.json → relevant_files`; `transcript.md` (Phase A) |
| Produces relevant code changes | `change.patch` + the committed branch |
| Follows project conventions | Conventions injected into prompts (`CONTRIBUTING`/`go.mod`/`README`); `gofmt`/`vet` in Phase B |
| Runs appropriate validation | `run_tests`/`go_build`/`go_vet`/`gofmt_check` in `transcript.md` |
| Reasonable PR summary | `pr.md` |

---

## Project layout

```
agent/
  cli.py          # the `run` subcommand
  config.py       # env-driven configuration (Sonnet default)
  issues.py       # GitHub issue fetch (gh) + URL/number parsing + saved-JSON loader
  repository.py   # clone/checkout, repo map, conventions, branch, diff
  tools.py        # the tool surface (schemas + sandboxed executors)
  llm.py          # Anthropic provider: the manual tool loop
  prompts.py      # per-phase system prompts ("project rules")
  pipeline.py     # the hybrid orchestration
  pr.py           # writes the run artifacts
examples/         # real run artifacts for validator #1550 and #1475
tests/            # unit tests for parsing, repo helpers, and tools
```

## Tests

```bash
python3 -m unittest discover -s tests
```

The tests cover issue parsing, the repo map / diff helpers, and every tool
executor (including the path sandbox and graceful handling of a missing Go
toolchain) — none require network or an API key.

## Limitations

- Validation quality depends on a working Go toolchain being installed.
- One issue per run; no multi-PR planning.
- A real run requires `ANTHROPIC_API_KEY` and (for fetching) an authenticated `gh`.
