from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.layout import Layout
from rich.live import Live
from rich.align import Align
from rich.text import Text
from rich.status import Status
from contextlib import contextmanager
import threading

from config import Config

console = Console()
_status_lock = threading.Lock()

MODEL_OPTIONS = [
    # CLIs (subscription via official binary login)
    ("c1", "claude-code-cli", "Claude Code CLI", "Subscription"),
    ("c2", "openai-codex-cli", "Codex CLI", "Subscription"),
    # Anthropic API
    ("a1", "claude-sonnet-4-20250514", "Anthropic API", "Paid"),
    # OpenAI
    ("1", "gpt-4o", "OpenAI", "Paid"),
    ("2", "gpt-o1", "OpenAI", "Paid"),
    ("3", "gpt-o3-mini", "OpenAI", "Paid"),
    # DeepSeek
    ("4", "deepseek-chat", "DeepSeek", "Paid"),
    ("5", "deepseek-reasoner", "DeepSeek", "Paid"),
    # OpenRouter — free models
    ("6", "qwen/qwen3-235b-a22b:free", "OpenRouter", "Free"),
    ("7", "deepseek/deepseek-r1-0528-qwen3-8b:free", "OpenRouter", "Free"),
    ("8", "qwen/qwen-2.5-72b-instruct:free", "OpenRouter", "Free"),
    ("9", "qwen/qwen-2.5-coder-32b-instruct:free", "OpenRouter", "Free"),
    ("10", "qwen/qwen2.5-vl-32b-instruct:free", "OpenRouter", "Free"),
    ("11", "x-ai/grok-4.1-fast:free", "OpenRouter", "Free"),
    ("12", "google/gemini-2.0-flash-exp:free", "OpenRouter", "Free"),
    ("13", "tngtech/deepseek-r1t2-chimera:free", "OpenRouter", "Free"),
    # OpenRouter — paid
    ("14", "qwen/qwen-2.5-vl-72b-instruct", "OpenRouter", "Paid"),
    # Auto-Rotate
    ("99", "Auto-Rotate Free Models", "OpenRouter", "Free"),
]

# Step labels for UI panels
STEP_LABELS = {
    "Thinking": "Thinking",
    "Executing": "Executing command",
    "Output": "Model response",
    "Observation": "Output / result",
    "System": "System",
    "Error": "Error",
    "Project": "Project",
    "Browser": "Browser",
    "Vision": "Visual capture",
    "Vision Analysis": "Visual analysis",
    "Report": "Report",
    "Context": "Context",
    "Executing MCP": "MCP",
    "Executing Browser": "Browser",
}


def model_display_label(model: str) -> str:
    """Short name for panels: which backend is generating/analyzing."""
    if not model:
        return "—"
    if model == Config.MODEL_CLAUDE_CODE_CLI:
        return "Claude Code (CLI)"
    if model == Config.MODEL_CODEX_CLI:
        return "OpenAI Codex (CLI)"
    m = model.lower()
    if "claude" in m:
        return f"Anthropic API · {model}"
    if "gpt" in m or "o1" in m or "o3" in m:
        return f"OpenAI API · {model}"
    if "deepseek" in m:
        return f"DeepSeek · {model}"
    if "/" in model:
        return f"OpenRouter · {model}"
    return model


@contextmanager
def ThinkingStatus(message="Processing…"):
    """
    Context manager for showing a spinner while the agent is thinking.
    Thread-safe: If another spinner is active, it just prints the message.
    """
    if _status_lock.acquire(blocking=False):
        try:
            with console.status(f"[bold yellow]{message}[/bold yellow]", spinner="dots"):
                yield
        finally:
            _status_lock.release()
    else:
        console.print(f"[dim yellow]{message}[/dim yellow]")
        yield


