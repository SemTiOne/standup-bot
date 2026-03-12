"""
main.py — CLI entry point for StandupBot.
"""

import sys

import argparse
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

console = Console()

__version__ = "0.1.0"

# ---------------------------------------------------------------------------
# Setup Wizard
# ---------------------------------------------------------------------------


def _prompt(label: str, default: str = "") -> str:
    """Input prompt with optional default value shown in brackets."""
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{label}{suffix}: ").strip()
        return value or default
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Setup cancelled.[/yellow]")
        sys.exit(0)


def run_setup_wizard() -> None:
    """Interactive config wizard."""
    from standup.config import save_config
    from standup.validator import (
        KNOWN_GROQ_MODELS,
        sanitize_path,
        sanitize_string,
        validate_setup_input,
    )

    console.print(Panel("[bold green]Welcome to StandupBot setup![/bold green]", expand=False))

    config: dict = {
        "repos": [],
        "author_email": "",
        "hours_lookback": 24,
        "tone": "casual",
        "slack_webhook_url": "",
        "provider": {
            "name": "ollama",
            "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
            "groq": {"api_key": "", "model": "llama3-8b-8192"},
        },
        "rate_limit": {"cooldown_minutes": 30, "max_calls_per_day": 10, "enabled": True},
    }

    # --- Provider ---
    console.print("\n[bold]Which LLM provider do you want to use?[/bold]")
    console.print("  1. Ollama (local, free, private — recommended)")
    console.print("  2. Groq (free cloud, needs free API key)")
    while True:
        choice = _prompt("Enter choice", "1")
        if choice in ("1", "2"):
            break
        print("❌ Invalid choice. Enter 1 or 2.")

    if choice == "2":
        config["provider"]["name"] = "groq"
        console.print(
            "\n[bold cyan]Get your free API key at:[/bold cyan] https://console.groq.com"
        )
        console.print("\n[bold]Available free Groq models:[/bold]")
        for i, m in enumerate(KNOWN_GROQ_MODELS, 1):
            console.print(f"  {i}. {m}")

        model_choice = _prompt("Model", "llama-3.1-8b-instant")
        ok, _ = validate_setup_input("groq_model", model_choice)
        config["provider"]["groq"]["model"] = model_choice if ok else "llama3-8b-8192"

        console.print(
            "\n[yellow]💡 Recommended: store your key as an env var:[/yellow]\n"
            "   export GROQ_API_KEY=your_key\n"
        )
        api_key = _prompt("Groq API key (leave blank to use env var)", "")
        if api_key:
            console.print(
                "[yellow]⚠️  Storing API key in config file. "
                "Consider using GROQ_API_KEY env var instead.[/yellow]"
            )
            config["provider"]["groq"]["api_key"] = api_key
    else:
        config["provider"]["name"] = "ollama"
        while True:
            base_url = _prompt("Ollama base URL", "http://localhost:11434")
            ok, msg = validate_setup_input("ollama_base_url", base_url)
            if ok:
                break
            print(f"❌ {msg}")
        config["provider"]["ollama"]["base_url"] = base_url

        model = _prompt("Ollama model", "llama3")
        config["provider"]["ollama"]["model"] = model if model else "llama3"

        # Check availability
        from standup.llm.ollama_provider import OllamaProvider
        provider = OllamaProvider(config)
        if not provider.is_available():
            console.print(
                "[yellow]⚠️  Ollama not detected.[/yellow]\n"
                "  Install it from: https://ollama.com\n"
                f"  Then run: ollama pull {config['provider']['ollama']['model']}\n"
                "[dim]Continuing setup anyway...[/dim]"
            )
        else:
            console.print("[green]✅ Ollama is running and model is available![/green]")

    # --- Repos ---
    console.print("\n[bold]Repo paths[/bold] (enter one per line, blank to finish):")
    repos = []
    while True:
        raw = _prompt(f"  Repo path {len(repos) + 1}", "")
        if not raw:
            break
        path = sanitize_path(raw)
        ok, msg = validate_setup_input("repo_path", path)
        if ok:
            repos.append(path)
            console.print(f"  [green]✅ Added: {path}[/green]")
        else:
            console.print(f"  [red]❌ {msg}[/red]")
    config["repos"] = repos

    # --- Author email ---
    while True:
        email = sanitize_string(_prompt("Author git email (leave blank for all commits)", ""))
        ok, msg = validate_setup_input("author_email", email)
        if ok:
            config["author_email"] = email
            break
        console.print(f"[red]❌ {msg}[/red]")

    # --- Hours lookback ---
    while True:
        hours = _prompt("Hours to look back", "24")
        ok, msg = validate_setup_input("hours_lookback", hours)
        if ok:
            config["hours_lookback"] = int(hours)
            break
        console.print(f"[red]❌ {msg}[/red]")

    # --- Tone ---
    while True:
        tone = _prompt("Tone (casual/formal)", "casual")
        ok, msg = validate_setup_input("tone", tone)
        if ok:
            config["tone"] = tone.lower().strip()
            break
        console.print(f"[red]❌ {msg}[/red]")

    # --- Slack ---
    webhook = sanitize_string(_prompt("Slack webhook URL (optional)", ""))
    ok, msg = validate_setup_input("slack_webhook_url", webhook)
    if ok:
        config["slack_webhook_url"] = webhook
    else:
        console.print(f"[red]❌ {msg} — leaving blank.[/red]")

    # --- Rate limits ---
    while True:
        cooldown = _prompt("Cooldown minutes between calls", "30")
        ok, msg = validate_setup_input("cooldown_minutes", cooldown)
        if ok:
            config["rate_limit"]["cooldown_minutes"] = int(cooldown)
            break
        console.print(f"[red]❌ {msg}[/red]")

    while True:
        max_calls = _prompt("Max calls per day", "10")
        ok, msg = validate_setup_input("max_calls_per_day", max_calls)
        if ok:
            config["rate_limit"]["max_calls_per_day"] = int(max_calls)
            break
        console.print(f"[red]❌ {msg}[/red]")

    save_config(config)
    console.print("\n[bold green]🎉 Setup complete! Run: standup[/bold green]")


