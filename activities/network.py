"""Network and messaging activities: HTTP, downloads, SFTP, email, Graph and UNC archive."""

from __future__ import annotations

import contextlib
import json
import mimetypes
import os
import shutil
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

from activities._common import artifact_for, safe_path, sha256_file, validate_url
from app.adapters.smtp import SmtpCredentialsRefused, smtp_connection
from app.domain.activity import Activity, ActivityContext, ActivityResult


class HttpInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, str] = Field(default_factory=dict)
    json_body: Any = None
    body: str | None = None
    bearer_token: str = ""
    timeout_seconds: float = Field(default=30, gt=0, le=300)
    max_response_bytes: int = Field(default=2_000_000, ge=1)
    output_path: str | None = None
    expected_status: list[int] = Field(default_factory=lambda: [200, 201, 202, 204])


class HttpRequestActivity(Activity[HttpInputs]):
    name = "http_request"
    category = "Platform / Integration"
    description = "Call an internal HTTP endpoint with an explicit timeout and response cap."
    input_model = HttpInputs
    sensitive_fields = ("bearer_token",)
    credential_inputs = ("bearer_token", "headers")
    destination_inputs = ("url",)

    def run(self, ctx: ActivityContext, inputs: HttpInputs) -> ActivityResult:
        validate_url(inputs.url)
        headers = dict(inputs.headers)
        if inputs.bearer_token:
            headers["Authorization"] = f"Bearer {inputs.bearer_token}"
        with (
            httpx.Client(timeout=inputs.timeout_seconds, follow_redirects=False) as client,
            client.stream(
                inputs.method,
                inputs.url,
                headers=headers,
                params=inputs.params,
                json=inputs.json_body,
                content=inputs.body,
            ) as response,
        ):
            buffer = bytearray()
            for chunk in response.iter_bytes():
                buffer.extend(chunk)
                if len(buffer) > inputs.max_response_bytes:
                    return ActivityResult.failed(
                        f"response exceeded {inputs.max_response_bytes} bytes"
                    )
            content = bytes(buffer)
            status = response.status_code
            response_headers = dict(response.headers)
        if status not in inputs.expected_status:
            return ActivityResult.failed(
                f"HTTP {status}: {content[:500].decode('utf-8', errors='replace')}",
                {"status": status, "headers": response_headers},
            )
        text = content.decode("utf-8", errors="replace")
        outputs: dict[str, Any] = {"status": status, "headers": response_headers, "text": text}
        # The body was streamed, so parse the collected bytes (response.json() would raise).
        with contextlib.suppress(ValueError):
            outputs["json"] = json.loads(text)
        if inputs.output_path:
            path = safe_path(ctx, inputs.output_path)
            path.write_bytes(content)
            outputs["path"] = str(path.relative_to(ctx.workspace))
            return ActivityResult.done(outputs, f"HTTP {status}", [artifact_for(ctx, path)])
        return ActivityResult.done(outputs, f"HTTP {status}")


class DownloadInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    path: str = "download.bin"
    headers: dict[str, str] = Field(default_factory=dict)
    bearer_token: str = ""
    timeout_seconds: float = Field(default=60, gt=0, le=600)
    expected_sha256: str = ""
    max_bytes: int = Field(default=2_000_000_000, ge=1)


class DownloadFileActivity(Activity[DownloadInputs]):
    name = "download_file"
    category = "Platform / Integration"
    description = "Stream a file into the run workspace with size and checksum verification."
    input_model = DownloadInputs
    sensitive_fields = ("bearer_token",)
    credential_inputs = ("bearer_token", "headers")
    destination_inputs = ("url",)

    def run(self, ctx: ActivityContext, inputs: DownloadInputs) -> ActivityResult:
        validate_url(inputs.url)
        path = safe_path(ctx, inputs.path)
        headers = dict(inputs.headers)
        if inputs.bearer_token:
            headers["Authorization"] = f"Bearer {inputs.bearer_token}"
        total = 0
        with (
            httpx.Client(timeout=inputs.timeout_seconds, follow_redirects=False) as client,
            client.stream("GET", inputs.url, headers=headers) as response,
        ):
            if response.status_code >= 400:
                return ActivityResult.failed(f"download failed with HTTP {response.status_code}")
            declared = int(response.headers.get("content-length", "0") or 0)
            if declared > inputs.max_bytes:
                return ActivityResult.failed("download exceeds the size cap")
            with path.open("wb") as handle:
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > inputs.max_bytes:
                        handle.close()
                        path.unlink(missing_ok=True)
                        return ActivityResult.failed("download exceeds the size cap")
                    handle.write(chunk)
        digest = sha256_file(path)
        if inputs.expected_sha256 and digest != inputs.expected_sha256.strip().lower():
            path.unlink(missing_ok=True)
            return ActivityResult.failed("downloaded file checksum does not match")
        return ActivityResult.done(
            {"path": str(path.relative_to(ctx.workspace)), "bytes": total, "sha256": digest},
            f"downloaded {total} bytes",
            [artifact_for(ctx, path)],
        )


class SftpInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["get", "put", "list"] = "get"
    host: str
    port: int = Field(default=22, ge=1, le=65535)
    username: str
    password: str = ""
    private_key_path: str = ""
    known_hosts_path: str = ""
    remote_path: str = "."
    local_path: str = ""
    timeout_seconds: float = Field(default=30, gt=0, le=300)


class SftpActivity(Activity[SftpInputs]):
    name = "sftp"
    category = "Platform / Integration"
    description = "SFTP get/put/list using paramiko."
    input_model = SftpInputs
    sensitive_fields = ("password",)
    credential_inputs = ("password",)
    destination_inputs = ("host",)

    def run(self, ctx: ActivityContext, inputs: SftpInputs) -> ActivityResult:
        import paramiko

        client = paramiko.SSHClient()
        if inputs.known_hosts_path:
            client.load_host_keys(str(safe_path(ctx, inputs.known_hosts_path, must_exist=True)))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            key = None
            if inputs.private_key_path:
                # Any key type (RSA, ECDSA, Ed25519), not only RSA.
                key = paramiko.PKey.from_path(
                    safe_path(ctx, inputs.private_key_path, must_exist=True)
                )
            client.connect(
                inputs.host,
                port=inputs.port,
                username=inputs.username,
                password=inputs.password or None,
                pkey=key,
                timeout=inputs.timeout_seconds,
                allow_agent=False,
                look_for_keys=False,
            )
            with client.open_sftp() as sftp:
                if inputs.operation == "list":
                    entries = [
                        {
                            "name": item.filename,
                            "bytes": item.st_size,
                            "directory": stat.S_ISDIR(item.st_mode or 0),
                        }
                        for item in sftp.listdir_attr(inputs.remote_path)
                    ]
                    return ActivityResult.done({"files": entries, "count": len(entries)})
                if inputs.operation == "get":
                    if not inputs.local_path:
                        return ActivityResult.failed("local_path is required for a get")
                    local = safe_path(ctx, inputs.local_path)
                    sftp.get(inputs.remote_path, str(local))
                    return ActivityResult.done(
                        {
                            "path": str(local.relative_to(ctx.workspace)),
                            "bytes": local.stat().st_size,
                        },
                        "file downloaded over SFTP",
                        [artifact_for(ctx, local)],
                    )
                if not inputs.local_path:
                    return ActivityResult.failed("local_path is required for a put")
                local = safe_path(ctx, inputs.local_path, must_exist=True)
                sftp.put(str(local), inputs.remote_path)
                return ActivityResult.done(
                    {"path": inputs.remote_path, "bytes": local.stat().st_size}
                )
        finally:
            client.close()


class EmailInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["smtp", "graph"] = "smtp"
    to: list[str]
    subject: str
    body: str = ""
    html: bool = False
    attachments: list[str] = Field(default_factory=list)
    smtp_host: str = "localhost"
    smtp_port: int = Field(default=25, ge=1, le=65535)
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "uaf@localhost"
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    sender: str = ""
    graph_base_url: str = "https://graph.microsoft.com/v1.0"
    login_base_url: str = "https://login.microsoftonline.com"


