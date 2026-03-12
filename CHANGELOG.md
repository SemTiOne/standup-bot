# Changelog

All notable changes to StandupBot will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- `standup doctor` — security and health check with rich table output
- `standup usage` — 7-day usage sparkline report
- `standup --setup` — interactive setup wizard with provider selection first
- Clipboard output support via `--copy`
- Slack webhook posting via `--slack`
- Commit message redaction before sending to LLM (passwords, IPs, hostnames)
- Config file permission enforcement (chmod 600 on Unix/macOS)
- Full test suite covering all modules
- `CONTRIBUTING.md` and `README.md`