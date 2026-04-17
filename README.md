# Hadouking

Hadouking is an interactive console for autonomous pentest agents. It can run `bash`, `python`, MCP tools defined in `settings.json`, and optional browser steps. It supports multiple LLM backends, parallel agents, background tasks, A2P peer consultation, and an orchestrated brain + subagent mode via `/multi_agent` (`/multi_agents` remains as a deprecated compatibility alias).

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

`requirements.txt` contains the runtime dependencies required to launch and use Hadouking.

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

## Running Hadouking

Start the app:

```bash
python main.py
```

At startup you will choose:
- authentication mode
- then configure models in runtime with `/model`

## Authentication Modes

Hadouking offers three authentication modes:

1. `API Keys`
2. `Claude Code (CLI)`
3. `Codex (CLI)`

Recommended default:
- use `API Keys` if you want the simplest setup

Use CLI modes only if:
- you already installed the official binary
- you already logged in locally

## Model Selection

Model selection is runtime-driven via `/model`.

Examples:

```text
/model list
/model set 4
/model peer same
```

The model catalog includes:
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

### Autotest

Use `/autotest` to run CLI diagnostics and apply the tested executor/peer pair:
- validates Claude/Codex CLI setup
- runs smoke checks
- runs a minimal lab recon flow

## MCP Integration

Only MCP servers defined in your local `settings.json` are loaded.

Useful commands:

```text
/mcp list
/mcp reload
```

Behavior:
- if MCP backends are offline, Hadouking still runs
- MCP is optional unless you explicitly invoke MCP-backed flows

Template:
- use `settings.example.json` as the base

## Agent Profiles

Agent profiles live in `agents/configs/*.json`.

Examples:
- `pentest_brain_agent`
- `recon_passive_agent`
- `recon_active_agent`
- `vuln_scanner_agent`
- `code_review_agent`
- `api_testing_agent`
- `exploit_validation_agent`
- `reporting_agent`

Rule:
- files starting with `_` are ignored

## How To Use The App

Hadouking now has one primary operating pattern, one focused secondary mode, and a legacy/advanced compatibility surface.

### 1. Primary Flow: Orchestrated Multi-Agent

Use `/multi_agent` when you want the PTES/OWASP stage-based workflow with:
- central brain agent
- parallel specialist agents only
- interactive setup quiz (OS, models, safety policy)
- temporary teammate profiles (`temporary`) generated per run and discarded on cleanup
- immutable native profiles (`native`) loaded from `agents/configs/`
- live taskboard updates
- shared task list with dependencies and task claiming
- teammate mailbox (lead/worker coordination messages)
- optional lead plan approval gate before task execution
- explicit team cleanup at the end of the run

Compatibility:
- `/multi_agents` is still accepted but deprecated; use `/multi_agent` for all new workflows.

Examples:

```text
/multi_agent testphp.vulnweb.com full PTES flow
/multi_agent workers recon_passive,recon_active,vuln_scanner testphp.vulnweb.com baseline mapping
/multi_agent resume
/multi_agent temporary testphp.vulnweb.com full PTES flow
/multi_agent native testphp.vulnweb.com
```

Use this as the default operator experience.

### 2. Secondary Flow: Single Agent

Use `/single_agent` when you want one persistent interactive session with one agent.

Example:

```text
/single_agent recon_passive_agent --model gpt-4o --limit 10 --auto-approve
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
/single_agent recon_passive_agent --model gpt-4o --limit 10 --auto-approve
recon_passive_agent> objective: assess test.vulnweb.com
recon_passive_agent> focus on subdomains now
recon_passive_agent> summarize findings so far
recon_passive_agent> /back
Hadouking>
```

### 3. Legacy / Advanced Compatibility Surface

Use the commands in this section only when you explicitly need the old operational model.

Legacy parallel persistent agents:

Example:

```text
/multi_agent add recon_passive_agent --model gpt-4o --name recon1 --limit 10 --auto-approve
/multi_agent add exploit_validation_agent --model gpt-4o --name exploit1 --limit 10 --auto-approve
```

Then type a normal prompt:

```text
Hadouking> assess test.vulnweb.com and compare findings
```

