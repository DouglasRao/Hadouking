# Tests - PentestLLM

## Run from the project root

```bash
pip install -r requirements-dev.txt   # includes pytest
pytest -q
```

Or with `unittest` only:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## Files

| File | Type |
|----------|------|
| `conftest.py` | Adds the project root to `sys.path` for pytest |
| `test_agents.py` | Agent, Manager, guardrails, bash extraction |
| `test_agent_integration.py` | Smoke Agent + context loader |
| `test_context_system.py` | ContextLoader + ToolValidator |
| `test_project_manager.py` | ProjectManager |
| `test_loop_prevention.py` | Command loop prevention |
| `test_report_generation.py` | Reports with mocked LLM |
| `test_mcp_mock.py` | `MCPConfig` structure |
| `test_analyzer.py` | Demo manual: `python test_analyzer.py` |
| `test_compaction_mock.py` | Demo manual: `python test_compaction_mock.py` |

The last two are **async demo scripts**, not pytest `test_*` functions.

## Note

`pytest.ini` sets `pythonpath = .` so `core.*` and `agents.*` imports work when you run `pytest` from the project root.