def print_banner():
    """Render the Hadouking banner."""
    banner = """
[bold red]
  ██╗  ██╗ █████╗ ██████╗  ██████╗ ██╗   ██╗██╗  ██╗██╗███╗   ██╗ ██████╗
  ██║  ██║██╔══██╗██╔══██╗██╔═══██╗██║   ██║██║ ██╔╝██║████╗  ██║██╔════╝
  ███████║███████║██║  ██║██║   ██║██║   ██║█████╔╝ ██║██╔██╗ ██║██║  ███╗
  ██╔══██║██╔══██║██║  ██║██║   ██║██║   ██║██╔═██╗ ██║██║╚██╗██║██║   ██║
  ██║  ██║██║  ██║██████╔╝╚██████╔╝╚██████╔╝██║  ██╗██║██║ ╚████║╚██████╔╝
  ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝  ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝ ╚═════╝
[/bold red]
[dim]  AI-Driven Offensive Security Operations · Multi-Agent · Multi-Backend · MCP[/dim]
"""
    console.print(banner)


def show_auth_method_menu(auth_manager):
    """Auth channel selection (API vs official CLI)."""
    from core.auth import AuthMethod
    from utils.auth_preferences import load_last_auth_method_name

    methods = auth_manager.detect_available_methods()

    console.print("\n[bold cyan]Authentication Channel[/bold cyan]\n")

    last_name = load_last_auth_method_name()
    for i, m in enumerate(methods, 1):
        ok = m["available"]
        flag = "[green]ok[/green]" if ok else "[red]unavailable[/red]"
        star = (
            " [dim](last used)[/dim]"
            if last_name and m["method"].name == last_name
            else ""
        )
        console.print(
            f"  {i}) {m.get('icon', '')} [bold]{m['name']}[/bold] [{flag}]{star}"
        )

    console.print()
    choices = [str(i) for i in range(1, len(methods) + 1)]
    default_choice = "1"
    if last_name:
        for i, m in enumerate(methods, 1):
            if m["method"].name == last_name and m["available"]:
                default_choice = str(i)
                break
    choice = Prompt.ask("Option", choices=choices, default=default_choice)
    picked = methods[int(choice) - 1]
    method = picked["method"]
    if method != AuthMethod.API_KEY and not picked["available"]:
        console.print(
            "[yellow]This channel is unavailable (missing binary). Using API keys.[/yellow]"
        )
        return AuthMethod.API_KEY
    return method


