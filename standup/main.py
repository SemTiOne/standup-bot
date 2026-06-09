"""
main.py - CLI entry point for StandupBot.
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from standup import __version__
from standup.logger import clear_logs, log_event, read_log_entries, rotate_logs_if_needed
from standup.security import sanitize_error_message

console = Console()


def _prompt(label: str, default: str = "") -> str:
    """Prompt for text input with an optional default value."""
    suffix = f" [{default}]" if default else ""
    try:
        value = console.input(f"{label}{suffix}: ").strip()
        return value or default
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Setup cancelled.[/yellow]")
        sys.exit(0)


def _prompt_bool(field_name: str, default: bool) -> bool:
    """Prompt for a boolean value using yes/no input."""
    from standup.validator import parse_bool_text, validate_setup_input

    default_text = "yes" if default else "no"
    while True:
        raw_value = _prompt(field_name, default_text)
        ok, message = validate_setup_input(field_name, raw_value)
        if ok:
            return parse_bool_text(raw_value)
        console.print(f"[red]❌ {message}[/red]")


def _post_to_slack(webhook_url: str, text: str) -> None:
    import requests

    try:
        response = requests.post(webhook_url, json={"text": text}, timeout=10)
        if response.status_code == 200:
            console.print("[green]✅ Posted to Slack![/green]")
        else:
            console.print(
                f"[red]❌ Slack post failed: {response.status_code} {response.text}[/red]"
            )
    except Exception as exc:
        console.print(f"[red]❌ Slack post error: {sanitize_error_message(exc)}[/red]")


def _get_provider_slug(provider: object) -> str:
    """Return the storage-friendly provider slug for a provider instance."""
    from standup.llm.groq_provider import GroqProvider
    from standup.llm.ollama_provider import OllamaProvider

    if isinstance(provider, OllamaProvider):
        return "ollama"
    if isinstance(provider, GroqProvider):
        return "groq"
    return provider.__class__.__name__.lower() or "unknown"


def _get_provider_model(provider: object) -> str:
    """Return the provider model string when available."""
    return str(getattr(provider, "model", "unknown"))


def _get_repo_names(commits: list[dict]) -> list[str]:
    """Return unique repo names from a commit list."""
    return sorted({str(commit.get("repo", "")) for commit in commits if commit.get("repo")})


def _render_final_output(
    raw_standup_text: str,
    template_name: str,
    config: dict,
    commits: list[dict],
    provider_slug: str,
) -> str:
    """Render the final standup output using the selected template."""
    from standup.templates import build_template_variables, get_template, render_template

    repo_names = _get_repo_names(commits)
    template_text = get_template(template_name, config.get("custom_templates", {}))
    variables = build_template_variables(
        raw_standup_text,
        commit_count=len(commits),
        repos=repo_names,
        provider=provider_slug,
        author_email=config.get("author_email", ""),
    )
    return render_template(template_text, variables)  # type: ignore[arg-type]


def _show_quality_breakdown(quality: dict[str, object]) -> None:
    """Print quality strengths and issues when available."""
    issues = quality.get("issues", [])
    strengths = quality.get("strengths", [])

    if isinstance(strengths, list) and strengths:
        console.print("[bold]Strengths[/bold]")
        for strength in strengths:
            console.print(f"  [green]• {strength}[/green]")

    if isinstance(issues, list) and issues:
        console.print("[bold]Issues[/bold]")
        for issue in issues:
            console.print(f"  [yellow]• {issue}[/yellow]")


def _should_auto_warm_up(provider: object, config: dict) -> bool:
    """Determine whether silent auto-warm-up should run before generation."""
    if not config.get("auto_warm_up", False):
        return False

    try:
        from standup.history import get_history
        from standup.llm.ollama_provider import OllamaProvider
        from standup.warmup import is_model_warm
    except Exception:
        return False

    if not isinstance(provider, OllamaProvider):
        return False
    if is_model_warm(provider):
        return False

    model = _get_provider_model(provider)
    for entry in get_history(limit=25):
        if entry.get("provider") != "ollama":
            continue
        if entry.get("model") != model:
            continue
        try:
            created_at = datetime.fromisoformat(str(entry.get("created_at")))
        except Exception:
            return True
        return datetime.now() - created_at > timedelta(minutes=60)
    return True


def _startup_paths() -> dict[str, Path]:
    """Return platform-specific startup artifact paths."""
    if sys.platform == "win32":
        base_dir = Path.home() / "AppData" / "Roaming" / "StandupBot"
        return {
            "base_dir": base_dir,
            "script": base_dir / "standupbot-warmup.ps1",
            "definition": base_dir / "standupbot-warmup.xml",
        }
    if sys.platform == "darwin":
        return {
            "base_dir": Path.home() / "Library" / "LaunchAgents",
            "definition": Path.home() / "Library" / "LaunchAgents" / "com.standupbot.warmup.plist",
        }
    return {
        "base_dir": Path.home() / ".config" / "systemd" / "user",
        "definition": Path.home() / ".config" / "systemd" / "user" / "standupbot-warmup.service",
    }


def _startup_definition_content(paths: dict[str, Path], script_content: str) -> dict[str, str]:
    """Build platform-specific startup artifact content."""
    if sys.platform == "win32":
        script_path = str(paths["script"])
        xml_content = f"""<?xml version=\"1.0\" encoding=\"UTF-16\"?>
