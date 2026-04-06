"""
Startup autotest suite: credentials, smoke LLM, A2P between two backends,
minimal multi-agent recon on testphp.vulnweb.com.
"""

from __future__ import annotations

import asyncio
from typing import List, Optional, Tuple

from rich.panel import Panel

from agents.definitions import AGENTS
from config import Config
from core.agent import Agent
from core.guardrails import Guardrails
from core.auth import AuthManager, AuthMethod
from core.llm import LLM
from core.manager import AgentManager
from core.mcp import MCPClient
from utils.ui import console, ThinkingStatus, model_display_label


async def _thread_input(message: str) -> str:
    return await asyncio.to_thread(input, message)


class _LightOutputAnalyzer:
    """Avoids extra LLM calls from OutputAnalyzer during autotest."""

    async def analyze(self, command, output, context_summary=""):
        o = (output or "").strip()
        if len(o) > 1500:
            o = o[:750] + "\n…\n" + o[-400:]
        return {"relevant": bool(o), "summary": o or "(no output)", "new_tasks": []}


async def _claude_cli_session_ready(bridge) -> bool:
    if not bridge.is_available():
        return False
    st = await bridge.claude_auth_status_ok()
    if st is True:
        return True
    return await bridge.claude_session_works_probe()


async def _codex_exec_ready(bridge) -> bool:
    """Autotest requires `codex exec` to work — `login status` alone is not enough."""
    if not bridge.is_available():
        return False
    return await bridge.codex_session_works_probe()


async def ensure_cli_sessions_for_autotest(
    auth_manager: AuthManager, *, max_rounds: int = 8
) -> None:
    """
    Ensure Claude and Codex are usable before autotest.
    If `codex exec` fails, show a recovery panel and offer `codex login`.
    """
    cb = auth_manager.claude_bridge
    db = auth_manager.codex_bridge
    if not cb.is_available() or not db.is_available():
        raise RuntimeError(
            "A2P autotest requires both binaries in PATH: `claude` (Claude Code) and `codex` (OpenAI Codex CLI)."
        )

    for attempt in range(max_rounds):
        cl_ok = await _claude_cli_session_ready(cb)
        cx_ok = await _codex_exec_ready(db)
        if cl_ok and cx_ok:
            return

        if not cl_ok:
            console.print(
                Panel(
                    "[bold]Claude Code session[/bold]\n\n"
                    "The autotest requires `claude --print` to respond (account / subscription).\n\n"
                    "[cyan]·[/cyan] [bold]y[/bold] = run [bold]claude auth login[/bold] in this terminal.\n"
                    "[cyan]·[/cyan] [bold]n[/bold] or Enter = not now (will ask again).\n",
                    title="Autotest — Claude CLI",
                    border_style="magenta",
                )
            )
            r = await _thread_input(
                "\n>>> Run `claude auth login` now? [y/N]: "
            )
            if r.strip().lower() in ("y", "yes"):
                console.print(
                    "[dim]Opening `claude auth login`... once you finish, we will re-verify.[/dim]"
                )
                await cb.run_official_interactive_login()
            continue

        if not cx_ok:
            st = await db.codex_login_status_ok()
            console.print(
                Panel(
                    "[bold]OpenAI Codex CLI session[/bold]\n\n"
                    "The autotest uses [bold]codex exec[/bold] (Codex / ChatGPT plan). "
                    "[yellow]`codex login status` may say OK with a token that is already invalid for exec.[/yellow]\n\n"
                    "Renew with [bold]codex login[/bold] in this terminal (browser or device code), "
                    "as you would manually.\n\n"
                    f"[dim]Reported state: login_status={st} · exec=real test[/dim]\n",
                    title="Autotest — Codex CLI",
                    border_style="cyan",
                )
            )
            r = await _thread_input(
                "\n>>> Run `codex login` now? [Y/n]: "
            )
            if r.strip().lower() not in ("n", "no"):
                console.print(
                    "[dim]Opening `codex login`... once you finish, we will re-verify.[/dim]"
                )
                await db.run_official_interactive_login()
            continue

    raise RuntimeError(
        "Autotest cancelled: could not validate Claude Code and Codex CLI "
        f"(after {max_rounds} attempts). Run `claude auth login` and `codex login` and choose autotest again."
    )


