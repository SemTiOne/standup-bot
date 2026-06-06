"""
history.py - Persist standup generations for deduplication and local history.

StandupBot stores only commit fingerprints and bounded standup output in a
local SQLite database. The module applies schema migrations, uses parameterized
queries exclusively, and automatically prunes old history to keep long-term
usage predictable.
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rich.console import Console

from standup.logger import log_event
from standup.security import enforce_file_permissions, sanitize_error_message
from standup.validator import MAX_HISTORY_LIMIT

console = Console()

_DB_NAME = ".standup_history.db"
_MAX_STANDUP_LENGTH = 4000
_MAX_HISTORY_ROWS = 365
_AUTO_CLEANUP_THRESHOLD = 400
_MIGRATIONS: List[Tuple[int, str, str]] = [
    (1, "2026-04-26", "Initial schema: standups table with indexes"),
    (2, "2026-04-26", "Add quality_score column to standups"),
]


def get_db_path() -> str:
    """
    Return the absolute path to the standup history database.

    Args:
        None.

    Returns:
        Absolute path to ``~/.standup_history.db``.

    Raises:
        None.
    """
    return str(Path.home() / _DB_NAME)


def _get_connection(db_path: str) -> sqlite3.Connection:
    """
    Open a SQLite connection with hardened settings.

    Args:
        db_path: Database path to connect to.

    Returns:
        Configured SQLite connection.

    Raises:
        sqlite3.Error: If SQLite cannot open the database.
    """
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _sanitize_for_storage(text: str) -> str:
    """
    Sanitize LLM output before writing it to the database.

    Args:
        text: Raw standup text.

    Returns:
        Sanitized text safe for SQLite storage.

    Raises:
        None.
    """
    if not isinstance(text, str):
        text = str(text)
    sanitized = text.replace("\x00", "")
    sanitized = sanitized.replace("\r\n", "\n").replace("\r", "\n")
    return sanitized[:_MAX_STANDUP_LENGTH]


def _row_to_entry(row: sqlite3.Row) -> Dict[str, object]:
    repos: List[str]
    try:
        parsed = json.loads(row["repos"])
        repos = parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        repos = []
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "commit_hash": row["commit_hash"],
        "provider": row["provider"],
        "model": row["model"],
        "tone": row["tone"],
        "standup_text": row["standup_text"],
        "repos": repos,
        "hours_lookback": row["hours_lookback"],
        "quality_score": row["quality_score"],
    }


def get_current_schema_version(conn: sqlite3.Connection) -> int:
    """
    Return the current schema version recorded in the database.

    Args:
        conn: Open SQLite connection.

    Returns:
        Latest applied schema version, or ``0`` if unavailable.

    Raises:
        None.
    """
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = ? AND name = ?",
            ("table", "schema_versions"),
        ).fetchone()
        if not table:
            return 0
        row = conn.execute("SELECT MAX(version) AS version FROM schema_versions").fetchone()
        if not row:
            return 0
        value = row["version"] if isinstance(row, sqlite3.Row) else row[0]
        return int(value or 0)
    except (sqlite3.Error, TypeError, ValueError):
        return 0


def _ensure_schema_versions_table(conn: sqlite3.Connection) -> None:
    """
    Ensure the schema version tracking table exists.

    Args:
        conn: Open SQLite connection.

    Returns:
        None.

    Raises:
        sqlite3.Error: If SQLite rejects the schema update.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_versions (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT NOT NULL
        )
        """
    )


def _apply_migration(conn: sqlite3.Connection, version: int, description: str) -> None:
    """
    Apply a single migration inside a transaction.

    Args:
        conn: Open SQLite connection.
        version: Migration version number.
        description: Human-readable migration description.

    Returns:
        None.

    Raises:
        sqlite3.Error: If a migration statement fails.
    """
    with conn:
        if version == 1:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS standups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    commit_hash TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    tone TEXT NOT NULL,
                    standup_text TEXT NOT NULL,
                    repos TEXT NOT NULL,
                    hours_lookback INTEGER NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_commit_hash ON standups(commit_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON standups(created_at)")
        elif version == 2:
            columns = [
                row["name"]
                for row in conn.execute("PRAGMA table_info(standups)").fetchall()
                if isinstance(row, sqlite3.Row)
            ]
            if "quality_score" not in columns:
                conn.execute(
                    "ALTER TABLE standups ADD COLUMN quality_score INTEGER NOT NULL DEFAULT 0"
                )
        conn.execute(
            """
            INSERT OR REPLACE INTO schema_versions (version, applied_at, description)
            VALUES (?, ?, ?)
            """,
            (version, datetime.now().isoformat(timespec="seconds"), description),
        )


def run_migrations(conn: sqlite3.Connection) -> None:
    """
    Apply all pending migrations in order.

    Args:
        conn: Open SQLite connection.

    Returns:
        None.

    Raises:
        None.
    """

    def _run_pending() -> None:
        current_version = get_current_schema_version(conn)
        for version, _, description in _MIGRATIONS:
            if version > current_version:
                _apply_migration(conn, version, description)

    try:
        _ensure_schema_versions_table(conn)
        _run_pending()
    except sqlite3.Error:
        conn.execute("DROP TABLE IF EXISTS schema_versions")
        _ensure_schema_versions_table(conn)
        _run_pending()


def init_db() -> None:
    """
    Create the history database and apply pending migrations.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    db_path = Path(get_db_path())
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with _get_connection(str(db_path)) as conn:
            run_migrations(conn)
        enforce_file_permissions(str(db_path), label="History database")
    except (sqlite3.Error, OSError) as exc:
        log_event("db_error", operation="init")
        console.print(
            f"[yellow]⚠️  Could not initialize history database: {sanitize_error_message(exc)}[/yellow]"
        )