<Task version=\"1.2\" xmlns=\"http://schemas.microsoft.com/windows/2004/02/mit/task\">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id=\"Author\">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context=\"Author\">
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>-ExecutionPolicy Bypass -File \"{script_path}\"</Arguments>
    </Exec>
  </Actions>
</Task>
"""
        return {"script": script_content, "definition": xml_content}

    if sys.platform == "darwin":
        plist = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\">
<dict>
  <key>Label</key>
  <string>com.standupbot.warmup</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>{0}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{1}</string>
  <key>StandardErrorPath</key>
  <string>{2}</string>
</dict>
</plist>
""".format(  # noqa: UP030
            script_content.strip(),
            str(Path.home() / ".standupbot-warmup.log"),
            str(Path.home() / ".standupbot-warmup.err"),
        )
        return {"definition": plist}

    service = f"""[Unit]
Description=StandupBot warm-up on login

[Service]
Type=oneshot
ExecStart=/bin/bash -lc '{script_content.strip()}'

[Install]
WantedBy=default.target
"""
    return {"definition": service}


def _confirm_action(prompt_text: str) -> bool:
    """Prompt the user to confirm a potentially sensitive action."""
    response = _prompt(prompt_text, "no").strip().lower()
    return response in ("y", "yes")


def _install_startup(config: dict) -> None:
    """Install a platform-specific login-time warm-up definition."""
    from standup.security import enforce_file_permissions
    from standup.warmup import get_warm_up_script_content

    paths = _startup_paths()
    script_content = get_warm_up_script_content(config.get("provider", {}))
    definition_content = _startup_definition_content(paths, script_content)

    console.print("[bold]Startup installation preview[/bold]")
    for name, content in definition_content.items():
        target = paths["script"] if name == "script" else paths["definition"]
        console.print(f"[cyan]{name}[/cyan] -> {target}")
        console.print(Panel(content.strip(), title=str(target), expand=False))

    if not _confirm_action("Install startup warm-up files?"):
        console.print("[yellow]Startup installation cancelled.[/yellow]")
        return

    paths["base_dir"].mkdir(parents=True, exist_ok=True)
    if "script" in definition_content:
        paths["script"].write_text(definition_content["script"], encoding="utf-8")
        enforce_file_permissions(str(paths["script"]), label="Warm-up startup script")
    paths["definition"].write_text(definition_content["definition"], encoding="utf-8")
    enforce_file_permissions(str(paths["definition"]), label="Warm-up startup definition")

    try:
        if sys.platform == "win32":
            subprocess.run(
                [
                    "schtasks",
                    "/Create",
                    "/TN",
                    "StandupBotWarmUp",
                    "/XML",
                    str(paths["definition"]),
                    "/F",
                ],
                check=True,
            )
        elif sys.platform == "darwin":
            subprocess.run(["launchctl", "load", str(paths["definition"])], check=True)
        else:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            subprocess.run(
                ["systemctl", "--user", "enable", "--now", "standupbot-warmup.service"], check=True
            )
        console.print("[green]✅ Startup warm-up installed.[/green]")
    except Exception as exc:
        console.print(
            f"[yellow]⚠️  Startup files were written, but automatic registration failed: {sanitize_error_message(exc)}[/yellow]"
        )