def print_model_table(table_title: str = "Executor model"):
    table = Table(title=table_title, show_lines=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Model", style="green")
    table.add_column("Provider", style="yellow")
    table.add_column("Cost", style="magenta")

    for mid, name, provider, cost in MODEL_OPTIONS:
        table.add_row(mid, name, provider, cost)

    console.print()
    console.print(table)
    console.print(
        "\n[dim]IDs [bold]c1[/bold] and [bold]c2[/bold] require `claude` / `codex` CLIs installed; "
        "all others use API (keys in `.env`).[/dim]"
    )
    console.print()
    console.print(
        "[bold cyan]Tip:[/bold cyan] Auto-Rotate (99) cycles through free OpenRouter models to reduce rate limits.\n"
    )


def resolve_model_input(choice: str):
    """
    Resolve model identifier or explicit model name.
    Returns a normalized model string or None when invalid.
    """
    raw = (choice or "").strip()
    if not raw:
        return None
    if raw == "99":
        return "auto-rotate-free"

    by_id = {mid: name for mid, name, _, _ in MODEL_OPTIONS}
    if raw in by_id:
        return by_id[raw]

    valid_names = {name for _, name, _, _ in MODEL_OPTIONS}
    if raw in valid_names:
        return raw
    if raw == "auto-rotate-free":
        return raw
    return None


def show_model_menu(table_title: str = "Executor model"):
    print_model_table(table_title)

    choice = Prompt.ask(
        "Choose model ID",
        choices=[m[0] for m in MODEL_OPTIONS],
        default="1",
    )

    if not choice or choice not in [m[0] for m in MODEL_OPTIONS]:
        choice = "1"

    selected_model = resolve_model_input(choice) or "gpt-4o"
    if selected_model == "auto-rotate-free":
        console.print("[green]Selected: auto-rotate (free OpenRouter models).[/green]\n")
    else:
        console.print(f"[green]Selected model: {selected_model}[/green]\n")

    return selected_model


def print_agent_list(agents_dict):
    table = Table(title="Available Agents", show_lines=True, padding=(0, 1))
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Description", style="magenta")

    for name, data in sorted(agents_dict.items()):
        table.add_row(name, data["description"])

    console.print(table)


def print_active_agents(active_agents):
    if not active_agents:
        console.print("[yellow]No active agents.[/yellow]")
        return

    table = Table(title="Active Parallel Agents", padding=(0, 1))
    table.add_column("Agent", style="green")
    table.add_column("Status", style="white")

    for name in active_agents:
        table.add_row(name, "Active")

    console.print(table)


def print_agent_step(agent_name, step_type, content, model=None):
    """Shows an autonomous loop step. `model` = model ID for clear labeling."""
    colors = {
        "Thinking": "yellow",
        "Executing": "red",
        "Output": "green",
        "Observation": "blue",
        "System": "cyan",
        "Error": "red",
        "Project": "magenta",
        "Browser": "blue",
        "Vision": "magenta",
        "Vision Analysis": "magenta",
        "Report": "green",
        "Context": "yellow",
        "Executing MCP": "red",
        "Executing Browser": "red",
    }
    color = colors.get(step_type, "white")
    step_label = STEP_LABELS.get(step_type, step_type)
    backend = model_display_label(model) if model else None
    title_core = f"{agent_name} · {step_label}"
    if backend:
        title = f"[{color}]{title_core}[/{color}] [dim]({backend})[/dim]"
    else:
        title = f"[{color}]{title_core}[/{color}]"

    panel_kwargs = {"title": title, "border_style": color, "padding": (1, 2)}
    if step_type == "Executing":
        panel = Panel(Text(content, style="bold white"), **panel_kwargs)
    else:
        panel = Panel(Markdown(content), **panel_kwargs)
    console.print(panel)


def print_agent_response(agent_name, response):
    print_agent_step(agent_name, "Output", response)


def ask_command_approval(command, tier_label: str = "", approval_cache=None):
    """
    Return values:
    - "once": approve only this execution
    - "command": approve this exact command for this agent session
    - "scope": approve this risk tier for this agent session
    - "persist_command": approve this exact command and persist across restarts
    - "persist_scope": approve this risk tier and persist across restarts
    - "always": approve this and auto-approve next executions in this agent session
    - "deny": deny this execution
    """
    console.print("\n[bold red]WARNING: the agent wants to execute locally:[/bold red]")
    if tier_label:
        console.print(f"[dim]Risk tier (Hadouking policy): {tier_label}[/dim]")
    if approval_cache:
        console.print(
            "[dim]Session approvals cached:"
            f" exact={approval_cache.get('exact_approvals', 0)}"
            f" | tiers={approval_cache.get('tier_approvals', 0)}"
            f" | always={'on' if approval_cache.get('session_always') else 'off'}[/dim]"
        )
    console.print(Panel(command, style="bold white on black"))
    console.print(
        "[dim]Permission options: [y] once | [c] exact command | [s] same risk tier"
        " | [p] persist command | [q] persist tier | [a] always for this agent session | [n] deny[/dim]"
    )
    choice = Prompt.ask("Allow command?", choices=["y", "c", "s", "p", "q", "a", "n"], default="y")
    if choice == "a":
        return "always"
    if choice == "s":
        return "scope"
    if choice == "q":
        return "persist_scope"
    if choice == "p":
        return "persist_command"
    if choice == "c":
        return "command"
    if choice == "y":
        return "once"
    return "deny"
