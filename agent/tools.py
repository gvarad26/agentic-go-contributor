"""The tool surface exposed to the model.

Each tool is a small, dedicated capability rather than a raw shell, which keeps
the harness in control: every action has a typed schema, all file paths are
sandboxed to the repository, and command tools are restricted to the Go
toolchain. Tools are split into a read-only set (used during exploration) and a
mutating/validation set (added during implementation).

A tool executor takes the parsed ``input`` dict and returns a string that is fed
back to the model as the tool result.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

from agent.config import Config
from agent.repository import RepoContext

_MAX_TOOL_OUTPUT = 16000  # chars returned to the model per tool call


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    executor: Callable[[dict], str]

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _truncate(text: str) -> str:
    if len(text) > _MAX_TOOL_OUTPUT:
        return text[:_MAX_TOOL_OUTPUT] + "\n…(output truncated)…"
    return text


def _safe_path(ctx: RepoContext, rel: str) -> str:
    """Resolve ``rel`` against the repo root, rejecting escapes."""
    rel = (rel or "").lstrip("/")
    full = os.path.abspath(os.path.join(ctx.path, rel))
    root = os.path.abspath(ctx.path)
    if full != root and not full.startswith(root + os.sep):
        raise ValueError(f"Path {rel!r} escapes the repository.")
    return full


def _run(cmd: List[str], cwd: str, timeout: int) -> str:
    if shutil.which(cmd[0]) is None:
        return (
            f"[tool] `{cmd[0]}` is not installed in this environment, so this "
            f"check could not run. Treat validation for this step as unavailable "
            f"and continue; do not loop retrying it."
        )
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return f"[tool] `{' '.join(cmd)}` timed out after {timeout}s."
    out = (proc.stdout or "") + (proc.stderr or "")
    status = "ok" if proc.returncode == 0 else f"exit {proc.returncode}"
    return _truncate(f"$ {' '.join(cmd)}\n[{status}]\n{out.strip() or '(no output)'}")


# --------------------------------------------------------------------------- #
# Read-only tools
# --------------------------------------------------------------------------- #

def _list_directory(ctx: RepoContext) -> Tool:
    def run(inp: dict) -> str:
        target = _safe_path(ctx, inp.get("path", ""))
        if not os.path.isdir(target):
            return f"[tool] not a directory: {inp.get('path', '')}"
        entries = []
        for name in sorted(os.listdir(target)):
            if name == ".git":
                continue
            full = os.path.join(target, name)
            entries.append(name + ("/" if os.path.isdir(full) else ""))
        return _truncate("\n".join(entries) or "(empty)")

    return Tool(
        name="list_directory",
        description="List the files and subdirectories at a path within the repository.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repo-relative directory path. Use '' for the root."}
            },
            "required": ["path"],
        },
        executor=run,
    )


def _find_files(ctx: RepoContext) -> Tool:
    def run(inp: dict) -> str:
        pattern = inp.get("pattern", "")
        if not pattern:
            return "[tool] 'pattern' is required."
        matches: List[str] = []
        root = os.path.abspath(ctx.path)
        import fnmatch
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for fn in filenames:
                rel = os.path.relpath(os.path.join(dirpath, fn), root)
                if fnmatch.fnmatch(fn, pattern) or fnmatch.fnmatch(rel, pattern):
                    matches.append(rel)
        matches.sort()
        return _truncate("\n".join(matches[:300]) or "(no matches)")

    return Tool(
        name="find_files",
        description="Find files by glob pattern (e.g. '*_test.go', 'binding/*.go').",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern matched against file name and repo-relative path."}
            },
            "required": ["pattern"],
        },
        executor=run,
    )


def _search_code(ctx: RepoContext, config: Config) -> Tool:
    def run(inp: dict) -> str:
        pattern = inp.get("pattern", "")
        if not pattern:
            return "[tool] 'pattern' is required."
        path_glob = inp.get("path_glob")
        if shutil.which("rg"):
            cmd = ["rg", "--line-number", "--no-heading", "--color", "never", "-S"]
            if path_glob:
                cmd += ["--glob", path_glob]
            cmd += [pattern, "."]
            return _run(cmd, ctx.path, config.command_timeout)
        # Fallback: plain Python scan if ripgrep is unavailable.
        import re as _re
        try:
            rx = _re.compile(pattern)
        except _re.error as exc:
            return f"[tool] invalid regex: {exc}"
        hits: List[str] = []
        for dirpath, dirnames, filenames in os.walk(ctx.path):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                        for i, line in enumerate(fh, 1):
                            if rx.search(line):
                                rel = os.path.relpath(fp, ctx.path)
                                hits.append(f"{rel}:{i}:{line.rstrip()}")
                except OSError:
                    continue
                if len(hits) > 400:
                    break
        return _truncate("\n".join(hits[:400]) or "(no matches)")

    return Tool(
        name="search_code",
        description="Search the repository for a regex pattern (ripgrep). Returns file:line:match.",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex to search for."},
                "path_glob": {"type": "string", "description": "Optional glob to restrict the search, e.g. '*.go'."},
            },
            "required": ["pattern"],
        },
        executor=run,
    )


def _read_file(ctx: RepoContext) -> Tool:
    def run(inp: dict) -> str:
        target = _safe_path(ctx, inp.get("path", ""))
        if not os.path.isfile(target):
            return f"[tool] not a file: {inp.get('path', '')}"
        with open(target, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        start = max(1, int(inp.get("start_line", 1)))
        end = inp.get("end_line")
        end = len(lines) if end is None else min(len(lines), int(end))
        numbered = [f"{i:>5}\t{lines[i - 1].rstrip(os.linesep)}" for i in range(start, end + 1)]
        header = f"{inp.get('path')} (lines {start}-{end} of {len(lines)})"
        return _truncate(header + "\n" + "\n".join(numbered))

    return Tool(
        name="read_file",
        description="Read a file (optionally a line range) from the repository.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repo-relative file path."},
                "start_line": {"type": "integer", "description": "First line (1-based). Optional."},
                "end_line": {"type": "integer", "description": "Last line (inclusive). Optional."},
            },
            "required": ["path"],
        },
        executor=run,
    )


# --------------------------------------------------------------------------- #
# Mutating + validation tools
# --------------------------------------------------------------------------- #

def _write_file(ctx: RepoContext) -> Tool:
    def run(inp: dict) -> str:
        target = _safe_path(ctx, inp.get("path", ""))
        content = inp.get("content")
        if content is None:
            return "[tool] 'content' is required."
        os.makedirs(os.path.dirname(target), exist_ok=True)
        existed = os.path.isfile(target)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)
        return f"[tool] {'overwrote' if existed else 'created'} {inp.get('path')} ({len(content)} bytes)."

    return Tool(
        name="write_file",
        description="Create or fully overwrite a file with the given content.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repo-relative file path."},
                "content": {"type": "string", "description": "Full new file content."},
            },
            "required": ["path", "content"],
        },
        executor=run,
    )


def _edit_file(ctx: RepoContext) -> Tool:
    def run(inp: dict) -> str:
        target = _safe_path(ctx, inp.get("path", ""))
        if not os.path.isfile(target):
            return f"[tool] not a file: {inp.get('path', '')}"
        old = inp.get("old_string", "")
        new = inp.get("new_string", "")
        if not old:
            return "[tool] 'old_string' is required and must be non-empty."
        with open(target, "r", encoding="utf-8") as fh:
            data = fh.read()
        occurrences = data.count(old)
        if occurrences == 0:
            return "[tool] old_string not found. Read the file again to copy the exact text."
        if occurrences > 1 and not inp.get("replace_all"):
            return (
                f"[tool] old_string appears {occurrences} times; it must be unique. "
                f"Add surrounding context, or pass replace_all=true."
            )
        data = data.replace(old, new)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(data)
        return f"[tool] edited {inp.get('path')} ({occurrences} replacement(s))."

    return Tool(
        name="edit_file",
        description="Replace an exact string in a file. old_string must be unique unless replace_all is set.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repo-relative file path."},
                "old_string": {"type": "string", "description": "Exact text to replace (copy verbatim, including indentation)."},
                "new_string": {"type": "string", "description": "Replacement text."},
                "replace_all": {"type": "boolean", "description": "Replace every occurrence. Optional."},
            },
            "required": ["path", "old_string", "new_string"],
        },
        executor=run,
    )


def _go_command(ctx: RepoContext, config: Config, name: str, description: str, build_cmd) -> Tool:
    def run(inp: dict) -> str:
        return _run(build_cmd(inp), ctx.path, config.command_timeout)

    return Tool(name=name, description=description, input_schema=_go_schema(name), executor=run)


def _go_schema(name: str) -> dict:
    if name == "run_tests":
        return {
            "type": "object",
            "properties": {
                "package": {"type": "string", "description": "Package pattern, e.g. './...' or './binding'. Defaults to ./...'."},
                "run": {"type": "string", "description": "Optional -run regex to select specific tests."},
            },
        }
    return {"type": "object", "properties": {}}


def _git_diff(ctx: RepoContext) -> Tool:
    def run(inp: dict) -> str:
        proc = subprocess.run(
            ["git", "-C", ctx.path, "diff"], capture_output=True, text=True
        )
        # Include untracked files so newly created files are visible.
        subprocess.run(["git", "-C", ctx.path, "add", "-AN"], capture_output=True, text=True)
        proc2 = subprocess.run(
            ["git", "-C", ctx.path, "diff"], capture_output=True, text=True
        )
        return _truncate(proc2.stdout or proc.stdout or "(no changes yet)")

    return Tool(
        name="git_diff",
        description="Show the current uncommitted diff for the working tree.",
        input_schema={"type": "object", "properties": {}},
        executor=run,
    )


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #

def build_tools(
    ctx: RepoContext, config: Config, *, allow_write: bool
) -> Tuple[List[dict], Dict[str, Callable[[dict], str]]]:
    """Return (tool schemas, name->executor) for a phase.

    With ``allow_write=False`` only read-only exploration tools are exposed.
    """
    tools: List[Tool] = [
        _list_directory(ctx),
        _find_files(ctx),
        _search_code(ctx, config),
        _read_file(ctx),
    ]
    if allow_write:
        tools += [
            _write_file(ctx),
            _edit_file(ctx),
            _git_diff(ctx),
            _go_command(
                ctx, config, "run_tests",
                "Run Go tests. Optionally restrict to a package and/or -run regex.",
                lambda inp: ["go", "test"]
                + (["-run", inp["run"]] if inp.get("run") else [])
                + [inp.get("package") or "./..."],
            ),
            _go_command(
                ctx, config, "go_build",
                "Compile the module with `go build ./...`.",
                lambda inp: ["go", "build", "./..."],
            ),
            _go_command(
                ctx, config, "go_vet",
                "Run `go vet ./...` to catch suspicious constructs.",
                lambda inp: ["go", "vet", "./..."],
            ),
            _go_command(
                ctx, config, "gofmt_check",
                "Check formatting with `gofmt -l .` (lists unformatted files; empty = OK).",
                lambda inp: ["gofmt", "-l", "."],
            ),
        ]

    schemas = [t.schema() for t in tools]
    # Wrap every executor so a raised exception (e.g. a sandbox violation) is
    # returned to the model as a tool result instead of crashing the run.
    executors = {t.name: _guard(t.executor) for t in tools}
    return schemas, executors


def _guard(fn: Callable[[dict], str]) -> Callable[[dict], str]:
    def wrapped(inp: dict) -> str:
        try:
            return fn(inp)
        except Exception as exc:  # noqa: BLE001 - feed the error back to the model
            return f"[tool] error: {exc}"

    return wrapped
