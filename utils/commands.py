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
    "/t": "/task",
    "/p": "/peer",
    "/m": "/mcp",
    "/as": "/auth status",
}


COMMAND_SECTIONS: Sequence[Tuple[str, Sequence[CommandEntry]]] = (
    (
        "General",
        (
            CommandEntry("/help", "Show the full command reference."),
            CommandEntry("/h", "Alias for /help."),
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
                "/multi_agent add <key> --model <model> [flags]",
                "Start a parallel agent instance.",
            ),
            CommandEntry("/multi_agent list", "List active parallel agents."),
            CommandEntry("/multi_agent remove <name>", "Remove an active parallel agent."),
            CommandEntry("/ma add|list|remove ...", "Alias for /multi_agent."),
        ),
    ),
    (
        "Tasks",
        (
            CommandEntry(
                "/task spawn <key> --model <model> [flags]",
                "Start a background task and prompt for the objective.",
            ),
            CommandEntry("/t spawn|list|pause|resume|cancel|insight ...", "Alias for /task."),
            CommandEntry("/task list", "List background tasks."),
            CommandEntry("/task pause <id>", "Pause a background task."),
            CommandEntry("/task resume <id>", "Resume a paused task."),
            CommandEntry("/task cancel <id>", "Cancel a background task."),
            CommandEntry(
                "/task insight <id> [note]",
                "Send the task snapshot to the A2P peer for text-only insight.",
            ),
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
)


COMMAND_SUGGESTIONS: Tuple[CommandSuggestion, ...] = (
    CommandSuggestion("/help", "/help", "Show the full command reference."),
    CommandSuggestion("/h", "/h", "Alias for /help."),
    CommandSuggestion("/agent list", "/agent list", "List all available agent profiles."),
    CommandSuggestion("/a list", "/a list", "Alias for /agent list."),
    CommandSuggestion(
        "/single_agent recon_agent --model gpt-4o --limit 10 --auto-approve",
        "Single agent: recon",
        "Persistent session. The next prompt asks for the objective, then you can keep chatting until /back.",
    ),
    CommandSuggestion(
        "/single_agent pentest_agent --model gpt-4o --limit 10 --auto-approve",
        "Single agent: pentest",
        "Persistent session for test.vulnweb.com with a direct pentest profile.",
    ),
    CommandSuggestion(
        "/sa recon_agent --model gpt-4o --limit 10 --auto-approve",
        "Alias: /sa recon",
        "Short alias for /single_agent with the same persistent session behavior.",
    ),
    CommandSuggestion(
        "/multi_agent add recon_agent --model gpt-4o --name recon1 --limit 10 --auto-approve",
        "Multi-agent add: recon1",
        "Example parallel recon agent for test.vulnweb.com.",
    ),
    CommandSuggestion(
        "/multi_agent add pentest_agent --model gpt-4o --name p1 --limit 10 --auto-approve",
        "Multi-agent add: p1",
        "Example parallel pentest agent for test.vulnweb.com.",
    ),
    CommandSuggestion("/multi_agent list", "/multi_agent list", "List active parallel agents."),
    CommandSuggestion("/ma list", "/ma list", "Alias for /multi_agent list."),
    CommandSuggestion(
        "/multi_agent remove recon1",
        "/multi_agent remove recon1",
        "Remove the example recon agent instance.",
    ),
    CommandSuggestion(
        "/task spawn recon_agent --model gpt-4o --name recon_task --limit 10 --auto-approve",
        "Task spawn: recon_task",
        "Background recon example for test.vulnweb.com.",
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


def iter_help_lines() -> Iterable[Tuple[str, List[CommandEntry]]]:
    for title, entries in COMMAND_SECTIONS:
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
