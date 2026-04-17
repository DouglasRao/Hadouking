import asyncio
import sys
import os
import platform

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config
from core.manager import AgentManager
from core.auth import AuthManager, AuthMethod
from core.llm import LLM
from core.task_runner import BackgroundTaskRegistry
from core.multi_agent_orchestrator import MultiAgentOrchestrator, NATIVE_WORKER_ORDER
from agents.definitions import AGENTS
from utils.ui import (
    print_banner,
    print_agent_list,
    print_active_agents,
    console,
    print_model_table,
    resolve_model_input,
    show_auth_method_menu,
    model_display_label,
)
from utils.mcp_config import MCPConfig
from utils.cli_auth_wizard import complete_cli_authentication
from core.mcp import MCPClient
from prompt_toolkit import PromptSession
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table
from rich.live import Live
from utils.commands import iter_help_lines, normalize_command_input
from core.agent_team_ui import LiveInputCapture
from utils.session_state import (
    clear_session_state,
    default_session_state,
    load_session_state,
    save_session_state,
    session_state_path,
)
from utils.tokens import count_tokens
from utils.model_info import model_context_window as _model_context_window, fmt_k as _fmt_k


def _parse_agent_cli_flags(parts, key_index, default_model, available_mcps):
    """Extracts common flags from /multi_agent add and /task spawn."""
    agent_key = parts[key_index]
    model = default_model
    if "--model" in parts:
        model_idx = parts.index("--model") + 1
        if model_idx < len(parts):
            potential_model = parts[model_idx]
            if potential_model.lower() != "mcp":
                model = potential_model

    selected_mcps = []
    if "mcp" in parts:
        mcp_idx = parts.index("mcp")
        if mcp_idx + 1 < len(parts):
            mcp_arg = parts[mcp_idx + 1]
            if mcp_arg == "all":
                selected_mcps = list(available_mcps.values())
            elif mcp_arg in available_mcps:
                selected_mcps = [available_mcps[mcp_arg]]
            else:
                console.print(
                    f"[red]MCP Server '{mcp_arg}' not found or not connected.[/red]"
                )

    auto_approve = "--auto-approve" in parts
    allow_installs = "--allow-install" in parts
    allow_deletes = "--allow-delete" in parts
    limit = 10
    if "--limit" in parts:
        try:
            limit_idx = parts.index("--limit") + 1
            if limit_idx < len(parts):
                limit = int(parts[limit_idx])
        except ValueError:
            console.print("[red]Invalid limit value. Using default (10).[/red]")

    agent_name = agent_key
    if "--name" in parts:
        try:
            name_arg_idx = parts.index("--name") + 1
            if name_arg_idx < len(parts):
                agent_name = parts[name_arg_idx]
        except ValueError:
            pass

    use_browser = False
    headless = True
    browser_intelligence = False
    if "--browser-cli" in parts:
        use_browser = True
        headless = True
    elif "--browser-gui" in parts:
        use_browser = True
        headless = False
    elif "--browser" in parts:
        use_browser = True
        headless = True
    if "--browser-intelligence" in parts:
        browser_intelligence = True
        if not use_browser:
            use_browser = True

    runtime_os = None
    runtime_distro = None
    if "--os" in parts:
        os_idx = parts.index("--os") + 1
        if os_idx < len(parts):
            runtime_os = parts[os_idx]
    if "--distro" in parts:
        distro_idx = parts.index("--distro") + 1
        if distro_idx < len(parts):
            runtime_distro = parts[distro_idx]

    return {
        "agent_key": agent_key,
        "model": model,
        "selected_mcps": selected_mcps,
        "auto_approve": auto_approve,
        "limit": limit,
        "agent_name": agent_name,
        "allow_installs": allow_installs,
        "allow_deletes": allow_deletes,
        "use_browser": use_browser,
        "headless": headless,
        "browser_intelligence": browser_intelligence,
        "runtime_os": runtime_os,
        "runtime_distro": runtime_distro,
    }


def _maybe_collect_essential_runtime_setup(parts, opts, setup_state=None):
    """
    If the user invoked an agent command with minimal args, offer a quick baseline setup
    (model/OS/safety) to avoid hardcoding everything in the slash command.
    """
    has_explicit_model = "--model" in parts
    has_explicit_os = "--os" in parts or "--distro" in parts
    has_explicit_safety = (
        "--auto-approve" in parts
        or "--allow-install" in parts
        or "--allow-delete" in parts
    )
    force_reconfigure = "--reconfigure" in parts or "--setup" in parts

    # Reuse previous baseline setup across the session.
    if (
        setup_state
        and setup_state.get("configured")
        and not force_reconfigure
    ):
        if not has_explicit_model and setup_state.get("model"):
            opts["model"] = setup_state["model"]
        if not has_explicit_os:
            opts["runtime_os"] = setup_state.get("runtime_os")
            opts["runtime_distro"] = setup_state.get("runtime_distro")
        if not has_explicit_safety:
            opts["auto_approve"] = bool(setup_state.get("auto_approve", False))
            opts["allow_installs"] = bool(setup_state.get("allow_installs", False))
            opts["allow_deletes"] = bool(setup_state.get("allow_deletes", False))
        return opts

    if has_explicit_model and has_explicit_os and has_explicit_safety:
        return opts

    if not Confirm.ask(
        "Configure essential baseline before starting this agent?",
        default=not (has_explicit_model or has_explicit_os or has_explicit_safety),
    ):
        return opts

    if not has_explicit_model:
        model_input = Prompt.ask(
            "Model (ID from /model list or name; Enter = keep current default)",
            default="",
        ).strip()
        if model_input:
            resolved = resolve_model_input(model_input)
            if resolved:
                opts["model"] = resolved
            else:
                console.print(
                    f"[yellow]Invalid model '{model_input}', keeping: {opts['model']}[/yellow]"
                )

    if not has_explicit_os:
        system_default = {
            "darwin": "MacOS",
            "linux": "Linux",
            "windows": "Windows",
        }.get(platform.system().lower(), "Linux")
        os_choice = Prompt.ask(
            "Runtime operating system",
            choices=["MacOS", "Linux", "Windows"],
            default=system_default,
        )
        opts["runtime_os"] = os_choice
        if os_choice == "Linux":
            distro = Prompt.ask(
                "Linux distribution",
                choices=["Kali", "Ubuntu", "Debian", "Parrot", "Other"],
                default="Kali",
            )
            opts["runtime_distro"] = distro
        else:
            opts["runtime_distro"] = None

    if not has_explicit_safety:
        opts["auto_approve"] = Confirm.ask(
            "Auto-approve commands for this agent?",
            default=opts.get("auto_approve", False),
        )
        opts["allow_installs"] = Confirm.ask(
            "Allow package install/removal?",
            default=opts.get("allow_installs", False),
        )
        opts["allow_deletes"] = Confirm.ask(
            "Allow destructive delete commands?",
            default=opts.get("allow_deletes", False),
        )

    if setup_state is not None:
        setup_state["configured"] = True
        setup_state["model"] = opts.get("model")
        setup_state["runtime_os"] = opts.get("runtime_os")
        setup_state["runtime_distro"] = opts.get("runtime_distro")
        setup_state["auto_approve"] = bool(opts.get("auto_approve", False))
        setup_state["allow_installs"] = bool(opts.get("allow_installs", False))
        setup_state["allow_deletes"] = bool(opts.get("allow_deletes", False))

    return opts


