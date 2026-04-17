from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

from prompt_toolkit.completion import Completer
from prompt_toolkit.completion import Completion


@dataclass(frozen=True)
class CommandEntry:
    command: str
    description: str


@dataclass(frozen=True)
class CommandSuggestion:
    text: str
    label: str
    help_text: str


COMMAND_ALIASES = {
    "/h": "/help",
    "/a": "/agent",
    "/sa": "/single_agent",
    "/ma": "/multi_agent",
    "/mas": "/multi_agents",
    "/mutli_agents": "/multi_agents",
    "/t": "/task",
    "/p": "/peer",
    "/m": "/mcp",
    "/as": "/auth status",
    "/mo": "/model",
}


COMMAND_SECTIONS: Sequence[Tuple[str, Sequence[CommandEntry]]] = (
    (
        "General",
        (
            CommandEntry("/help", "Show the full command reference."),
            CommandEntry("/h", "Alias for /help."),
            CommandEntry("/model [show|list|set|peer]", "Manage executor/peer models during runtime."),
            CommandEntry("/mo ...", "Alias for /model."),
            CommandEntry("/session [show|resume|reset]", "Inspect, resume, or clear persisted CLI session state."),
            CommandEntry("/autotest", "Run CLI autotest flow and update executor/peer models from result."),
            CommandEntry("/approvals", "Show current approval state (session tiers, commands, persistent)."),
            CommandEntry("exit", "Exit the application and disconnect MCP clients."),
            CommandEntry("quit", "Exit the application and disconnect MCP clients."),
        ),
    ),
    (
        "Agents",
        (
            CommandEntry("/agent list", "List all available agent profiles."),
            CommandEntry("/a list", "Alias for /agent list."),
            CommandEntry(
                "/single_agent <key> --model <model> [flags]",
                "Start a persistent interactive session with one agent.",
            ),
            CommandEntry(
                "/sa <key> --model <model> [flags]",
                "Alias for /single_agent.",
            ),
            CommandEntry(
                "/multi_agent <target> [objective]",
                "Run the orchestrated brain + all PTES/OWASP workers by default.",
            ),
            CommandEntry(
                "/multi_agent [temporary|native] <target> [objective]",
                "Run the orchestrated brain with explicit worker-profile mode selection.",
            ),
            CommandEntry(
                "/multi_agent workers <w1,w2,...> <target> [objective]",
                "Run the orchestrated brain with only the selected worker subset.",
            ),
            CommandEntry(
                "/multi_agent resume [session_dir]",
                "Resume the last persisted orchestrated run, or a specific session directory.",
            ),
            CommandEntry(
                "/multi_agents [temporary|native] <target> [objective]",
                "Deprecated alias for /multi_agent (kept for backward compatibility).",
            ),
            CommandEntry("/ma ...", "Alias for /multi_agent."),
            CommandEntry("/mas ...", "Deprecated alias for /multi_agents."),
        ),
    ),
    (
        "Tasks",
        (
            CommandEntry("/task list", "List background tasks."),
            CommandEntry("/task pause <id>", "Pause a background task."),
            CommandEntry("/task resume <id>", "Resume a paused task."),
            CommandEntry("/task cancel <id>", "Cancel a background task."),
            CommandEntry(
                "/task insight <id> [note]",
                "Send the task snapshot to the A2P peer for text-only insight.",
            ),
            CommandEntry("/t list|pause|resume|cancel|insight ...", "Alias for /task."),
        ),
    ),
    (
        "Peer",
        (
            CommandEntry(
                "/peer consult <agent_name> [note]",
                "Ask the A2P peer for advice using an agent's history.",
            ),
            CommandEntry("/p consult <agent_name> [note]", "Alias for /peer consult."),
        ),
    ),
    (
        "MCP",
        (
            CommandEntry("/mcp list", "List connected MCP servers and tool counts."),
            CommandEntry("/mcp reload", "Reload MCP servers from settings.json."),
            CommandEntry("/m list|reload", "Alias for /mcp."),
        ),
    ),
    (
        "Auth",
        (
            CommandEntry("/auth status", "Show CLI/authentication status."),
            CommandEntry("/as", "Alias for /auth status."),
        ),
    ),
    (
        "Legacy (compatibility)",
        (
            CommandEntry(
                "/multi_agent add <key> --model <model> [flags]",
                "[Legacy] Parallel persistent agent instance management.",
            ),
            CommandEntry("/multi_agent list", "[Legacy] List active parallel agents."),
            CommandEntry("/multi_agent remove <name>", "[Legacy] Remove an active parallel agent."),
            CommandEntry(
                "/multi_agent <key> <objective>",
                "[Legacy] Quick one-shot run for one explicit agent profile.",
            ),
            CommandEntry("/ma add|list|remove ...", "[Legacy] Alias for /multi_agent subcommands."),
            CommandEntry(
                "/task spawn <key> --model <model> [flags]",
                "[Legacy] Start a background task and prompt for objective.",
            ),
            CommandEntry("/t spawn ...", "[Legacy] Alias for /task spawn."),
        ),
    ),
)


