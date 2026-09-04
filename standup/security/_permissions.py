"""
standup.security._permissions - File permissions and restricted file I/O.
"""

import os
import stat
import sys
from pathlib import Path

from rich.console import Console

console = Console()


_PERMISSION_WARNED_PATHS: set = set()


def enforce_file_permissions(file_path: str, label: str = "File") -> None:
    """
    Restrict a file to the current user only: chmod 600 on Unix/macOS,
    an icacls ACL reset on Windows.

    Args:
        file_path: Path to the file.
        label: Human-friendly file label for warnings.

    Returns:
        None.

    Raises:
        None.
    """
    path = Path(file_path)
    try:
        if not path.exists():
            return
    except OSError:
        return
    if sys.platform == "win32":
        _enforce_windows_acl(file_path, label)
        return
    try:
        current = stat.S_IMODE(path.stat().st_mode)
        if current != 0o600:
            path.chmod(0o600)
    except OSError:
        return


def _enforce_windows_acl(file_path: str, label: str = "File") -> None:
    """
    Restrict a file to the current user on Windows using ``icacls``:
    strip inherited permissions and grant full control to the owner
    only. Falls back to a one-time warning if ``icacls`` itself is
    unavailable or fails (e.g. on a filesystem that doesn't support
    ACLs), rather than silently claiming the file is protected.
    """
    import subprocess

    try:
        result = subprocess.run(
            [
                "icacls",
                file_path,
                "/inheritance:r",
                "/grant:r",
                f"{os.environ.get('USERNAME', '')}:F",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return
    except (OSError, subprocess.SubprocessError):
        pass

    if file_path not in _PERMISSION_WARNED_PATHS:
        _PERMISSION_WARNED_PATHS.add(file_path)
        console.print(
            f"[yellow][!]  Could not restrict permissions on {label} via icacls. "
            "Ensure only your user can read it.[/yellow]"
        )


def write_text_restricted(file_path: str, content: str, label: str = "File") -> None:
    """
    Write ``content`` to ``file_path`` such that the file never has
    broader-than-owner-only permissions, including the moment it is
    first created.

    ``Path.write_text()`` creates the file with the OS's default mode
    (commonly 644; world-readable) and only becomes owner-only after
    a subsequent, separate ``enforce_file_permissions()`` call, a
    window in which sensitive content (API keys, webhook URLs) sits
    world-readable on disk. This creates the file empty first (with
    permissions locked down immediately after creation, before any
    content exists), then writes the real content, closing that
    window.

    Deliberately does NOT scan or scrub content for secrets: this is
    a generic write primitive and cannot know whether a given caller's
    secret-shaped content is an accidental leak or an intentional,
    already-considered persistence decision (e.g. save_config()'s
    documented OS-keychain-first, permission-restricted-file-fallback
    design). An earlier version of this function auto-redacted
    detected secrets, which (a) was silently non-functional for Groq
    keys specifically; see the GROQ_KEY note on _TAGGED_PATTERNS;
    and (b) would, if made to actually work, silently corrupt
    save_config()'s fallback value on every save in environments
    without a keychain (headless Linux, CI, Docker), since it can't
    distinguish that case from an accidental leak. Secret redaction
    belongs at the call site, where intent is known; see
    redact_sensitive_patterns() for callers (e.g. commit message
    formatting) that do want it.

    Args:
        file_path: Path to write to.
        content: Text content to write.
        label: Human-friendly file label for warnings.

    Returns:
        None.
    """
    path = Path(file_path)
    path.touch(exist_ok=True)
    enforce_file_permissions(file_path, label=label)

    from cryptography.fernet import Fernet

    key_path = Path(str(path) + ".key")
    if not key_path.exists():
        key = Fernet.generate_key()
        key_path.write_bytes(key)
        enforce_file_permissions(str(key_path), label=f"{label} encryption key")
    else:
        key = key_path.read_bytes()

    encrypted = Fernet(key).encrypt(content.encode("utf-8"))
    path.write_bytes(encrypted)


def read_text_restricted(file_path: str, label: str = "File") -> str:
    """Read and decrypt a file written by write_text_restricted.

    Falls back to plain text if no encryption key is found, preserving
    backward compatibility with files written before encryption was added.
    """
    path = Path(file_path)
    data = path.read_bytes()
    key_path = Path(str(path) + ".key")
    if key_path.exists():
        try:
            from cryptography.fernet import Fernet

            key = key_path.read_bytes()
            return Fernet(key).decrypt(data).decode("utf-8")
        except Exception:  # noqa: S110
            pass
    return data.decode("utf-8")


def enforce_config_permissions(config_path: str) -> None:
    """
    Backward-compatible wrapper for config permission enforcement.

    Args:
        config_path: Config file path.

    Returns:
        None.

    Raises:
        None.
    """
    enforce_file_permissions(config_path, label="Config file")
