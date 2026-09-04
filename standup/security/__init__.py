"""
standup.security - Package re-export layer.

Public API stays importable from ``standup.security``; implementation
lives in ``_redact``, ``_permissions`` and ``_keyring``.
"""

import contextlib
import sys  # noqa: F401 - keeps standup.security.sys working (doctor reads sys.version_info)

from standup.logger import get_log_path, get_log_size_bytes, log_event  # noqa: F401
from standup.security._keyring import (  # noqa: F401
    _KEYRING_SERVICE,
    _KEYRING_WARNED_KEYS,
    delete_secret,
    get_secret,
    store_secret,
)
from standup.security._permissions import (  # noqa: F401
    _PERMISSION_WARNED_PATHS,
    _enforce_windows_acl,
    enforce_config_permissions,
    enforce_file_permissions,
    read_text_restricted,
    write_text_restricted,
)
from standup.security._redact import (  # noqa: F401
    _ERROR_PATTERNS,
    _PATTERNS,
    _REDACTED,
    _TAGGED_PATTERNS,
    mask_api_key,
    redact_sensitive_patterns,
    sanitize_error_message,
    validate_groq_api_key,
)

with contextlib.suppress(ImportError):  # pragma: no cover
    from standup.doctor import _format_size, _permission_status, run_doctor  # noqa: F401