That prompt is broadcast to all active agents.

Useful commands:

```text
/multi_agent list
/multi_agent remove recon1
```

Background tasks (advanced):

```text
/task spawn recon_passive_agent --model gpt-4o --name recon_task --limit 10 --auto-approve
/task list
/task pause 1
/task resume 1
/task cancel 1
/task insight 1 review findings so far
```

### Agent Teams — orchestrated design

`/multi_agent` uses the Agent Teams model with coordinated state and safe parallel execution:

- shared task list (`pending` / `in_progress` / `completed` / `failed`) with explicit dependencies
- per-worker mailbox + broadcast (`*`) for lead/worker coordination
- lifecycle event hooks (`TaskCreated`, `TaskCompleted`, `TeammateIdle`) for automation/telemetry
- file-lock on task claiming to prevent races between concurrent workers
- interactive teammate navigation via arrow keys / `j`/`k` when TTY is available; automatic non-interactive fallback otherwise
- **runtime instruction queue**: type `:new instruction` + Enter during a `/multi_agent` run to queue guidance — applied at the next safe coordination checkpoint without interrupting the current execution round
- **preemption checkpoints**: after each bash/python/MCP/browser tool execution, running agents check for queued operator instructions and reorient
- **auto-resume at startup**: if an orchestrated session is found incomplete on disk, Hadouking asks whether to resume it
- **terminal split panes**: iTerm2 (macOS), tmux (Linux/macOS), or manual tail fallback for Windows/unsupported envs

Orchestration design reference: https://code.claude.com/docs/en/agent-teams

### A2P Peer Consultation

A2P (agent-to-peer) is **disabled by default**. Enable with `HADOUKING_A2P_ENABLED=1` in `.env`.

When enabled:
- `/peer consult <agent_name> [note]` — asks the peer model for text-only insight using the agent's session history
- `/task insight <id> [note]` — same, scoped to a background task agent

A2P never executes commands; the peer model reads the history and returns analysis only.

## Command Discovery

Use `/help` for the current command catalog and examples.

The prompt keeps shell-like typing behavior and command history without forcing a slash-popup menu.

## Aliases

Short aliases are supported to reduce typing:

- `/h` => `/help`
- `/a` => `/agent`
- `/sa` => `/single_agent`
- `/ma` => `/multi_agent`
- `/mas` => `/multi_agents` (deprecated alias)
- `/t` => `/task`
- `/p` => `/peer`
- `/m` => `/mcp`
- `/as` => `/auth status`

Examples:

```text
/sa recon_passive_agent --model gpt-4o --limit 10 --auto-approve
/ma testphp.vulnweb.com quick baseline
/mas testphp.vulnweb.com   # deprecated alias path
/t list
/m reload
/as
```

## Command Reference

### General

- `/help`
- `/h`
- `/session [show|resume|reset]`
- `exit`
- `quit`

### Agents

- `/agent list`
- `/a list`
- `/single_agent <key> --model <model> [flags]`
- `/sa <key> --model <model> [flags]`
- `/multi_agent <target> [objective]`
- `/multi_agent [temporary|native] <target> [objective]`
- `/multi_agent workers <w1,w2,...> <target> [objective]`
- `/multi_agent resume [session_dir]`
- `/multi_agents [temporary|native] <target> [objective]` (deprecated alias)
- `/mas ...` (deprecated alias)

### Tasks

- `/task list`
- `/task pause <id>`
- `/task resume <id>`
- `/task cancel <id>`
- `/task insight <id> [note]`
- `/t list|pause|resume|cancel|insight ...`

### Legacy / Advanced

- `/multi_agent add <key> --model <model> [flags]`
- `/multi_agent list`
- `/multi_agent remove <name>`
- `/multi_agent <key> <objective>`
- `/ma add|list|remove ...`
- `/task spawn <key> --model <model> [flags]`
- `/t spawn ...`

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
- `--allow-install`
- `--allow-delete`
- `--os <name>`
- `--distro <name>`

## Typical Workflows

### Orchestrated PTES Flow

```text
/multi_agent testphp.vulnweb.com map attack surface and validate top risks
/multi_agent workers recon_passive,recon_active,api_testing testphp.vulnweb.com auth and attack-surface focus
/multi_agent resume
```

