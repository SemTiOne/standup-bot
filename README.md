# StandupBot 🤖

> Generate your daily standup in seconds from git history — no paid APIs required.

![Tests](https://github.com/SemTiOne/standup-bot/actions/workflows/tests.yml/badge.svg)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![No Paid APIs](https://img.shields.io/badge/paid%20APIs-none-brightgreen)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

**StandupBot reads your recent git commits and uses a local or free cloud LLM to produce a clean 3-part standup: Yesterday | Today | Blockers.**

---

## ✨ No Paid APIs Required

StandupBot defaults to **Ollama** — a local, free, fully offline LLM runner. Your code never leaves your machine. As a fallback, it supports **Groq's free cloud tier** (no credit card needed).

---

## Quick Start

```bash
# 1. Install Ollama
#    macOS/Linux: https://ollama.com
#    Then:
ollama pull llama3

# 2. Install StandupBot
pip install -e .

# 3. Configure and run
standup --setup
standup
```

---

## Installation

```bash
pip install -e .
```

Requires Python 3.9+.

---

## Provider Comparison

| Provider | Cost         | Privacy       | Setup             |
|----------|--------------|---------------|-------------------|
| Ollama   | Free forever | 100% local    | Install Ollama    |
| Groq     | Free tier    | Cloud         | Free API key      |

### Ollama (default — recommended)
- Runs entirely on your machine
- No internet required after setup
- Install: https://ollama.com
- Pull a model: `ollama pull llama3`

### Groq (free cloud fallback)
- Free tier: https://console.groq.com
- No credit card required
- Available free models:
  - `llama-3.1-8b-instant` — fastest, recommended
  - `llama-3.3-70b-versatile` — higher quality
  - `mixtral-8x7b-32768` — longer context

---

## Usage

```bash
# Basic — uses config defaults
standup

# Custom time range
standup --hours 48
standup --week            # Last 7 days

# Output options
standup --copy            # Copy to clipboard
standup --slack           # Post to Slack webhook
standup --raw             # Print raw git data before summary

# Provider override (one-time, does not change your config)
standup --provider ollama
standup --provider groq

# Bypass rate limit
standup --force

# Setup & maintenance
standup --setup           # Interactive config wizard
standup doctor            # Security and health check
standup usage             # API usage stats (7-day sparkline)
standup models            # List locally pulled Ollama models
standup --version
standup --changelog
```

---

## Example Output

```
────────────── Your Standup ──────────────
**Yesterday:** Fixed the authentication bug in the login flow and refactored
token validation logic. Added unit tests for the auth module.

**Today:** Working on the new /users endpoint in the API service and reviewing
open PRs.

**Blockers:** None
──────────────────────────────────────────
```

---

## Config Reference

StandupBot reads `~/.standup.json`. Run `standup --setup` to create it interactively.

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
  }
}
```

| Field | Description | Default |
|-------|-------------|---------|
| `repos` | List of absolute paths to git repos | `[]` |
| `author_email` | Filter commits by this email (leave blank for all) | `""` |
| `hours_lookback` | How far back to look (1–720) | `24` |
| `tone` | `"casual"` or `"formal"` | `"casual"` |
| `slack_webhook_url` | Slack incoming webhook URL | `""` |
| `provider.name` | `"ollama"` or `"groq"` | `"ollama"` |
| `rate_limit.cooldown_minutes` | Minutes between calls | `30` |
| `rate_limit.max_calls_per_day` | Max daily LLM calls | `10` |
| `rate_limit.enabled` | Enable/disable rate limiting | `true` |

---

## Security

- **`~/.standup.json`** is automatically set to `chmod 600` on Unix/macOS.
- **API keys** are never logged in plain text — always masked.
- **Groq API key priority:** `GROQ_API_KEY` environment variable → `provider.groq.api_key` in config. Prefer the env var:
  ```bash
  export GROQ_API_KEY=your_key
  ```
- **Commit messages** are scanned for passwords, IPs, and private hostnames before sending to any LLM. Sensitive patterns are replaced with `[REDACTED]`.
- Run `standup doctor` to audit your setup.

---

## Rate Limiting

StandupBot tracks usage in `~/.standup_usage.json` (also `chmod 600`).

- **Cooldown:** Prevents back-to-back calls within `cooldown_minutes`.
- **Daily cap:** Limits total calls per day to `max_calls_per_day`.
- **Override:** Use `--force` to bypass both limits when needed.
- **Report:** Run `standup usage` to see a 7-day sparkline.

---

## Validation

All config values and CLI arguments are validated before use:

- Repo paths must exist and contain a `.git` directory
- `author_email` must be a valid email format (or empty)
- `hours_lookback` must be an integer between 1 and 720
- `tone` must be `"casual"` or `"formal"`
- `slack_webhook_url` must start with `https://hooks.slack.com/` (or be empty)
- `provider.name` must be `"ollama"` or `"groq"`
- Rate limit values have enforced bounds

---

## Why?

Because writing your standup is the most tedious part of the dev day.

> "What did you do yesterday?"  
> "I… uh… let me check Slack… and git log… and… *opens 7 tabs*"

StandupBot fixes this. One command. Three bullet points. Done.

---

## Python Version

Requires **Python 3.9+**. Tested on Python 3.9, 3.10, 3.11, 3.12, and 3.14.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contact

Dane Parin - [@DParin28178](https://x.com/DParin28178)

Project Link: [https://github.com/SemTiOne/standup-bot](https://github.com/SemTiOne/standup-bot)