def compute_commit_fingerprint(commits: List[dict]) -> str:
    """
    Compute a deterministic SHA256 fingerprint from commit hashes.

    Args:
        commits: Commit dictionaries containing ``hash`` keys.

    Returns:
        Hex-encoded SHA256 digest of the sorted commit hashes.

    Raises:
        None.
    """
    hashes = sorted(
        str(commit.get("hash", "")).strip()
        for commit in commits
        if str(commit.get("hash", "")).strip()
    )
    return hashlib.sha256("\n".join(hashes).encode("utf-8")).hexdigest()


def find_cached_standup_entry(
    fingerprint: str, tone: str, provider: str
) -> Optional[Dict[str, object]]:
    """
    Find the most recent cached standup for today matching the fingerprint.

    Args:
        fingerprint: SHA256 commit fingerprint.
        tone: Requested standup tone.
        provider: Provider name used for generation.

    Returns:
        Matching history row as a dict, or ``None`` when no cache hit exists.

    Raises:
        None.
    """
    init_db()
    today = datetime.now().strftime("%Y-%m-%d")
    query = """
        SELECT id, created_at, commit_hash, provider, model, tone, standup_text,
               repos, hours_lookback, quality_score
        FROM standups
        WHERE commit_hash = ?
          AND tone = ?
          AND provider = ?
          AND substr(created_at, 1, 10) = ?
        ORDER BY created_at DESC
        LIMIT 1
    """
    try:
        with _get_connection(get_db_path()) as conn:
            row = conn.execute(query, (fingerprint, tone, provider, today)).fetchone()
        if not row:
            return None
        entry = _row_to_entry(row)
        log_event("cache_hit", fingerprint=fingerprint[:8], tone=tone, provider=provider)
        return entry
    except sqlite3.Error as exc:
        log_event("db_error", operation="find_cached")
        console.print(
            f"[yellow]⚠️  Could not read standup history: {sanitize_error_message(exc)}[/yellow]"
        )
        return None


def find_cached_standup(fingerprint: str, tone: str, provider: str) -> Optional[str]:
    """
    Return cached standup text for today's matching commit fingerprint.

    Args:
        fingerprint: SHA256 commit fingerprint.
        tone: Requested standup tone.
        provider: Provider name used for generation.

    Returns:
        Cached standup text, or ``None`` if no entry matches.

    Raises:
        None.
    """
    entry = find_cached_standup_entry(fingerprint, tone, provider)
    if not entry:
        return None
    return str(entry.get("standup_text", ""))


def _enforce_max_rows(db_path: Optional[str] = None) -> Optional[int]:
    """
    Unconditionally trim the standups table to _MAX_HISTORY_ROWS.

    Called after every save_standup() to guarantee the table never
    exceeds the configured row ceiling regardless of how many consecutive
    saves occur.

    Args:
        db_path: Optional explicit database path.

    Returns:
        Number of rows deleted, or ``None`` when the table is within bounds.

    Raises:
        None.
    """
    path = db_path or get_db_path()
    count = get_row_count(path)
    if count <= _MAX_HISTORY_ROWS:
        return None
    excess = count - _MAX_HISTORY_ROWS
    try:
        with _get_connection(path) as conn:
            conn.execute(
                "DELETE FROM standups WHERE id IN "
                "(SELECT id FROM standups ORDER BY created_at ASC, id ASC LIMIT ?)",
                (excess,),
            )
        return excess
    except sqlite3.Error:
        return None


