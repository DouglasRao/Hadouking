"""Shared model metadata helpers — single source of truth for context windows and formatting."""

from __future__ import annotations


def model_context_window(model_name: str) -> int:
    """Estimated context window size (tokens) for a given model identifier."""
    m = (model_name or "").lower()
    if m in ("claude-code-cli", "openai-codex-cli"):
        return 200000
    if "claude" in m:
        return 200000
    if "gpt-4o" in m:
        return 128000
    if "gpt-o1" in m or "gpt-o3" in m:
        return 200000
    if "deepseek-chat" in m or "deepseek-reasoner" in m:
        return 64000
    if "/" in m:  # OpenRouter generic fallback
        return 128000
    return 128000


def fmt_k(n: int) -> str:
    """Format a number as human-readable k/M shorthand."""
    if n >= 1000000:
        return f"{n/1000000:.1f}M"
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)
