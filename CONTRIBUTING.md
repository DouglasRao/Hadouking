# Contributing

Thanks for contributing to PentestLLM.

## Before You Start

- Open an issue or discussion for large changes before implementing them.
- Keep changes focused and avoid mixing unrelated fixes in the same pull request.
- Never commit secrets, local auth state, or machine-specific configuration.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## Development Guidelines

- Keep the codebase and user-facing text in English.
- Preserve the project name `PentestLLM`.
- Use `settings.example.json` as the public template and keep `settings.json` local only.
- Prefer small, reviewable pull requests with a clear summary.
- Update documentation when behavior, commands, configuration, or workflows change.

## Testing

Run the test suite before opening a pull request:

```bash
pytest -q
```

If you change runtime behavior, also run a quick manual smoke test in the console flow when relevant.

## Security

- Do not commit `.env`, `settings.json`, `.claude/`, `.codex/`, or generated pentest artifacts.
- If a secret is exposed, rotate it immediately before opening a pull request.
- Only test systems you are authorized to assess.

## Pull Requests

- Describe what changed and why.
- Mention any tradeoffs, follow-up work, or known limitations.
- Include validation details such as tests run or manual checks performed.
