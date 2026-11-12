"""HashiCorp Vault adapter (optional dependency).

Enabled with ``secrets.adapter: vault`` and ``pip install 'worktree[vault]'``. The client is
injectable so the adapter can be unit-tested without a live Vault.
"""

from __future__ import annotations

from typing import Any

from app.adapters.secrets.base import SecretInfo, SecretNotFound
from app.domain.clock import Clock


class VaultSecretStore:
    def __init__(
        self,
        url: str,
        token: str,
        mount: str,
        clock: Clock,
        client: Any = None,
    ) -> None:
        self.url = url
        self.mount = mount
        self.clock = clock
        if client is not None:
            self._client = client
        else:  # pragma: no cover - requires the optional extra
            try:
                import hvac
            except ImportError as exc:
                raise RuntimeError(
                    "Vault adapter requires the optional dependency: pip install 'worktree[vault]'"
                ) from exc
            self._client = hvac.Client(url=url, token=token)
        self._cache: dict[str, SecretInfo] = {}

    def get(self, name: str) -> str | None:
        try:
            response = self._client.secrets.kv.v2.read_secret_version(
                path=name, mount_point=self.mount
            )
        except Exception as exc:
            # Only "no such path" means missing; an outage must not look like an absent secret.
            if type(exc).__name__ == "InvalidPath":
                return None
            raise
        data = response.get("data", {}).get("data", {})
        value = data.get("value")
        return str(value) if value is not None else None

    def require(self, name: str) -> str:
        value = self.get(name)
        if value is None:
            raise SecretNotFound(name)
        return value

    def set(self, name: str, value: str) -> None:
        self._client.secrets.kv.v2.create_or_update_secret(
            path=name, secret={"value": value}, mount_point=self.mount
        )

    def list_metadata(self) -> list[SecretInfo]:
        try:
            keys = self._client.secrets.kv.v2.list_secrets(path="", mount_point=self.mount)
        except Exception:
            return []
        names = keys.get("data", {}).get("keys", [])
        return [SecretInfo(name=str(n).rstrip("/"), source="vault") for n in names]

    def names(self) -> list[str]:
        return [info.name for info in self.list_metadata()]

    def ensure(self, name: str, factory: Any = None) -> str:
        existing = self.get(name)
        if existing:
            return existing
        import secrets as pysecrets

        generated = str(factory()) if factory else pysecrets.token_urlsafe(48)
        self.set(name, generated)
        return generated