def _resolve_agent_key(raw_key: str):
    """
    Resolve user-friendly agent identifiers to existing AGENTS keys.
    Examples:
    - recon_passive -> recon_passive_agent
    - reporting_agent -> reporting_agent
    """
    key = (raw_key or "").strip().lower()
    if not key:
        return None
    if key in AGENTS:
        return key
    candidate = f"{key}_agent"
    if candidate in AGENTS:
        return candidate
    # Prefix match fallback (only if unique)
    matches = [k for k in AGENTS.keys() if k.startswith(key)]
    if len(matches) == 1:
        return matches[0]
    return None


def _collect_agent_runtime_metrics(label: str, agent) -> dict:
    try:
        used = count_tokens(agent.history, agent.llm.model)
    except Exception:
        used = 0
    max_ctx = getattr(agent, "max_context_tokens", _model_context_window(agent.llm.model))
    pct = (used * 100.0 / max_ctx) if max_ctx else 0.0
    return {
        "label": label,
        "used": _fmt_k(int(used)),
        "max": _fmt_k(int(max_ctx)),
        "pct": pct,
        "ctx_injections": int(getattr(agent, "context_injection_count", 0) or 0),
        "ctx_docs": int(getattr(agent, "context_docs_loaded", 0) or 0),
        "actions": int(getattr(agent, "action_count", 0) or 0),
    }


def _check_pending_orchestrated_session():
    """Check if there's a pending orchestrated session that can be resumed."""
    from pathlib import Path as _Path

    state = load_session_state()
    if not state:
        return None
    last_session = state.get("last_orchestrated_session")
    if not last_session:
        return None
    session_dir = last_session.get("session_dir")
    if not session_dir:
        return None
    session_path = _Path(session_dir)
    team_dir = session_path / "team"
    config_path = team_dir / "config.json"
    cleanup_path = team_dir / "cleanup.json"
    if not config_path.exists() or cleanup_path.exists():
        return None
    return last_session


def _parse_worker_selection(raw: str) -> list[str]:
    allowed_workers = {key for key, _label in NATIVE_WORKER_ORDER}
    selected = []
    seen = set()
    for token in (raw or "").split(","):
        resolved = _resolve_agent_key(token.strip())
        if not resolved:
            raise ValueError(f"Worker '{token.strip()}' not found.")
        if resolved not in allowed_workers:
            raise ValueError(f"Worker '{token.strip()}' is not a valid orchestrated subagent.")
        if resolved not in seen:
            selected.append(resolved)
            seen.add(resolved)
    return selected


async def _await_session_with_live_context(
    task_session,
    agent,
    title: str,
    selected_model: str,
    advisor_model: str,
):
    def _render():
        metrics = _collect_agent_runtime_metrics(agent.name, agent)
        table = Table(title=title)
        table.add_column("Task")
        table.add_column("State")
        table.add_column("Actions")
        table.add_column("Contexts")
        table.add_column("Docs")
        table.add_column("Usage")
        table.add_row(
            str(task_session.id),
            task_session.state.value,
            str(metrics["actions"]),
            str(metrics["ctx_injections"]),
            str(metrics["ctx_docs"]),
            f"{metrics['used']}/{metrics['max']} ({metrics['pct']:.1f}%)",
        )
        return Panel(
            table,
            title=(
                f"CTX executor={selected_model} (~{_fmt_k(_model_context_window(selected_model))}) | "
                f"peer={advisor_model} (~{_fmt_k(_model_context_window(advisor_model))})"
            ),
            border_style="magenta",
        )

    with Live(_render(), console=console, refresh_per_second=4) as live:
        while task_session.asyncio_task and not task_session.asyncio_task.done():
            live.update(_render())
            await asyncio.sleep(0.25)
        if task_session.asyncio_task:
            await task_session.asyncio_task
        live.update(_render())


async def _await_agent_task_with_live_context(
    task,
    agent,
    title: str,
    selected_model: str,
    advisor_model: str,
):
    def _render():
        metrics = _collect_agent_runtime_metrics(agent.name, agent)
        table = Table(title=title)
        table.add_column("Agent")
        table.add_column("Actions")
        table.add_column("Contexts")
        table.add_column("Docs")
        table.add_column("Usage")
        table.add_row(
            agent.name,
            str(metrics["actions"]),
            str(metrics["ctx_injections"]),
            str(metrics["ctx_docs"]),
            f"{metrics['used']}/{metrics['max']} ({metrics['pct']:.1f}%)",
        )
        return Panel(
            table,
            title=(
                f"CTX executor={selected_model} (~{_fmt_k(_model_context_window(selected_model))}) | "
                f"peer={advisor_model} (~{_fmt_k(_model_context_window(advisor_model))})"
            ),
            border_style="magenta",
        )

    cap = LiveInputCapture()
    cap.start()
    try:
        with Live(_render(), console=console, refresh_per_second=4) as live:
            while not task.done():
                instr = cap.poll()
                if instr:
                    agent.submit_instruction(instr)
                    console.print(
                        f"[dim cyan]Instruction queued → applied at next checkpoint: {instr[:120]}[/dim cyan]"
                    )
                live.update(_render())
                await asyncio.sleep(0.25)
            await task
            live.update(_render())
    finally:
        cap.stop()


