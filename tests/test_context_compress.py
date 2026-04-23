"""Tests for context compression of tool output."""

from utils.context_compress import (
    compress_tool_output,
    dedupe_consecutive_lines,
    head_tail_truncate,
    strip_ansi,
)


def test_strip_ansi():
    raw = "\x1b[31merror\x1b[0m plain"
    assert strip_ansi(raw) == "error plain"


def test_dedupe_consecutive_lines():
    t = "a\na\na\nb"
    d = dedupe_consecutive_lines(t, min_repeat=3)
    assert "x3 identical lines" in d
    assert "b" in d


def test_head_tail_truncate():
    s = "x" * 1000
    out, truncated = head_tail_truncate(s, 200)
    assert truncated
    assert len(out) <= 200
    assert out.startswith("x")
    assert out.endswith("x")


def test_compress_tool_output_respects_max():
    long = "\n".join([f"line {i}" for i in range(5000)])
    out = compress_tool_output(long, max_chars=2000, dedupe=False, strip_ansi_flag=False)
    assert len(out) <= 2000


def test_compress_dedupe_ansi():
    block = "\n".join(["\x1b[32mok\x1b[0m"] * 10)
    out = compress_tool_output(block, max_chars=10000, dedupe=True, strip_ansi_flag=True)
    assert "ok" in out
    assert "\x1b[" not in out