def _run_maintenance() -> None:
    """Run lightweight maintenance tasks and print a summary."""
    from standup.history import auto_cleanup_if_needed
    from standup.rate_limiter import load_usage, save_usage

    cleanup_result = auto_cleanup_if_needed()
    usage = load_usage()
    save_usage(usage)
    rotated = rotate_logs_if_needed()

    table = Table(title="Standup Maintenance")
    table.add_column("Task", style="bold cyan")
    table.add_column("Result")
    table.add_row(
        "History cleanup",
        "No cleanup needed" if cleanup_result is None else f"{cleanup_result} row(s) deleted",
    )
    table.add_row("Usage prune", "Completed")
    table.add_row("Log rotation", "Rotated" if rotated else "No rotation needed")
    console.print(table)


def _uninstall_startup() -> None:
    """Uninstall startup warm-up artifacts."""
    paths = _startup_paths()
    console.print("[bold]Startup uninstall preview[/bold]")
    for key in ("script", "definition"):
        if key in paths:
            console.print(f"[cyan]{key}[/cyan] -> {paths[key]}")

    if not _confirm_action("Remove startup warm-up files?"):
        console.print("[yellow]Startup uninstall cancelled.[/yellow]")
        return

    try:
        if sys.platform == "win32":
            subprocess.run(["schtasks", "/Delete", "/TN", "StandupBotWarmUp", "/F"], check=False)
        elif sys.platform == "darwin":
            subprocess.run(["launchctl", "unload", str(paths["definition"])], check=False)
        else:
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", "standupbot-warmup.service"],
                check=False,
            )
    except Exception:  # noqa: S110
        pass

    for key in ("script", "definition"):
        artifact = paths.get(key)
        if artifact and artifact.exists():
            artifact.unlink()
    console.print("[green]✅ Startup warm-up files removed.[/green]")