def _print_context_status_line(manager, task_registry, selected_model: str, advisor_model: str):
    exec_ctx = _model_context_window(selected_model)
    peer_ctx = _model_context_window(advisor_model)

    # Aggregate unique agents from interactive manager + background sessions.
    # This keeps context metrics updated even when work runs via /task spawn or quick /multi_agent.
    unique_agents = {}
    for name, agent in manager.agents.items():
        unique_agents[id(agent)] = (name, agent)
    sessions = task_registry.list_sessions()
    for s in sessions:
        if s.agent is None:
            continue
        if id(s.agent) in unique_agents:
            continue
        unique_agents[id(s.agent)] = (f"task#{s.id}:{s.name}", s.agent)

    active_parts = []
    total_context_injections = 0
    total_context_docs = 0
    for name, agent in unique_agents.values():
        try:
            used = count_tokens(agent.history, agent.llm.model)
        except Exception:
            used = 0
        max_ctx = getattr(agent, "max_context_tokens", _model_context_window(agent.llm.model))
        pct = (used * 100.0 / max_ctx) if max_ctx else 0.0
        ctx_injections = int(getattr(agent, "context_injection_count", 0) or 0)
        ctx_docs = int(getattr(agent, "context_docs_loaded", 0) or 0)
        total_context_injections += ctx_injections
        total_context_docs += ctx_docs
        active_parts.append(
            f"{name}:{_fmt_k(used)}/{_fmt_k(max_ctx)} ({pct:.1f}%) ctx={ctx_injections}/{ctx_docs}"
        )

    bg_running = sum(
        1 for s in sessions if str(s.state.value) in ("pending", "running", "paused")
    )
    active_agents_txt = " | ".join(active_parts) if active_parts else "no active agents"

    # Approval state summary across all agents
    approval_parts = []
    for name, agent in unique_agents.values():
        try:
            ap = agent.get_approval_cache_state()
            always = ap.get("session_always", False)
            cmds = int(ap.get("exact_approvals", 0) or 0)
            tiers = len(ap.get("session_tiers", []) or [])
            persist_cmds = int(ap.get("persistent_commands", 0) or 0)
            persist_tiers = len(ap.get("persistent_tiers", []) or [])
            if always or cmds or tiers or persist_cmds or persist_tiers:
                flags = []
                if always:
                    flags.append("always")
                if tiers:
                    flags.append(f"{tiers}tier")
                if cmds:
                    flags.append(f"{cmds}cmd")
                if persist_tiers or persist_cmds:
                    flags.append(f"persisted:{persist_tiers}t/{persist_cmds}c")
                approval_parts.append(f"{name}:[{','.join(flags)}]")
        except Exception:
            pass
    approval_txt = " | ".join(approval_parts) if approval_parts else ""

    status_line = (
        f"[dim]CTX executor={selected_model} (~{_fmt_k(exec_ctx)}) | "
        f"peer={advisor_model} (~{_fmt_k(peer_ctx)}) | "
        f"contexts_used={total_context_injections} (docs={total_context_docs}) | "
        f"agents: {active_agents_txt} | bg_tasks={bg_running}"
    )
    if approval_txt:
        status_line += f" | approvals: {approval_txt}"
    status_line += "[/dim]"
    console.print(status_line)


