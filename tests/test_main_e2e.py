"""Happy-path E2E test for standup generation with a mocked Groq provider."""

import argparse
from unittest.mock import MagicMock

import standup.main as main_mod

_STANDUP_TEXT = "**Yesterday:** built app\n**Today:** polish\n**Blockers:** None"


class _GroqStub:
    model = "llama-3.1-8b-instant"

    def get_provider_name(self) -> str:
        return "Groq (llama-3.1-8b-instant)"

    def generate_standup(self, prompt: str, tone: str) -> str:
        assert prompt.strip()
        assert tone in ("casual", "formal")
        return _STANDUP_TEXT


def _make_e2e_repo(tmp_path):
    import git as git_module

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    repo = git_module.Repo.init(str(repo_dir))
    with repo.config_writer() as cw:
        cw.set_value("user", "email", "a@b.com")
        cw.set_value("user", "name", "Test")
    (repo_dir / "app.py").write_text("print('hi')\n")
    repo.index.add(["app.py"])
    repo.index.commit("feat: add app")
    (repo_dir / "app.py").write_text("print('hi')\nprint('fix')\n")
    repo.index.add(["app.py"])
    repo.index.commit("fix: handle edge case")
    return str(repo_dir)


def _e2e_config(repo_path: str) -> dict:
    return {
        "repos": [repo_path],
        "author_email": "",
        "hours_lookback": 24,
        "tone": "casual",
        "slack_webhook_url": "",
        "provider": {
            "name": "groq",
            "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
            "groq": {"api_key": "", "model": "llama-3.1-8b-instant"},
        },
        "rate_limit": {"cooldown_minutes": 30, "max_calls_per_day": 10, "enabled": True},
        "quality": {"enabled": False, "min_score": 0, "show_breakdown": False},
        "noise_filter_enabled": True,
        "template": "default",
        "custom_templates": {},
        "auto_warm_up": False,
    }


def _e2e_args() -> argparse.Namespace:
    return argparse.Namespace(
        week=False,
        hours=24,
        no_filter=False,
        raw=False,
        template="default",
        no_cache=False,
        copy=False,
        slack=False,
        force=False,
        verbose=False,
        provider=None,
    )


def test_run_generation_happy_groq(tmp_path, monkeypatch, capsys):
    repo_path = _make_e2e_repo(tmp_path)
    config = _e2e_config(repo_path)
    args = _e2e_args()

    monkeypatch.setattr(
        "standup.llm.factory.get_provider_with_fallback",
        lambda cfg, override=None: _GroqStub(),
    )
    monkeypatch.setattr("standup.history.find_cached_standup_entry", lambda *a, **kw: None)
    saved = {}
    monkeypatch.setattr(
        "standup.history.save_standup",
        lambda fingerprint, provider, model, tone, text, repos, hours, quality_score=0: (
            saved.update(
                {
                    "fingerprint": fingerprint,
                    "provider": provider,
                    "model": model,
                    "tone": tone,
                    "text": text,
                    "repos": repos,
                    "hours": hours,
                    "quality_score": quality_score,
                }
            )
        ),
    )
    rate_limit_mock = MagicMock()
    monkeypatch.setattr("standup.rate_limiter.enforce_rate_limit", rate_limit_mock)
    monkeypatch.setattr("standup.rate_limiter.load_usage", lambda: {})
    monkeypatch.setattr("standup.rate_limiter.record_call", lambda usage: usage)
    monkeypatch.setattr("standup.rate_limiter.save_usage", lambda usage: None)
    monkeypatch.setattr("standup.rate_limiter.USAGE_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setattr("standup.logger.get_log_path", lambda: str(tmp_path / "standup.log"))

    main_mod._run_generation(args, config)

    rate_limit_mock.assert_called_once()
    assert saved["repos"] == ["repo"]
    assert saved["hours"] == 24
    assert saved["tone"] == "casual"
    assert "Yesterday" in saved["text"]
    out = capsys.readouterr().out
    assert "Your Standup" in out
