"""
standup.security._keyring - OS keychain abstraction via keyring.
"""

from rich.console import Console

console = Console()


_KEYRING_SERVICE = "standup-bot"
_KEYRING_WARNED_KEYS: set = set()


def store_secret(key_name: str, value: str) -> bool:
    """
    Store a secret in the OS keychain (Keychain on macOS, Credential
    Manager on Windows, Secret Service on Linux) via ``keyring``.

    Returns:
        True if the secret was stored in the OS keychain. False if no
        keychain backend is available (common in headless Linux, CI,
        and Docker environments) or the backend raised any other
        error; callers should fall back to their own storage in
        that case rather than lose the value. Warns once per key,
        not on every call, to avoid spamming a CLI tool's output.
    """
    if not value:
        return False
    try:
        import keyring

        keyring.set_password(_KEYRING_SERVICE, key_name, value)
        return True
    except Exception:
        if key_name not in _KEYRING_WARNED_KEYS:
            _KEYRING_WARNED_KEYS.add(key_name)
            console.print(
                f"[yellow][!]  No OS keychain available for {key_name}; "
                "storing it in the config file instead (permissions "
                "still restricted to your user).[/yellow]"
            )
        return False


def get_secret(key_name: str) -> str | None:
    """
    Retrieve a secret previously stored via ``store_secret``.

    Returns:
        The stored value, or ``None`` if it isn't in the OS keychain
        (never stored there, or no backend available); callers
        should fall back to a config-file value in that case.
    """
    try:
        import keyring

        return keyring.get_password(_KEYRING_SERVICE, key_name)
    except Exception:
        return None


def delete_secret(key_name: str) -> None:
    """Best-effort delete of a secret from the OS keychain. Never raises."""
    try:
        import keyring

        keyring.delete_password(_KEYRING_SERVICE, key_name)
    except Exception:  # noqa: S110 – intentionally swallowed; best-effort delete
        pass
