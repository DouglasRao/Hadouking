"""
Local execution policy (inspired by tiered layers like Claude Code / Codex: read vs network vs mutation).
Classifies bash commands and decides if human confirmation is needed before running on the machine.
"""

from __future__ import annotations

import re
import shlex
from enum import IntEnum
from typing import List, Tuple

from config import Config

class ExecTier(IntEnum):
    """Order: higher = more sensitive (needs more care / confirmation)."""

    READ_LOCAL = 10
    NETWORK = 20
    MUTATE = 30
    PRIVILEGED = 40


# Compound segments (&& || ; |) — classification = highest tier among parts.
_SEGMENT_SPLIT = re.compile(r"\s*(?:&&|\|\||;)\s*|\s*\|\s*")

_PRIV = re.compile(
    r"(?:^|\s)(?:sudo|doas)\s+|\bsu\s+(?:-|\w)|run0\s+",
    re.IGNORECASE,
)
# Redirections / writes
_MUTATE = re.compile(
    r"(?:^|\s)(?:chmod|chown|chgrp|install|rm|mv|cp|mkdir|rmdir|touch|ln\s|dd|mkfs|mount|umount)\s+"
    r"|(?:^|\s)git\s+(?:commit|push|pull|merge|rebase|reset|checkout)\s+"
    r"|(?:^|\s)(?:apt|apt-get|dpkg|dnf|yum|pacman|pip|pip3|npm|cargo)\s+(?:install|remove|uninstall|upgrade)\b"
    r"|\btee\s+"
    r"|[>]{2}?"
    r"|\bcurl\b[^;\n]*\s-(?:o|O)\s"
    r"|\bwget\b[^;\n]*\s-O\s",
    re.IGNORECASE,
)
_NETWORK = re.compile(
    r"\b(?:curl|wget|w3m|lynx|links|fetch|nc\b|netcat|ncat|nmap|masscan|rustscan|zmap|"
    r"ping\d?|hping|traceroute|tracepath|mtr|dig|nslookup|host|whois|"
    r"ssh|scp|sftp|ftp|lftp|rsync|telnet|openssl\s+s_client|"
    r"sqlmap|hydra|medusa|nxc|netexec|enum4linux|rpcclient|smbclient|ldapsearch|"
    r"feroxbuster|ffuf|gobuster|dirb|wfuzz|nikto|httpx|subfinder|amass|"
    r"burpsuite|zaproxy)\b",
    re.IGNORECASE,
)

# First "obvious" read-only local token (no typical outbound network)
_READ_BINS = frozenset(
    {
        "cat", "head", "tail", "less", "more", "ls", "dir", "pwd",
        "echo", "printf", "grep", "egrep", "fgrep", "rg", "find",
        "file", "strings", "stat", "wc", "sort", "uniq", "cut", "tr",
        "column", "expand", "unexpand", "id", "whoami", "groups",
        "date", "uname", "hostname", "dmesg", "journalctl", "ps",
        "pgrep", "pidof", "ss", "netstat", "lsof", "readlink",
        "realpath", "basename", "dirname", "which", "whereis",
        "type", "command", "true", "false", "test", "[",
    }
)


def _basename0(tok: str) -> str:
    t = tok.strip().lower()
    if "/" in t:
        t = t.rsplit("/", 1)[-1]
    return t


