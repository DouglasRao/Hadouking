import json
import os
from typing import List, Optional

# ---------------------------------------------------------------------------
# Optional dependency flags (Item G: Dependency Robustness)
# ---------------------------------------------------------------------------
_HAS_DOTENV = False
_HAS_RICH = False
_HAS_PLAYWRIGHT = False
_HAS_AIOHTTP = False
_HAS_PROMPT_TOOLKIT = False

try:
    from dotenv import load_dotenv
    _HAS_DOTENV = True
    load_dotenv()
except ImportError:
    # dotenv is optional — rely on environment variables already set
    pass

try:
    import rich  # noqa: F401 — presence check
    _HAS_RICH = True
except ImportError:
    pass

try:
    import playwright  # noqa: F401
    _HAS_PLAYWRIGHT = True
except ImportError:
    pass

try:
    import aiohttp  # noqa: F401
    _HAS_AIOHTTP = True
except ImportError:
    pass

try:
    import prompt_toolkit  # noqa: F401
    _HAS_PROMPT_TOOLKIT = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Dependency introspection helpers
# ---------------------------------------------------------------------------
_DEPENDENCY_FLAGS = {
    "dotenv": _HAS_DOTENV,
    "rich": _HAS_RICH,
    "playwright": _HAS_PLAYWRIGHT,
    "aiohttp": _HAS_AIOHTTP,
    "prompt_toolkit": _HAS_PROMPT_TOOLKIT,
}

_CRITICAL_DEPS = ("rich", "prompt_toolkit")


def check_dependency(name: str) -> bool:
    """Return True if the optional dependency *name* is available."""
    return _DEPENDENCY_FLAGS.get(name, False)


def missing_dependencies() -> List[str]:
    """Return a list of names of missing optional dependencies."""
    return [name for name, available in _DEPENDENCY_FLAGS.items() if not available]


def _warn_missing_dependencies() -> None:
    """Print a brief one-time warning if critical optional deps are missing."""
    missing = [d for d in _CRITICAL_DEPS if not check_dependency(d)]
    if missing:
        print(
            f"[Hadouking] Warning: optional dependencies not installed: {', '.join(missing)}."
            f"  Some features will be limited. Install with: pip install {' '.join(missing)}"
        )


_warn_missing_dependencies()


def _anthropic_bearer_token() -> Optional[str]:
    """
    Bearer token for the Messages API (same mechanism as Claude Code: ANTHROPIC_AUTH_TOKEN).
    Optionally reads ~/.claude/.credentials.json (OAuth Claude.ai) if HADOUKING_USE_CLAUDE_CODE_CREDENTIALS=1.
    """
    env_t = (os.getenv("ANTHROPIC_AUTH_TOKEN") or "").strip()
    if env_t:
        return env_t
    if os.getenv("HADOUKING_USE_CLAUDE_CODE_CREDENTIALS", "").lower() not in (
        "1",
        "true",
        "yes",
    ):
        return None
    cfg_dir = (os.getenv("CLAUDE_CONFIG_DIR") or "").strip()
    base = os.path.expanduser(cfg_dir) if cfg_dir else os.path.expanduser("~/.claude")
    cred_path = os.path.join(base, ".credentials.json")
    try:
        with open(cred_path, encoding="utf-8") as f:
            data = json.load(f)
        oat = data.get("claudeAiOauth")
        if isinstance(oat, dict):
            at = (oat.get("accessToken") or oat.get("access_token") or "").strip()
            return at or None
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return None


