"""The model provider and the agentic tool loop.

``AnthropicProvider`` drives Claude through the Messages API with a manual tool
loop (so we keep full control over logging and iteration limits). It uses
adaptive thinking and the effort parameter, with a graceful fallback for models
or SDK versions that don't accept them.
"""

from __future__ import annotations

import json
from typing import Callable, Dict, List, Optional, Tuple

from agent.config import Config
from agent.logging_util import RunLog

ToolExecutors = Dict[str, Callable[[dict], str]]
# An event log entry: (kind, detail). kind in {"thinking","text","tool","result"}.
Event = Tuple[str, str]


def extract_json(text: str) -> dict:
    """Best-effort extraction of a JSON object from model text."""
    text = text.strip()
    if text.startswith("```"):
        # Strip a ```json fence if present.
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost {...} span.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError("Model did not return parseable JSON:\n" + text[:500])


# --------------------------------------------------------------------------- #
# Anthropic
# --------------------------------------------------------------------------- #

class AnthropicProvider:
    def __init__(self, config: Config, log: RunLog) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "The 'anthropic' package is required. Run: pip install -r requirements.txt"
            ) from exc
        if not config.api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Export it before running, e.g. "
                "`export ANTHROPIC_API_KEY=sk-ant-...`."
            )
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=config.api_key)
        self.config = config
        self.log = log
        self._optional_features = True  # thinking + effort; disabled on first rejection

    def _create(self, *, thinking: bool, **kwargs):
        extra: dict = {}
        if self._optional_features:
            if thinking and self.config.thinking:
                extra["thinking"] = {"type": "adaptive"}
            if self.config.effort:
                extra["output_config"] = {"effort": self.config.effort}
        try:
            if extra:
                return self.client.messages.create(extra_body=extra, **kwargs)
            return self.client.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - we re-raise unless it's a param issue
            if extra and self._is_param_error(exc):
                self.log.log(
                    f"Model rejected optional params ({exc}); retrying without them.",
                    level="WARN",
                )
                self._optional_features = False
                return self.client.messages.create(**kwargs)
            raise

    def _is_param_error(self, exc: Exception) -> bool:
        if isinstance(exc, getattr(self._anthropic, "BadRequestError", ())):
            return True
        blob = str(exc).lower()
        return any(k in blob for k in ("thinking", "output_config", "effort"))

    def complete_json(self, system: str, user: str, *, purpose: str = "") -> dict:
        resp = self._create(
            thinking=False,
            model=self.config.model,
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return extract_json(_text_of(resp.content))

    def agent_loop(
        self,
        system: str,
        user: str,
        tool_schemas: List[dict],
        executors: ToolExecutors,
        *,
        max_iterations: Optional[int] = None,
    ) -> Tuple[str, List[Event]]:
        max_iterations = max_iterations or self.config.max_iterations
        messages: List[dict] = [{"role": "user", "content": user}]
        events: List[Event] = []
        final_text = ""

        for turn in range(1, max_iterations + 1):
            resp = self._create(
                thinking=True,
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                system=system,
                tools=tool_schemas,
                messages=messages,
            )
            # Preserve the full assistant content (incl. thinking blocks) in history.
            messages.append({"role": "assistant", "content": resp.content})

            for block in resp.content:
                btype = getattr(block, "type", None)
                if btype == "text" and block.text.strip():
                    events.append(("text", block.text.strip()))
                    final_text = block.text.strip()
                elif btype == "thinking" and getattr(block, "thinking", ""):
                    events.append(("thinking", block.thinking.strip()))

            if resp.stop_reason == "pause_turn":
                # Server-side pause; resend to let the model continue.
                continue
            if resp.stop_reason != "tool_use":
                break

            tool_results = []
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                detail = f"{block.name}({json.dumps(block.input, ensure_ascii=False)[:200]})"
                self.log.log(f"  tool: {detail}")
                events.append(("tool", detail))
                try:
                    out = executors[block.name](block.input)
                except KeyError:
                    out = f"[tool] unknown tool: {block.name}"
                except Exception as exc:  # noqa: BLE001 - surface to the model
                    out = f"[tool] error: {exc}"
                events.append(("result", out[:500]))
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": out}
                )
            messages.append({"role": "user", "content": tool_results})
        else:
            self.log.log("Reached max iterations for this phase.", level="WARN")

        return final_text, events


def _text_of(content_blocks) -> str:
    return "\n".join(
        b.text for b in content_blocks if getattr(b, "type", None) == "text"
    ).strip()
