# Changelog

All notable changes to StandupBot will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.4] - 2026-06-09

### Fixed
- `quality.py`: `_score_with_ollama` had the same timeout bug fixed in v0.2.3 for
  `ollama_provider.py` but never applied here. `timeout` was passed inside the
  `options` dict (a model parameter — silently ignored by Ollama) and the `Client`
  was created without any timeout, meaning quality scoring could hang indefinitely.
  Fixed by adding `_OLLAMA_SCORING_TIMEOUT = 30.0` and passing it to
  `ollama.Client(host=..., timeout=_OLLAMA_SCORING_TIMEOUT)`. The spurious
  `"timeout"` key removed from `options`. An `or ""` guard was also added on
  `response["message"]["content"]` for consistency with `groq_provider.py`.
- `ollama_provider.py`: Added `or ""` guard on `response["message"]["content"]`
  in `generate_standup`. A null content field (possible on aborted generation)
  previously caused a `TypeError` in `len(content)` that was swallowed by the
  broad `except` and surfaced as a misleading generic error message.
- `history.py`: `auto_cleanup_if_needed` was unreachable in normal usage because
  `_AUTO_CLEANUP_THRESHOLD = 400` exceeded the hard ceiling enforced by
  `_enforce_max_rows` (`_MAX_HISTORY_ROWS = 365`). Removed the dead threshold
  constant and collapsed `auto_cleanup_if_needed` to delegate directly to
  `_enforce_max_rows`, eliminating the duplicate deletion logic.
- `git_reader.py`: `_infer_modules` used `parts[1]` (second path component) for
  any path with two or more components. Two-component paths like
  `tests/test_auth.py` incorrectly returned the filename (`test_auth.py`) instead
  of the parent directory (`tests`). Fixed with a three-way branch: `parts[1]`
  for three-or-more-component paths, `parts[0]` for two-component paths, and
  `parts[0]` for single-component (root) files.

### Changed
- `validator.py`: Groq model validation changed from a hard allowlist to a
  non-empty-string check. `KNOWN_GROQ_MODELS` is now documented as a suggestion
  list for the setup wizard only; users are no longer blocked from using models
  added after this list was last updated. Removed deprecated `llama3-8b-8192`
  from the list.
- `main.py`: `_get_provider_slug` replaced fragile class-name string matching
  (`"ollama" in class_name`) with explicit `isinstance` checks against
  `OllamaProvider` and `GroqProvider`. Avoids silent misidentification if a
  provider class is renamed or a third provider added.
- `main.py`, `quality.py`, `validator.py`, `git_reader.py`, `ollama_provider.py`:
  Modernized type annotations throughout — `List[X]` → `list[X]`, `Dict[K, V]` →
  `dict[K, V]`, `Optional[X]` → `X | None`, `Tuple[X, Y]` → `tuple[X, Y]`.
  Removed all `from typing import Dict, List, Optional, Tuple` imports; only
  `Any` remains where needed.
- `ruff.toml`: Updated `target-version` from `"py39"` to `"py310"` and removed
  suppression of `UP006`, `UP007`, `UP035` (pyupgrade rules for legacy typing
  syntax). These were kept for Python 3.9 compatibility which was dropped in
  v0.2.3.
- `setup.py`: Removed BOM marker; no functional change.
- `README.md`: Fixed Python version badge (`3.9+` → `3.10+`), removed UTF-8 BOM,
  updated "What is new" section to reflect v0.2.4 changes.
- `CONTRIBUTING.md`: Updated Python version requirement (`3.9+` → `3.10+`),
  updated typing guidance to use modern syntax (`X | None`, built-in generics),
  updated `Tuple[bool, str]` → `tuple[bool, str]` in the validator function
  standard.

