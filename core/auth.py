"""
Unified authentication: API keys, Claude Code CLI, Codex CLI.
Uses only official flows (login via binaries / console keys).
"""

import asyncio
import json
import shlex
import shutil
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import Config


def _parse_codex_login_status_text(text: str) -> bool:
    """Parses output from `codex login status` (avoids false positives)."""
    t = text.lower().strip()
    if not t:
        return False
    negative = (
        "not logged in",
        "not signed in",
        "no active session",
        "not authenticated",
        "not authenticated",
        "not authenticated",
        "log out",
        "logged out",
    )
    if any(neg in t for neg in negative):
        return False
    # `login status` may report "logged in" with a token already invalid for `exec`
    stale = (
        "expired",
        "expired",
        "invalid token",
        "invalid token",
        "re-authenticate",
        "reauthenticate",
        "please log in again",
    )
    if any(s in t for s in stale):
        return False
    positive = (
        "logged in",
        "signed in",
        "active session",
        "active session",
    )
    return any(pos in t for pos in positive)


def _parse_claude_auth_status_text(text: str) -> Optional[bool]:
    """
    Parses output from `claude auth status` (text or JSON).
    None = could not determine (command missing / unexpected output).
    """
    t = text.lower().strip()
    if not t:
        return None
    if any(
        x in t
        for x in (
            "unknown",
            "unrecognized",
            "invalid command",
            "unexpected argument",
            "no such command",
        )
    ):
        return None
    negative = (
        "not logged in",
        "not authenticated",
        "no active",
        "logged out",
        '"logged_in":false',
        '"authenticated":false',
        '"isauthenticated":false',
    )
    if any(neg in t for neg in negative):
        return False
    positive = (
        "logged in",
        "authenticated",
        "signed in",
        '"logged_in":true',
        '"authenticated":true',
        '"isauthenticated":true',
    )
    if any(pos in t for pos in positive):
        return True
    return None


class AuthMethod(Enum):
    API_KEY = "api_key"
    CLAUDE_CODE_SUB = "claude_code"
    CODEX_SUB = "codex"


def _decode(out: bytes) -> str:
    return out.decode(errors="replace").strip()


