"""Typed application settings and configuration loading.

Every value has a safe default for a local install. Secrets never live in ``config.yaml``;
they are referenced by name and resolved through the secret store.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

DEFAULT_CONFIG_PATH = Path("config.yaml")
INSECURE_PASSWORDS = {"admin", "password", "changeme", "letmein", "123456", "admin123"}


class AppInfo(BaseModel):
    name: str = "UAF"
    environment: Literal["dev", "test", "prod"] = "dev"
    base_url: str = "http://127.0.0.1:8000"


class DatabaseSettings(BaseModel):
    url: str = "sqlite:///./runtime/uaf.db"
    echo: bool = False


class DataSettings(BaseModel):
    root: Path = Path("./runtime")
    workspaces: Path = Path("./runtime/workspaces")
    artifacts: Path = Path("./runtime/artifacts")
    playwright_state: Path = Path("./runtime/playwright-state")
    retention_days: int = Field(default=30, ge=1)


class LoggingSettings(BaseModel):
    level: str = "INFO"
    directory: Path = Path("./runtime/logs")
    json_logs: bool = True
    max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    backup_count: int = Field(default=10, ge=1)


class AuditSettings(BaseModel):
    retention_years: int = Field(default=7, ge=1)


class SecuritySettings(BaseModel):
    session_ttl_minutes: int = Field(default=480, ge=1)
    cookie_secure: bool = False
    cookie_name: str = "uaf_session"
    login_rate_limit_attempts: int = Field(default=10, ge=1)
    login_rate_limit_window_seconds: int = Field(default=60, ge=1)
    # Failures per window from one address across all usernames (password spraying), and
    # against one account across all addresses. Both are looser than the per-pair limit above,
    # so a person mistyping is stopped first by the pair limit.
    login_rate_limit_address_attempts: int = Field(default=50, ge=1)
    login_rate_limit_account_attempts: int = Field(default=30, ge=1)
    csrf_cookie_name: str = "uaf_csrf"
    csrf_header_name: str = "X-CSRF-Token"


class WorkerSettings(BaseModel):
    count: int = Field(default=2, ge=1, le=64)
    poll_seconds: float = Field(default=0.5, gt=0, le=60)
    default_timeout_seconds: int = Field(default=300, ge=1)


class BusSettings(BaseModel):
    adapter: Literal["db"] = "db"
    visibility_timeout_seconds: int = Field(default=300, ge=1)
    max_attempts: int = Field(default=3, ge=1)


class SecretSettings(BaseModel):
    adapter: Literal["local", "vault"] = "local"
    file: Path = Path("./runtime/secrets.json")
    vault_url: str = ""
    # Name of the environment variable that holds the Vault token. The token itself never
    # lives in config.yaml.
    vault_token_env: str = "VAULT_TOKEN"
    vault_mount: str = "secret"

    @model_validator(mode="after")
    def _vault_requires_url(self) -> SecretSettings:
        if self.adapter == "vault" and not self.vault_url:
            raise ValueError("secrets.vault_url is required when secrets.adapter is 'vault'")
        return self


class ActivitySettings(BaseModel):
    extra_folder: Path = Path("./runtime/activities")
    # Folders ``unc_archive`` may write into. Empty (the default) refuses every destination.
    # Never list the activity folder: it is refused even when a root contains it.
    archive_roots: list[Path] = Field(default_factory=list)


class SchedulerSettings(BaseModel):
    enabled: bool = True
    tick_seconds: int = Field(default=15, ge=1)
    file_watch_seconds: int = Field(default=5, ge=1)


class AISettings(BaseModel):
    enabled: bool = False
    endpoint: str = ""
    timeout_seconds: int = Field(default=30, ge=1)


class NotificationSettings(BaseModel):
    webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = Field(default=25, ge=1, le=65535)
    smtp_from: str = ""
    smtp_to: str = ""
    smtp_user: str = ""
    smtp_password_secret: str = "smtp_password"


class OTelSettings(BaseModel):
    enabled: bool = False


class Settings(BaseSettings):
    """Validated application settings.

    Precedence: constructor arguments, environment, ``.env``, ``config.yaml`` defaults.
    Environment variables use the ``UAF_`` prefix and ``__`` between levels.
    """

    model_config = SettingsConfigDict(
        env_prefix="UAF_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app: AppInfo = AppInfo()
    database: DatabaseSettings = DatabaseSettings()
    data: DataSettings = DataSettings()
    logging: LoggingSettings = LoggingSettings()
    audit: AuditSettings = AuditSettings()
    security: SecuritySettings = SecuritySettings()
    workers: WorkerSettings = WorkerSettings()
    bus: BusSettings = BusSettings()
    secrets: SecretSettings = SecretSettings()
    activities: ActivitySettings = ActivitySettings()
    scheduler: SchedulerSettings = SchedulerSettings()
    notifications: NotificationSettings = NotificationSettings()
    ai: AISettings = AISettings()
    otel: OTelSettings = OTelSettings()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_file = os.environ.get("UAF_CONFIG", str(DEFAULT_CONFIG_PATH))
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=yaml_file),
            file_secret_settings,
        )

    @field_validator("logging")
    @classmethod
    def _valid_log_level(cls, value: LoggingSettings) -> LoggingSettings:
        if value.level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid logging level: {value.level}")
        return value


def load_settings(**overrides: Any) -> Settings:
    """Load settings, creating the runtime directories referenced by the config."""
    settings = Settings(**overrides)
    for path in (
        settings.data.root,
        settings.data.workspaces,
        settings.data.artifacts,
        settings.data.playwright_state,
        settings.logging.directory,
        settings.activities.extra_folder,
        settings.secrets.file.parent,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return settings


class InsecureConfiguration(RuntimeError):
    """The settings would start the server in a state its environment must not be in."""


def assert_startup_safe(settings: Settings) -> None:
    """Refuse to start a ``prod`` server that would send its session cookie over plain HTTP.

    The flag is not forced on: an operator who terminates TLS elsewhere must say so, and a
    silent override would hide a misconfiguration (SEC-6).
    """
    if settings.app.environment == "prod" and not settings.security.cookie_secure:
        raise InsecureConfiguration(
            "app.environment is 'prod' but security.cookie_secure is false: the session cookie "
            "would be sent without the Secure flag. Set security.cookie_secure: true "
            "(UAF_SECURITY__COOKIE_SECURE=true) and serve the app over HTTPS."
        )


def is_insecure_password(password: str) -> bool:
    """True when a bootstrap password is empty or one of the well-known defaults."""
    return not password or password.strip().lower() in INSECURE_PASSWORDS