class EmailActivity(Activity[EmailInputs]):
    name = "email"
    category = "Platform / Messaging"
    description = "Send mail through Microsoft Graph client-secret auth or SMTP fallback."
    input_model = EmailInputs
    sensitive_fields = ("smtp_password", "client_secret")
    credential_inputs = ("smtp_password", "client_secret")
    destination_inputs = ("smtp_host", "graph_base_url", "login_base_url")

    @classmethod
    def active_destination_fields(cls, values: Mapping[str, Any]) -> tuple[str, ...]:
        # SMTP connects to smtp_host only; Graph to its API and its token endpoint only.
        if values.get("provider", "smtp") == "graph":
            return ("graph_base_url", "login_base_url")
        return ("smtp_host",)

    def run(self, ctx: ActivityContext, inputs: EmailInputs) -> ActivityResult:
        if inputs.provider == "graph":
            return self._graph(ctx, inputs)
        message = EmailMessage()
        message["Subject"] = inputs.subject
        message["From"] = inputs.smtp_from
        message["To"] = ", ".join(inputs.to)
        message.set_content(inputs.body)
        if inputs.html:
            message.add_alternative(inputs.body, subtype="html")
        for name in inputs.attachments:
            path = safe_path(ctx, name, must_exist=True)
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            maintype, _, subtype = content_type.partition("/")
            message.add_attachment(
                path.read_bytes(),
                maintype=maintype or "application",
                subtype=subtype or "octet-stream",
                filename=path.name,
            )
        try:
            with smtp_connection(
                inputs.smtp_host,
                inputs.smtp_port,
                user=inputs.smtp_user,
                password=inputs.smtp_password,
                timeout=30,
            ) as (smtp, encrypted):
                smtp.send_message(message)
        except SmtpCredentialsRefused as exc:
            return ActivityResult.failed(str(exc))
        return ActivityResult.done(
            {"provider": "smtp", "to": inputs.to, "starttls": encrypted}, "mail sent"
        )

    def _graph(self, ctx: ActivityContext, inputs: EmailInputs) -> ActivityResult:
        token = _graph_token(inputs)
        if token is None:
            return ActivityResult.failed("Microsoft Graph token request failed")
        sender = inputs.sender or inputs.smtp_from
        message: dict[str, Any] = {
            "subject": inputs.subject,
            "body": {"contentType": "HTML" if inputs.html else "Text", "content": inputs.body},
            "toRecipients": [{"emailAddress": {"address": address}} for address in inputs.to],
        }
        attachments = []
        for name in inputs.attachments:
            path = safe_path(ctx, name, must_exist=True)
            import base64

            attachments.append(
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": path.name,
                    "contentBytes": base64.b64encode(path.read_bytes()).decode(),
                }
            )
        if attachments:
            message["attachments"] = attachments
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{inputs.graph_base_url.rstrip('/')}/users/{quote(sender, safe='@')}/sendMail",
                headers={"Authorization": f"Bearer {token}"},
                json={"message": message, "saveToSentItems": True},
            )
        if response.status_code >= 400:
            return ActivityResult.failed(f"Graph sendMail returned HTTP {response.status_code}")
        return ActivityResult.done({"provider": "graph", "to": inputs.to}, "mail sent")


class GraphReadMailInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    client_id: str
    client_secret: str
    mailbox: str
    sender: str = ""
    since: str = ""
    top: int = Field(default=10, ge=1, le=50)
    code_regex: str = ""
    graph_base_url: str = "https://graph.microsoft.com/v1.0"
    login_base_url: str = "https://login.microsoftonline.com"