def run_setup_wizard() -> None:
    """Interactive configuration wizard."""
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
            "groq": {"api_key": "", "model": "llama-3.1-8b-instant"},
        },
        "rate_limit": {"cooldown_minutes": 30, "max_calls_per_day": 10, "enabled": True},
        "quality": {"enabled": True, "min_score": 0, "show_breakdown": False},
        "noise_filter_enabled": True,
        "template": "default",
        "custom_templates": {},
        "auto_warm_up": False,
    }

    console.print("\n[bold]Which LLM provider do you want to use?[/bold]")
    console.print("  1. Ollama (local, free, private - recommended)")
    console.print("  2. Groq (free cloud, needs free API key)")
    while True:
        choice = _prompt("Enter choice", "1")
        if choice in ("1", "2"):
            break
        console.print("[red]❌ Invalid choice. Enter 1 or 2.[/red]")

    if choice == "2":
        config["provider"]["name"] = "groq"
        console.print("\n[bold cyan]Get your free API key at:[/bold cyan] https://console.groq.com")
        console.print("\n[bold]Suggested Groq models:[/bold]")
        for index, model_name in enumerate(KNOWN_GROQ_MODELS[:3], 1):
            console.print(f"  {index}. {model_name}")
        while True:
            model_choice = _prompt("Model", "llama-3.1-8b-instant")
            ok, message = validate_setup_input("groq_model", model_choice)
            if ok:
                config["provider"]["groq"]["model"] = model_choice
                break
            console.print(f"[red]❌ {message}[/red]")

        api_key = _prompt("Groq API key (leave blank to use env var)", "")
        ok, message = validate_setup_input("groq_api_key", api_key)
        if ok and api_key:
            console.print(
                "[yellow]⚠️  Storing API key in config file. Consider using GROQ_API_KEY env var instead.[/yellow]"
            )
            config["provider"]["groq"]["api_key"] = api_key
        elif not ok:
            console.print(f"[yellow]⚠️  {message} Leaving API key blank.[/yellow]")
    else:
        config["provider"]["name"] = "ollama"
        while True:
            base_url = _prompt("Ollama base URL", "http://localhost:11434")
            ok, message = validate_setup_input("ollama_base_url", base_url)
            if ok:
                config["provider"]["ollama"]["base_url"] = base_url
                break
            console.print(f"[red]❌ {message}[/red]")

        while True:
            model = _prompt("Ollama model", "llama3")
            ok, message = validate_setup_input("ollama_model", model)
            if ok:
                config["provider"]["ollama"]["model"] = model
                break
            console.print(f"[red]❌ {message}[/red]")

        from standup.llm.ollama_provider import OllamaProvider

        provider = OllamaProvider(config)
        if provider.is_available():
            console.print("[green]✅ Ollama is running and the model is available.[/green]")
        else:
            model_name = config["provider"]["ollama"]["model"]
            console.print(
                f"[yellow]⚠️  Ollama not detected. Install from https://ollama.com, "
                f"then run: ollama pull {model_name}[/yellow]"
            )

    console.print("\n[bold]Repo paths[/bold] (enter one per line, blank to finish):")
    repos: list[str] = []
    while True:
        raw_path = _prompt(f"  Repo path {len(repos) + 1}", "")
        if not raw_path:
            break
        repo_path = sanitize_path(raw_path)
        ok, message = validate_setup_input("repo_path", repo_path)
        if ok:
            repos.append(repo_path)
            console.print(f"  [green]✅ Added: {repo_path}[/green]")
        else:
            console.print(f"  [red]❌ {message}[/red]")
    config["repos"] = repos

    while True:
        email = sanitize_string(_prompt("Author git email (leave blank for all commits)", ""))
        ok, message = validate_setup_input("author_email", email)
        if ok:
            config["author_email"] = email
            break
        console.print(f"[red]❌ {message}[/red]")

    while True:
        hours = _prompt("Hours to look back", "24")
        ok, message = validate_setup_input("hours_lookback", hours)
        if ok:
            config["hours_lookback"] = int(hours)
            break
        console.print(f"[red]❌ {message}[/red]")

    while True:
        tone = _prompt("Tone (casual/formal)", "casual")
        ok, message = validate_setup_input("tone", tone)
        if ok:
            config["tone"] = tone.lower().strip()
            break
        console.print(f"[red]❌ {message}[/red]")

    webhook = sanitize_string(_prompt("Slack webhook URL (optional)", ""))
    ok, message = validate_setup_input("slack_webhook_url", webhook)
    if ok:
        config["slack_webhook_url"] = webhook
    else:
        console.print(f"[yellow]⚠️  {message} Leaving Slack webhook blank.[/yellow]")

    while True:
        cooldown = _prompt("Cooldown minutes between calls", "30")
        ok, message = validate_setup_input("cooldown_minutes", cooldown)
        if ok:
            config["rate_limit"]["cooldown_minutes"] = int(cooldown)
            break
        console.print(f"[red]❌ {message}[/red]")

    while True:
        max_calls = _prompt("Max calls per day", "10")
        ok, message = validate_setup_input("max_calls_per_day", max_calls)
        if ok:
            config["rate_limit"]["max_calls_per_day"] = int(max_calls)
            break
        console.print(f"[red]❌ {message}[/red]")

    while True:
        template_name = _prompt("Template (default/slack/minimal/detailed/jira)", "default")
        ok, message = validate_setup_input("template", template_name)
        if ok:
            config["template"] = template_name
            break
        console.print(f"[red]❌ {message}[/red]")

    config["noise_filter_enabled"] = _prompt_bool("noise_filter_enabled", True)
    config["quality"]["enabled"] = _prompt_bool("quality_enabled", True)

    while True:
        min_score = _prompt("quality_min_score", "0")
        ok, message = validate_setup_input("quality_min_score", min_score)
        if ok:
            config["quality"]["min_score"] = int(min_score)
            break
        console.print(f"[red]❌ {message}[/red]")

    config["quality"]["show_breakdown"] = _prompt_bool("quality_show_breakdown", False)
    config["auto_warm_up"] = _prompt_bool("auto_warm_up", False)

    save_config(config)
    console.print("\n[bold green]Setup complete! Run: standup[/bold green]")


