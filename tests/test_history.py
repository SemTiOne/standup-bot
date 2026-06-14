"""Tests for standup/history.py."""

import importlib
import sqlite3
from pathlib import Path

from standup import history as history_module
from standup.validator import MAX_HISTORY_LIMIT


def _patch_db(monkeypatch, tmp_path):
    db_path = tmp_path / ".standup_history.db"
    importlib.reload(history_module)
    monkeypatch.setattr(history_module, "get_db_path", lambda: str(db_path))
    return db_path


def _insert_rows_directly(db_path, count: int) -> None:
    """Bypass save_standup (and _enforce_max_rows) to set up over-ceiling state."""
    with history_module._get_connection(str(db_path)) as conn:
        for i in range(count):
            # Use ascending timestamps so the oldest-first DELETE is deterministic.
            ts = f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}"
            conn.execute(
                "INSERT INTO standups "
                "(created_at, commit_hash, provider, model, tone, "
                " standup_text, repos, hours_lookback, quality_score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, str(i), "ollama", "llama3", "casual", "text", "[]", 24, 0),
            )


def test_get_db_path_default_name():
    assert history_module.get_db_path().endswith(".standup_history.db")


def test_init_db_creates_database_file(tmp_path, monkeypatch):
    db_path = _patch_db(monkeypatch, tmp_path)
    history_module.init_db()
    assert db_path.exists()


def test_compute_commit_fingerprint_is_order_independent():
    first = history_module.compute_commit_fingerprint([{"hash": "b"}, {"hash": "a"}])
    second = history_module.compute_commit_fingerprint([{"hash": "a"}, {"hash": "b"}])
    assert first == second


def test_compute_commit_fingerprint_empty_list_is_stable():
    assert history_module.compute_commit_fingerprint(
        []
    ) == history_module.compute_commit_fingerprint([])


def test_save_and_get_history_round_trip(tmp_path, monkeypatch):
    _patch_db(monkeypatch, tmp_path)
    history_module.save_standup(
        "abc", "ollama", "llama3", "casual", "text", ["app"], 24, quality_score=88
    )
    history = history_module.get_history()
    assert len(history) == 1
    assert history[0]["provider"] == "ollama"
    assert history[0]["quality_score"] == 88


def test_find_cached_standup_hit_same_day(tmp_path, monkeypatch):
    _patch_db(monkeypatch, tmp_path)
    history_module.save_standup("abc", "ollama", "llama3", "casual", "cached text", ["app"], 24)
    assert history_module.find_cached_standup("abc", "casual", "ollama") == "cached text"


def test_find_cached_standup_miss_for_tone(tmp_path, monkeypatch):
    _patch_db(monkeypatch, tmp_path)
    history_module.save_standup("abc", "ollama", "llama3", "casual", "cached text", ["app"], 24)
    assert history_module.find_cached_standup("abc", "formal", "ollama") is None


def test_get_history_respects_limit(tmp_path, monkeypatch):
    _patch_db(monkeypatch, tmp_path)
    history_module.save_standup("a", "ollama", "llama3", "casual", "one", ["app"], 24)
    history_module.save_standup("b", "ollama", "llama3", "casual", "two", ["app"], 24)
    assert len(history_module.get_history(limit=1)) == 1


def test_clear_history_deletes_all_rows(tmp_path, monkeypatch):
    _patch_db(monkeypatch, tmp_path)
    history_module.save_standup("a", "ollama", "llama3", "casual", "one", ["app"], 24)
    history_module.save_standup("b", "ollama", "llama3", "casual", "two", ["app"], 24)
    assert history_module.clear_history() == 2
    assert history_module.get_history() == []