class GraphReadMailActivity(Activity[GraphReadMailInputs]):
    name = "graph_read_mail"
    category = "Platform / Messaging"
    description = "Read the newest messages for a mailbox and optionally extract a code."
    input_model = GraphReadMailInputs
    sensitive_fields = ("client_secret",)
    credential_inputs = ("client_secret",)
    destination_inputs = ("graph_base_url", "login_base_url")

    def run(self, ctx: ActivityContext, inputs: GraphReadMailInputs) -> ActivityResult:
        token = _graph_token(inputs)
        if token is None:
            return ActivityResult.failed("Microsoft Graph token request failed")
        params: dict[str, str] = {
            "$top": str(inputs.top),
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,bodyPreview,receivedDateTime,from",
        }
        filters: list[str] = []
        if inputs.since:
            filters.append(f"receivedDateTime ge {_graph_timestamp(inputs.since)}")
        if inputs.sender:
            # Filter on the server: the newest message from this sender after the timestamp
            # must be in the page, even when other senders wrote more recently.
            filters.append(f"from/emailAddress/address eq '{_odata_literal(inputs.sender)}'")
        if filters:
            params["$filter"] = " and ".join(filters)
        with httpx.Client(timeout=30) as client:
            response = client.get(
                f"{inputs.graph_base_url.rstrip('/')}/users/{quote(inputs.mailbox, safe='@')}/messages",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
        if response.status_code >= 400:
            return ActivityResult.failed(f"Graph read returned HTTP {response.status_code}")
        messages = response.json().get("value", [])
        if inputs.sender:
            messages = [
                item
                for item in messages
                if inputs.sender.lower()
                in str(item.get("from", {}).get("emailAddress", {}).get("address", "")).lower()
            ]
        code = ""
        if inputs.code_regex and messages:
            import re

            match = re.search(inputs.code_regex, str(messages[0].get("bodyPreview", "")))
            code = match.group(1) if match and match.groups() else (match.group(0) if match else "")
        return ActivityResult.done({"messages": messages, "code": code, "count": len(messages)})


class UncArchiveInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["copy", "move"] = "copy"
    source_path: str
    destination_dir: str
    filename: str = ""
    expected_sha256: str = ""
    overwrite: bool = False


def _archive_roots(ctx: ActivityContext) -> list[Path]:
    """The folders ``unc_archive`` may write into: ``activities.archive_roots`` in-process, or
    the ``UAF_CHILD_ARCHIVE_ROOTS`` JSON list the worker passes to a child."""
    activities = getattr(getattr(ctx, "settings", None), "activities", None)
    if activities is not None:
        return [Path(root) for root in activities.archive_roots]
    try:
        roots = json.loads(os.environ.get("UAF_CHILD_ARCHIVE_ROOTS") or "[]")
    except ValueError:
        return []
    return [Path(root) for root in roots] if isinstance(roots, list) else []


def _extra_folder(ctx: ActivityContext) -> Path | None:
    activities = getattr(getattr(ctx, "settings", None), "activities", None)
    if activities is not None:
        return Path(activities.extra_folder)
    raw = os.environ.get("UAF_CHILD_ACTIVITIES_EXTRA")
    return Path(raw) if raw else None


def _is_inside(path: Path, folder: Path) -> bool:
    root, candidate = folder.resolve(), path.resolve()
    return candidate == root or root in candidate.parents


def archive_refusal(ctx: ActivityContext, target: Path) -> str | None:
    """Why ``target`` (a resolved file or folder) may not be written to, or None if it may."""
    roots = _archive_roots(ctx)
    if not roots:
        return (
            "unc_archive is not configured: it refuses every destination until "
            "activities.archive_roots lists the folders it may write to"
        )
    extra = _extra_folder(ctx)
    if extra is not None and _is_inside(target, extra):
        return "unc_archive may not write into the activity folder (activities.extra_folder)"
    if not any(_is_inside(target, root) for root in roots):
        return "destination is outside every folder listed in activities.archive_roots"
    return None


class UncArchiveActivity(Activity[UncArchiveInputs]):
    name = "unc_archive"
    category = "Platform / Files"
    description = (
        "Copy or move a file to a UNC/network path and verify its SHA-256. The destination "
        "must be inside a folder listed in the server's activities.archive_roots."
    )
    input_model = UncArchiveInputs

    def run(self, ctx: ActivityContext, inputs: UncArchiveInputs) -> ActivityResult:
        source = safe_path(ctx, inputs.source_path, must_exist=True)
        if inputs.filename and Path(inputs.filename).name != inputs.filename:
            return ActivityResult.failed("filename must be a plain file name, not a path")
        destination_dir = Path(inputs.destination_dir)
        destination = destination_dir / (inputs.filename or source.name)
        # Both the folder and the final file are checked after resolving links and "..", so a
        # symlink or a crafted name cannot step out of an archive root.
        for target in (destination_dir, destination):
            refusal = archive_refusal(ctx, target)
            if refusal:
                return ActivityResult.failed(refusal)
        destination_dir.mkdir(parents=True, exist_ok=True)
        if destination.exists() and not inputs.overwrite:
            return ActivityResult.failed(f"destination already exists: {destination}")
        # A move is copy, verify, then delete: the source is only removed once the archived
        # copy is known to be good, and a bad copy is never left behind.
        shutil.copy2(source, destination)
        digest = sha256_file(destination)
        expected = inputs.expected_sha256.strip().lower() or sha256_file(source)
        if digest != expected:
            destination.unlink(missing_ok=True)
            return ActivityResult.failed("archived file checksum does not match")
        if inputs.operation == "move":
            source.unlink()
        return ActivityResult.done(
            {"path": str(destination), "sha256": digest, "bytes": destination.stat().st_size},
            "file archived",
        )


def _graph_timestamp(value: str) -> str:
    """Normalise a caller-supplied ISO timestamp for an OData filter (no raw interpolation)."""
    moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _odata_literal(value: str) -> str:
    """Escape a string for an OData filter literal (single quotes are doubled)."""
    return value.replace("'", "''")


def _graph_token(inputs: EmailInputs | GraphReadMailInputs) -> str | None:
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{inputs.login_base_url.rstrip('/')}/{inputs.tenant_id}/oauth2/v2.0/token",
            data={
                "client_id": inputs.client_id,
                "client_secret": inputs.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        )
    if response.status_code >= 400:
        return None
    return str(response.json().get("access_token", "")) or None