class CLIBridge:
    """Invokes `claude` / `codex`; OAuth/session login via `run_official_interactive_login` or a separate terminal."""

    def __init__(self, cli_name: str):
        self.cli_name = cli_name
        self.binary_path = shutil.which(cli_name)
        self.available = self.binary_path is not None

    def is_available(self) -> bool:
        return self.available

    async def codex_login_status_ok(self) -> bool:
        """Checks `codex login status` (fast, without MCP or agent loop)."""
        if not self.available or self.cli_name != "codex":
            return False
        try:
            proc = await asyncio.create_subprocess_exec(
                self.binary_path,
                "login",
                "status",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            text = _decode(out)
            if proc.returncode != 0:
                return False
            return _parse_codex_login_status_text(text)
        except (asyncio.TimeoutError, FileNotFoundError, OSError):
            return False

    async def claude_version_probe_ok(self) -> bool:
        """Confirms that the `claude` binary responds (without a full LLM turn)."""
        if not self.available or self.cli_name != "claude":
            return False
        for argv in (["--version"], ["-h"]):
            try:
                proc = await asyncio.create_subprocess_exec(
                    self.binary_path,
                    *argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=15.0)
                if proc.returncode == 0:
                    return True
            except (asyncio.TimeoutError, FileNotFoundError, OSError):
                return False
        return False

    async def claude_auth_status_ok(self) -> Optional[bool]:
        """
        `claude auth status` (official). True/False if the output is clear; None if the CLI
        does not support the subcommand or the output is ambiguous.
        """
        if not self.available or self.cli_name != "claude":
            return None
        for argv in (["auth", "status", "--text"], ["auth", "status"]):
            try:
                proc = await asyncio.create_subprocess_exec(
                    self.binary_path,
                    *argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=20.0)
                text = _decode(out)
                parsed = _parse_claude_auth_status_text(text)
                if proc.returncode != 0:
                    if parsed is None:
                        continue
                    return False
                if parsed is not None:
                    return parsed
            except (asyncio.TimeoutError, FileNotFoundError, OSError):
                return None
        return None

    def claude_credentials_file_present(self) -> bool:
        """Heuristic: file that Claude Code writes after a successful login."""
        try:
            p = Path.home() / ".claude" / ".credentials.json"
            return p.is_file() and p.stat().st_size > 10
        except OSError:
            return False

    async def claude_session_works_probe(self) -> bool:
        """
        Confirms real session with a single short `claude --print` (without opening a browser).
        Used when `claude auth status` is ambiguous or outdated.
        """
        if not self.available or self.cli_name != "claude":
            return False
        timeout = min(60.0, float(Config.CLAUDE_EXEC_TIMEOUT_SEC))
        cmd = [
            self.binary_path,
            "--print",
            "-p",
            "Reply with exactly the single word PING and nothing else.",
        ]
        for tok in shlex.split(Config.CLAUDE_EXTRA_ARGS or ""):
            cmd.append(tok)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except (asyncio.TimeoutError, FileNotFoundError, OSError):
            return False
        out_s, err_s = _decode(stdout), _decode(stderr)
        merged = (out_s + "\n" + err_s).lower()
        if proc.returncode != 0:
            if any(
                x in merged
                for x in (
                    "authentication",
                    "auth",
                    "login",
                    "unauthorized",
                    "not logged",
                )
            ):
                return False
            return False
        return "ping" in out_s.lower()

    def codex_auth_json_present(self) -> bool:
        try:
            p = Path.home() / ".codex" / "auth.json"
            if not p.is_file() or p.stat().st_size < 20:
                return False
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return False
            # Structure varies between versions; it suffices to have any sign of saved credentials
            return bool(data)
        except (OSError, json.JSONDecodeError, TypeError):
            return False

    async def codex_session_works_probe(self) -> bool:
        """
        A minimal `codex exec` to validate the token when `login status` is wrong or outdated.
        Only used during the initial authentication phase (not in self-test).
        """
        if not self.available or self.cli_name != "codex":
            return False
        try:
            await self._invoke_codex(
                "Reply with exactly the single word PING and nothing else.",
                model=None,
                timeout_sec=float(Config.CODEX_AUTH_PROBE_TIMEOUT_SEC),
            )
            return True
        except RuntimeError as e:
            es = str(e).lower()
            if "session" in str(e) or "authentication" in es or "login" in es:
                return False
            return False
        except (asyncio.TimeoutError, Exception):
            return False

    async def run_official_interactive_login(self) -> int:
        """
        Runs the official login flow on the same TTY as the parent process (inherited stdin/stdout/stderr),
        as when manually running `codex login` or `claude auth login`.
        """
        if not self.available:
            return 127
        if self.cli_name == "codex":
            proc = await asyncio.create_subprocess_exec(
                self.binary_path,
                "login",
                stdin=None,
                stdout=None,
                stderr=None,
            )
            return await proc.wait()
        if self.cli_name == "claude":
            proc = await asyncio.create_subprocess_exec(
                self.binary_path,
                "auth",
                "login",
                stdin=None,
                stdout=None,
                stderr=None,
            )
            return await proc.wait()
        raise ValueError(f"Interactive login not defined for CLI: {self.cli_name}")

    async def send_prompt(self, messages: List[Dict[str, Any]], model: str = None) -> str:
        if not self.available:
            raise RuntimeError(f"CLI '{self.cli_name}' not found in PATH.")

        prompt = self._messages_to_prompt(messages)

        if self.cli_name == "claude":
            return await self._invoke_claude(prompt, model)
        if self.cli_name == "codex":
            return await self._invoke_codex(prompt, model)
        raise ValueError(f"Unknown CLI: {self.cli_name}")

    async def _invoke_claude(self, prompt: str, model: str = None) -> str:
        cmd = [self.binary_path, "--print", "-p", prompt]
        if model:
            cmd.extend(["--model", model])
        for tok in shlex.split(Config.CLAUDE_EXTRA_ARGS or ""):
            cmd.append(tok)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=Config.CLAUDE_EXEC_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(
                f"Claude CLI timed out after {Config.CLAUDE_EXEC_TIMEOUT_SEC}s"
            ) from None

        out_s, err_s = _decode(stdout), _decode(stderr)
        if proc.returncode != 0:
            merged = (err_s or out_s).lower()
            if "authentication" in merged or "login" in merged or "unauthorized" in merged:
                raise RuntimeError(
                    "Claude Code: authentication failure. Run `claude auth login` (official flow) and re-check."
                )
            raise RuntimeError(
                f"Claude CLI (code {proc.returncode}): {err_s or out_s or '(no output)'}"
            )

        return out_s or err_s

    async def _invoke_codex(
        self, prompt: str, model: str = None, *, timeout_sec: Optional[float] = None
    ) -> str:
        cmd = [
            self.binary_path,
            "exec",
            "--sandbox",
            Config.CODEX_EXEC_SANDBOX,
            "--skip-git-repo-check",
        ]
        if Config.CODEX_SKIP_MCP_OVERRIDE:
            cmd.extend(["-c", "mcp_servers={}"])
        for tok in shlex.split(Config.CODEX_EXTRA_ARGS or ""):
            cmd.append(tok)
        m = (model or "").strip() or (Config.CODEX_MODEL or "").strip() or None
        if m:
            cmd.extend(["-m", m])
        wd = (Config.CODEX_WORKDIR or "").strip()
        if wd:
            cmd.extend(["-C", wd])
        cmd.append(prompt)

        t_out = (
            float(timeout_sec)
            if timeout_sec is not None
            else float(Config.CODEX_EXEC_TIMEOUT_SEC)
        )
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=t_out,
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(
                f"Codex CLI timed out after {t_out}s"
            ) from None

        out_s, err_s = _decode(stdout), _decode(stderr)
        if proc.returncode != 0:
            merged = (err_s + "\n" + out_s).lower()
            if (
                "authentication" in merged
                or "login" in merged
                or "unauthorized" in merged
                or "refresh token" in merged
            ):
                raise RuntimeError(
                    "Codex: invalid or expired session. Run `codex login` (or `codex login status`)."
                )
            raise RuntimeError(
                f"Codex CLI (code {proc.returncode}): {err_s or '(empty stderr)'} | tail stdout: {out_s[-2000:] if out_s else '—'}"
            )

        return out_s or err_s

    def _messages_to_prompt(self, messages: List[Dict[str, Any]]) -> str:
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [p["text"] for p in content if p.get("type") == "text"]
                content = "\n".join(text_parts)
            if role == "system":
                parts.append(f"[System Instructions]\n{content}")
            elif role == "assistant":
                parts.append(f"[Previous Response]\n{content}")
            else:
                parts.append(content)
        return "\n\n".join(parts)


class AuthManager:
    def __init__(self):
        self.claude_bridge = CLIBridge("claude")
        self.codex_bridge = CLIBridge("codex")
        self.active_method: Optional[AuthMethod] = None
        self._authenticated = False

    def detect_available_methods(self) -> List[Dict[str, Any]]:
        methods = [
            {
                "method": AuthMethod.API_KEY,
                "name": "API Keys",
                "description": "API keys + ANTHROPIC_AUTH_TOKEN (Bearer/Claude account) — no claude/codex binary needed",
                "available": True,
                "icon": "🔑",
            },
            {
                "method": AuthMethod.CLAUDE_CODE_SUB,
                "name": "Claude Code (CLI)",
                "description": "Subscription / account via `claude` binary",
                "available": self.claude_bridge.is_available(),
                "icon": "🟣",
                "binary": self.claude_bridge.binary_path,
            },
            {
                "method": AuthMethod.CODEX_SUB,
                "name": "Codex (CLI)",
                "description": "ChatGPT plan via `codex login`",
                "available": self.codex_bridge.is_available(),
                "icon": "🟢",
                "binary": self.codex_bridge.binary_path,
            },
        ]
        return methods

    async def authenticate(
        self, method: AuthMethod, *, cli_login_ack: bool = False
    ) -> bool:
        self.active_method = method

        if method == AuthMethod.API_KEY:
            from config import Config as C

            has_key = any(
                [
                    C.OPENAI_API_KEY,
                    C.ANTHROPIC_API_KEY,
                    C.ANTHROPIC_AUTH_TOKEN,
                    C.DEEPSEEK_API_KEY,
                    C.OPENROUTER_API_KEY,
                ]
            )
            self._authenticated = has_key
            return has_key

        if method == AuthMethod.CLAUDE_CODE_SUB:
            if not self.claude_bridge.is_available():
                self._authenticated = False
                return False
            auth_state = await self.claude_bridge.claude_auth_status_ok()
            if auth_state is True:
                self._authenticated = True
                return True
            # Session stored in ~/.claude — validate with a short `claude --print` (no new OAuth)
            if await self.claude_bridge.claude_session_works_probe():
                self._authenticated = True
                return True
            if auth_state is False:
                self._authenticated = False
                return False
            # `auth status` ambiguous (None): credentials on disk + probe already failed
            ok = await self.claude_bridge.claude_version_probe_ok()
            if not ok:
                self._authenticated = False
                return False
            if cli_login_ack:
                self._authenticated = True
                return True
            self._authenticated = False
            return False

        if method == AuthMethod.CODEX_SUB:
            if not self.codex_bridge.is_available():
                self._authenticated = False
                return False
            if await self.codex_bridge.codex_login_status_ok():
                self._authenticated = True
                return True
            # `login status` may be wrong; ~/.codex/auth.json + minimal exec
            if self.codex_bridge.codex_auth_json_present():
                if await self.codex_bridge.codex_session_works_probe():
                    self._authenticated = True
                    return True
            self._authenticated = False
            return False

        return False

    def get_bridge(self) -> Optional[CLIBridge]:
        if self.active_method == AuthMethod.CLAUDE_CODE_SUB:
            return self.claude_bridge
        if self.active_method == AuthMethod.CODEX_SUB:
            return self.codex_bridge
        return None

    def is_cli_mode(self) -> bool:
        return self.active_method in (AuthMethod.CLAUDE_CODE_SUB, AuthMethod.CODEX_SUB)

    def is_authenticated(self) -> bool:
        return self._authenticated

    async def refresh_cli_status(self) -> Dict[str, Any]:
        """For /auth status: revalidates CLIs without starting an LLM turn."""
        claude_session = await self.claude_bridge.claude_auth_status_ok()
        return {
            "claude_bin": self.claude_bridge.binary_path,
            "claude_ok": await self.claude_bridge.claude_version_probe_ok(),
            "claude_logged_in": claude_session,
            "codex_bin": self.codex_bridge.binary_path,
            "codex_logged_in": await self.codex_bridge.codex_login_status_ok(),
        }
