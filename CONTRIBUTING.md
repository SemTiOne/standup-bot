# Contributing to StandupBot

Thank you for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/SemTiOne/standupbot.git
cd standupbot
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest tests/ -v
# With coverage
pytest tests/ --cov=standup --cov-report=term-missing
```

## Code Standards

- **Type hints** on all functions and methods
- **Docstrings** on all modules, classes, and public functions
- **`rich`** for all terminal output — no plain `print()` calls in production code
- **`validator.py`** is the single source of truth for all validation — do not add validation logic elsewhere
- All validator functions must return `Tuple[bool, str]` and never raise exceptions
- All regex patterns in `security.py` must be precompiled at module level with `re.compile()`
- Never log raw API keys — always use `mask_api_key()`
- Support Python 3.9+ — use `Optional[X]` and `Union[X, Y]` from `typing`, not `X | Y`

## Adding a New LLM Provider

1. Create `standup/llm/your_provider.py` implementing `BaseLLMProvider`
2. Implement `generate_standup()`, `is_available()`, and `get_provider_name()`
3. Register the provider in `llm/factory.py`
4. Add the provider name to `VALID_PROVIDERS` in `validator.py`
5. Update `README.md` provider comparison table
6. Add tests in `tests/test_llm_factory.py`

## Pull Request Process

1. Fork the repo and create a feature branch
2. Write tests for new functionality
3. Ensure all tests pass: `pytest tests/ -v`
4. Update `CHANGELOG.md` under `[Unreleased]`
5. Open a PR with a clear description of the change

## Reporting Issues

Please include:
- Python version (`python --version`)
- StandupBot version (`standup --version`)
- Output of `standup doctor`
- The full error message