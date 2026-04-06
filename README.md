# PentestLLM

PentestLLM is an interactive console for autonomous pentest agents. It can run `bash`, `python`, MCP tools defined in `settings.json`, and optional browser steps. It supports multiple LLM backends, parallel agents, background tasks, and A2P peer consultation.

## Overview

Included:
- Core runtime in `main.py`
- Agent logic in `core/`
- Agent profiles in `agents/configs/`
- UI and utility code in `utils/`
- Tests in `tests/`
- A sanitized MCP template in `settings.example.json`

Not included:
- Your real `settings.json`
- Your `.env`
- Your Claude/Codex local login state
- External MCP backends unless you start them yourself
- Third-party local reference repositories

## Requirements

Minimum:
- Python 3.10+
- `pip`

Optional depending on your setup:
- `claude` CLI for Claude Code mode
- `codex` CLI for Codex mode
- Local MCP backends if you use MCP integrations

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` contains the runtime dependencies required to launch and use PentestLLM.

For development and tests:

```bash
pip install -r requirements-dev.txt
```

`requirements-dev.txt` contains development and test dependencies, such as `pytest`, and is only needed if you plan to run the test suite or contribute changes.

## Local Configuration

### `.env`

Create a local `.env` only if you want API-based models:

```env
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
ANTHROPIC_AUTH_TOKEN=...
DEEPSEEK_API_KEY=...
OPENROUTER_API_KEY=...
```

Notes:
- You do not need every key.
- API key mode works as long as at least one usable provider is configured.
- `ANTHROPIC_AUTH_TOKEN` is supported for Anthropic bearer auth.

### `settings.json`

If you use MCP, create a local `settings.json` from the template:

```bash
cp settings.example.json settings.json
```

Then replace the placeholder paths with your own local paths.

Important:
- `settings.json` is ignored by Git
- `settings.example.json` is the file intended for GitHub
- do not place secrets directly into `settings.example.json`

## Secret Safety

This repository is configured to avoid accidental leaks of local secrets and auth state.

Ignored by Git:
- `.env`
- `.env.*`
- `settings.json`
- `.claude/`
- `.codex/`
- local history files
- local pentest artifacts such as `subdomains.txt`, `Projects/`, and similar outputs

Why this matters:
- API keys in `.env` must never be committed
- Claude CLI local auth state must never be committed
- Codex CLI local auth state must never be committed
- `settings.json` often contains local paths, ports, and machine-specific details

If any secret was ever committed before these ignore rules existed:
- rotate the secret
- remove the file from Git tracking
- clean history if necessary before publishing

## Running PentestLLM

Start the app:

```bash
python main.py
```

At startup you will choose:
- authentication mode
- startup mode
- executor model
- optional A2P peer model

## Authentication Modes

PentestLLM offers three authentication modes:

1. `API Keys`
2. `Claude Code (CLI)`
3. `Codex (CLI)`

Recommended default:
- use `API Keys` if you want the simplest setup

Use CLI modes only if:
- you already installed the official binary
- you already logged in locally

## Startup Modes

Available modes:
- `Normal`
- `Autotest`

`Normal`:
- standard interactive usage

`Autotest`:
- validates Claude/Codex CLI setup
- runs smoke checks
- runs a minimal lab recon flow
- intended for local verification, not daily usage

## Model Selection

The model menu includes:
- Claude Code CLI
- Codex CLI
- Anthropic API models
- OpenAI API models
- DeepSeek models
- OpenRouter models
- auto-rotate free OpenRouter mode

General guidance:
- use `gpt-4o` for broad general use
- use CLI models only if that is your intended auth path
- use vision-capable models if you enable browser intelligence

## MCP Integration

Only MCP servers defined in your local `settings.json` are loaded.

Useful commands:

```text
/mcp list
/mcp reload
```

Behavior:
- if MCP backends are offline, PentestLLM still runs
- MCP is optional unless you explicitly invoke MCP-backed flows

Template:
- use `settings.example.json` as the base

## Agent Profiles

Agent profiles live in `agents/configs/*.json`.

Examples:
- `recon_agent`
- `pentest_agent`
- `bug_bounty_agent`
- `osint_agent`
- `redteam_agent`

Rule:
- files starting with `_` are ignored

## How To Use The App

PentestLLM has three main operating patterns.

### 1. Single Agent

Use `/single_agent` when you want one persistent interactive session with one agent.

Example:

```text
/single_agent recon_agent --model gpt-4o --limit 10 --auto-approve
```

What happens:
- the agent is created
- you are asked for the first objective
- the agent runs
- the session stays open
- you can keep chatting with the same agent
- use `/back`, `exit`, or `quit` to leave that single-agent session

Example interaction:

```text
/single_agent recon_agent --model gpt-4o --limit 10 --auto-approve
recon_agent> objective: assess test.vulnweb.com
recon_agent> focus on subdomains now
recon_agent> summarize findings so far
recon_agent> /back
PentestLLM>
```

### 2. Multi-Agent

Use `/multi_agent add` when you want several agents running in parallel and receiving broadcast prompts.

Example:

```text
/multi_agent add recon_agent --model gpt-4o --name recon1 --limit 10 --auto-approve
/multi_agent add pentest_agent --model gpt-4o --name p1 --limit 10 --auto-approve
```

Then type a normal prompt:

```text
PentestLLM> assess test.vulnweb.com and compare findings
```

That prompt is broadcast to all active agents.

Useful commands:

```text
/multi_agent list
/multi_agent remove recon1
```

### 3. Background Tasks

Use `/task spawn` when you want a background job you can manage later.

Example:

```text
/task spawn recon_agent --model gpt-4o --name recon_task --limit 10 --auto-approve
```

Useful commands:

```text
/task list
/task pause 1
/task resume 1
/task cancel 1
/task insight 1 review findings so far
```

## Command Autocomplete

In the main prompt:
- type `/` to open command suggestions
- use arrow keys to choose a suggestion
- press `TAB` to accept the selected suggestion
- edit the command before sending it

The suggestions include ready-made examples using `test.vulnweb.com`.

## Aliases

Short aliases are supported to reduce typing:

- `/h` => `/help`
- `/a` => `/agent`
- `/sa` => `/single_agent`
- `/ma` => `/multi_agent`
- `/t` => `/task`
- `/p` => `/peer`
- `/m` => `/mcp`
- `/as` => `/auth status`

Examples:

```text
/sa recon_agent --model gpt-4o --limit 10 --auto-approve
/ma list
/t list
/m reload
/as
```

## Command Reference

### General

- `/help`
- `/h`
- `exit`
- `quit`

### Agents

- `/agent list`
- `/a list`
- `/single_agent <key> --model <model> [flags]`
- `/sa <key> --model <model> [flags]`
- `/multi_agent add <key> --model <model> [flags]`
- `/multi_agent list`
- `/multi_agent remove <name>`
- `/ma add|list|remove ...`

### Tasks

- `/task spawn <key> --model <model> [flags]`
- `/task list`
- `/task pause <id>`
- `/task resume <id>`
- `/task cancel <id>`
- `/task insight <id> [note]`
- `/t spawn|list|pause|resume|cancel|insight ...`

### Peer

- `/peer consult <agent_name> [note]`
- `/p consult <agent_name> [note]`

### MCP

- `/mcp list`
- `/mcp reload`
- `/m list|reload`

### Auth

- `/auth status`
- `/as`

### Common Flags

- `--model <name>`
- `--limit <n>`
- `--name <alias>`
- `--auto-approve`
- `mcp all`
- `mcp <name>`
- `--browser`
- `--browser-cli`
- `--browser-gui`
- `--browser-intelligence`

## Typical Workflows

### Quick Single Recon

```text
/sa recon_agent --model gpt-4o --limit 10 --auto-approve
recon_agent> objective: assess test.vulnweb.com
```

### Multi-Agent Comparison

```text
/multi_agent add recon_agent --model gpt-4o --name recon1 --limit 10 --auto-approve
/multi_agent add pentest_agent --model gpt-4o --name pentest1 --limit 10 --auto-approve
PentestLLM> assess test.vulnweb.com and compare recon vs exploitability
```

### Background Investigation

```text
/task spawn recon_agent --model gpt-4o --name recon_task --limit 10 --auto-approve
/task list
/task insight 1 summarize highest-value next steps
```

### MCP Reload After Starting Backends

```text
/mcp reload
/mcp list
```

## Browser Mode

Relevant flags:
- `--browser`
- `--browser-cli`
- `--browser-gui`
- `--browser-intelligence`

Notes:
- browser mode is optional
- browser intelligence requires a vision-capable model
- CLI bridge models may not support vision behavior the same way API vision models do

## Execution and Approval Model

PentestLLM classifies execution requests into practical tiers such as:
- local read
- network
- mutation
- privileged

What this means:
- harmless local reads may run without extra confirmation
- network, mutation, or privileged actions may require confirmation depending on mode
- `--auto-approve` relaxes approval prompts but does not bypass hard guardrails

Relevant environment variables:
- `PENTESTLLM_EXEC_MODE`
- `PENTESTLLM_ALLOW_SUDO`
- `PENTESTLLM_MAX_AGENT_TURNS`
- `PENTESTLLM_MAX_STUCK_COMMAND_ROUNDS`

## Environment Variables

Common variables:
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_AUTH_TOKEN`
- `DEEPSEEK_API_KEY`
- `OPENROUTER_API_KEY`
- `PENTESTLLM_CODEX_MODEL`
- `PENTESTLLM_EXEC_MODE`
- `PENTESTLLM_ALLOW_SUDO`
- `PENTESTLLM_MAX_AGENT_TURNS`
- `PENTESTLLM_MAX_STUCK_COMMAND_ROUNDS`
- `PENTESTLLM_MAX_BG_TASKS`
- `PENTESTLLM_COMPRESS_OUTPUT`
- `PENTESTLLM_CONTEXT_MAX_CHARS`
- `PENTESTLLM_LOCALE`

Language note:
- if `PENTESTLLM_LOCALE` starts with `pt`, the system prompt asks agents to reply in Brazilian Portuguese
- your own prompt input can still be written in English

## Project Structure

Important paths:
- `main.py` - top-level interactive console
- `config.py` - runtime configuration and env variables
- `core/` - agent execution, auth, MCP, browser, reports, policies
- `agents/configs/` - agent profiles
- `utils/` - UI helpers, command catalog, auth wizard, compression, helpers
- `tests/` - tests and test docs
- `settings.example.json` - safe MCP template
- `.gitignore` - local secret and artifact protection

## Testing

Run the full test suite:

```bash
pytest -q
```

Or:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## Troubleshooting

### `/mcp list` shows nothing

Check:
- you created `settings.json`
- your MCP backend processes are actually running
- your local paths inside `settings.json` are valid

Then run:

```text
/mcp reload
```

### CLI auth mode does not work

Check:
- `claude` or `codex` is installed
- the binary is in `PATH`
- you already completed local login

Use:

```text
/auth status
```

### I typed a normal prompt and got "No active agents"

That means you have not started any persistent or parallel agent yet.

Start one of these first:
- `/single_agent ...`
- `/multi_agent add ...`

### `/single_agent` ended unexpectedly

Possible reasons:
- the agent hit its action limit
- the turn limit was reached
- the agent stopped after repeated blocked/denied executions
- the session was ended with `/back`, `exit`, or `quit`

### MCP or CLI details might contain secrets

Do not commit:
- `settings.json`
- `.env`
- `.claude/`
- `.codex/`

These are already ignored in `.gitignore`.

## Publishing Checklist

Before pushing to GitHub, verify:
- `settings.json` is not tracked
- `.env` is not tracked
- `.claude/` is not tracked
- `.codex/` is not tracked
- local pentest artifacts are not tracked
- only `settings.example.json` is committed, not your real MCP file

Quick checks:

```bash
git status
git check-ignore -v settings.json .env .claude .codex
```

## Notes

- The `/` autocomplete includes example commands for `test.vulnweb.com`
- `Ctrl+C` interrupts interactive agent runs and requests summaries
- Background tasks are managed separately from interactive agent sessions
- Use only authorized targets and scopes

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add new skills or improve existing scripts.

New skills follow the same structure: `skills/<name>/SKILL.md` + `scripts/`.

## License

This project is licensed under the MIT License.

## Acknowledgements

PentestLLM is a more robust successor to my earlier project, [`HackingGPT`](https://github.com/DouglasRao/hackingGPT).

During development, I studied public ideas from agent tooling projects, including [`CAI`](https://github.com/aliasrobotics/cai) by Alias Robotics. PentestLLM is an independent implementation and is not affiliated with those projects.