def test_clear_history_older_than_days_only_removes_old_rows(tmp_path, monkeypatch):
    db_path = _patch_db(monkeypatch, tmp_path)
    history_module.save_standup("a", "ollama", "llama3", "casual", "old", ["app"], 24)
    history_module.save_standup("b", "ollama", "llama3", "casual", "new", ["app"], 24)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE standups SET created_at = ? WHERE commit_hash = ?",
            ("2020-01-01T00:00:00", "a"),
        )
        conn.commit()
    deleted = history_module.clear_history(older_than_days=30)
    assert deleted == 1
    history = history_module.get_history(limit=10)
    assert len(history) == 1
    assert history[0]["standup_text"] == "new"


def test_get_history_parses_repos_json(tmp_path, monkeypatch):
    _patch_db(monkeypatch, tmp_path)
    history_module.save_standup("abc", "groq", "mixtral", "formal", "text", ["api", "web"], 48)
    history = history_module.get_history()
    assert history[0]["repos"] == ["api", "web"]


def test_run_migrations_is_idempotent(tmp_path, monkeypatch):
    db_path = _patch_db(monkeypatch, tmp_path)
    history_module.init_db()
    with history_module._get_connection(str(db_path)) as conn:
        history_module.run_migrations(conn)
        first = history_module.get_current_schema_version(conn)
        history_module.run_migrations(conn)
        second = history_module.get_current_schema_version(conn)
    assert first == second == max(version for version, _, _ in history_module._MIGRATIONS)


