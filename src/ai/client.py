"""Claude client — no API key required.

Two transports, same public interface:

1. ClaudeCodeClient  — uses claude-code-sdk (async, OAuth via Claude subscription)
2. ClaudeSubprocessClient — calls `claude` CLI via subprocess (sync fallback)

Both expose:
    ask(system, user) -> str
    ask_json(system, user) -> Any
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from typing import Any


def _extract_json(text: str) -> Any:
    """Parse JSON from Claude response, stripping markdown fences if present."""
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(cleaned[start: end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not extract JSON from Claude response:\n{text[:500]}")


class ClaudeCodeClient:
    """Uses claude-code-sdk-python. OAuth via Claude subscription, no API key."""

    def __init__(self, model: str = "claude-opus-4-5") -> None:
        self.model = model
        self._check_sdk()

    def _check_sdk(self) -> None:
        try:
            import claude_code_sdk  # noqa: F401
        except ImportError:
            raise ImportError(
                "claude-code-sdk not installed.\n"
                "Run: pip install claude-code-sdk"
            )

    def ask(self, system: str, user: str, max_tokens: int = 4096) -> str:
        try:
            return asyncio.run(self._ask_async(system, user, max_tokens))
        except Exception as e:
            if "Unknown message type" in str(e) or "already running" in str(e):
                return ClaudeSubprocessClient(model=self.model).ask(system, user, max_tokens)
            raise

    async def _ask_async(self, system: str, user: str, max_tokens: int) -> str:
        from claude_code_sdk import query, ClaudeCodeOptions

        full_prompt = f"{system}\n\n{user}" if system else user
        result_parts: list[str] = []

        async for message in query(
            prompt=full_prompt,
            options=ClaudeCodeOptions(max_turns=1),
        ):
            content = getattr(message, "content", None)
            if content is None:
                continue
            if isinstance(content, str):
                result_parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    text = getattr(block, "text", None)
                    if text:
                        result_parts.append(text)

        return "".join(result_parts)

    def ask_json(self, system: str, user: str, max_tokens: int = 4096) -> Any:
        return _extract_json(self.ask(system, user, max_tokens))

    @staticmethod
    def _extract_json(text: str) -> Any:
        return _extract_json(text)


class ClaudeSubprocessClient:
    """Calls `claude` CLI via subprocess. Sync fallback, zero extra deps."""

    def __init__(self, model: str = "claude-opus-4-5", claude_path: str = "claude") -> None:
        self.model = model
        self.claude_path = claude_path
        self._check_cli()

    def _check_cli(self) -> None:
        if not shutil.which(self.claude_path):
            raise RuntimeError(
                f"claude CLI not found at '{self.claude_path}'.\n"
                "Install Claude Code: https://claude.ai/code"
            )

    def ask(self, system: str, user: str, max_tokens: int = 4096) -> str:
        full_prompt = f"{system}\n\n{user}" if system else user
        result = subprocess.run(
            [self.claude_path, "--print", "--output-format", "text",
             "--model", self.model, "--max-turns", "1"],
            input=full_prompt,
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"claude CLI exited with code {result.returncode}:\n{result.stderr[:500]}"
            )
        return result.stdout.strip()

    def ask_json(self, system: str, user: str, max_tokens: int = 4096) -> Any:
        return _extract_json(self.ask(system, user, max_tokens))

    @staticmethod
    def _extract_json(text: str) -> Any:
        return _extract_json(text)


# Type alias for backwards-compatible agent signatures
ClaudeClient = ClaudeCodeClient | ClaudeSubprocessClient


def make_client(
    model: str = "claude-opus-4-5",
    claude_path: str = "claude",
) -> ClaudeCodeClient | ClaudeSubprocessClient:
    """Factory: tries SDK first, falls back to subprocess CLI."""
    try:
        import claude_code_sdk  # noqa: F401
        return ClaudeCodeClient(model=model)
    except ImportError:
        return ClaudeSubprocessClient(model=model, claude_path=claude_path)
