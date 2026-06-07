"""Tiny logging helper shared across the package.

We keep this deliberately small: a console logger plus an in-memory buffer so the
full run can be written to ``run.log`` alongside the other artifacts.
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import List


class RunLog:
    """Collects log lines for console output and for persisting to disk."""

    def __init__(self, verbose: bool = True) -> None:
        self.verbose = verbose
        self.lines: List[str] = []

    def log(self, message: str, *, level: str = "INFO") -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {level:<5} {message}"
        self.lines.append(line)
        if self.verbose:
            print(line, file=sys.stderr, flush=True)

    def section(self, title: str) -> None:
        bar = "=" * len(title)
        self.log("")
        self.log(title)
        self.log(bar)

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"