def pick_autotest_cli_order(auth_manager: AuthManager) -> Tuple[str, str, str]:
    """
    Executor/peer order for autotest (both already validated by ensure_cli_sessions_for_autotest).
    """
    c1 = Config.MODEL_CLAUDE_CODE_CLI
    c2 = Config.MODEL_CODEX_CLI
    if auth_manager.active_method == AuthMethod.CODEX_SUB:
        return (
            c2,
            c1,
            "Executor=Codex CLI (login session) · Peer=Claude Code CLI (login session)",
        )
    return (
        c1,
        c2,
        "Executor=Claude Code CLI (login session) · Peer=Codex CLI (login session)",
    )


async def _smoke_llm(label: str, llm: LLM) -> Tuple[bool, str]:
    try:
        with ThinkingStatus(f"Autotest: quick test for model `{label}`…"):
            r = await asyncio.wait_for(
                llm.generate(
                    [
                        {
                            "role": "user",
                            "content": (
                                "PentestLLM autotest ping. Reply in **one single line** containing "
                                "exactly the token AUTOTEST_OK (without a markdown code block)."
                            ),
                        }
                    ]
                ),
                timeout=90.0,
            )
        ok = r and "AUTOTEST_OK" in r and not str(r).strip().lower().startswith("error")
        return ok, (r or "")[:500]
    except Exception as e:
        return False, str(e)