async def main():
    print_banner()

    auth_manager = AuthManager()
    auth_method = show_auth_method_menu(auth_manager)
    ok = await complete_cli_authentication(auth_manager, auth_method)
    if ok:
        from utils.auth_preferences import save_last_auth_method

        save_last_auth_method(auth_method)
    if not ok:
        console.print(
            "[bold red]Authentication failed.[/bold red] "
            "Claude Code and Codex are not required: with [bold]option 1[/bold] just set credentials in `.env` "
            "(OPENAI_API_KEY, ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN Bearer, DEEPSEEK_API_KEY or OPENROUTER_API_KEY). "
            "If you chose CLI (2 or 3), install the binary and complete login, or restart and choose API keys."
        )
        return

    available_mcps = {}

    async def load_mcps():
        nonlocal available_mcps
        for client in available_mcps.values():
            await client.disconnect()
        available_mcps.clear()
        mcp_config = MCPConfig()
        if mcp_config.servers:
            console.print("\n[blue]Connecting MCP servers from settings.json...[/blue]\n")
            failed_names = []
            for name, config in mcp_config.servers.items():
                try:
                    client = MCPClient(name, config)
                    try:
                        if await asyncio.wait_for(client.connect(), timeout=5.0):
                            available_mcps[name] = client
                            console.print(
                                f"[green]✓ MCP '{name}' connected ({len(client.tools)} tools)[/green]"
                            )
                        else:
                            failed_names.append(name)
                            console.print(
                                f"[red]✗ MCP '{name}' failed to connect (process or backend unreachable)[/red]"
                            )
                    except asyncio.TimeoutError:
                        failed_names.append(name)
                        console.print(
                            f"[red]✗ MCP '{name}' timed out; the service is likely down or responding too slowly[/red]"
                        )
                        await client.disconnect()
                except Exception as e:
                    failed_names.append(name)
                    console.print(f"[red]✗ MCP '{name}': {e}[/red]")
            if failed_names:
                console.print()
                console.print(
                    "[yellow]These MCPs depend on external services (Burp/proxy, Kali API, Hexstrike, and similar) "
                    "running on the ports or URLs defined in settings.json.[/yellow]"
                )
                console.print(
                    "[dim]Start the services and run [bold]/mcp reload[/bold]. The rest of the app still works without MCP.[/dim]"
                )

    await load_mcps()

    persisted_state = load_session_state()
    session_persistence_enabled = True

    persisted_cli = persisted_state.get("cli", {})
    persisted_workspace = persisted_state.get("workspace", {})
    persisted_baseline = persisted_state.get("baseline", {})

    selected_model = (
        persisted_cli.get("selected_model")
        or Config.DEFAULT_MODEL
    )
    advisor_model = (
        persisted_cli.get("advisor_model")
        or (Config.A2P_DEFAULT_PEER_MODEL if Config.A2P_ENABLED and Config.A2P_DEFAULT_PEER_MODEL else "")
        or selected_model
    )
    peer_follows_executor = bool(
        persisted_cli.get("peer_follows_executor", advisor_model == selected_model)
    )
    advisor_llm = LLM(advisor_model, auth_manager=auth_manager)
    if Config.A2P_ENABLED and Config.A2P_DEFAULT_PEER_MODEL and not persisted_cli.get("advisor_model"):
        console.print(
            f"[dim]A2P peer model from env:[/dim] [magenta]{model_display_label(advisor_model)}[/magenta]"
        )
    console.print(
        f"\n[dim]Default executor:[/dim] [yellow]{model_display_label(selected_model)}[/yellow]"
    )
    console.print(
        f"[dim]A2P peer:[/dim] [magenta]{model_display_label(advisor_model)}[/magenta] (follows executor by default)\n"
    )

    restored_project_dir = (persisted_workspace.get("shared_project_dir") or "").strip()
    manager = AgentManager(shared_project_dir=restored_project_dir or None)
    task_registry = BackgroundTaskRegistry()
    essential_setup_state = {
        "configured": bool(persisted_baseline.get("configured", False)),
        "model": persisted_baseline.get("model"),
        "runtime_os": persisted_baseline.get("runtime_os"),
        "runtime_distro": persisted_baseline.get("runtime_distro"),
        "auto_approve": bool(persisted_baseline.get("auto_approve", False)),
        "allow_installs": bool(persisted_baseline.get("allow_installs", False)),
        "allow_deletes": bool(persisted_baseline.get("allow_deletes", False)),
    }
    multi_agent_orchestrator = MultiAgentOrchestrator(
        auth_manager=auth_manager,
        manager=manager,
    )

    def _persist_runtime_state() -> None:
        if not session_persistence_enabled:
            return
        save_session_state(
            {
                "cli": {
                    "selected_model": selected_model,
                    "advisor_model": advisor_model,
                    "peer_follows_executor": peer_follows_executor,
                },
                "baseline": dict(essential_setup_state),
                "workspace": {
                    "shared_project_dir": manager.shared_project_dir,
                },
                "last_orchestrated_session": {
                    "session_dir": (
                        str(multi_agent_orchestrator.last_session_dir)
                        if multi_agent_orchestrator.last_session_dir
                        else (
                            persisted_state.get("last_orchestrated_session", {}) or {}
                        ).get("session_dir", "")
                    ),
                    "report_path": (
                        str(multi_agent_orchestrator.last_report_path)
                        if multi_agent_orchestrator.last_report_path
                        else (
                            persisted_state.get("last_orchestrated_session", {}) or {}
                        ).get("report_path", "")
                    ),
                    "target": multi_agent_orchestrator.last_target
                    or (persisted_state.get("last_orchestrated_session", {}) or {}).get("target", ""),
                    "mode": multi_agent_orchestrator.last_mode
                    or (persisted_state.get("last_orchestrated_session", {}) or {}).get("mode", "auto"),
                    "selected_worker_keys": multi_agent_orchestrator.last_selected_worker_keys
                    or (persisted_state.get("last_orchestrated_session", {}) or {}).get("selected_worker_keys", []),
                    "models": multi_agent_orchestrator.last_models
                    or (persisted_state.get("last_orchestrated_session", {}) or {}).get("models", {}),
                },
            }
        )

    _persist_runtime_state()

    if restored_project_dir or essential_setup_state.get("configured"):
        console.print(
            f"[dim]Restored session state from {session_state_path()}[/dim]"
        )

    history_file = os.path.join(os.path.dirname(__file__), ".hadouking_history")
    kb = KeyBindings()

    @kb.add("tab")
    def _(event):
        buffer = event.app.current_buffer
        suggestion = buffer.suggestion
        if suggestion:
            buffer.insert_text(suggestion.text)
        else:
            buffer.insert_text("    ")

    session = PromptSession(
        history=FileHistory(history_file),
        auto_suggest=AutoSuggestFromHistory(),
        enable_history_search=True,
        key_bindings=kb,
        completer=None,
        complete_while_typing=False,
        complete_style=CompleteStyle.MULTI_COLUMN,
        reserve_space_for_menu=8,
    )

    console.print(
        "\n[bold yellow]System ready.[/bold yellow] Primary workflow: "
        "[bold]/multi_agent <target> [objective][/bold]. Use [bold]/help[/bold] for commands.\n"
    )
    console.print(
        "[dim]Tip: use /model to configure executor/peer models, /multi_agent workers <w1,w2,...> for scoped runs, "
        "and ↑/↓ for history. /multi_agents remains as a deprecated compatibility alias.[/dim]\n"
    )

    async def _run_orchestrated_multi(parts):
        if len(parts) < 2:
            target = (await session.prompt_async("Target (/multi_agent)> ")).strip()
            if not target:
                console.print("[yellow]No target provided.[/yellow]")
                return
            objective = (await session.prompt_async("Objective (optional)> ")).strip()
            mode = "auto"
            selected_worker_keys = None
        else:
            mode = "auto"
            idx = 1
            if parts[idx] in ("temporary", "native"):
                mode = parts[idx]
                idx += 1

            selected_worker_keys = None
            if idx < len(parts) and parts[idx] in ("workers", "only"):
                if idx + 1 >= len(parts):
                    console.print(
                        "[red]Usage: /multi_agent [temporary|native] workers <w1,w2,...> <target> [objective][/red]"
                    )
                    return
                try:
                    selected_worker_keys = _parse_worker_selection(parts[idx + 1])
                except ValueError as e:
                    console.print(f"[red]{e}[/red]")
                    return
                idx += 2
            elif idx < len(parts) and "," in parts[idx]:
                try:
                    selected_worker_keys = _parse_worker_selection(parts[idx])
                    idx += 1
                except ValueError:
                    selected_worker_keys = None

            if idx >= len(parts):
                target = (await session.prompt_async("Target (/multi_agent)> ")).strip()
                if not target:
                    console.print("[yellow]No target provided.[/yellow]")
                    return
                objective = (await session.prompt_async("Objective (optional)> ")).strip()
            else:
                target = parts[idx]
                objective = " ".join(parts[idx + 1 :]).strip()

        console.print(
            f"[cyan]Starting orchestrated multi-agent workflow for target: {target}[/cyan]"
        )
        console.print(
            "[dim]During /multi_agent run, you can queue runtime guidance with "
            "`:your instruction` + Enter (applied in the next coordination cycle).[/dim]"
        )
        try:
            summary = await multi_agent_orchestrator.run(
                target=target,
                default_model=Config.DEFAULT_MODEL,
                available_mcps=available_mcps,
                mode=mode,
                user_objective=objective,
                selected_worker_keys=selected_worker_keys,
            )
            console.print(
                Panel(
                    Markdown(summary[:6000]),
                    title=f"Multi-agent final summary ({target})",
                    border_style="cyan",
                )
            )
        except (KeyboardInterrupt, asyncio.CancelledError):
            console.print(
                "\n[yellow]Orchestrated session interrupted.[/yellow] "
                "Session state has been persisted — use [bold]/session resume[/bold] or restart to continue."
            )
            _persist_runtime_state()
        except Exception as e:
            console.print(f"[red]/multi_agent failed: {e}[/red]")

    async def _resume_orchestrated_session(session_dir: str = ""):
        state = load_session_state()
        last_team = state.get("last_orchestrated_session", {}) or {}
        target_session_dir = session_dir or str(last_team.get("session_dir", "")).strip()
        if not target_session_dir:
            console.print("[yellow]No persisted orchestrated session available to resume.[/yellow]")
            return
        details = multi_agent_orchestrator.inspect_resumable_session(target_session_dir)
        if not details.get("resumable", False):
            errors = details.get("errors", [])
            if isinstance(errors, list) and errors:
                console.print("[red]Resume precheck failed:[/red]")
                for err in errors:
                    console.print(f"[red]- {err}[/red]")
            else:
                console.print("[red]Resume precheck failed: session is not resumable.[/red]")
            return
        console.print(
            f"[cyan]Resuming orchestrated session from:[/cyan] {target_session_dir}"
        )
        try:
            summary = await multi_agent_orchestrator.resume(
                session_dir=target_session_dir,
                available_mcps=available_mcps,
            )
            _persist_runtime_state()
            console.print(
                Panel(
                    Markdown(summary[:6000]),
                    title="Resumed multi-agent final summary",
                    border_style="cyan",
                )
            )
        except Exception as e:
            console.print(f"[red]Resume failed: {e}[/red]")

    # Auto-resume detection (Item C)
    pending = _check_pending_orchestrated_session()
    if pending:
        console.print(
            f"\n[yellow]Pending orchestrated session found:[/yellow] {pending.get('session_dir', 'unknown')}"
        )
        console.print(
            f"  Target: {pending.get('target', 'unknown')} | "
            f"Mode: {pending.get('mode', 'unknown')}"
        )
        if Confirm.ask("Resume this session?", default=True):
            await _resume_orchestrated_session(pending.get("session_dir", ""))

    while True:
        try:
            _persist_runtime_state()
            _print_context_status_line(
                manager=manager,
                task_registry=task_registry,
                selected_model=selected_model,
                advisor_model=advisor_model,
            )
            user_input = await session.prompt_async("Hadouking> ")
            user_input = normalize_command_input(user_input)
            user_input = user_input.strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit"]:
                break

            if user_input.startswith("/"):
                parts = user_input.split()
                command = parts[0].lower()

                if command == "/help":
                    _strict = Config.HADOUKING_STRICT_MODERN
                    console.print("\n[bold cyan]Hadouking command reference[/bold cyan]\n")
                    if _strict:
                        console.print("[dim](strict-modern mode: legacy commands hidden — unset HADOUKING_STRICT_MODERN to see all)[/dim]\n")
                    console.print("[bold]Quick start[/bold]")
                    console.print("  1. Use /model to list or change the default executor model.")
                    console.print("  2. Use /multi_agent <target> to run the orchestrated brain + specialists flow with all workers by default.")
                    console.print("  3. Use /multi_agent workers <w1,w2,...> <target> to run only a selected subset of workers.")
                    console.print("  4. Use /session resume to resume the last persisted orchestrated session.")
                    console.print("  5. Use /single_agent (or /sa) only when you want one persistent specialist session.")
                    if not _strict:
                        console.print("  6. Legacy/advanced commands are listed in the Legacy / Advanced section.")
                    console.print()
                    for section_title, entries in iter_help_lines(strict_modern=_strict):
                        console.print(f"[bold]{section_title}[/bold]")
                        for entry in entries:
                            console.print(f"  {entry.command} — {entry.description}")
                        console.print()
                    console.print("\n[bold]Modern Flow Examples[/bold]")
                    console.print("  /multi_agent testphp.vulnweb.com map attack surface and validate top risks")
                    console.print("  /multi_agent native testphp.vulnweb.com full PTES flow")
                    console.print("  /multi_agent workers recon_passive,recon_active,api_testing testphp.vulnweb.com auth and attack-surface focus")
                    console.print("  /multi_agent resume")
                    console.print("  /single_agent recon_passive_agent --model deepseek-chat")
                    console.print(
                        "\n[bold]Quick Test Prompts[/bold]"
                    )
                    console.print("  /multi_agent testphp.vulnweb.com full PTES flow")
                    console.print("  /multi_agent workers recon_passive,recon_active,vuln_scanner testphp.vulnweb.com baseline mapping")
                    console.print("  /single_agent recon_passive_agent --model deepseek-chat")
                    console.print("  /single_agent api_testing_agent --model deepseek-chat")
                    console.print("  /session resume")
                    console.print("\n[bold]Legacy / Advanced Examples[/bold]")
                    console.print("  /multi_agents temporary testphp.vulnweb.com full PTES flow")
                    console.print("  (deprecated alias path; prefer /multi_agent)")
                    console.print("  /multi_agent add recon_passive_agent --model deepseek-chat --name recon1 --limit 10 --auto-approve")
                    console.print("  /task spawn reporting_agent --model deepseek-chat --name report_task")
                    console.print(
                        "[dim]Common flags: --model, --limit, --name, --auto-approve, --browser, "
                        "--browser-cli, --browser-gui, --browser-intelligence, --allow-install, --allow-delete, "
                        "--os, --distro, mcp all, mcp <name>[/dim]"
                    )
                    console.print(
                        "[dim]Short aliases: /h, /mo, /a, /sa, /ma, /t, /p, /m, /as (legacy: /mas)[/dim]"
                    )
                    console.print(
                        "[dim]CLI login is only required for c1/c2. API-backed models do not need `claude` or `codex` installed.[/dim]"
                    )
                    console.print()
                    if available_mcps:
                        console.print("\n[bold]Connected MCPs[/bold]")
                        for name in available_mcps:
                            console.print(f"  - {name}")
                        console.print()

                elif command == "/model":
                    sub = parts[1].lower() if len(parts) > 1 else "show"
                    if sub in ("show", "current"):
                        follow_mode = "on" if peer_follows_executor else "off"
                        console.print(
                            f"[cyan]Executor model:[/cyan] {selected_model}\n"
                            f"[cyan]A2P peer model:[/cyan] {advisor_model} "
                            f"[dim](follow executor: {follow_mode})[/dim]"
                        )
                    elif sub == "list":
                        print_model_table("Main model (executor)")
                    elif sub == "set":
                        if len(parts) < 3:
                            console.print("[red]Usage: /model set <id|model_name>[/red]")
                            continue
                        selected = resolve_model_input(parts[2])
                        if not selected:
                            console.print(f"[red]Invalid model: {parts[2]}[/red]")
                            print_model_table("Main model (executor)")
                            continue
                        selected_model = selected
                        Config.DEFAULT_MODEL = selected_model
                        if peer_follows_executor:
                            advisor_model = selected_model
                            advisor_llm = LLM(advisor_model, auth_manager=auth_manager)
                        console.print(
                            f"[green]Executor model updated:[/green] {selected_model}"
                        )
                    elif sub == "peer":
                        if len(parts) < 3:
                            console.print(
                                "[red]Usage: /model peer <same|id|model_name>[/red]"
                            )
                            continue
                        raw = parts[2].strip()
                        if raw.lower() == "same":
                            peer_follows_executor = True
                            advisor_model = selected_model
                            advisor_llm = LLM(advisor_model, auth_manager=auth_manager)
                            console.print(
                                f"[green]A2P peer now follows executor:[/green] {advisor_model}"
                            )
                            continue
                        peer_selected = resolve_model_input(raw)
                        if not peer_selected:
                            console.print(f"[red]Invalid peer model: {raw}[/red]")
                            print_model_table("Peer model")
                            continue
                        peer_follows_executor = False
                        advisor_model = peer_selected
                        advisor_llm = LLM(advisor_model, auth_manager=auth_manager)
                        console.print(
                            f"[green]A2P peer model updated:[/green] {advisor_model}"
                        )
                    else:
                        console.print(
                            "[red]Usage: /model [show|list|set <id|name>|peer <same|id|name>][/red]"
                        )

                elif command == "/autotest":
                    from utils.autotest import run_full_autotest

                    mcp_list = list(available_mcps.values())
                    try:
                        ex_m, adv_m, _pair_desc = await run_full_autotest(
                            auth_manager, mcp_list
                        )
                        selected_model = ex_m
                        advisor_model = adv_m
                        peer_follows_executor = advisor_model == selected_model
                        Config.DEFAULT_MODEL = selected_model
                        advisor_llm = LLM(advisor_model, auth_manager=auth_manager)
                        console.print(
                            "[green]Autotest complete. Models updated from autotest result.[/green]"
                        )
                    except Exception as e:
                        console.print(f"[bold red]Autotest failed:[/bold red] {e}")

                elif command == "/mcp" and len(parts) > 1 and parts[1] == "reload":
                    await load_mcps()

                elif command == "/mcp" and len(parts) > 1 and parts[1] == "list":
                    if available_mcps:
                        console.print("\n[bold cyan]Connected MCPs[/bold cyan]\n")
                        for name, client in available_mcps.items():
                            tc = len(client.tools) if hasattr(client, "tools") else 0
                            console.print(f"  [green]✓[/green] {name} ({tc} tools)")
                        console.print()
                    else:
                        console.print("[yellow]No MCPs connected.[/yellow]")

                elif command == "/auth":
                    if len(parts) < 2 or parts[1] != "status":
                        console.print("[yellow]Usage: /auth status[/yellow]")
                    else:
                        st = await auth_manager.refresh_cli_status()
                        c_ok = "[green]OK[/green]" if st["claude_ok"] else "[red]failed[/red]"
                        cli_in = st["claude_logged_in"]
                        if cli_in is True:
                            c_sess = "[green]session OK[/green]"
                        elif cli_in is False:
                            c_sess = "[red]no session[/red]"
                        else:
                            c_sess = "[dim]auth status unavailable (old CLI?)[/dim]"
                        x_ok = (
                            "[green]logged in[/green]"
                            if st["codex_logged_in"]
                            else "[red]not authenticated[/red]"
                        )
                        auth_ok = (
                            "[green]yes[/green]"
                            if auth_manager.is_authenticated()
                            else "[red]no[/red]"
                        )
                        console.print(
                            f"[cyan]claude[/cyan]: bin={st['claude_bin']}  probe={c_ok}  {c_sess}"
                        )
                        console.print(
                            f"[cyan]codex[/cyan]: bin={st['codex_bin']}  {x_ok}"
                        )
                        console.print(
                            f"Active method: [bold]{auth_manager.active_method}[/bold]  "
                            f"startup session={auth_ok}"
                        )

                elif command == "/session":
                    sub = parts[1].lower() if len(parts) > 1 else "show"
                    if sub == "show":
                        state = load_session_state()
                        last_team = state.get("last_orchestrated_session", {}) or {}
                        console.print(
                            Panel(
                                "\n".join(
                                    [
                                        f"state file: {session_state_path()}",
                                        f"executor: {state.get('cli', {}).get('selected_model') or '-'}",
                                        f"peer: {state.get('cli', {}).get('advisor_model') or '-'}",
                                        f"peer_follows_executor: {state.get('cli', {}).get('peer_follows_executor', True)}",
                                        f"shared_project_dir: {state.get('workspace', {}).get('shared_project_dir') or '-'}",
                                        f"baseline_configured: {state.get('baseline', {}).get('configured', False)}",
                                        f"last_team_target: {last_team.get('target') or '-'}",
                                        f"last_team_session_dir: {last_team.get('session_dir') or '-'}",
                                        f"last_team_report: {last_team.get('report_path') or '-'}",
                                    ]
                                ),
                                title="Persisted Session",
                                border_style="cyan",
                            )
                        )
                    elif sub == "resume":
                        session_dir = parts[2] if len(parts) > 2 else ""
                        await _resume_orchestrated_session(session_dir=session_dir)
                    elif sub == "reset":
                        session_persistence_enabled = False
                        clear_session_state()
                        save_session_state(default_session_state())
                        essential_setup_state = {"configured": False}
                        persisted_state = default_session_state()
                        multi_agent_orchestrator.last_session_dir = None
                        multi_agent_orchestrator.last_report_path = None
                        multi_agent_orchestrator.last_target = ""
                        multi_agent_orchestrator.last_mode = "auto"
                        multi_agent_orchestrator.last_selected_worker_keys = []
                        multi_agent_orchestrator.last_models = {}
                        console.print(
                            f"[green]Persisted session state cleared:[/green] {session_state_path()}"
                        )
                        session_persistence_enabled = True
                    else:
                        console.print("[yellow]Usage: /session [show|resume [session_dir]|reset][/yellow]")

                elif command == "/approvals":
                    # Collect approval state from all active agents
                    all_agents = {}
                    for name, agent in manager.agents.items():
                        all_agents[name] = agent
                    sessions = task_registry.list_sessions()
                    for s in sessions:
                        if s.agent is not None and id(s.agent) not in {id(a) for a in all_agents.values()}:
                            all_agents[f"task#{s.id}:{s.name}"] = s.agent
                    a2p_status = "[green]enabled[/green]" if Config.A2P_ENABLED else "[dim]disabled (set HADOUKING_A2P_ENABLED=1)[/dim]"
                    console.print(f"\n[bold cyan]Approval State[/bold cyan]  |  A2P: {a2p_status}\n")
                    if not all_agents:
                        console.print("[yellow]No active agents with approval state.[/yellow]")
                    else:
                        from rich.table import Table as _Table
                        tbl = _Table(show_lines=True)
                        tbl.add_column("Agent", style="cyan")
                        tbl.add_column("Always", style="yellow")
                        tbl.add_column("Session tiers")
                        tbl.add_column("Session cmds")
                        tbl.add_column("Persist tiers")
                        tbl.add_column("Persist cmds")
                        for aname, agent in all_agents.items():
                            ap = agent.get_approval_cache_state()
                            session_tiers = ap.get("session_tiers") or []
                            persist_tiers = ap.get("persistent_tiers") or []
                            tbl.add_row(
                                aname,
                                "[bold green]YES[/bold green]" if ap.get("session_always") else "no",
                                ", ".join(str(t).replace("tier::", "") for t in session_tiers) or "—",
                                str(ap.get("exact_approvals", 0)),
                                ", ".join(str(t).replace("tier::", "") for t in persist_tiers) or "—",
                                str(ap.get("persistent_commands", 0)),
                            )
                        console.print(tbl)
                    console.print(
                        "\n[dim]Scopes: [y] once | [c] cmd/session | [s] tier/session | "
                        "[p] cmd/persist | [q] tier/persist | [a] always/session[/dim]\n"
                    )

                elif command == "/agent" and len(parts) > 1 and parts[1] == "list":
                    print_agent_list(AGENTS)

                elif command == "/peer":
                    if len(parts) >= 3 and parts[1] == "consult":
                        aname = parts[2]
                        note = " ".join(parts[3:]) if len(parts) > 3 else ""
                        agent = manager.agents.get(aname)
                        if not agent:
                            console.print(f"[red]Agent '{aname}' not found.[/red]")
                        else:
                            r = await agent.consult_peer(advisor_llm, user_note=note)
                            console.print(Panel(Markdown(r), title="Peer A2P", border_style="cyan"))
                    else:
                        console.print(
                            "[red]Usage: /peer consult <agent_name> [optional note][/red]"
                        )

                elif command == "/task":
                    if len(parts) < 2:
                        console.print(
                            "[red]Usage: /task list | pause | resume | cancel | insight (legacy/advanced: spawn)[/red]"
                        )
                    else:
                        sub = parts[1].lower()
                        if sub == "list":
                            rows = task_registry.list_sessions()
                            if not rows:
                                console.print("[yellow]No background tasks.[/yellow]")
                            else:
                                from rich.table import Table

                                t = Table(title="Tasks")
                                t.add_column("ID")
                                t.add_column("Name")
                                t.add_column("Status")
                                t.add_column("Error")
                                for s in rows:
                                    err = (s.error or "")[:60]
                                    if s.error and len(s.error) > 60:
                                        err += "…"
                                    t.add_row(
                                        str(s.id),
                                        s.name,
                                        s.state.value,
                                        err or "—",
                                    )
                                console.print(t)
                        elif sub == "pause" and len(parts) > 2:
                            try:
                                console.print(
                                    task_registry.pause_task(int(parts[2]))
                                )
                            except ValueError:
                                console.print("[red]Invalid ID. Usage: /task pause <numeric id>[/red]")
                        elif sub == "resume" and len(parts) > 2:
                            try:
                                console.print(
                                    task_registry.resume_task(int(parts[2]))
                                )
                            except ValueError:
                                console.print("[red]Invalid ID. Usage: /task resume <numeric id>[/red]")
                        elif sub == "cancel" and len(parts) > 2:
                            try:
                                console.print(
                                    await task_registry.cancel_task(int(parts[2]))
                                )
                            except ValueError:
                                console.print("[red]Invalid ID. Usage: /task cancel <numeric id>[/red]")
                        elif sub == "insight" and len(parts) > 2:
                            try:
                                tid = int(parts[2])
                            except ValueError:
                                console.print("[red]Invalid ID. Usage: /task insight <numeric id>[/red]")
                                continue
                            note = " ".join(parts[3:]) if len(parts) > 3 else ""
                            sess = task_registry.get(tid)
                            if not sess:
                                console.print(f"[red]Task {tid} does not exist.[/red]")
                            else:
                                r = await sess.agent.consult_peer(
                                    advisor_llm, user_note=note
                                )
                                console.print(
                                    Panel(Markdown(r), title=f"Insight task {tid}", border_style="magenta")
                                )
                        elif sub == "spawn":
                            console.print(
                                "[yellow]/task spawn is an advanced legacy surface. "
                                "Prefer /multi_agent for primary orchestrated runs.[/yellow]"
                            )
                            try:
                                opts = _parse_agent_cli_flags(
                                    parts, 2, Config.DEFAULT_MODEL, available_mcps
                                )
                                opts = _maybe_collect_essential_runtime_setup(
                                    parts, opts, setup_state=essential_setup_state
                                )
                                ak = opts["agent_key"]
                                if ak not in AGENTS:
                                    console.print(f"[red]Agent '{ak}' is invalid.[/red]")
                                else:
                                    from core.agent import Agent

                                    definition = AGENTS[ak]
                                    ta = opts["agent_name"]
                                    ag = Agent(
                                        ta,
                                        opts["model"],
                                        definition["system_prompt"],
                                        mcp_clients=opts["selected_mcps"],
                                        output_analyzer=None,
                                        auto_approve=opts["auto_approve"],
                                        limit=opts["limit"],
                                        use_browser=opts["use_browser"],
                                        headless=opts["headless"],
                                        browser_intelligence=opts[
                                            "browser_intelligence"
                                        ],
                                        project_dir=manager.shared_project_dir,
                                        auth_manager=auth_manager,
                                        allow_installs=opts["allow_installs"],
                                        allow_deletes=opts["allow_deletes"],
                                        runtime_os=opts["runtime_os"],
                                        runtime_distro=opts["runtime_distro"],
                                    )
                                    task_txt = await session.prompt_async(
                                        f"Objective (task {ta})> "
                                    )
                                    s = await task_registry.spawn(
                                        ta, ag, task_txt.strip()
                                    )
                                    console.print(
                                        f"[green]Task {s.id} started in background (agent '{ta}').[/green]"
                                    )
                            except (IndexError, ValueError) as e:
                                console.print(
                                    f"[red]/task spawn <agent_key> --model … error: {e}[/red]"
                                )
                        else:
                            console.print("[red]Invalid /task subcommand.[/red]")

                elif command == "/single_agent":
                    try:
                        if len(parts) < 2:
                            console.print(
                                "[red]Usage: /single_agent <key> --model <m> …[/red]"
                            )
                            continue
                        opts = _parse_agent_cli_flags(
                            parts, 1, Config.DEFAULT_MODEL, available_mcps
                        )
                        opts = _maybe_collect_essential_runtime_setup(
                            parts, opts, setup_state=essential_setup_state
                        )
                        agent_key = opts["agent_key"]
                        if agent_key not in AGENTS:
                            console.print(f"[red]Agent '{agent_key}' does not exist.[/red]")
                            continue
                        definition = AGENTS[agent_key]
                        console.print(f"[green]Single agent: {agent_key}[/green]")
                        from core.agent import Agent

                        single_agent = Agent(
                            agent_key,
                            opts["model"],
                            definition["system_prompt"],
                            mcp_clients=opts["selected_mcps"],
                            output_analyzer=None,
                            auto_approve=opts["auto_approve"],
                            limit=opts["limit"],
                            use_browser=opts["use_browser"],
                            headless=opts["headless"],
                            browser_intelligence=opts["browser_intelligence"],
                            auth_manager=auth_manager,
                            allow_installs=opts["allow_installs"],
                            allow_deletes=opts["allow_deletes"],
                            runtime_os=opts["runtime_os"],
                            runtime_distro=opts["runtime_distro"],
                        )
                        console.print(
                            "[dim]While running: type [bold]:your instruction[/bold] + Enter to queue a reorientation "
                            "(applied at the next safe checkpoint). Use [bold]/back[/bold] or [bold]quit[/bold] to exit.[/dim]"
                        )
                        task_input = await session.prompt_async(
                            f"{agent_key}> objective: "
                        )
                        agent_task = asyncio.create_task(single_agent.process_message(task_input))
                        await _await_agent_task_with_live_context(
                            agent_task,
                            single_agent,
                            title=f"Single agent ({agent_key})",
                            selected_model=selected_model,
                            advisor_model=advisor_model,
                        )

                        if single_agent.active:
                            console.print(
                                "\n[dim]Single-agent session is still active. Keep sending prompts to this agent. "
                                "Use `/back`, `exit`, or `quit` to end this session.[/dim]\n"
                            )

                        while single_agent.active:
                            follow_up = await session.prompt_async(f"{agent_key}> ")
                            follow_up = follow_up.strip()
                            if not follow_up:
                                continue
                            if follow_up.lower() in ("/back", "exit", "quit"):
                                break
                            agent_task = asyncio.create_task(single_agent.process_message(follow_up))
                            await _await_agent_task_with_live_context(
                                agent_task,
                                single_agent,
                                title=f"Single agent ({agent_key})",
                                selected_model=selected_model,
                                advisor_model=advisor_model,
                            )

                        await single_agent.stop()
                    except Exception as e:
                        console.print(f"[red]Error single_agent: {e}[/red]")

                elif command == "/multi_agent":
                    if len(parts) < 2:
                        await _run_orchestrated_multi(parts)
                    elif len(parts) > 1:
                        subcmd = parts[1]
                        if subcmd == "resume":
                            session_dir = parts[2] if len(parts) > 2 else ""
                            await _resume_orchestrated_session(session_dir=session_dir)
                        elif subcmd == "list":
                            console.print(
                                "[yellow]/multi_agent list is a legacy parallel-agent command.[/yellow]"
                            )
                            print_active_agents(manager.list_agents())
                        elif subcmd == "add":
                            console.print(
                                "[yellow]/multi_agent add is a legacy parallel-agent command. "
                                "Prefer /multi_agent <target> for orchestrated flow.[/yellow]"
                            )
                            try:
                                opts = _parse_agent_cli_flags(
                                    parts, 2, Config.DEFAULT_MODEL, available_mcps
                                )
                                opts = _maybe_collect_essential_runtime_setup(
                                    parts, opts, setup_state=essential_setup_state
                                )
                                agent_key = opts["agent_key"]
                                if agent_key not in AGENTS:
                                    console.print(
                                        f"[red]Agent '{agent_key}' does not exist.[/red]"
                                    )
                                else:
                                    definition = AGENTS[agent_key]
                                    msg = manager.add_agent(
                                        opts["agent_name"],
                                        opts["model"],
                                        definition["system_prompt"],
                                        mcp_clients=opts["selected_mcps"],
                                        output_analyzer=None,
                                        auto_approve=opts["auto_approve"],
                                        limit=opts["limit"],
                                        use_browser=opts["use_browser"],
                                        headless=opts["headless"],
                                        browser_intelligence=opts[
                                            "browser_intelligence"
                                        ],
                                        auth_manager=auth_manager,
                                        allow_installs=opts["allow_installs"],
                                        allow_deletes=opts["allow_deletes"],
                                        runtime_os=opts["runtime_os"],
                                        runtime_distro=opts["runtime_distro"],
                                    )
                                    console.print(f"[green]{msg}[/green]")
                            except IndexError:
                                console.print(
                                    "[red]Usage: /multi_agent add <key> --model <m> …[/red]"
                                )
                        elif subcmd == "remove":
                            if len(parts) > 2:
                                console.print(
                                    "[yellow]/multi_agent remove is a legacy parallel-agent command.[/yellow]"
                                )
                                console.print(manager.remove_agent(parts[2]))
                            else:
                                console.print(
                                    "[red]Usage: /multi_agent remove <name>[/red]"
                                )
                        else:
                            # Legacy explicit one-shot still works only when the first token is a known agent key.
                            resolved_key = _resolve_agent_key(parts[1])
                            if resolved_key:
                                console.print(
                                    "[yellow]/multi_agent <agent_key> <objective> is a legacy one-shot path. "
                                    "Prefer orchestrated targets with /multi_agent <target>.[/yellow]"
                                )
                                objective = " ".join(parts[2:]).strip() if len(parts) > 2 else ""
                                if not objective:
                                    objective = await session.prompt_async(
                                        f"Objective ({resolved_key})> "
                                    )
                                    objective = objective.strip()
                                if not objective:
                                    console.print("[yellow]No objective provided.[/yellow]")
                                    continue
                                try:
                                    pseudo_parts = ["/multi_agent", "add", resolved_key]
                                    opts = _parse_agent_cli_flags(
                                        pseudo_parts, 2, Config.DEFAULT_MODEL, available_mcps
                                    )
                                    opts["limit"] = 1
                                    opts = _maybe_collect_essential_runtime_setup(
                                        pseudo_parts, opts, setup_state=essential_setup_state
                                    )
                                    definition = AGENTS[resolved_key]
                                    from core.agent import Agent

                                    quick_name = opts.get("agent_name") or f"{resolved_key}_quick"
                                    quick_agent = Agent(
                                        quick_name,
                                        opts["model"],
                                        definition["system_prompt"],
                                        mcp_clients=opts["selected_mcps"],
                                        output_analyzer=None,
                                        auto_approve=opts["auto_approve"],
                                        limit=opts["limit"],
                                        use_browser=opts["use_browser"],
                                        headless=opts["headless"],
                                        browser_intelligence=opts["browser_intelligence"],
                                        project_dir=manager.shared_project_dir,
                                        auth_manager=auth_manager,
                                        allow_installs=opts["allow_installs"],
                                        allow_deletes=opts["allow_deletes"],
                                        runtime_os=opts["runtime_os"],
                                        runtime_distro=opts["runtime_distro"],
                                    )
                                    quick_session = await task_registry.spawn(
                                        quick_name,
                                        quick_agent,
                                        objective,
                                    )
                                    console.print(
                                        f"[cyan]Quick task registered:[/cyan] id={quick_session.id} "
                                        f"name={quick_name} state={quick_session.state.value}"
                                    )
                                    await _await_session_with_live_context(
                                        task_session=quick_session,
                                        agent=quick_agent,
                                        title=f"Quick multi_agent ({resolved_key})",
                                        selected_model=selected_model,
                                        advisor_model=advisor_model,
                                    )
                                    await quick_agent.stop()
                                except Exception as e:
                                    console.print(f"[red]Quick /multi_agent failed: {e}[/red]")
                            else:
                                await _run_orchestrated_multi(parts)

                elif command == "/multi_agents":
                    console.print(
                        "[yellow]/multi_agents is deprecated; use /multi_agent instead. Running the same orchestrated flow.[/yellow]"
                    )
                    await _run_orchestrated_multi(parts)

            else:
                if not manager.agents:
                    console.print(
                        "[yellow]No active interactive agents. Start the primary flow with /multi_agent, "
                        "or open one specialist with /single_agent.[/yellow]"
                    )
                    console.print()
                else:
                    console.print(
                        "[cyan]Broadcasting to active agents... (Ctrl+C interrupts and requests a summary)[/cyan]"
                    )
                    try:
                        await manager.broadcast(user_input)
                    except asyncio.CancelledError:
                        pass

        except KeyboardInterrupt:
            console.print(
                "\n[yellow]Interrupted. Generating summaries for interactive agents...[/yellow]"
            )
            stop_tasks = [agent.stop() for agent in manager.agents.values()]
            if stop_tasks:
                await asyncio.gather(*stop_tasks, return_exceptions=True)
            continue

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

    for client in available_mcps.values():
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
