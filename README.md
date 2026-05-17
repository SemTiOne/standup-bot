# StandupBot

Generate standup updates from recent git activity with a local Ollama model or Groq's free cloud tier.

![Tests](https://github.com/SemTiOne/standup-bot/actions/workflows/tests.yml/badge.svg)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## What is new in 0.2.1

- Structured JSON-line logging in `~/.standup.log` with rotation and `standup logs`
- Hardened SQLite history with schema migrations, WAL mode, and automatic cleanup
- Safer template rendering with strict placeholder allowlisting and output bounds
- Path traversal defenses, resource limits, and safer error message sanitization
- `standup --maintenance` for DB cleanup, usage pruning, and early log rotation

## Quick Start

```bash
# Install dependencies
pip install -e .

# Configure StandupBot
standup --setup

# Generate a standup
standup
```

For Ollama, install and pull a model first:

```bash
ollama pull llama3
```

## Providers

| Provider | Cost | Privacy | Best for |
|---|---|---|---|
| Ollama | Free | Fully local | Private, offline workflows |
| Groq | Free tier | Cloud | Fast generation without local model setup |

Groq API keys should be supplied through `GROQ_API_KEY` when possible.

## Core Commands

```bash
# Standard generation
standup
standup --hours 48
standup --week
standup --provider groq

# Output options
standup --copy
standup --slack
standup --raw
standup --template slack
standup --verbose

# Cache and filtering controls
standup --no-cache
standup --no-filter

# Maintenance
standup doctor
standup usage
standup logs
standup logs --tail 50
standup logs --clear
standup models
standup templates
standup history
standup history --limit 25
standup history --clear
standup history --clear --days 30
standup warm-up
standup warm-up --install-startup
standup warm-up --uninstall-startup
standup --maintenance
```

## Templates

Built-in templates:

- `default`
- `slack`
- `minimal`
- `detailed`
- `jira`

You can also define custom templates in config. StandupBot extracts `yesterday`, `today`, and `blockers` from the LLM output, then renders the final format with these variables:

- `{yesterday}`
- `{today}`
- `{blockers}`
- `{date}`
- `{time}`
- `{commit_count}`
- `{repos}`
- `{provider}`
- `{author_email}`

## Config

StandupBot reads `~/.standup.json`.

```json
{
  "repos": [
    "/path/to/repo1",
    "/path/to/repo2"
  ],
  "author_email": "you@example.com",
  "hours_lookback": 24,
  "tone": "casual",
  "slack_webhook_url": "",
  "provider": {
    "name": "ollama",
    "ollama": {
      "base_url": "http://localhost:11434",
      "model": "llama3"
    },
    "groq": {
      "api_key": "",
      "model": "llama-3.1-8b-instant"
    }
  },
  "rate_limit": {
    "cooldown_minutes": 30,
    "max_calls_per_day": 10,
    "enabled": true
  },
  "quality": {
    "enabled": true,
    "min_score": 0,
    "show_breakdown": false
  },
  "noise_filter_enabled": true,
  "template": "default",
  "custom_templates": {
    "my_format": "Done: {yesterday} | Doing: {today} | Help needed: {blockers}"
  },
  "auto_warm_up": false
}
```

## Caching and History

Every generated standup is stored locally in `~/.standup_history.db`.

- Cache keys are based on a SHA256 fingerprint of sorted commit hashes.
- Cache reuse is limited to the same day, tone, and provider.
- The database stores standup text, provider metadata, repo names, lookback hours, and quality score.
- Raw commit messages are not stored in the database.

## Quality Scoring

After generation, StandupBot can score the standup from 0-100 and show a colored badge.

- Green: 80+
- Yellow: 60-79
- Red: below 60

When `quality.min_score` is above zero, StandupBot retries low-quality outputs up to two times with refined guidance.

## Warm-Up

Use `standup warm-up` to pre-load the configured model before your first real run.

- Ollama: sends a minimal warm-up request to keep the selected model ready in memory.
- Groq: runs a lightweight availability ping.
- `auto_warm_up` can trigger a silent warm-up when the model has not been used recently.

## Security

StandupBot treats config, git metadata, templates, provider responses, and local storage as hostile inputs until proven otherwise.

- `~/.standup.json`, `~/.standup_usage.json`, `~/.standup_history.db`, and `~/.standup.log` use restricted permissions on Unix/macOS.
- Repo paths go through explicit path-safety checks to block traversal tricks, network paths, and unsafe symlinks.
- Commit messages and LLM responses are length-capped before they reach prompts, storage, or terminal rendering.
- Custom templates only substitute a fixed allowlist of variables and reject Python-style format syntax.
- All history database queries are parameterized, and stored standup text is sanitized before persistence.
- User-facing exception messages are sanitized so file paths, emails, and API-key-shaped values are not echoed back to the terminal.
- `standup doctor` now checks log health, DB size, schema version, WAL mode, file permissions, and full config validity.

## Development

```bash
py -3 -B -m pytest tests -q
```

If your environment restricts Python temp directories or `__pycache__` writes, set a writable `--basetemp` or `PYTHONDONTWRITEBYTECODE=1` while testing.

## License

MIT