class Config:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    # Bearer: Claude.ai account / gateway / OAuth (Authorization header); see Claude Code IAM docs
    ANTHROPIC_AUTH_TOKEN = _anthropic_bearer_token()
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

    _OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
    OPENAI_ENDPOINT = f"{_OPENAI_API_BASE}/chat/completions"

    # A2P (Agent-to-Peer) — optional and disabled by default (Item H)
    A2P_ENABLED = os.getenv("HADOUKING_A2P_ENABLED", "0") == "1"
    A2P_DEFAULT_PEER_MODEL = os.getenv("HADOUKING_A2P_PEER_MODEL", "")

    DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"
    OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
    ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
    ANTHROPIC_VERSION = os.getenv("ANTHROPIC_API_VERSION", "2023-06-01")

    DEFAULT_MODEL = "deepseek-chat"

    # Optional (c1/c2): route to official CLIs; not required for other models
    MODEL_CLAUDE_CODE_CLI = "claude-code-cli"
    MODEL_CODEX_CLI = "openai-codex-cli"

    @staticmethod
    def validate_keys():
        """Requires OPENAI + DEEPSEEK only in legacy mode; use validate_keys_for_api_mode at startup."""
        missing = []
        if not Config.OPENAI_API_KEY:
            missing.append("OPENAI_API_KEY")
        if not Config.DEEPSEEK_API_KEY:
            missing.append("DEEPSEEK_API_KEY")
        return missing

    @staticmethod
    def has_any_api_key():
        return any(
            [
                Config.OPENAI_API_KEY,
                Config.ANTHROPIC_API_KEY,
                Config.ANTHROPIC_AUTH_TOKEN,
                Config.DEEPSEEK_API_KEY,
                Config.OPENROUTER_API_KEY,
            ]
        )

    # Bridge `codex exec` (LLM via CLI)
    CODEX_EXEC_TIMEOUT_SEC = float(os.getenv("HADOUKING_CODEX_EXEC_TIMEOUT", "900"))
    CODEX_AUTH_PROBE_TIMEOUT_SEC = float(
        os.getenv("HADOUKING_CODEX_AUTH_PROBE_TIMEOUT", "75")
    )
    CODEX_EXEC_SANDBOX = os.getenv("HADOUKING_CODEX_SANDBOX", "read-only")
    CODEX_SKIP_MCP_OVERRIDE = os.getenv("HADOUKING_CODEX_SKIP_MCP", "1").lower() in (
        "1",
        "true",
        "yes",
    )
    CODEX_EXTRA_ARGS = os.getenv("HADOUKING_CODEX_EXTRA_ARGS", "")
    CODEX_WORKDIR = os.getenv("HADOUKING_CODEX_WORKDIR", "")
    # Codex subscription model; passed to `codex exec -m`. Empty = default from ~/.codex/config.toml
    CODEX_MODEL = (os.getenv("HADOUKING_CODEX_MODEL") or "").strip()

    CLAUDE_EXEC_TIMEOUT_SEC = float(os.getenv("HADOUKING_CLAUDE_EXEC_TIMEOUT", "900"))
    CLAUDE_EXTRA_ARGS = os.getenv("HADOUKING_CLAUDE_EXTRA_ARGS", "")

    HADOUKING_MAX_BG_TASKS = int(os.getenv("HADOUKING_MAX_BG_TASKS", "0"))

    # Strict modern mode: hide legacy/deprecated commands from /help
    HADOUKING_STRICT_MODERN = os.getenv("HADOUKING_STRICT_MODERN", "").lower() in (
        "1",
        "true",
        "yes",
    )

    # Output compaction (bash/MCP/Python) before LLM history — RTK-style, no external binary
    HADOUKING_COMPRESS_OUTPUT = os.getenv("HADOUKING_COMPRESS_OUTPUT", "1").lower() in (
        "1",
        "true",
        "yes",
    )
    HADOUKING_CONTEXT_MAX_CHARS = int(os.getenv("HADOUKING_CONTEXT_MAX_CHARS", "48000"))
    HADOUKING_CONTEXT_DEDUPE = os.getenv("HADOUKING_CONTEXT_DEDUPE", "1").lower() in (
        "1",
        "true",
        "yes",
    )
    HADOUKING_CONTEXT_STRIP_ANSI = os.getenv("HADOUKING_CONTEXT_STRIP_ANSI", "1").lower() in (
        "1",
        "true",
        "yes",
    )

    # Local execution: tiered layers like Claude Code / Codex (tiered = confirm network/mutation/priv)
    HADOUKING_EXEC_MODE = (os.getenv("HADOUKING_EXEC_MODE") or "tiered").strip().lower()
    HADOUKING_ALLOW_SUDO = os.getenv("HADOUKING_ALLOW_SUDO", "1").lower() in (
        "1",
        "true",
        "yes",
    )

    # Autonomous loop: prevents infinite cycles when commands are only suggested/denied/blocked
    HADOUKING_MAX_AGENT_TURNS = int(os.getenv("HADOUKING_MAX_AGENT_TURNS", "80"))
    HADOUKING_MAX_STUCK_COMMAND_ROUNDS = int(os.getenv("HADOUKING_MAX_STUCK_COMMAND_ROUNDS", "5"))
    # Safer default: only execute explicit fenced ```bash``` blocks.
    # Inline command extraction can be re-enabled for legacy behavior.
    HADOUKING_ALLOW_INLINE_BASH_FALLBACK = os.getenv(
        "HADOUKING_ALLOW_INLINE_BASH_FALLBACK", "0"
    ).lower() in ("1", "true", "yes")
    # LLM resilience / latency controls
    HADOUKING_LLM_TIMEOUT_SEC = float(os.getenv("HADOUKING_LLM_TIMEOUT_SEC", "120"))
    HADOUKING_LLM_RETRIES = int(os.getenv("HADOUKING_LLM_RETRIES", "1"))
    HADOUKING_HTTP_TIMEOUT_SEC = float(os.getenv("HADOUKING_HTTP_TIMEOUT_SEC", "110"))
    # Allowed executable names for MCP subprocess startup.
    # Comma-separated list; names are matched against command basename.
    HADOUKING_ALLOWED_MCP_COMMANDS = {
        item.strip()
        for item in (os.getenv("HADOUKING_ALLOWED_MCP_COMMANDS", "python,python3,node,npx,uv,uvx").split(","))
        if item.strip()
    }

    @staticmethod
    def input_guardrails_mode() -> str:
        """
        Input filter (messages / broadcast): suited for pentest with technical prompts.
        Executed commands always go through Guardrails.check_command (rm -rf /, etc.).

        - off / 0: disables check_input (only for fully controlled environments).
        - minimal (default): blocks obvious instruction overrides; doesn't block 'bash/curl' in prose.
        - full / 2: full list of injection patterns.
        """
        v = (os.getenv("HADOUKING_INPUT_GUARDRAILS") or "minimal").strip().lower()
        if v in ("0", "off", "false", "no", "disable"):
            return "off"
        if v in ("2", "full", "strict", "all"):
            return "full"
        return "minimal"

    @staticmethod
    def reply_locale() -> str:
        """en (default) or pt-BR - suffix injected into agent system prompts."""
        v = (os.getenv("HADOUKING_LOCALE") or "en").strip().lower()
        if v.startswith("pt"):
            return "pt-br"
        return "en"

    @staticmethod
    def system_prompt_locale_suffix() -> str:
        if Config.reply_locale() == "pt-br":
            return (
                "\n\n## Language (Hadouking)\n"
                "Reply to the operator **in Brazilian Portuguese (pt-BR)**. "
                "Keep tool names, HTTP headers, and technical acronyms in English as usual.\n"
            )
        return ""
