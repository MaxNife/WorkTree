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
from typing import Any

import uvicorn
from fastapi import Body, FastAPI, Form, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse


@dataclass
class RunningServer:
    base_url: str
    server: uvicorn.Server
    thread: threading.Thread

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_server(app: FastAPI) -> RunningServer:
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
    return RunningServer(f"http://127.0.0.1:{port}", server, thread)


@dataclass
class FixtureState:
    messages: list[dict[str, Any]] = field(default_factory=list)
    sent_mail: list[dict[str, Any]] = field(default_factory=list)
    portal_sessions: set[str] = field(default_factory=lambda: {"fixture-session"})
    llm_requests: list[dict[str, Any]] = field(default_factory=list)
    download_bytes: bytes = b"fixture,payload\n1,alpha\n2,beta\n"


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

    @app.post("/portal/login", response_class=HTMLResponse)
    def portal_login(
        response: Response,
        username: str = Form(default=""),
        password: str = Form(default=""),
    ) -> str:
        if username != "demo" or password != "correct-horse":
            response.status_code = 401
            return "<html><body>denied</body></html>"
        response.set_cookie("fixture_session", "fixture-session", httponly=True)
        return """
        <html><body><h1>Welcome</h1>
        <div id="otp">654321</div>
        <a id="download" href="/portal/report.csv">Download report</a>
        </body></html>
        """

    @app.get("/portal/report.csv")
    def portal_report(request: Request) -> PlainTextResponse:
        if request.cookies.get("fixture_session") not in state.portal_sessions:
            raise HTTPException(status_code=401, detail="expired session")
        return PlainTextResponse("account,amount\n1000,42.50\n")

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
        authorization: str = Header(default=""),
    ) -> dict[str, Any]:
        if authorization != "Bearer fixture-token":
            raise HTTPException(status_code=401, detail="bad token")
        return {"value": state.messages}

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