### Tests
- `test_history.py`: Rewrote `test_auto_cleanup_if_needed_deletes_rows_over_threshold`
  which previously passed trivially — it inserted rows via `save_standup` (which
  calls `_enforce_max_rows` on every insert), so the ceiling was never exceeded and
  `auto_cleanup_if_needed` never ran. New tests use a `_insert_rows_directly` helper
  that writes to SQLite directly, bypassing `save_standup`. Added dedicated
  `_enforce_max_rows` tests and four `auto_cleanup_if_needed` tests covering: no-op
  within ceiling, trim above ceiling, log event emission, and exact-ceiling no-op.
- `test_git_reader.py`: Added three tests covering the fixed `_infer_modules` logic:
  two-component path returns directory, two-component `src/` path, and mixed-depth
  commit with all three path lengths in one call.
- `test_validator.py`: Replaced `test_provider_config_groq_unknown_model` (expected
  rejection of `"gpt-4"` — correct under the old allowlist, wrong now) with
  `test_provider_config_groq_accepts_unlisted_model` and
  `test_provider_config_groq_rejects_empty_model`. Added
  `test_setup_input_groq_model_unlisted_accepted` and
  `test_setup_input_groq_model_empty_rejected` to pin the new contract.

## [0.2.3] - 2026-06-06

### Fixed
- `llm/ollama_provider.py`: `options={"timeout": 60}` was passed as a model parameter
  (e.g. temperature, top_p) instead of as an HTTP connection timeout — Ollama silently
  ignored it. Fixed by moving timeout to `ollama.Client(host=..., timeout=60.0)`, which
  propagates correctly to the underlying `httpx.Client` via `**kwargs`.

### Changed
- `llm/base.py`: Extracted `DEFAULT_SYSTEM_PROMPT` as a single shared constant.
  Both `GroqProvider` and `OllamaProvider` previously defined the identical 7-line
  prompt string independently — a maintenance hazard if the prompt ever needs updating.
- `requirements.txt` / `setup.py`: Widened upper version bounds on `groq` (`<1.0.0` →
  `<2.0.0`) and `rich` (`<14.0.0` → `<16.0.0`). The previous caps blocked users who had
  groq 1.x or rich 14–15.x installed, causing pip dependency conflicts.
- `setup.py`: Dropped Python 3.9 from `python_requires` (now `>=3.10`) and from the
  PyPI classifiers. Python 3.9 reached end-of-life in October 2025 and was already absent
  from the CI test matrix.

### Infrastructure
- `.gitattributes`: Added to enforce LF line endings across all text files. Without this,
  `core.autocrlf=true` on Windows fights with ruff's `line-ending = "lf"` setting,
  causing files edited by ruff to appear perpetually modified in `git status`.

## [0.2.2] - 2026-06-05

### Fixed
- `validator.py`: `validate_full_config()` no longer validates repo filesystem state
  (existence, `.git` presence). It now only checks structural integrity (non-empty string)
  and path safety (traversal, symlinks). The graceful "Skipping invalid repo" filter in
  `load_config()` was previously unreachable because `validate_full_config()` would call
  `sys.exit(1)` first — now both mechanisms work as intended.
- `history.py`: `auto_cleanup_if_needed()` was emitting `log_event("db_error", ...)` on
  a **successful** row deletion. Fixed to emit `log_event("db_maintenance", ...)` for the
  success path; the `db_error` event is preserved only for actual `sqlite3.Error` failures.
- `quality.py`: `completion.choices[0].message.content` can be `None` on empty or
  malformed API responses. Added an `or ""` fallback to prevent a `TypeError` crash inside
  `_extract_json()` at runtime.
- `logger.py`: Replaced `__import__("datetime")` inline expression inside `log_event()`
  with a proper module-level `import datetime as _dt`. The inline pattern bypasses standard
  import conventions and is harder to audit.
- `main.py`: Removed dead code — `if used_cache: return` at the very end of `main()` was
  the last statement in the function and therefore never skipped anything.

### Changed
- `README.md`: Development section now uses `python -m pytest tests/ -q` instead of the
  Windows-specific `py -3 -B -m pytest tests -q`, which fails on Linux and macOS.
