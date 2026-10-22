"""In-app notifications plus optional webhook and SMTP delivery."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.adapters.db.models import Notification
from app.adapters.secrets.base import SecretStore
from app.config import NotificationSettings
from app.domain.clock import Clock
from app.logging_setup import get_logger
from app.security.masking import get_masker


class NotificationService:
    def __init__(
        self,
        clock: Clock,
        settings: NotificationSettings,
        secret_store: SecretStore,
    ) -> None:
        self.clock = clock
        self.settings = settings
        self.secret_store = secret_store
        self.log = get_logger(__name__)

    def notify(
        self,
        session: Session,
        *,
        title: str,
        body: str = "",
        role: str | None = None,
        user_id: str | None = None,
        kind: str = "info",
        link: str = "",
    ) -> Notification:
        masker = get_masker()
        row = Notification(
            user_id=user_id,
            role=role,
            title=masker.mask(title)[:255],
            body=masker.mask(body)[:4000],
            kind=kind,
            link=link[:500],
            created_at=self.clock.now(),
        )
        session.add(row)
        session.flush()
        self._deliver(title=masker.mask(title), body=masker.mask(body), kind=kind, link=link)
        return row

    def _deliver(self, *, title: str, body: str, kind: str, link: str) -> None:
        if self.settings.webhook_url:
            try:
                httpx.post(
                    self.settings.webhook_url,
                    json={"title": title, "body": body, "kind": kind, "link": link},
                    timeout=5,
                )
            except Exception as exc:  # delivery must never break the task
                self.log.warning("notification_webhook_failed", error=type(exc).__name__)
        if self.settings.smtp_host and self.settings.smtp_to:
            try:
                message = EmailMessage()
                message["Subject"] = title
                message["From"] = self.settings.smtp_from or "uaf@localhost"
                message["To"] = self.settings.smtp_to
                message.set_content(f"{body}\n\n{link}")
                password = self.secret_store.get(self.settings.smtp_password_secret) or ""
                with smtplib.SMTP(
                    self.settings.smtp_host, self.settings.smtp_port, timeout=5
                ) as smtp:
                    if self.settings.smtp_user and password:
                        smtp.login(self.settings.smtp_user, password)
                    smtp.send_message(message)
            except Exception as exc:
                self.log.warning("notification_smtp_failed", error=type(exc).__name__)

    def list_for(
        self,
        session: Session,
        *,
        roles: list[str],
        user_id: str,
        unread_only: bool = False,
    ) -> list[Notification]:
        from sqlalchemy import or_, select

        query = select(Notification).where(
            or_(
                Notification.user_id == user_id,
                Notification.role.in_(roles) if roles else Notification.role.is_(None),
                Notification.role.is_(None),
            )
        )
        if unread_only:
            query = query.where(Notification.read.is_(False))
        return list(
            session.execute(query.order_by(Notification.created_at.desc()).limit(200)).scalars()
        )

    def mark_read(self, session: Session, notification_id: str, user_id: str) -> bool:
        from sqlalchemy import select

        row = session.execute(
            select(Notification).where(
                Notification.id == notification_id,
                (Notification.user_id == user_id) | (Notification.user_id.is_(None)),
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        row.read = True
        return True

    def serialize(self, row: Notification) -> dict[str, Any]:
        return {
            "id": row.id,
            "title": row.title,
            "body": row.body,
            "kind": row.kind,
            "link": row.link,
            "read": row.read,
            "created_at": row.created_at.isoformat(),
        }