async def run_full_autotest(
    auth_manager: AuthManager,
    mcp_clients: Optional[List[MCPClient]] = None,
) -> Tuple[str, str, str]:
    """
    Runs the full suite. Returns (executor_model, advisor_model, pair_description).
    The pair is always CLI+CLI (login), never API keys.
    """
    mcp_clients = mcp_clients or []
    await ensure_cli_sessions_for_autotest(auth_manager)
    ex_m, adv_m, pair_desc = pick_autotest_cli_order(auth_manager)

    ex_lbl = model_display_label(ex_m)
    adv_lbl = model_display_label(adv_m)
    console.print(
        Panel.fit(
            f"[bold cyan]PentestLLM - Autotest (diagnostics)[/bold cyan]\n\n"
            f"[bold]Pair in use[/bold]: [green]{pair_desc}[/green]\n"
            f"· [bold]Executor[/bold] (generates commands in this phase): [yellow]{ex_lbl}[/yellow] (`{ex_m}`)\n"
            f"· [bold]Peer / A2P[/bold] (advice only, second model): [magenta]{adv_lbl}[/magenta] (`{adv_m}`)\n\n"
            f"[dim]Steps: (1) CLI status → (2) ping executor → (3) ping peer → "
            f"(4) A2P (executor requests text from peer) → (5) two recon agents in parallel on lab target → "
            f"(6) summary of what each produced. All chained; each panel shows the backend in the title.[/dim]",
            border_style="cyan",
        )
    )

    # 1) Credentials / CLI
    console.print("\n[bold]1) Credentials and binaries[/bold]")
    st = await auth_manager.refresh_cli_status()
    console.print(
        f"  claude bin={st['claude_bin']} probe={st['claude_ok']} session={st['claude_logged_in']}"
    )
    codex_model = (Config.CODEX_MODEL or "(default config.toml)").strip() or "(default config.toml)"
    console.print(
        f"  codex bin={st['codex_bin']} login_status={st['codex_logged_in']} "
        f"model_flag={codex_model}"
    )
    console.print(
        f"  startup auth method: [yellow]{auth_manager.active_method}[/yellow]  "
        f"authenticated={auth_manager.is_authenticated()}"
    )

    # 2) Smoke LLM executor
    console.print(f"\n[bold]2) Ping executor[/bold] [dim]({ex_lbl})[/dim]")
    llm_ex = LLM(ex_m, auth_manager=auth_manager)
    ok_ex, msg_ex = await _smoke_llm(ex_m, llm_ex)
    if ok_ex:
        console.print(f"  [green]✓[/green] executor responded: {msg_ex[:120]}…")
    else:
        console.print(f"  [red]✗[/red] executor failed: {msg_ex}")
        raise RuntimeError(
            "Autotest aborted: the executor (CLI) did not respond to the smoke test. "
            "Re-validate `claude auth login` or `codex login` according to the executor model."
        )

    # 3) Smoke of the second CLI (always different from the executor in this autotest)
    console.print(f"\n[bold]3) Ping peer (second CLI)[/bold] [dim]({adv_lbl})[/dim]")
    llm_adv = LLM(adv_m, auth_manager=auth_manager)
    ok_ad, msg_ad = await _smoke_llm(adv_m, llm_adv)
    if ok_ad:
        console.print(f"  [green]✓[/green] peer responded: {msg_ad[:120]}…")
    else:
        console.print(f"  [red]✗[/red] peer failed: {msg_ad}")
        if adv_m == Config.MODEL_CODEX_CLI:
            console.print(
                Panel(
                    "[bold]Peer smoke test Codex failed[/bold]\n\n"
                    "Do you want to run [bold]codex login[/bold] again and retry the peer smoke test?\n"
                    "[cyan]·[/cyan] Enter or [bold]y[/bold] = yes · [bold]n[/bold] = abort autotest\n",
                    border_style="yellow",
                )
            )
            r = await _thread_input("\n>>> Run `codex login` and retry peer smoke test? [Y/n]: ")
            if r.strip().lower() not in ("n", "no"):
                await auth_manager.codex_bridge.run_official_interactive_login()
                ok_ad, msg_ad = await _smoke_llm(adv_m, LLM(adv_m, auth_manager=auth_manager))
                if ok_ad:
                    console.print(f"  [green]✓[/green] peer responded after login: {msg_ad[:120]}…")
                else:
                    console.print(f"  [red]✗[/red] peer still failed: {msg_ad}")
                    raise RuntimeError(
                        "Autotest aborted: Codex CLI (peer) did not respond after `codex login`. "
                        "Check `PENTESTLLM_CODEX_MODEL` and the Codex account."
                    )
            else:
                raise RuntimeError(
                    "Autotest aborted: peer smoke test failed. Run `codex login` and try again."
                )
        elif adv_m == Config.MODEL_CLAUDE_CODE_CLI:
            console.print(
                Panel(
                    "[bold]Peer smoke test Claude failed[/bold]\n\n"
                    "Do you want to run [bold]claude auth login[/bold] and retry the peer smoke test?\n"
                    "[cyan]·[/cyan] Enter or [bold]y[/bold] = yes · [bold]n[/bold] = abort\n",
                    border_style="yellow",
                )
            )
            r = await _thread_input(
                "\n>>> Run `claude auth login` and retry peer smoke test? [Y/n]: "
            )
            if r.strip().lower() not in ("n", "no"):
                await auth_manager.claude_bridge.run_official_interactive_login()
                ok_ad, msg_ad = await _smoke_llm(adv_m, LLM(adv_m, auth_manager=auth_manager))
                if ok_ad:
                    console.print(f"  [green]✓[/green] peer responded after login: {msg_ad[:120]}…")
                else:
                    raise RuntimeError(
                        "Autotest aborted: Claude CLI (peer) did not respond after `claude auth login`."
                    )
            else:
                raise RuntimeError(
                    "Autotest aborted: peer smoke test failed. Run `claude auth login` and try again."
                )
        else:
            raise RuntimeError(
                "Autotest aborted: peer smoke test failed (unexpected model)."
            )

    # 4) A2P
    console.print(
        f"\n[bold]4) A2P[/bold] - executor [yellow]{ex_lbl}[/yellow] requests insight from "
        f"[magenta]{adv_lbl}[/magenta] (the peer knows it is advising the executor, and the executor sees that envelope in history). "
        f"The peer **does not execute** commands in this channel."
    )
    mini_sys = (
        "You are the minimal **executor** for PentestLLM autotest. Use short replies in English.\n"
        "In the A2P step you will request insight from the **peer** (second model); that peer **does not execute** commands — text only.\n"
        "You are aware that the insight comes from that peer and that it knows it is advising you (the executor)."
    )
    peer_agent = Agent(
        "_autotest_a2p",
        ex_m,
        mini_sys,
        mcp_clients,
        output_analyzer=_LightOutputAnalyzer(),
        auto_approve=True,
        limit=1,
        auth_manager=auth_manager,
    )
    peer_agent.history.append(
        {
            "role": "user",
            "content": (
                f"[AUTOTEST - executor {ex_lbl}] Fictional context: passive check of "
                "http://testphp.vulnweb.com/ (lab). Assume a `curl -sI` would have returned HTTP 200. "
                "Goal: confirm it is a PHP test app."
            ),
        }
    )
    peer_agent.history.append(
        {
            "role": "assistant",
            "content": (
                "Understood. The next step would be to inspect `Server` / `X-Powered-By` headers or the HTML title."
            ),
        }
    )
    try:
        insight = await asyncio.wait_for(
            peer_agent.consult_peer(
                LLM(adv_m, auth_manager=auth_manager),
                user_note=(
                    f"A2P autotest: you are responding to executor **{ex_lbl}**. "
                    "List **2** passive recon priorities in **short bullets**. "
                    "Do not assume any commands have already been executed."
                ),
            ),
            timeout=120.0,
        )
        console.print(
            Panel(
                insight[:4000],
                title=f"A2P insight · generated by {adv_lbl}",
                border_style="magenta",
            )
        )
        console.print(f"  [green]✓[/green] A2P completed (text above = model [bold]{adv_lbl}[/bold])")
    except Exception as e:
        console.print(f"  [red]✗[/red] A2P failed: {e}")
        raise RuntimeError(f"Autotest: A2P failed: {e}") from e
    finally:
        peer_agent.active = False

    # 5) Multi-agent mini recon
    console.print(
        "\n[bold]5) Parallel recon[/bold] - [cyan]autotest_recon_alpha[/cyan] uses "
        f"[yellow]{ex_lbl}[/yellow]; [cyan]autotest_recon_beta[/cyan] uses [magenta]{adv_lbl}[/magenta]. "
        "Each response panel shows the model in the title."
    )
    recon_cfg = AGENTS.get("recon_agent")
    if not recon_cfg:
        raise RuntimeError("Autotest: missing agents/configs/recon_agent.json")

    mgr = AgentManager()
    mgr.add_agent(
        "autotest_recon_alpha",
        ex_m,
        recon_cfg["system_prompt"],
        mcp_clients,
        output_analyzer=_LightOutputAnalyzer(),
        auto_approve=True,
        limit=6,
        auth_manager=auth_manager,
    )
    mgr.add_agent(
        "autotest_recon_beta",
        adv_m,
        recon_cfg["system_prompt"],
        mcp_clients,
        output_analyzer=_LightOutputAnalyzer(),
        auto_approve=True,
        limit=6,
        auth_manager=auth_manager,
    )

    broadcast_msg = f"""\
[AUTOTEST - single passive recon]
Authorized lab target: **http://testphp.vulnweb.com/** - this host only; no active exploitation.

**Preferred order (important):**
1) **First** try **host bash**: `curl -sI --connect-timeout 10 'http://testphp.vulnweb.com/'` and/or `getent hosts testphp.vulnweb.com` (or `dig +short`). The Python process resolver can differ from the system resolver.
2) Only then, if needed, use a short ```python``` block with timeouts for HEAD/GET plus a concise header summary.
3) Use at most **2-3** useful commands total (for example curl, dig/host, whatweb) - lightweight recon.

Finish with **bullets** covering stack, cookies, redirects, and technologies. No aggressive wordlists.
In the final conclusion, include **no** new shell blocks.

Note: in this parallel recon **both** agents may execute commands; the peer "advice only" behavior applies only to the A2P step above, not to this phase.
"""
    for name, agent in mgr.agents.items():
        ok, reason = Guardrails.check_input(broadcast_msg)
        if not ok:
            console.print(
                f"  [yellow]Guardrails: broadcast message blocked for {name}: {reason}[/yellow]"
            )
            continue
        agent.history.append({"role": "user", "content": broadcast_msg})

    results = await asyncio.gather(
        *[
            _safe_autonomous_loop(name, ag)
            for name, ag in mgr.agents.items()
        ],
        return_exceptions=True,
    )
    for name, res in zip(mgr.agents.keys(), results):
        if isinstance(res, Exception):
            console.print(f"  [red]✗[/red] {name}: {res}")
        else:
            console.print(f"  [green]✓[/green] {name}: loop finished")

    # Final snapshot of the most recent assistant turns.
    console.print(
        "\n[bold]6) Latest replies from both recon agents[/bold] "
        "[dim](to compare what each model produced)[/dim]"
    )
    for name, ag in mgr.agents.items():
        tail = ""
        for msg in ag.history[-4:]:
            if msg.get("role") == "assistant":
                tail += (msg.get("content") or "")[:800] + "\n---\n"
        if tail.strip():
            ml = model_display_label(ag.model)
            console.print(
                Panel(
                    tail[:3500],
                    title=f"Latest reply · {name} · {ml}",
                    border_style="dim",
                )
            )

    for ag in mgr.agents.values():
        ag.active = False

    console.print(
        Panel(
            "[green]Autotest complete.[/green] The interactive console continues with the same models selected above.",
            border_style="green",
        )
    )
    return ex_m, adv_m, pair_desc


async def _safe_autonomous_loop(name: str, agent: Agent):
    try:
        await agent.autonomous_loop()
    except Exception as e:
        raise RuntimeError(f"{name}: {e}") from e
