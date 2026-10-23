"""Local fake services for tests and acceptance runs.

Nothing here talks to the internet. Each server binds to an ephemeral loopback port and is
started and stopped by the pytest fixtures in ``tests/conftest.py``.
"""

from __future__ import annotations

import contextlib
import json
import socket
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import uvicorn
from fastapi import Body, FastAPI, Form, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse


@dataclass
class RunningServer:
    base_url: str
    server: uvicorn.Server
    thread: threading.Thread
    state: FixtureState | None = None

    @property
    def running(self) -> bool:
        return self.thread.is_alive() and bool(self.server.started)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_server(app: FastAPI, *, state: FixtureState | None = None) -> RunningServer:
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="uaf-fixture", daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("fixture server did not start")
    return RunningServer(f"http://127.0.0.1:{port}", server, thread, state)


def _fixture_messages() -> list[dict[str, Any]]:
    return [
        {
            "id": "msg-1",
            "subject": "Older invoice",
            "bodyPreview": "Invoice INV-099 is ready",
            "receivedDateTime": "2026-01-01T08:00:00Z",
            "from": {"emailAddress": {"address": "billing@old.example"}},
        },
        {
            "id": "msg-2",
            "subject": "Newest invoice",
            "bodyPreview": "Your verification code is 654321",
            "receivedDateTime": "2026-01-02T09:30:00Z",
            "from": {"emailAddress": {"address": "billing@acme.example"}},
        },
    ]


@dataclass
class FixtureState:
    messages: list[dict[str, Any]] = field(default_factory=_fixture_messages)
    sent_mail: list[dict[str, Any]] = field(default_factory=list)
    portal_sessions: set[str] = field(default_factory=lambda: {"fixture-session"})
    llm_requests: list[dict[str, Any]] = field(default_factory=list)
    uploads: dict[str, bytes] = field(default_factory=dict)
    download_bytes: bytes = b"fixture,payload\n1,alpha\n2,beta\n"
    otp_code: str = "654321"
    api_token: str = "fixture-api-token"


def _parse_graph_time(value: str) -> datetime:
    return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).astimezone(UTC)


