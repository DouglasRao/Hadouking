"""
Claude Code / Codex authentication: delegates to the official binary flows (`codex login`, `claude auth login`)
on the same TTY when possible; re-checks with `codex login status` / `claude auth status`.
"""

import asyncio
from typing import TYPE_CHECKING

from rich.panel import Panel

from core.auth import AuthMethod

if TYPE_CHECKING:
    from core.auth import AuthManager

from utils.ui import console


async def _thread_input(message: str) -> str:
    return await asyncio.to_thread(input, message)


async def complete_cli_authentication(auth_manager: "AuthManager", method: AuthMethod) -> bool:
    """
    API keys: single verification.
    Codex: option to run `codex login` here (inherited TTY) + `codex login status`.
    Claude: option to run `claude auth login` here + `claude auth status` (with fallback for older CLI).
    """
    if method == AuthMethod.API_KEY:
        return await auth_manager.authenticate(method)

    if method == AuthMethod.CODEX_SUB:
        if not auth_manager.codex_bridge.is_available():
            console.print(
                Panel(
                    "[bold red]The `codex` command is not in PATH.[/bold red]\n\n"
                    "Install the [cyan]OpenAI Codex CLI[/cyan] (official OpenAI documentation) and ensure "
                    "`which codex` works for this user.\n\n"
                    "Or [bold]you don't need Codex[/bold]: go back to start and choose [bold]option 1[/bold] (API keys).\n\n"
                    "Then run Hadouking again.",
                    title="Codex CLI not found",
                    border_style="red",
                )
            )
            return False

        ok = await auth_manager.authenticate(method)
        if ok:
            console.print(
                "[green]Codex: session detected (`codex login status`).[/green]"
            )
            return True

        console.print(
            Panel(
                "[bold]Codex login (official)[/bold]\n\n"
                "Hadouking can launch the same command you would run manually: [bold]codex login[/bold] "
                "(browser or device code, stdin/stdout of this terminal).\n\n"
                "[cyan]·[/cyan] [bold]y[/bold] = run [bold]codex login[/bold] now here (new browser/device code).\n"
                "[cyan]·[/cyan] [bold]Enter[/bold] or [bold]n[/bold] = no — the session is already stored in [dim]~/.codex/[/dim]; "
                "only choose this if you have not logged in on this machine yet.\n",
                title="Codex authentication",
                border_style="cyan",
            )
        )
        run_now = await _thread_input(
            "\n>>> Run `codex login` in this terminal now? [y/N]: "
        )
        if run_now.strip().lower() in ("y", "yes"):
            console.print("[dim]Opening `codex login` flow (when done, return to the menu below)…[/dim]")
            code = await auth_manager.codex_bridge.run_official_interactive_login()
            console.print(f"[dim]Process exited with code {code}.[/dim]")

        for attempt in range(20):
            ok = await auth_manager.authenticate(AuthMethod.CODEX_SUB)
            if ok:
                console.print("[green]Codex: session OK. Continuing…[/green]")
                return True
            reply = await _thread_input(
                "\n>>> Enter = check again · type quit + Enter = cancel: "
            )
            if reply.strip().lower() in ("exit", "quit", "q"):
                console.print(
                    "[yellow]Cancelled. Choose API keys or run codex login and restart Hadouking.[/yellow]"
                )
                return False
            console.print(
                f"[red]Still no valid session (attempt {attempt + 1}). "
                "Run `codex login` (you can retry after a restart) and confirm with Enter.[/red]"
            )

        return False

    if method == AuthMethod.CLAUDE_CODE_SUB:
        if not auth_manager.claude_bridge.is_available():
            console.print(
                Panel(
                    "[bold red]The `claude` command is not in PATH.[/bold red]\n\n"
                    "Install [cyan]Claude Code[/cyan] (official script or package manager) — see "
                    "https://code.claude.com/docs/en/setup\n\n"
                    "Or [bold]you don't need Claude Code[/bold]: go back to start and choose [bold]option 1[/bold] (API keys).\n\n"
                    "Then run Hadouking again.",
                    title="Claude Code not found",
                    border_style="red",
                )
            )
            return False

        if not await auth_manager.claude_bridge.claude_version_probe_ok():
            console.print(
                "[red]The claude binary did not respond to the probe (--version / -h). Reinstall it or check your PATH.[/red]"
            )
            return False

        ok = await auth_manager.authenticate(method)
        if ok:
            console.print(
                "[green]Claude: session confirmed (`claude auth status`).[/green]"
            )
            return True

        sess = await auth_manager.claude_bridge.claude_auth_status_ok()
        if sess is False:
            console.print(
                Panel(
                    "[bold]Claude Code login (official)[/bold]\n\n"
                    "Account / subscription: the flow supported by the CLI is [bold]claude auth login[/bold] "
                    "(same TTY as this one, as in the normal terminal).\n\n"
                    "After login, Hadouking uses [bold]claude --print -p[/bold] with the same session.\n",
                    title="Claude Code — session missing",
                    border_style="magenta",
                )
            )
        else:
            console.print(
                Panel(
                    "[bold]Claude Code[/bold]\n\n"
                    "This binary did not return [bold]claude auth status[/bold] reliably (older CLI?).\n"
                    "If you don't have a session yet, try [bold]claude auth login[/bold]. "
                    "When done, press Enter below to confirm you want to continue.\n",
                    title="Claude Code",
                    border_style="magenta",
                )
            )

        run_now = await _thread_input(
            "\n>>> Run `claude auth login` in this terminal now? [y/N]: "
        )
        if run_now.strip().lower() in ("y", "yes"):
            console.print(
                "[dim]Opening `claude auth login` flow (when done, return to the menu below)…[/dim]"
            )
            code = await auth_manager.claude_bridge.run_official_interactive_login()
            console.print(f"[dim]Process exited with code {code}.[/dim]")

        for attempt in range(20):
            if await auth_manager.authenticate(AuthMethod.CLAUDE_CODE_SUB):
                console.print("[green]Claude: session OK. Continuing…[/green]")
                return True
            if await auth_manager.claude_bridge.claude_auth_status_ok() is None:
                ack = await _thread_input(
                    "\n>>> Enter = continue (CLI without reliable auth status) · type quit + Enter = cancel: "
                )
                if ack.strip().lower() in ("exit", "quit", "q"):
                    console.print("[yellow]Cancelled.[/yellow]")
                    return False
                if await auth_manager.authenticate(
                    AuthMethod.CLAUDE_CODE_SUB, cli_login_ack=True
                ):
                    console.print(
                        "[yellow]Continuing without `claude auth status` confirmation — if it fails, log in and restart.[/yellow]"
                    )
                    return True
                continue

            reply = await _thread_input(
                "\n>>> Enter = check again · type quit + Enter = cancel: "
            )
            if reply.strip().lower() in ("exit", "quit", "q"):
                console.print("[yellow]Cancelled.[/yellow]")
                return False
            console.print(
                f"[red]Still no session (attempt {attempt + 1}). "
                "Repeat `claude auth login` and confirm with Enter.[/red]"
            )

        return False

    return await auth_manager.authenticate(method)
