"""One place that connects, upgrades to TLS and logs in to an SMTP relay.

The alert mailer and the ``email`` activity both use this, so they cannot drift apart.
Rule: with a user and password, the connection must be encrypted (STARTTLS) before the
password is sent; otherwise login is refused. Without credentials, a plain relay is allowed.
"""

from __future__ import annotations

import smtplib
import ssl
from collections.abc import Iterator
from contextlib import contextmanager


class SmtpCredentialsRefused(RuntimeError):
    """Credentials were set but the relay offers no STARTTLS, so nothing was sent."""


@contextmanager
def smtp_connection(
    host: str, port: int, *, user: str = "", password: str = "", timeout: float = 30
) -> Iterator[tuple[smtplib.SMTP, bool]]:
    """Yield ``(connection, encrypted)``, ready to ``send_message``."""
    with smtplib.SMTP(host, port, timeout=timeout) as smtp:
        smtp.ehlo()
        encrypted = False
        if smtp.has_extn("starttls"):
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            encrypted = True
        if user and password:
            if not encrypted:
                raise SmtpCredentialsRefused("refusing to send SMTP credentials without STARTTLS")
            smtp.login(user, password)
        yield smtp, encrypted