def build_fake_app(state: FixtureState | None = None) -> FastAPI:
    state = state or FixtureState()
    app = FastAPI(title="UAF local fixtures")
    app.state.fixture = state

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/download")
    def download() -> PlainTextResponse:
        return PlainTextResponse(state.download_bytes.decode())

    @app.get("/status/{code}")
    def status(code: int) -> PlainTextResponse:
        return PlainTextResponse(f"status {code}", status_code=code)

    @app.post("/echo")
    def echo(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        return {"echo": payload, "ok": True}

    @app.get("/large")
    def large() -> PlainTextResponse:
        return PlainTextResponse("x" * 5000)

    @app.get("/portal", response_class=HTMLResponse)
    def portal() -> str:
        return """
        <html><body><h1>Fixture Portal</h1>
        <form method="post" action="/portal/login">
          <input name="username" id="username" />
          <input name="password" id="password" type="password" />
          <button type="submit" id="login">Sign in</button>
        </form></body></html>
        """

    @app.get("/portal/login/otp", response_class=HTMLResponse)
    def portal_otp_login_page() -> str:
        return """
        <html><body><h1>Fixture Portal (OTP)</h1>
        <form method="post" action="/portal/login">
          <input type="hidden" name="otp_required" value="1" />
          <input name="username" id="username" />
          <input name="password" id="password" type="password" />
          <button type="submit" id="login">Sign in</button>
        </form></body></html>
        """

    @app.post("/portal/login", response_class=HTMLResponse)
    def portal_login(
        response: Response,
        username: str = Form(default=""),
        password: str = Form(default=""),
        otp_required: str = Form(default=""),
    ) -> str:
        if username != "demo" or password != "correct-horse":
            response.status_code = 401
            return "<html><body>denied</body></html>"
        response.set_cookie("fixture_session", "fixture-session", httponly=True)
        state.portal_sessions.add("fixture-session")
        if otp_required:
            return """
            <html><body><h1>Two-step verification</h1>
            <form method="post" action="/portal/otp">
              <input name="code" id="otp" autocomplete="one-time-code" />
              <button type="submit" id="verify">Verify</button>
            </form></body></html>
            """
        return """
        <html><body><h1>Welcome</h1>
        <div id="otp">654321</div>
        <a id="download" href="/portal/report.csv">Download report</a>
        </body></html>
        """

    @app.post("/portal/otp", response_class=HTMLResponse)
    def portal_otp(
        response: Response,
        request: Request,
        code: str = Form(default=""),
    ) -> str:
        if request.cookies.get("fixture_session") not in state.portal_sessions:
            response.status_code = 401
            return "<html><body>expired session</body></html>"
        if code != state.otp_code:
            response.status_code = 401
            return "<html><body>invalid code</body></html>"
        return '<html><body><div id="verified">verified</div></body></html>'

    @app.get("/portal/report.csv")
    def portal_report(request: Request) -> PlainTextResponse:
        if request.cookies.get("fixture_session") not in state.portal_sessions:
            raise HTTPException(status_code=401, detail="expired session")
        return PlainTextResponse("account,amount\n1000,42.50\n")

    @app.get("/portal/api/report")
    def portal_api_report(x_api_token: str = Header(default="")) -> dict[str, Any]:
        if x_api_token != state.api_token:
            raise HTTPException(status_code=401, detail="bad API token")
        return {"account": "1000", "amount": 42.5, "source": "api-token"}

    @app.post("/{tenant}/oauth2/v2.0/token")
    def graph_token(tenant: str, client_secret: str = Form(default="")) -> dict[str, Any]:
        if client_secret != "fixture-secret":
            raise HTTPException(status_code=401, detail="bad client secret")
        return {"access_token": "fixture-token", "token_type": "Bearer", "expires_in": 3600}

    @app.post("/v1.0/users/{mailbox}/sendMail")
    def send_mail(
        mailbox: str,
        payload: dict[str, Any] = Body(default={}),
        authorization: str = Header(default=""),
    ) -> Response:
        if authorization != "Bearer fixture-token":
            raise HTTPException(status_code=401, detail="bad token")
        state.sent_mail.append({"mailbox": mailbox, **payload})
        return Response(status_code=202)

    @app.get("/v1.0/users/{mailbox}/messages")
    def messages(
        mailbox: str,
        request: Request,
        authorization: str = Header(default=""),
    ) -> dict[str, Any]:
        if authorization != "Bearer fixture-token":
            raise HTTPException(status_code=401, detail="bad token")
        items = [dict(item) for item in state.messages]
        filter_expression = request.query_params.get("$filter", "")
        for clause in filter_expression.split(" and "):
            clause = clause.strip()
            if clause.startswith("receivedDateTime ge "):
                moment = _parse_graph_time(clause.removeprefix("receivedDateTime ge ").strip())
                items = [
                    item
                    for item in items
                    if _parse_graph_time(str(item["receivedDateTime"])) >= moment
                ]
            elif clause.startswith("from/emailAddress/address eq "):
                sender = clause.removeprefix("from/emailAddress/address eq ").strip(" '")
                items = [
                    item
                    for item in items
                    if item["from"]["emailAddress"]["address"].lower() == sender.lower()
                ]
        order = request.query_params.get("$orderby", "")
        if order.startswith("receivedDateTime"):
            items.sort(
                key=lambda item: str(item["receivedDateTime"]),
                reverse="desc" in order.lower(),
            )
        if request.query_params.get("$top"):
            items = items[: int(request.query_params["$top"])]
        selected = request.query_params.get("$select")
        if selected:
            fields = [field.strip() for field in selected.split(",") if field.strip()]
            items = [{field: item[field] for field in fields if field in item} for item in items]
        return {"value": items}

    @app.put("/v1.0/users/{mailbox}/drive/root:/{item_path:path}:/content")
    async def upload(
        mailbox: str,
        item_path: str,
        request: Request,
        authorization: str = Header(default=""),
    ) -> dict[str, Any]:
        if authorization != "Bearer fixture-token":
            raise HTTPException(status_code=401, detail="bad token")
        state.uploads[item_path] = await request.body()
        return {
            "id": f"upload-{len(state.uploads)}",
            "name": item_path.rsplit("/", 1)[-1],
            "size": len(state.uploads[item_path]),
        }

    @app.post("/v1/chat/completions")
    def chat(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        state.llm_requests.append(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"invoice_number": "INV-100", "amount": "42.50", "supplier": "Acme"}
                        )
                    }
                }
            ]
        }

    return app


@dataclass
class FakeSmtpServer:
    port: int
    messages: list[str]
    _server: socket.socket
    _thread: threading.Thread

    def stop(self) -> None:
        with contextlib.suppress(OSError):
            self._server.close()


def start_smtp_sink() -> FakeSmtpServer:
    """A tiny SMTP sink: enough for the email activity, no delivery."""
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    port = int(listener.getsockname()[1])
    messages: list[str] = []
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                listener.settimeout(0.5)
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with connection:
                connection.sendall(b"220 fixture ESMTP\r\n")
                data_mode = False
                buffer: list[str] = []
                while True:
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    if data_mode:
                        text = chunk.decode("utf-8", errors="replace")
                        if "\r\n.\r\n" in text:
                            body, _, _ = text.partition("\r\n.\r\n")
                            buffer.append(body)
                            messages.append("".join(buffer))
                            buffer = []
                            data_mode = False
                            connection.sendall(b"250 queued\r\n")
                        else:
                            buffer.append(text)
                        continue
                    command = chunk.decode("utf-8", errors="replace").strip()
                    upper = command.upper()
                    if upper.startswith("EHLO") or upper.startswith("HELO"):
                        connection.sendall(b"250-fixture\r\n250 8BITMIME\r\n")
                    elif upper.startswith("MAIL FROM") or upper.startswith("RCPT TO"):
                        connection.sendall(b"250 ok\r\n")
                    elif upper == "DATA":
                        data_mode = True
                        connection.sendall(b"354 end with .\r\n")
                    elif upper == "QUIT":
                        connection.sendall(b"221 bye\r\n")
                        break
                    else:
                        connection.sendall(b"250 ok\r\n")

    thread = threading.Thread(target=serve, daemon=True, name="uaf-smtp")
    thread.start()
    return FakeSmtpServer(port, messages, listener, thread)


__all__ = [
    "FakeSmtpServer",
    "FixtureState",
    "RunningServer",
    "build_fake_app",
    "start_server",
    "start_smtp_sink",
]