COMMAND_SUGGESTIONS: Tuple[CommandSuggestion, ...] = (
    CommandSuggestion("/help", "/help", "Show the full command reference."),
    CommandSuggestion("/h", "/h", "Alias for /help."),
    CommandSuggestion("/model show", "/model show", "Show current executor and peer model."),
    CommandSuggestion("/model list", "/model list", "List available model IDs and names."),
    CommandSuggestion("/model set 4", "/model set <id|name>", "Set default executor model for new agents."),
    CommandSuggestion("/model peer same", "/model peer same", "Make A2P peer follow the executor model."),
    CommandSuggestion("/model peer c2", "/model peer <id|name>", "Set A2P peer model independently."),
    CommandSuggestion("/mo list", "/mo list", "Alias for /model list."),
    CommandSuggestion("/session show", "/session show", "Show persisted runtime state and last orchestrated session metadata."),
    CommandSuggestion("/session resume", "/session resume", "Resume the last persisted orchestrated session."),
    CommandSuggestion("/session reset", "/session reset", "Clear persisted runtime state."),
    CommandSuggestion("/autotest", "/autotest", "Run CLI autotest and adopt the resulting executor/peer models."),
    CommandSuggestion("/agent list", "/agent list", "List all available agent profiles."),
    CommandSuggestion("/a list", "/a list", "Alias for /agent list."),
    CommandSuggestion(
        "/single_agent recon_passive_agent --model gpt-4o --limit 10 --auto-approve",
        "Single agent: recon passive",
        "Persistent session with the passive recon specialist; the next prompt asks for the objective.",
    ),
    CommandSuggestion(
        "/single_agent exploit_validation_agent --model gpt-4o --limit 10 --auto-approve",
        "Single agent: exploit validation",
        "Persistent session with the impact-validation specialist.",
    ),
    CommandSuggestion(
        "/sa recon_active_agent --model gpt-4o --limit 10 --auto-approve",
        "Alias: /sa recon active",
        "Short alias for /single_agent with the active recon specialist.",
    ),
    CommandSuggestion(
        "/multi_agent testphp.vulnweb.com full PTES flow",
        "Orchestrated all workers",
        "Runs the brain with all default workers in parallel and opens the quiz flow.",
    ),
    CommandSuggestion(
        "/multi_agent workers recon_passive,recon_active,vuln_scanner testphp.vulnweb.com baseline mapping",
        "Orchestrated selected workers",
        "Runs the brain with only the selected worker subset.",
    ),
    CommandSuggestion(
        "/multi_agent native testphp.vulnweb.com full PTES flow",
        "Orchestrated native profiles",
        "Runs native stage profiles from agents/configs.",
    ),
    CommandSuggestion(
        "/multi_agent temporary testphp.vulnweb.com full PTES flow",
        "Orchestrated temporary profiles",
        "Builds temporary worker profiles for this run and cleans them after completion.",
    ),
    CommandSuggestion(
        "/multi_agent resume",
        "Resume orchestrated session",
        "Resumes the last persisted orchestrated team session from disk.",
    ),
    CommandSuggestion(
        "/multi_agents temporary testphp.vulnweb.com full PTES flow",
        "Deprecated alias: /multi_agents",
        "Deprecated alias for /multi_agent; executes the same orchestrated flow.",
    ),
    CommandSuggestion(
        "/multi_agents native testphp.vulnweb.com",
        "Deprecated alias: /multi_agents native",
        "Deprecated alias for /multi_agent native.",
    ),
    CommandSuggestion(
        "/mas testphp.vulnweb.com",
        "Deprecated alias: /mas",
        "Deprecated shortcut alias for /multi_agents.",
    ),
    CommandSuggestion(
        "/multi_agent add recon_passive_agent --model gpt-4o --name recon1 --limit 10 --auto-approve",
        "Legacy multi-agent add",
        "Legacy parallel persistent passive-recon specialist instance.",
    ),
    CommandSuggestion(
        "/multi_agent recon_active_agent baseline only with curl http://businesscorp.com.br/",
        "Legacy quick one-shot active recon",
        "Legacy immediate one-shot with one explicit specialist profile.",
    ),
    CommandSuggestion("/multi_agent list", "/multi_agent list", "List active parallel agents."),
    CommandSuggestion("/ma list", "/ma list", "Alias for /multi_agent list."),
    CommandSuggestion(
        "/multi_agent remove recon1",
        "/multi_agent remove recon1",
        "Remove the example recon agent instance.",
    ),
    CommandSuggestion(
        "/task spawn recon_passive_agent --model gpt-4o --name recon_task --limit 10 --auto-approve",
        "Advanced task spawn: recon_task",
        "Advanced background passive-recon example for test.vulnweb.com.",
    ),
    CommandSuggestion("/t list", "/t list", "Alias for /task list."),
    CommandSuggestion("/task list", "/task list", "List background tasks."),
    CommandSuggestion("/task pause 1", "/task pause 1", "Pause example task ID 1."),
    CommandSuggestion("/task resume 1", "/task resume 1", "Resume example task ID 1."),
    CommandSuggestion("/task cancel 1", "/task cancel 1", "Cancel example task ID 1."),
    CommandSuggestion(
        "/task insight 1 focus on test.vulnweb.com findings",
        "/task insight 1 ...",
        "Ask the peer for guidance about task 1.",
    ),
    CommandSuggestion(
        "/peer consult recon1 review findings for test.vulnweb.com",
        "/peer consult recon1 ...",
        "Ask the peer to review the example recon agent history.",
    ),
    CommandSuggestion("/p consult recon1 summarize findings", "/p consult recon1 ...", "Alias for /peer consult."),
    CommandSuggestion("/mcp list", "/mcp list", "List connected MCP servers and tool counts."),
    CommandSuggestion("/mcp reload", "/mcp reload", "Reload MCP servers from settings.json."),
    CommandSuggestion("/m list", "/m list", "Alias for /mcp list."),
    CommandSuggestion("/auth status", "/auth status", "Show CLI and authentication status."),
    CommandSuggestion("/as", "/as", "Alias for /auth status."),
)


class SlashCommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text.lstrip()
        if not text.startswith("/"):
            return

        cursor_text = document.text_before_cursor.lstrip()
        for suggestion in COMMAND_SUGGESTIONS:
            if suggestion.text.startswith(cursor_text):
                yield Completion(
                    suggestion.text,
                    start_position=-len(document.text_before_cursor),
                    display=suggestion.label,
                    display_meta=suggestion.help_text,
                )


def iter_help_lines(*, strict_modern: bool = False) -> Iterable[Tuple[str, List[CommandEntry]]]:
    """Yield (section_title, entries) for /help display.

    When *strict_modern* is True, sections whose title starts with
    "Legacy" are skipped entirely.
    """
    for title, entries in COMMAND_SECTIONS:
        if strict_modern and title.startswith("Legacy"):
            continue
        yield title, list(entries)


def normalize_command_input(user_input: str) -> str:
    stripped = (user_input or "").strip()
    if not stripped.startswith("/"):
        return stripped

    for alias, expanded in sorted(COMMAND_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if stripped == alias:
            return expanded
        if stripped.startswith(alias + " "):
            return expanded + stripped[len(alias):]
    return stripped
