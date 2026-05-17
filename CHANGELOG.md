# Changelog

All notable changes to StandupBot will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