### Quick Single Recon

```text
/sa recon_passive_agent --model gpt-4o --limit 10 --auto-approve
recon_passive_agent> objective: assess test.vulnweb.com
```

### Deprecated Alias Compatibility

```text
/multi_agents temporary testphp.vulnweb.com full PTES flow
/mas testphp.vulnweb.com
```

### Legacy / Advanced Multi-Agent Comparison

```text
/multi_agent add recon_passive_agent --model gpt-4o --name recon1 --limit 10 --auto-approve
/multi_agent add exploit_validation_agent --model gpt-4o --name exploit1 --limit 10 --auto-approve
Hadouking> assess test.vulnweb.com and compare passive recon vs exploit validation
```

### Legacy / Advanced Background Investigation

```text
/task spawn recon_passive_agent --model gpt-4o --name recon_task --limit 10 --auto-approve
/task list
/task insight 1 summarize highest-value next steps
```

### Persisted Session State

```text
/session show
/session resume
/session reset
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

Hadouking classifies execution requests into practical tiers such as:
- local read
- network
- mutation
- privileged

At each approval prompt the following scopes are available:

| Key | Scope | Persists across restarts |
|-----|-------|--------------------------|
| `y` | once (this execution only) | no |
| `c` | exact command (this agent session) | no |
| `s` | same risk tier (this agent session) | no |
| `p` | exact command (persisted to disk) | yes |
| `q` | same risk tier (persisted to disk) | yes |
| `a` | always approve for this agent session | no |
| `n` | deny | — |

Approvals are scoped per-agent and per-project directory to prevent leakage across agents, sessions, and projects.

The context status line shows live approval state per agent: `approvals: agent:[always|2tier|3cmd|persisted:1t/0c]`.

Use `/approvals` to inspect the full approval state for all active agents.

`--auto-approve` relaxes approval prompts but does not bypass hard guardrails.

Relevant environment variables:
- `HADOUKING_EXEC_MODE`
- `HADOUKING_ALLOW_SUDO`
- `HADOUKING_MAX_AGENT_TURNS`
- `HADOUKING_MAX_STUCK_COMMAND_ROUNDS`

## Environment Variables

Common variables:
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_AUTH_TOKEN`
- `DEEPSEEK_API_KEY`
- `OPENROUTER_API_KEY`
- `HADOUKING_CODEX_MODEL`
- `HADOUKING_EXEC_MODE`
- `HADOUKING_ALLOW_SUDO`
- `HADOUKING_MAX_AGENT_TURNS`
- `HADOUKING_MAX_STUCK_COMMAND_ROUNDS`
- `HADOUKING_MAX_BG_TASKS`
- `HADOUKING_COMPRESS_OUTPUT`
- `HADOUKING_CONTEXT_MAX_CHARS`
- `HADOUKING_LOCALE`
- `HADOUKING_STRICT_MODERN` — set to `1` to hide legacy commands from `/help`
- `HADOUKING_A2P_ENABLED` — set to `1` to enable A2P peer-consultation calls (`/peer consult`, `/task insight`); off by default
- `HADOUKING_A2P_PEER_MODEL` — override the peer model for A2P calls

Language note:
- if `HADOUKING_LOCALE` starts with `pt`, the system prompt asks agents to reply in Brazilian Portuguese
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
- `/multi_agent <target> ...`

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

- `/help` is the authoritative command catalog during runtime
- `Ctrl+C` interrupts interactive agent runs and requests summaries
- Background tasks are managed separately from interactive agent sessions
- Use only authorized targets and scopes

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add new skills or improve existing scripts.

New skills follow the same structure: `skills/<name>/SKILL.md` + `scripts/`.

## License

This project is licensed under the MIT License.

## Acknowledgements

Hadouking is a more robust successor to my earlier project, [`HackingGPT`](https://github.com/DouglasRao/hackingGPT).

During development, I studied public ideas from agent tooling projects, including [`CAI`](https://github.com/aliasrobotics/cai) by Alias Robotics. Hadouking is an independent implementation and is not affiliated with those projects.