def save_standup(
    fingerprint: str,
    provider: str,
    model: str,
    tone: str,
    standup_text: str,
    repos: List[str],
    hours: int,
    quality_score: int = 0,
) -> None:
    """
    Save a generated standup to local history.

    Args:
        fingerprint: SHA256 commit fingerprint.
        provider: Provider name used to generate the standup.
        model: Provider model name.
        tone: Requested tone.
        standup_text: Final standup output shown to the user.
        repos: Repository names included in the run.
        hours: Hours lookback used to gather commits.
        quality_score: Optional quality score stored with the entry.

    Returns:
        None.

    Raises:
        None.
    """
    init_db()
    payload = (
        datetime.now().isoformat(timespec="seconds"),
        fingerprint,
        str(provider),
        str(model),
        str(tone),
        _sanitize_for_storage(standup_text),
        json.dumps([str(repo) for repo in repos], ensure_ascii=True),
        int(hours),
        int(quality_score),
    )
    query = """
        INSERT INTO standups (
            created_at, commit_hash, provider, model, tone, standup_text,
            repos, hours_lookback, quality_score
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    try:
        with _get_connection(get_db_path()) as conn:
            conn.execute(query, payload)
        enforce_file_permissions(get_db_path(), label="History database")
        _enforce_max_rows()
    except (sqlite3.Error, OSError, TypeError, ValueError) as exc:
        log_event("db_error", operation="save")
        console.print(
            f"[yellow]⚠️  Could not save standup history: {sanitize_error_message(exc)}[/yellow]"
        )


def get_history(limit: int = 10) -> List[Dict[str, object]]:
    """
    Return recent standup history entries.

    Args:
        limit: Maximum number of entries to return. Defaults to 10.

    Returns:
        List of history row dictionaries ordered newest first.

    Raises:
        None.
    """
    init_db()
    safe_limit = max(1, min(int(limit), MAX_HISTORY_LIMIT))
    query = """
        SELECT id, created_at, commit_hash, provider, model, tone, standup_text,
               repos, hours_lookback, quality_score
        FROM standups
        ORDER BY created_at DESC, id DESC
        LIMIT ?
    """
    try:
        with _get_connection(get_db_path()) as conn:
            rows = conn.execute(query, (safe_limit,)).fetchall()
        return [_row_to_entry(row) for row in rows]
    except (sqlite3.Error, TypeError, ValueError) as exc:
        log_event("db_error", operation="history")
        console.print(
            f"[yellow]⚠️  Could not fetch standup history: {sanitize_error_message(exc)}[/yellow]"
        )
        return []


def clear_history(older_than_days: Optional[int] = None) -> int:
    """
    Delete history rows, optionally only those older than a day threshold.

    Args:
        older_than_days: Optional day threshold for deletion.

    Returns:
        Number of deleted rows.

    Raises:
        None.
    """
    init_db()
    try:
        with _get_connection(get_db_path()) as conn:
            if older_than_days is None:
                cursor = conn.execute("DELETE FROM standups")
            else:
                cutoff = (datetime.now() - timedelta(days=int(older_than_days))).isoformat(
                    timespec="seconds"
                )
                cursor = conn.execute("DELETE FROM standups WHERE created_at < ?", (cutoff,))
        return int(cursor.rowcount or 0)
    except (sqlite3.Error, TypeError, ValueError) as exc:
        log_event("db_error", operation="clear")
        console.print(
            f"[yellow]⚠️  Could not clear standup history: {sanitize_error_message(exc)}[/yellow]"
        )
        return 0


def get_db_size_bytes(db_path: Optional[str] = None) -> int:
    """
    Return the database file size in bytes.

    Args:
        db_path: Optional explicit database path.

    Returns:
        File size in bytes, or ``0`` when the database does not exist.

    Raises:
        None.
    """
    path = Path(db_path or get_db_path())
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def get_row_count(db_path: Optional[str] = None) -> int:
    """
    Return the total number of rows in the standups table.

    Args:
        db_path: Optional explicit database path.

    Returns:
        Row count, or ``0`` when the database is unavailable.

    Raises:
        None.
    """
    path = db_path or get_db_path()
    if not Path(path).exists():
        return 0
    try:
        with _get_connection(path) as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM standups").fetchone()
        if not row:
            return 0
        return int(row["count"] if isinstance(row, sqlite3.Row) else row[0])
    except (sqlite3.Error, TypeError, ValueError):
        return 0


def auto_cleanup_if_needed(db_path: Optional[str] = None) -> Optional[int]:
    """
    Automatically prune the history database when it grows too large.

    Args:
        db_path: Optional explicit database path.

    Returns:
        Number of rows deleted, or ``None`` when cleanup was not needed.

    Raises:
        None.
    """
    path = db_path or get_db_path()
    row_count = get_row_count(path)
    if row_count <= _AUTO_CLEANUP_THRESHOLD:
        return None
    try:
        with _get_connection(path) as conn:
            cursor = conn.execute(
                """
                DELETE FROM standups
                WHERE id NOT IN (
                    SELECT id
                    FROM standups
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                )
                """,
                (_MAX_HISTORY_ROWS,),
            )
        deleted = int(cursor.rowcount or 0)
        if deleted > 0:
            log_event("db_maintenance", operation="auto_cleanup", rows_deleted=deleted)
        return deleted
    except sqlite3.Error:
        log_event("db_error", operation="auto_cleanup")
        return 0
