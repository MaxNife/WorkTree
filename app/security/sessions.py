"""Signed session cookies and CSRF tokens.

Routes depend on ``current_user`` (``app/api/deps.py``), which calls the ``Authenticator``
protocol in ``app/services/auth.py``; an SSO backend replaces that, not the route handlers.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.adapters.secrets.base import SecretStore
from app.domain.clock import Clock

if TYPE_CHECKING:
    from app.adapters.db.models import SessionRow

SESSION_SALT = "uaf-session-v1"
# Internal namespace (see ``is_internal_secret``): workflows can never read it.
AUDIT_HMAC_KEY_NAME = "uaf_internal_audit_hmac_key"


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IssuedSession:
    session_id: str
    cookie_value: str
    csrf_token: str
    expires_at: datetime


class SessionCodec:
    def __init__(self, secret_store: SecretStore, max_age_seconds: int = 60 * 60 * 24 * 30) -> None:
        key = secret_store.ensure("session_signing_key")
        self._serializer = URLSafeTimedSerializer(key, salt=SESSION_SALT)
        self._secret_store = secret_store
        # ``SessionFactory`` narrows this to the configured session TTL.
        self.max_age_seconds = max_age_seconds

    def keyed_hash(self, text: str) -> str:
        """HMAC-SHA256 of ``text`` under an internal key, as hex (never reversible to text)."""
        key = self._secret_store.ensure(AUDIT_HMAC_KEY_NAME)
        return hmac.new(key.encode("utf-8"), text.encode("utf-8"), hashlib.sha256).hexdigest()

    def sign(self, session_id: str) -> str:
        value: str = self._serializer.dumps({"sid": session_id})
        return value

    def unsign(self, value: str) -> str | None:
        try:
            data: Any = self._serializer.loads(value, max_age=self.max_age_seconds)
        except BadSignature:
            return None
        if not isinstance(data, dict):
            return None
        sid = data.get("sid")
        return str(sid) if sid else None


class SessionFactory:
    def __init__(self, codec: SessionCodec, clock: Clock, ttl_minutes: int) -> None:
        self.codec = codec
        self.clock = clock
        self.ttl_minutes = ttl_minutes
        # A cookie signed longer ago than the session TTL is refused even if its row is live.
        codec.max_age_seconds = ttl_minutes * 60

    def create(self, user_id: str, source_ip: str, user_agent: str) -> IssuedSession:
        raw = secrets.token_urlsafe(32)
        session_id = hash_token(raw)
        csrf = secrets.token_urlsafe(32)
        now = self.clock.now()
        issued = IssuedSession(
            session_id=session_id,
            cookie_value=self.codec.sign(raw),
            csrf_token=csrf,
            expires_at=now + _minutes(self.ttl_minutes),
        )
        return issued

    def cookie_session_id(self, cookie_value: str) -> str | None:
        raw = self.codec.unsign(cookie_value)
        if raw is None:
            return None
        return hash_token(raw)


def _minutes(value: int) -> Any:
    from datetime import timedelta

    return timedelta(minutes=value)


def is_expired(session: SessionRow, now: datetime) -> bool:
    return session.revoked_at is not None or session.expires_at <= now


def csrf_matches(expected: str, supplied: str | None) -> bool:
    if not supplied:
        return False
    return secrets.compare_digest(expected, supplied)