def main() -> None:  # noqa: C901
    """CLI entry point."""
    from standup.validator import (
        validate_cli_args,
        validate_hours_arg,
        validate_positive_int_arg,
        validate_provider_arg,
    )

    parser = argparse.ArgumentParser(
        prog="standup",
        description="StandupBot - Generate daily standups from your git history.",
    )

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("doctor", help="Run security and health checks")
    subparsers.add_parser("usage", help="Show API usage stats")
    subparsers.add_parser("models", help="List available local Ollama models")
    subparsers.add_parser("templates", help="List available standup templates")
    logs_parser = subparsers.add_parser("logs", help="Show or clear structured logs")
    logs_parser.add_argument(
        "--tail",
        type=lambda value: validate_positive_int_arg("--tail", value, 1, 200),
        default=20,
        help="Number of log entries to show",
    )
    logs_parser.add_argument("--clear", action="store_true", help="Clear the log file")

    history_parser = subparsers.add_parser("history", help="Show or clear standup history")
    history_parser.add_argument(
        "--limit",
        type=lambda value: validate_positive_int_arg("--limit", value, 1, 100),
        default=10,
        help="Number of history entries to show",
    )
    history_parser.add_argument("--clear", action="store_true", help="Clear history entries")
    history_parser.add_argument(
        "--days",
        type=lambda value: validate_positive_int_arg("--days", value, 1, 3650),
        help="Only clear entries older than this many days",
    )

    warmup_parser = subparsers.add_parser("warm-up", help="Pre-load the configured model")
    warmup_parser.add_argument(
        "--install-startup",
        action="store_true",
        help="Install warm-up to run automatically at login",
    )
    warmup_parser.add_argument(
        "--uninstall-startup", action="store_true", help="Remove startup warm-up integration"
    )

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
    parser.add_argument("--no-cache", action="store_true", help="Bypass standup history cache")
    parser.add_argument("--no-filter", action="store_true", help="Disable commit noise filtering")
    parser.add_argument("--template", metavar="NAME", help="Template override for this run")
    parser.add_argument("--verbose", action="store_true", help="Show quality score breakdown")
    parser.add_argument(
        "--maintenance", action="store_true", help="Run safe local maintenance tasks"
    )

    args = parser.parse_args()

    if args.version:
        console.print(f"StandupBot v{__version__}")
        return

    if args.changelog:
        changelog_path = Path(__file__).parent.parent / "CHANGELOG.md"
        if changelog_path.exists():
            console.print(changelog_path.read_text(encoding="utf-8"))
        else:
            console.print("[yellow]CHANGELOG.md not found.[/yellow]")
        return

    if args.setup:
        run_setup_wizard()
        return

    from standup.config import load_config

    config = load_config()
    log_event(
        "app_start",
        version=__version__,
        provider=config.get("provider", {}).get("name", "unknown"),
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    )

    errors = validate_cli_args(args, config)
    if errors:
        for error in errors:
            console.print(f"[red]❌ {error}[/red]")
        sys.exit(1)

    if args.command == "doctor":
        from standup.security import run_doctor

        run_doctor()
        return

    if args.command == "usage":
        from standup.rate_limiter import get_usage_report

        console.print(get_usage_report())
        return

    if args.command == "logs":
        if args.clear:
            if not _confirm_action("Clear structured logs?"):
                console.print("[yellow]Log clear cancelled.[/yellow]")
                return
            if clear_logs():
                console.print("[green]✅ Log file cleared.[/green]")
            else:
                console.print("[yellow]⚠️  Could not clear log file.[/yellow]")
            return

        entries = read_log_entries(args.tail)
        if not entries:
            console.print("[yellow]No structured logs found yet.[/yellow]")
            return

        table = Table(title="Standup Logs")
        table.add_column("Time", style="bold cyan")
        table.add_column("Event")
        table.add_column("Detail")
        for entry in entries:
            detail_parts = []
            for key in sorted(entry.keys()):
                if key in ("ts", "event", "level"):
                    continue
                detail_parts.append(f"{key}={entry[key]}")
            table.add_row(
                str(entry.get("ts", ""))[11:19],
                str(entry.get("event", "")),
                ", ".join(detail_parts)[:120],
            )
        console.print(table)
        return

    if args.command == "models":
        from standup.llm.ollama_provider import OllamaProvider

        provider = OllamaProvider(config)
        models = provider.list_local_models()
        if models:
            console.print("[bold]Local Ollama models:[/bold]")
            for model_name in models:
                console.print(f"  • {model_name}")
        else:
            console.print(
                "[yellow]No models found. Is Ollama running?[/yellow]\n  Start it with: ollama serve\n  Pull a model:  ollama pull llama3"
            )
        return

    if args.command == "templates":
        from standup.templates import list_templates

        table = Table(title="Standup Templates")
        table.add_column("Name", style="bold cyan")
        table.add_column("Type")
        available = list_templates(config.get("custom_templates", {}))
        for name in available:
            template_type = "Custom" if name in config.get("custom_templates", {}) else "Built-in"
            table.add_row(name, template_type)
        console.print(table)
        return

    if args.command == "history":
        from standup.history import clear_history, get_history

        if args.clear:
            description = (
                f"entries older than {args.days} days" if args.days else "all history entries"
            )
            if not _confirm_action(f"Delete {description}?"):
                console.print("[yellow]History clear cancelled.[/yellow]")
                return
            deleted = clear_history(args.days)
            noun = "entry" if deleted == 1 else "entries"
            console.print(f"[green]✅ Deleted {deleted} history {noun}.[/green]")
            return

        entries = get_history(args.limit)
        if not entries:
            console.print("[yellow]No standup history found yet.[/yellow]")
            return

        table = Table(title="Standup History")
        table.add_column("Date", style="bold cyan")
        table.add_column("Repos")
        table.add_column("Provider")
        table.add_column("Preview")
        for entry in entries:
            preview = str(entry.get("standup_text", "")).replace("\n", " ")[:80]
            _repos = entry.get("repos")
            repos = ", ".join(str(r) for r in (_repos if isinstance(_repos, list) else []))
            table.add_row(
                str(entry.get("created_at", ""))[:16],
                repos,
                str(entry.get("provider", "")),
                preview,
            )
        console.print(table)
        return

    if args.command == "warm-up":
        from standup.llm.factory import get_provider_with_fallback
        from standup.warmup import warm_up_provider

        if args.install_startup:
            _install_startup(config)
            return
        if args.uninstall_startup:
            _uninstall_startup()
            return

        provider = get_provider_with_fallback(config, override=args.provider)  # type: ignore[assignment]
        success = warm_up_provider(provider, verbose=True)
        if not success:
            sys.exit(1)
        return

    if args.maintenance:
        _run_maintenance()
        return

    hours = 168 if args.week else args.hours or config.get("hours_lookback", 24)
    started_at = time.perf_counter()

    from standup.rate_limiter import enforce_rate_limit, load_usage, record_call, save_usage

    enforce_rate_limit(config, force=args.force)

    from standup.llm.factory import get_provider_with_fallback

    provider = get_provider_with_fallback(config, override=args.provider)  # type: ignore[assignment]
    provider_slug = _get_provider_slug(provider)
    console.print(f"[dim]Using {provider.get_provider_name()}...[/dim]")

    if _should_auto_warm_up(provider, config):
        from standup.warmup import warm_up_provider

        warm_up_provider(provider, verbose=False)

    from standup.git_reader import get_recent_commits

    repos = config.get("repos", [])
    if not repos:
        console.print("[yellow]⚠️  No repos configured. Run: standup --setup[/yellow]")
        sys.exit(1)

    author_email = config.get("author_email", "")
    all_commits = []
    for repo_path in repos:
        all_commits.extend(get_recent_commits(repo_path, hours, author_email))

    if not all_commits:
        console.print(
            f"[yellow]No commits found in the last {hours} hours. Did you take a day off?[/yellow]"
        )
        return

    from standup.classifier import annotate_commits, filter_and_classify_commits

    filtering_enabled = config.get("noise_filter_enabled", True) and not args.no_filter
    processed_commits = (
        filter_and_classify_commits(all_commits)
        if filtering_enabled
        else annotate_commits(all_commits)
    )
    if filtering_enabled and not processed_commits:
        console.print(
            "[yellow]⚠️  All commits matched the default noise filter. Falling back to unfiltered commits for this run.[/yellow]"
        )
        processed_commits = annotate_commits(all_commits)

    from standup.formatter import build_standup_prompt, format_commits_for_prompt

    formatted = format_commits_for_prompt(processed_commits)
    if args.raw:
        console.print(Rule("Raw Git Data"))
        console.print(formatted)
        console.print(Rule())

    template_name = args.template or config.get("template", "default")
    tone = config.get("tone", "casual")

    from standup.history import compute_commit_fingerprint, find_cached_standup_entry, save_standup

    fingerprint = compute_commit_fingerprint(processed_commits)
    cached_entry = (
        None if args.no_cache else find_cached_standup_entry(fingerprint, tone, provider_slug)
    )

    raw_standup_text = ""
    quality: dict[str, object] = {"score": 0, "issues": [], "strengths": []}
    used_cache = False

    if cached_entry:
        raw_standup_text = str(cached_entry.get("standup_text", ""))
        quality["score"] = int(cached_entry.get("quality_score") or 0)  # type: ignore[call-overload]
        used_cache = True
        cache_time = str(cached_entry.get("created_at", ""))[11:16]
        console.print(f"[dim]⚡ Using cached standup from {cache_time}[/dim]")
    else:
        prompt = build_standup_prompt(formatted, tone)
        from standup.llm.base import LLMProviderError
        from standup.quality import generate_with_quality_retry, score_standup

        try:
            if config.get("quality", {}).get("enabled", True):
                generation = generate_with_quality_retry(
                    prompt,
                    provider,
                    tone,
                    int(config.get("quality", {}).get("min_score") or 0),  # type: ignore[call-overload]
                    max_retries=2,
                )
                raw_standup_text = str(generation.get("standup_text", ""))
                quality = generation.get("quality", quality)  # type: ignore[assignment]
            else:
                raw_standup_text = provider.generate_standup(prompt, tone)
                quality = score_standup(raw_standup_text, provider)
        except LLMProviderError as exc:
            console.print(f"[red]❌ {sanitize_error_message(exc)}[/red]")
            sys.exit(1)

        usage = load_usage()
        usage = record_call(usage)
        save_usage(usage)
        save_standup(
            fingerprint,
            provider_slug,
            _get_provider_model(provider),
            tone,
            raw_standup_text,
            _get_repo_names(processed_commits),
            hours,
            quality_score=int(quality.get("score") or 0),  # type: ignore[call-overload]
        )

    final_output = _render_final_output(
        raw_standup_text, template_name, config, processed_commits, provider_slug
    )

    console.print(Rule("Your Standup"))
    console.print(final_output)
    console.print(Rule())

    from standup.quality import format_score_badge

    if config.get("quality", {}).get("enabled", True) or int(quality.get("score") or 0) > 0:  # type: ignore[call-overload]
        score = int(quality.get("score") or 0)  # type: ignore[call-overload]
        console.print(f"Quality Score: {format_score_badge(score)} {score}/100")
        if args.verbose or config.get("quality", {}).get("show_breakdown", False):
            _show_quality_breakdown(quality)

    if args.copy:
        try:
            import pyperclip

            pyperclip.copy(final_output)
            console.print("[green]✅ Copied to clipboard![/green]")
        except Exception as exc:
            console.print(
                f"[yellow]⚠️  Clipboard copy failed: {sanitize_error_message(exc)}[/yellow]"
            )

    if args.slack:
        webhook = config.get("slack_webhook_url", "")
        if webhook:
            _post_to_slack(webhook, final_output)
        else:
            console.print("[red]❌ No Slack webhook configured.[/red]")

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    log_event(
        "standup_generated",
        provider=provider_slug,
        model=_get_provider_model(provider),
        repos=_get_repo_names(processed_commits),
        commit_count=len(processed_commits),
        cached=used_cache,
        quality_score=int(quality.get("score") or 0),  # type: ignore[call-overload]
        duration_ms=duration_ms,
    )


if __name__ == "__main__":
    main()