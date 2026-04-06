"""
Tool output compaction before going into the LLM history.
Inspired by RTK (fewer tokens in context), implemented in pure Python —
no external proxies by default (see README: optional RTK).
"""

import re
from typing import Tuple

_RE_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    if not text:
        return text
    return _RE_ANSI.sub("", text)


def dedupe_consecutive_lines(text: str, min_repeat: int = 3) -> str:
    """Collapses blocks of the same consecutive line (e.g.: progress bars, repeated logs)."""
    lines = text.splitlines()
    if len(lines) < min_repeat:
        return text
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        j = i + 1
        while j < n and lines[j] == line:
            j += 1
        count = j - i
        if count >= min_repeat:
            out.append(f"{line}  [x{count} identical lines]")
        else:
            out.extend(lines[i:j])
        i = j
    return "\n".join(out)


def head_tail_truncate(text: str, max_chars: int) -> Tuple[str, bool]:
    """Keeps beginning and end; the middle is usually noise in long scans."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    omitted = len(text) - max_chars
    mid = f"\n\n... [{omitted} chars omitted (middle)]\n\n"
    inner = max_chars - len(mid)
    if inner < 24:
        return text[:max_chars], True
    h = inner // 2
    t = inner - h
    return text[:h] + mid + text[-t:], True


def compress_tool_output(
    text: str,
    *,
    max_chars: int,
    dedupe: bool,
    strip_ansi_flag: bool,
) -> str:
    """Reduces raw command/MCP/script text for what enters the agent history."""
    if not text or not text.strip():
        return text

    t = strip_ansi(text) if strip_ansi_flag else text
    if dedupe:
        t = dedupe_consecutive_lines(t)
    t, _ = head_tail_truncate(t, max_chars)
    return t


def maybe_compress_for_llm(text: str) -> str:
    """Applies Config limits; disable with PENTESTLLM_COMPRESS_OUTPUT=0."""
    from config import Config

    if not Config.PENTESTLLM_COMPRESS_OUTPUT:
        return text
    return compress_tool_output(
        text,
        max_chars=Config.PENTESTLLM_CONTEXT_MAX_CHARS,
        dedupe=Config.PENTESTLLM_CONTEXT_DEDUPE,
        strip_ansi_flag=Config.PENTESTLLM_CONTEXT_STRIP_ANSI,
    )
