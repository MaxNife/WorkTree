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

from app.adapters.net import CheckedSMTP


class SmtpCredentialsRefused(RuntimeError):
    """Credentials were set but the relay offers no STARTTLS, so nothing was sent."""


@contextmanager
def smtp_connection(
    host: str,
    port: int,
    *,
    user: str = "",
    password: str = "",
    timeout: float = 30,
    checked: bool = False,
) -> Iterator[tuple[smtplib.SMTP, bool]]:
    """Yield ``(connection, encrypted)``, ready to ``send_message``.

    ``checked`` applies the activities' egress policy (ADR 0001 rule 4). The control plane's
    own notifier leaves it off: its relay is set by the operator and is often on localhost.
    """
    factory = CheckedSMTP if checked else smtplib.SMTP
    with factory(host, port, timeout=timeout) as smtp:
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