def test_run_migrations_handles_corrupted_schema_versions(tmp_path, monkeypatch):
    db_path = _patch_db(monkeypatch, tmp_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE schema_versions (broken TEXT)")
        conn.commit()
    history_module.init_db()
    with history_module._get_connection(str(db_path)) as conn:
        assert history_module.get_current_schema_version(conn) == max(
            version for version, _, _ in history_module._MIGRATIONS
        )


def test_sanitize_for_storage_truncates_at_limit():
    value = "x" * (history_module._MAX_STANDUP_LENGTH + 50)
    assert len(history_module._sanitize_for_storage(value)) == history_module._MAX_STANDUP_LENGTH


def test_sanitize_for_storage_removes_null_bytes():
    assert "\x00" not in history_module._sanitize_for_storage("a\x00b")


def test_get_connection_sets_wal_and_busy_timeout(tmp_path, monkeypatch):
    db_path = _patch_db(monkeypatch, tmp_path)
    history_module.init_db()
    with history_module._get_connection(str(db_path)) as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert str(journal_mode).lower() == "wal"
    assert int(busy_timeout) == 5000


def test_db_created_with_correct_permissions_on_unix(tmp_path, monkeypatch):
    db_path = _patch_db(monkeypatch, tmp_path)
    history_module.init_db()
    if Path("/").exists() and str(Path(db_path)).startswith("/"):
        assert oct(db_path.stat().st_mode & 0o777) == "0o600"


def test_get_history_clamps_large_limit(tmp_path, monkeypatch):
    _patch_db(monkeypatch, tmp_path)
    for index in range(MAX_HISTORY_LIMIT + 10):
        history_module.save_standup(str(index), "ollama", "llama3", "casual", "text", ["app"], 24)
    assert len(history_module.get_history(limit=9999)) == MAX_HISTORY_LIMIT


def test_get_db_size_bytes_returns_zero_for_missing(tmp_path, monkeypatch):
    db_path = _patch_db(monkeypatch, tmp_path)
    assert history_module.get_db_size_bytes(str(db_path)) == 0


def test_get_row_count_returns_zero_for_empty_db(tmp_path, monkeypatch):
    db_path = _patch_db(monkeypatch, tmp_path)
    history_module.init_db()
    assert history_module.get_row_count(str(db_path)) == 0


# ---------------------------------------------------------------------------
# _enforce_max_rows
# ---------------------------------------------------------------------------


def test_enforce_max_rows_returns_none_when_under_ceiling(tmp_path, monkeypatch):
    db_path = _patch_db(monkeypatch, tmp_path)
    history_module.init_db()
    _insert_rows_directly(db_path, 10)
    assert history_module._enforce_max_rows(str(db_path)) is None
    assert history_module.get_row_count(str(db_path)) == 10


def test_enforce_max_rows_trims_to_ceiling(tmp_path, monkeypatch):
    db_path = _patch_db(monkeypatch, tmp_path)
    history_module.init_db()
    excess = 5
    total = history_module._MAX_HISTORY_ROWS + excess
    _insert_rows_directly(db_path, total)
    deleted = history_module._enforce_max_rows(str(db_path))
    assert deleted == excess
    assert history_module.get_row_count(str(db_path)) == history_module._MAX_HISTORY_ROWS


def test_enforce_max_rows_deletes_oldest_rows(tmp_path, monkeypatch):
    """The oldest rows (by created_at ASC) should be removed first."""
    db_path = _patch_db(monkeypatch, tmp_path)
    history_module.init_db()
    total = history_module._MAX_HISTORY_ROWS + 3
    _insert_rows_directly(db_path, total)
    # The helper inserts ascending timestamps; row 0 is oldest.
    # After trimming, commit_hash "0", "1", "2" should be gone.
    history_module._enforce_max_rows(str(db_path))
    with history_module._get_connection(str(db_path)) as conn:
        hashes = {
            row[0]
            for row in conn.execute("SELECT commit_hash FROM standups").fetchall()
        }
    assert "0" not in hashes
    assert "1" not in hashes
    assert "2" not in hashes


# ---------------------------------------------------------------------------
# auto_cleanup_if_needed
# ---------------------------------------------------------------------------


def test_auto_cleanup_returns_none_when_within_ceiling(tmp_path, monkeypatch):
    """With a small DB, auto_cleanup_if_needed should be a no-op."""
    db_path = _patch_db(monkeypatch, tmp_path)
    history_module.init_db()
    _insert_rows_directly(db_path, 5)
    assert history_module.auto_cleanup_if_needed(str(db_path)) is None
    assert history_module.get_row_count(str(db_path)) == 5


def test_auto_cleanup_trims_rows_above_ceiling(tmp_path, monkeypatch):
    """Rows inserted directly above the ceiling should be pruned."""
    db_path = _patch_db(monkeypatch, tmp_path)
    history_module.init_db()
    excess = 10
    total = history_module._MAX_HISTORY_ROWS + excess
    _insert_rows_directly(db_path, total)

    assert history_module.get_row_count(str(db_path)) == total  # confirm setup

    deleted = history_module.auto_cleanup_if_needed(str(db_path))

    assert deleted == excess
    assert history_module.get_row_count(str(db_path)) == history_module._MAX_HISTORY_ROWS


def test_auto_cleanup_logs_maintenance_event(tmp_path, monkeypatch):
    """Successful cleanup should emit a db_maintenance log event."""
    db_path = _patch_db(monkeypatch, tmp_path)
    history_module.init_db()
    _insert_rows_directly(db_path, history_module._MAX_HISTORY_ROWS + 2)

    events = []
    monkeypatch.setattr(
        history_module,
        "log_event",
        lambda event, **kwargs: events.append(event),
    )

    history_module.auto_cleanup_if_needed(str(db_path))
    assert "db_maintenance" in events


def test_auto_cleanup_at_exact_ceiling_is_noop(tmp_path, monkeypatch):
    """A DB at exactly _MAX_HISTORY_ROWS should not trigger any deletion."""
    db_path = _patch_db(monkeypatch, tmp_path)
    history_module.init_db()
    _insert_rows_directly(db_path, history_module._MAX_HISTORY_ROWS)
    assert history_module.auto_cleanup_if_needed(str(db_path)) is None


def test_history_source_contains_no_fstring_sql():
    source = Path("standup/history.py").read_text(encoding="utf-8")
    assert 'f"""' not in source
    assert "f'SELECT" not in source
