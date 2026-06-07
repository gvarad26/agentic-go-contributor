"""Runtime configuration.

Everything is overridable via environment variables so the system is easy to run
on another machine without editing code. The defaults follow the project's
guidance: use the most capable Claude model unless told otherwise.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

# Default to Sonnet for a fast, cost-effective run. Override with
# AGENT_MODEL=claude-opus-4-8 for the most capable (slower/pricier) model.
DEFAULT_MODEL = "claude-sonnet-4-6"


def load_dotenv(path: str = ".env") -> None:
    """Load simple KEY=VALUE pairs from a .env file into os.environ.

    Stdlib-only (no python-dotenv dependency). Real environment variables take
    precedence, so an already-exported value is never overwritten. Lines may be
    blank, comments (``#``), or ``KEY=VALUE``; surrounding quotes and stray
    whitespace around the key/value are stripped.
    """
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key.startswith("export "):
                key = key[len("export "):].strip()
            value = value.strip().strip('"').strip("'").strip()
            if key and key not in os.environ:
                os.environ[key] = value


# Load .env as soon as the config module is imported so every Config() and the
# CLI see the keys without an explicit `export`.
load_dotenv()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Config:
    """Knobs for a single run."""

    model: str = field(default_factory=lambda: os.environ.get("AGENT_MODEL", DEFAULT_MODEL))
    # Max tool-loop turns per phase before we give up.
    max_iterations: int = field(default_factory=lambda: _env_int("AGENT_MAX_ITERATIONS", 40))
    # Thinking depth / token budget hint. low | medium | high | max.
    effort: str = field(default_factory=lambda: os.environ.get("AGENT_EFFORT", "high"))
    # Adaptive thinking for the agent loops (set AGENT_THINKING=0 to disable).
    thinking: bool = field(default_factory=lambda: os.environ.get("AGENT_THINKING", "1") != "0")
    # Max output tokens per model call (kept under the non-streaming ceiling).
    max_tokens: int = field(default_factory=lambda: _env_int("AGENT_MAX_TOKENS", 16000))
    # Timeout (seconds) for shell commands such as `go test`.
    command_timeout: int = field(default_factory=lambda: _env_int("AGENT_COMMAND_TIMEOUT", 600))
    # Where repositories are cloned.
    workdir: str = field(default_factory=lambda: os.environ.get("AGENT_WORKDIR", ".work"))
    # Where run artifacts are written.
    output_root: str = field(default_factory=lambda: os.environ.get("AGENT_OUTPUT", "output"))

    api_key: Optional[str] = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY"))