def _first_executable_token(segment: str) -> str | None:
    s = segment.strip()
    if not s:
        return None
    try:
        parts = shlex.split(s, posix=True)
    except ValueError:
        return None
    i = 0
    while i < len(parts):
        p = parts[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", p):
            i += 1
            continue
        if p == "env" and i + 1 < len(parts) and "=" in parts[i + 1]:
            i += 2
            continue
        if p in ("command", "builtin", "exec"):
            i += 1
            continue
        return p
    return None


def classify_segment(segment: str) -> ExecTier:
    seg = segment.strip()
    if not seg:
        return ExecTier.READ_LOCAL
    if _PRIV.search(seg):
        return ExecTier.PRIVILEGED
    if _MUTATE.search(seg):
        return ExecTier.MUTATE
    if _NETWORK.search(seg):
        return ExecTier.NETWORK
    tok = _first_executable_token(seg)
    if tok and _basename0(tok) in _READ_BINS:
        return ExecTier.READ_LOCAL
    # Unknown binary: conservative (treat as typical pentest network/probe)
    return ExecTier.NETWORK


def classify_command(command: str) -> Tuple[ExecTier, str]:
    """Returns (tier, short note) for the full command (including compound)."""
    cmd = (command or "").strip()
    if not cmd:
        return ExecTier.READ_LOCAL, "empty"
    parts = [p.strip() for p in _SEGMENT_SPLIT.split(cmd) if p.strip()]
    if not parts:
        parts = [cmd]
    tiers: List[ExecTier] = [classify_segment(p) for p in parts]
    tmax = max(tiers, key=int)
    if len(parts) > 1:
        return tmax, f"compound ({len(parts)} segments) -> {tmax.name}"
    return tmax, tmax.name.lower()


def exec_mode() -> str:
    return Config.PENTESTLLM_EXEC_MODE


def allow_sudo() -> bool:
    return Config.PENTESTLLM_ALLOW_SUDO


def is_blocked(tier: ExecTier) -> Tuple[bool, str]:
    """Hard block (before asking the user)."""
    mode = exec_mode()
    if mode == "strict" and tier == ExecTier.PRIVILEGED and not allow_sudo():
        return True, (
            "Strict mode: privileged commands (sudo/su) blocked. "
            "Set PENTESTLLM_ALLOW_SUDO=1 or use a different mode."
        )
    return False, ""


def needs_user_confirmation(tier: ExecTier, auto_approve: bool) -> bool:
    """If True, the operator must confirm (when auto_approve is off)."""
    if auto_approve:
        return False
    mode = exec_mode()
    if mode in ("always_confirm", "all", "legacy"):
        return True
    if mode in ("guardrails_only", "none", "off"):
        return False
    # tiered (default): only confirm network+, mutation and privileged
    return tier >= ExecTier.NETWORK


def classify_python_script(script: str) -> Tuple[ExecTier, str]:
    """Conservative heuristic: Python scripts can do anything; no full AST sandbox."""
    s = script or ""
    if re.search(r"\b(?:sudo|doas)\b", s) or re.search(
        r"\b(?:subprocess|os\.system|os\.popen|pty\.spawn)\b", s
    ):
        return ExecTier.PRIVILEGED, "python (subprocess/sudo)"
    if re.search(r"open\s*\([^)]*['\"]w", s) or re.search(
        r"\bPath\s*\([^)]+\)\.write_text\b", s
    ):
        return ExecTier.MUTATE, "python (disk write)"
    if re.search(
        r"\b(?:requests|urllib|httpx|aiohttp|socket\.|paramiko|ftplib)\b", s
    ):
        return ExecTier.NETWORK, "python (network)"
    # Conservative: arbitrary code treated as network/mutation for tiered confirmation
    return ExecTier.NETWORK, "python (unclassified — confirm)"


def policy_summary_for_prompt() -> str:
    mode = exec_mode()
    lines = [
        "## Local execution policy (PentestLLM)",
        f"- **Current mode:** `{mode}` (`PENTESTLLM_EXEC_MODE`). Aligned with tiered permission layers (read / network / mutation / privileged), like Claude Code or Codex agents.",
        "- **READ_LOCAL** (e.g.: `ls`, `cat`, `grep`, `find` read-only): in `tiered` mode, can execute **without** extra confirmation (as long as it passes guardrails).",
        "- **NETWORK** (e.g.: `curl`, `nmap`, `ping`, scanners): in `tiered` **asks for confirmation** from the operator if `--auto-approve` is off.",
        "- **MUTATE** (redirections `>`, `rm`, `git commit/push`, installs): confirmation in `tiered` without auto-approve.",
        "- **PRIVILEGED** (`sudo`, `su`): confirmation in `tiered`; in `strict` mode may block without `PENTESTLLM_ALLOW_SUDO=1`.",
        '- With **`--auto-approve`**, the confirmation policy is relaxed (like "approve all tools" in CLIs), but **guardrails** (dangerous patterns) still apply.',
        "",
    ]
    return "\n".join(lines)
