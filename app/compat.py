"""The old ``uaf`` names, accepted for one release after the rename to WorkTree (docs/03 Part 3).

Everything that still knows the old names lives here, so removing them next release is one file.
New names always win when both are set; reading an old one logs a deprecation warning once.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

PREFIX = "WORKTREE_"
LEGACY_PREFIX = "UAF_"
# The session and CSRF cookies set before the rename stay valid until they expire.
LEGACY_SESSION_COOKIE = "uaf_session"
LEGACY_CSRF_COOKIE = "uaf_csrf"
# The database file's old default name; the start guard refuses to start beside it.
LEGACY_DATABASE_FILE = "uaf.db"

_warned: set[str] = set()
_log = logging.getLogger("worktree.compat")


def warn_legacy(old: str, new: str) -> None:
    if old in _warned:
        return
    _warned.add(old)
    _log.warning("%s is deprecated and will stop working next release; use %s", old, new)


def env(name: str, default: str | None = None) -> str | None:
    """``WORKTREE_<name>``, else ``UAF_<name>`` (with a warning), else ``default``."""
    value = os.environ.get(PREFIX + name)
    if value is not None:
        return value
    legacy = os.environ.get(LEGACY_PREFIX + name)
    if legacy is not None:
        warn_legacy(LEGACY_PREFIX + name, PREFIX + name)
        return legacy
    return default


def is_platform_variable(key: str) -> bool:
    """A variable that configures the platform, under either prefix. Activity children never
    inherit these: they could hold the database URL or a secret."""
    upper = key.upper()
    return upper.startswith(PREFIX) or upper.startswith(LEGACY_PREFIX)


def legacy_settings_variables(environ: Mapping[str, str] | None = None) -> list[str]:
    """``UAF_*`` settings variables still in use (not secrets, which are reported on read)."""
    source = os.environ if environ is None else environ
    return sorted(
        key
        for key in source
        if key.upper().startswith(LEGACY_PREFIX)
        and not key.upper().startswith(LEGACY_PREFIX + "SECRET_")
        and not key.upper().startswith(LEGACY_PREFIX + "CHILD_")
    )


def session_cookie(cookies: Mapping[str, str], name: str) -> str | None:
    """The session cookie, falling back to the one set before the rename."""
    value = cookies.get(name)
    if value:
        return value
    legacy = cookies.get(LEGACY_SESSION_COOKIE)
    if legacy:
        warn_legacy(LEGACY_SESSION_COOKIE, name)
    return legacy or None