# ---------------------------------------------------------------------------
# Slack post helper
# ---------------------------------------------------------------------------


def _post_to_slack(webhook_url: str, text: str) -> None:
    import requests

    try:
        resp = requests.post(webhook_url, json={"text": text}, timeout=10)
        if resp.status_code == 200:
            console.print("[green]✅ Posted to Slack![/green]")
        else:
            console.print(f"[red]❌ Slack post failed: {resp.status_code} {resp.text}[/red]")
    except Exception as exc:
        console.print(f"[red]❌ Slack post error: {exc}[/red]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:  # noqa: C901
    """CLI entry point."""
    from standup.validator import validate_cli_args, validate_hours_arg, validate_provider_arg

    parser = argparse.ArgumentParser(
        prog="standup",
        description="StandupBot — Generate daily standups from your git history.",
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("doctor", help="Run security and health checks")
    subparsers.add_parser("usage", help="Show API usage stats")
    subparsers.add_parser("models", help="List available local Ollama models")

    # Flags
    parser.add_argument("--hours", type=validate_hours_arg, metavar="N", help="Hours to look back")
    parser.add_argument("--week", action="store_true", help="Look back 7 days (168 hours)")
    parser.add_argument("--copy", action="store_true", help="Copy output to clipboard")
    parser.add_argument("--slack", action="store_true", help="Post to Slack webhook")
    parser.add_argument("--raw", action="store_true", help="Print raw git data before summary")
    parser.add_argument(
        "--provider",
        type=validate_provider_arg,
        metavar="NAME",
        help="Provider override: ollama or groq (one-time, does not change config)",
    )
    parser.add_argument("--force", action="store_true", help="Bypass rate limit")
    parser.add_argument("--setup", action="store_true", help="Run interactive setup wizard")
    parser.add_argument("--version", action="store_true", help="Print version")
    parser.add_argument("--changelog", action="store_true", help="Print recent changelog")

    args = parser.parse_args()

    # --- Version ---
    if args.version:
        console.print(f"StandupBot v{__version__}")
        return

    # --- Changelog ---
    if args.changelog:
        import importlib.resources
        from pathlib import Path as _Path
        # Try to read CHANGELOG.md from project root
        changelog_path = _Path(__file__).parent.parent / "CHANGELOG.md"
        if changelog_path.exists():
            console.print(changelog_path.read_text())
        else:
            console.print("[yellow]CHANGELOG.md not found.[/yellow]")
        return

    # --- Setup wizard ---
    if args.setup:
        run_setup_wizard()
        return

    # --- Load config (all other commands need it) ---
    from standup.config import load_config

    config = load_config()

    # --- Subcommands ---
    if args.command == "doctor":
        from standup.security import run_doctor
        run_doctor()
        return

    if args.command == "usage":
        from standup.rate_limiter import get_usage_report
        console.print(get_usage_report())
        return

    if args.command == "models":
        from standup.llm.ollama_provider import OllamaProvider
        provider = OllamaProvider(config)
        models = provider.list_local_models()
        if models:
            console.print("[bold]Local Ollama models:[/bold]")
            for m in models:
                console.print(f"  • {m}")
        else:
            console.print(
                "[yellow]No models found. Is Ollama running?[/yellow]\n"
                "  Start it with: ollama serve\n"
                "  Pull a model:  ollama pull llama3"
            )
        return

    # --- Cross-argument validation ---
    errors = validate_cli_args(args, config)
    if errors:
        for err in errors:
            console.print(f"[red]❌ {err}[/red]")
        sys.exit(1)

    # --- Determine hours ---
    hours: int
    if args.week:
        hours = 168
    elif args.hours:
        hours = args.hours
    else:
        hours = config.get("hours_lookback", 24)

    # --- Rate limit ---
    from standup.rate_limiter import enforce_rate_limit, load_usage, record_call, save_usage

    enforce_rate_limit(config, force=args.force)

    # --- Get provider ---
    from standup.llm.factory import get_provider_with_fallback

    provider = get_provider_with_fallback(config, override=args.provider)
    console.print(f"[dim]Using {provider.get_provider_name()}...[/dim]")

    # --- Read git commits ---
    from standup.git_reader import get_recent_commits

    repos = config.get("repos", [])
    if not repos:
        console.print(
            "[yellow]⚠️  No repos configured. Run: standup --setup[/yellow]"
        )
        sys.exit(1)

    author_email = config.get("author_email", "")
    all_commits = []
    for repo_path in repos:
        commits = get_recent_commits(repo_path, hours, author_email)
        all_commits.extend(commits)

    if not all_commits:
        console.print(
            f"[yellow]No commits found in the last {hours} hours. "
            "Did you take a day off? 🏖️[/yellow]"
        )
        return

    # --- Format ---
    from standup.formatter import build_standup_prompt, format_commits_for_prompt

    formatted = format_commits_for_prompt(all_commits)

    if args.raw:
        console.print(Rule("Raw Git Data"))
        console.print(formatted)
        console.print(Rule())

    prompt = build_standup_prompt(formatted, config.get("tone", "casual"))

    # --- Generate ---
    from standup.llm.base import LLMProviderError

    try:
        standup_text = provider.generate_standup(prompt, config.get("tone", "casual"))
    except LLMProviderError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        sys.exit(1)

    # --- Record usage ---
    usage = load_usage()
    usage = record_call(usage)
    save_usage(usage)

    # --- Output ---
    console.print(Rule("Your Standup"))
    console.print(standup_text)
    console.print(Rule())

    # --- Copy to clipboard ---
    if args.copy:
        try:
            import pyperclip
            pyperclip.copy(standup_text)
            console.print("[green]✅ Copied to clipboard![/green]")
        except Exception as exc:
            console.print(f"[yellow]⚠️  Clipboard copy failed: {exc}[/yellow]")

    # --- Post to Slack ---
    if args.slack:
        webhook = config.get("slack_webhook_url", "")
        if webhook:
            _post_to_slack(webhook, standup_text)
        else:
            console.print("[red]❌ No Slack webhook configured.[/red]")


if __name__ == "__main__":
    main()