import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config
from core.manager import AgentManager
from core.auth import AuthManager, AuthMethod
from core.llm import LLM
from core.task_runner import BackgroundTaskRegistry
from agents.definitions import AGENTS
from utils.ui import (
    print_banner,
    print_agent_list,
    print_active_agents,
    console,
    show_model_menu,
    show_auth_method_menu,
    show_startup_mode_menu,
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
from rich.prompt import Prompt
from rich.panel import Panel
from utils.commands import SlashCommandCompleter, iter_help_lines, normalize_command_input


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

    return {
        "agent_key": agent_key,
        "model": model,
        "selected_mcps": selected_mcps,
        "auto_approve": auto_approve,
        "limit": limit,
        "agent_name": agent_name,
        "use_browser": use_browser,
        "headless": headless,
        "browser_intelligence": browser_intelligence,
    }


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

    startup_mode = show_startup_mode_menu()
    if startup_mode == "autotest":
        from utils.autotest import run_full_autotest

        mcp_list = list(available_mcps.values())
        try:
            ex_m, adv_m, _pair_desc = await run_full_autotest(auth_manager, mcp_list)
            selected_model = ex_m
            advisor_model = adv_m
            Config.DEFAULT_MODEL = selected_model
        except Exception as e:
            console.print(f"[bold red]Autotest failed:[/bold red] {e}")
            console.print(
                "[yellow]Continuing in normal mode; select models manually.[/yellow]"
            )
            selected_model = show_model_menu("Main model (executor)")
            Config.DEFAULT_MODEL = selected_model
            advisor_model = (
                Prompt.ask(
                    "A2P Peer (2nd model: insights only; empty = same as 1st)",
                    default="",
                ).strip()
                or selected_model
            )
    else:
        selected_model = show_model_menu("Main model (executor)")
        Config.DEFAULT_MODEL = selected_model

        advisor_model = (
            Prompt.ask(
                "A2P Peer (2nd model: insights only; empty = same as 1st)",
                default="",
            ).strip()
            or selected_model
        )

    advisor_llm = LLM(advisor_model, auth_manager=auth_manager)
    console.print(
        f"\n[dim]Pair:[/dim] executor [yellow]{model_display_label(selected_model)}[/yellow] "
        f"· A2P peer (insights) [magenta]{model_display_label(advisor_model)}[/magenta]\n"
    )

    manager = AgentManager()
    task_registry = BackgroundTaskRegistry()

    history_file = os.path.join(os.path.dirname(__file__), ".pentestllm_history")
    kb = KeyBindings()

    @kb.add("tab")
    def _(event):
        buffer = event.app.current_buffer
        suggestion = buffer.suggestion
        if suggestion:
            buffer.insert_text(suggestion.text)
        else:
            buffer.insert_text("    ")

    @kb.add("/")
    def _(event):
        buffer = event.app.current_buffer
        buffer.insert_text("/")
        if buffer.text.lstrip().startswith("/"):
            buffer.start_completion(select_first=False)

    command_completer = SlashCommandCompleter()

    session = PromptSession(
        history=FileHistory(history_file),
        auto_suggest=AutoSuggestFromHistory(),
        enable_history_search=True,
        key_bindings=kb,
        completer=command_completer,
        complete_while_typing=True,
        complete_style=CompleteStyle.MULTI_COLUMN,
        reserve_space_for_menu=8,
    )

    console.print(
        "\n[bold yellow]System ready.[/bold yellow] Use [bold]/help[/bold] for commands. "
        "Any plain prompt is broadcast to active agents.\n"
    )
    console.print(
        "[dim]Tip: type `/` for command suggestions, use ↑/↓ for history, TAB accepts the current suggestion, and /task spawn starts a background task.[/dim]\n"
    )

    while True:
        try:
            user_input = await session.prompt_async("PentestLLM> ")
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
                    console.print("\n[bold cyan]PentestLLM command reference[/bold cyan]\n")
                    console.print("[bold]Quick start[/bold]")
                    console.print("  1. Use /single_agent (or /sa) when you want one persistent interactive agent.")
                    console.print("  2. Use /multi_agent add (or /ma add) when you want multiple parallel agents.")
                    console.print("  3. Use /task spawn (or /t spawn) when you want a background run you can inspect later.")
                    console.print("  4. Type / to open command suggestions with ready-made examples, then edit them.")
                    console.print("  5. Inside a /single_agent session, keep chatting with the same agent until /back, exit, or quit.\n")
                    for section_title, entries in iter_help_lines():
                        console.print(f"[bold]{section_title}[/bold]")
                        for entry in entries:
                            console.print(f"  {entry.command} — {entry.description}")
                        console.print()
                    console.print(
                        "[dim]Common flags: --model, --limit, --name, --auto-approve, --browser, "
                        "--browser-cli, --browser-gui, --browser-intelligence, mcp all, mcp <name>[/dim]"
                    )
                    console.print(
                        "[dim]Short aliases: /h, /a, /sa, /ma, /t, /p, /m, /as[/dim]"
                    )
                    console.print(
                        "[dim]CLI login is only required for c1/c2. API-backed models do not need `claude` or `codex` installed.[/dim]"
                    )
                    if available_mcps:
                        console.print("\n[bold]Connected MCPs[/bold]")
                        for name in available_mcps:
                            console.print(f"  - {name}")
                        console.print()

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
                            console.print(Panel(r, title="Peer A2P", border_style="cyan"))
                    else:
                        console.print(
                            "[red]Usage: /peer consult <agent_name> [optional note][/red]"
                        )

                elif command == "/task":
                    if len(parts) < 2:
                        console.print(
                            "[red]Usage: /task spawn … | list | pause | resume | cancel | insight[/red]"
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
                                    Panel(r, title=f"Insight task {tid}", border_style="magenta")
                                )
                        elif sub == "spawn":
                            try:
                                opts = _parse_agent_cli_flags(
                                    parts, 2, Config.DEFAULT_MODEL, available_mcps
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
                        )
                        task_input = await session.prompt_async(
                            f"{agent_key}> objective: "
                        )
                        await single_agent.process_message(task_input)

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
                            await single_agent.process_message(follow_up)

                        summary = await single_agent.stop()
                        console.print(f"\n[bold cyan]Summary:[/bold cyan]\n{summary}")
                    except Exception as e:
                        console.print(f"[red]Error single_agent: {e}[/red]")

                elif command == "/multi_agent":
                    if len(parts) < 2:
                        console.print("[red]Usage: /multi_agent add|list|remove[/red]")
                    elif len(parts) > 1:
                        subcmd = parts[1]
                        if subcmd == "list":
                            print_active_agents(manager.list_agents())
                        elif subcmd == "add":
                            try:
                                opts = _parse_agent_cli_flags(
                                    parts, 2, Config.DEFAULT_MODEL, available_mcps
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
                                    )
                                    console.print(f"[green]{msg}[/green]")
                            except IndexError:
                                console.print(
                                    "[red]Usage: /multi_agent add <key> --model <m> …[/red]"
                                )
                        elif subcmd == "remove":
                            if len(parts) > 2:
                                console.print(manager.remove_agent(parts[2]))
                            else:
                                console.print(
                                    "[red]Usage: /multi_agent remove <name>[/red]"
                                )
                        else:
                            console.print("[red]Invalid multi_agent command.[/red]")

            else:
                if not manager.agents:
                    console.print(
                        "[yellow]No active agents. Use /multi_agent add or /single_agent.[/yellow]"
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
            tasks = [agent.stop() for agent in manager.agents.values()]
            if tasks:
                summaries = await asyncio.gather(*tasks)
                for agent_name, summary in zip(manager.agents.keys(), summaries):
                    console.print(f"\n[bold green]{agent_name}:[/bold green]")
                    console.print(summary)
            continue

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

    for client in available_mcps.values():
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
