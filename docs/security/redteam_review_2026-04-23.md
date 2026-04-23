# Internal Red-Team Security Review (2026-04-23)

This document captures high-level exploit chains identified through static code inspection and safe local validation in the repository sandbox.

## Top 5 realistic exploit chains

1. Prompt-injection-to-shell execution chain in agent command loop.
2. Auto-loading untrusted MCP server definitions can execute attacker-controlled local binaries.
3. Persistent approval-state tampering can silently downgrade command-confirmation safeguards.
4. Browser screenshot path argument allows arbitrary local file write paths.
5. Team hook commands execute through `shell=True`, enabling shell-level execution of arbitrary hook strings.

## Scope notes

- Analysis only uses repository code and local sandbox tests.
- No external targets, real credentials, malware, or weaponized payloads were used.
- Any potential secret exposure was treated as metadata-only risk (path + impact), not value disclosure.