- `pytest.ini`: Added to the project root to suppress `DeprecationWarning` noise emitted
  by globally-installed `pytest_asyncio` on Python 3.14+ (unrelated to this project's
  test suite, which contains no async tests).

## [0.2.1] - 2026-04-27

### Added
- Structured JSON-line logging in `~/.standup.log` with rotation, redaction, and `standup logs` management commands.
- Schema migration tracking for `~/.standup_history.db` plus automatic history cleanup and richer doctor visibility into DB health.
- Meta-tests that enforce security and code-quality invariants such as no raw SQL interpolation and no plain `print()` in production code.

### Changed
- Bumped package version to `0.2.1`.
- Hardened template rendering with allowlisted placeholders, bounded substitution, and validation against Python-style format syntax.
- Added path-safety and resource-limit validation for repo paths, template counts, commit volume, and history limits.
- Truncated oversized commit messages and LLM responses before they can reach prompts, storage, or terminal output.
- Added `standup --maintenance` for local cleanup tasks and log rotation.
- Expanded CI to include linting, type checking, dependency audit, bandit, and a broader Python matrix.

### Security
- Added safe error-message sanitization to prevent leaking API keys, local file paths, and email addresses.
- Hardened SQLite connections with WAL mode, busy timeout, migration tracking, and bounded storage sanitization.
- Added structured audit events for cache hits, LLM failures, warm-up results, rate-limit hits, doctor runs, and DB errors.

## [0.2.0] - 2026-04-26

### Added
- Intelligent standup history backed by `~/.standup_history.db` with same-day cache reuse for identical commit fingerprints.
- `standup history` subcommand with listing, limit controls, and safe clear modes including age-based pruning.
- Local commit classification and noise filtering with commit-type emojis and richer prompt context.
- Template system with built-in formats (`default`, `slack`, `minimal`, `detailed`, `jira`) plus config-driven custom templates.
- Quality scoring with colored badges, optional breakdowns, minimum-score retries, and persisted quality scores in history.
- `standup templates` subcommand for discovering available built-in and custom templates.
- `standup warm-up` command for pre-loading Ollama models or pinging Groq connectivity.
- Optional startup integration paths for warm-up on Windows, macOS, and Linux login.
- New config keys for quality scoring, template selection, noise filtering, custom templates, and auto warm-up.
- Dedicated test modules for classifier, templates, history, quality, and warm-up behavior.

### Changed
- Bumped package version to `0.2.0`.
- Setup wizard now captures template, quality, noise-filter, and warm-up preferences.
- Formatter output now includes commit classification details so the LLM can better distinguish features, fixes, refactors, and support work.
- Security doctor now checks history database permissions and validates the new config sections.
- Cache hits skip fresh generation and show a `⚡ Using cached standup from HH:MM` hint.

### Security
- History entries store only commit fingerprints, not raw commit messages.
- New on-disk artifacts use the same permission-hardening pattern as config and usage files on Unix/macOS.
- All history SQL operations use parameterized queries.

## [0.1.0] - 2026-03-12

### Added
- Initial release
- Git log parsing across multiple local repositories
- Ollama local LLM provider (default, free, 100% offline)
- Groq free cloud LLM provider (fallback option)
- Automatic fallback from Ollama → Groq when Ollama is unavailable
- `--provider` flag for one-time provider override (does not modify config)
- `standup models` command to list locally pulled Ollama models
- Rate limiting with configurable cooldown and daily call cap
- `--force` flag to bypass rate limits when needed
- Input validation for all config fields and CLI arguments via `validator.py`
- `standup doctor` - security and health check with rich table output
- `standup usage` - 7-day usage sparkline report
- `standup --setup` - interactive setup wizard with provider selection first
- Clipboard output support via `--copy`
- Slack webhook posting via `--slack`
- Commit message redaction before sending to LLM (passwords, IPs, hostnames)
- Config file permission enforcement (chmod 600 on Unix/macOS)
- Full test suite covering all modules
- `CONTRIBUTING.md` and `README.md`