"""A local SFTP server rooted in a temp directory, for SFTP activity tests.

Password auth only (``demo`` / ``correct-horse``). The server never leaves the loopback
interface and every path is confined to the supplied root.
"""

from __future__ import annotations

import contextlib
import os
import posixpath
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import paramiko

USERNAME = "demo"
PASSWORD = "correct-horse"
_BINARY = getattr(os, "O_BINARY", 0)


class _AuthServer(paramiko.ServerInterface):
    def check_auth_password(self, username: str, password: str) -> int:
        if username == USERNAME and password == PASSWORD:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username: str) -> str:
        return "password"

    def check_channel_request(self, kind: str, chanid: int) -> int:
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED


class _RootedSFTPServer(paramiko.SFTPServerInterface):
    def __init__(
        self, server: paramiko.ServerInterface, root: str, *args: object, **kwargs: object
    ):
        super().__init__(server, *args, **kwargs)
        self.root = Path(root).resolve()

    def canonicalize(self, path: str) -> str:
        normalized = posixpath.normpath("/" + path.replace("\\", "/").lstrip("/"))
        if ".." in normalized.split("/"):
            raise OSError("path escapes the fixture root")
        return normalized

    def _realpath(self, path: str) -> Path:
        virtual = self.canonicalize(path)
        candidate = (self.root / virtual.lstrip("/")).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise OSError("path escapes the fixture root")
        return candidate

    def list_folder(self, path: str) -> list[paramiko.SFTPAttributes] | int:
        try:
            folder = self._realpath(path)
            entries = []
            for child in sorted(folder.iterdir()):
                attributes = paramiko.SFTPAttributes.from_stat(child.stat())
                attributes.filename = child.name
                entries.append(attributes)
            return entries
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno or 2)

    def stat(self, path: str) -> paramiko.SFTPAttributes | int:
        try:
            return paramiko.SFTPAttributes.from_stat(self._realpath(path).stat())
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno or 2)

    def lstat(self, path: str) -> paramiko.SFTPAttributes | int:
        try:
            return paramiko.SFTPAttributes.from_stat(self._realpath(path).lstat())
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno or 2)

    def open(
        self, path: str, flags: int, attr: paramiko.SFTPAttributes
    ) -> paramiko.SFTPHandle | int:
        try:
            target = self._realpath(path)
            mode = "wb" if flags & os.O_WRONLY else "r+b" if flags & os.O_RDWR else "rb"
            descriptor = os.open(target, flags | _BINARY, 0o644)
            stream = os.fdopen(descriptor, mode)
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno or 2)
        handle = paramiko.SFTPHandle(flags)
        handle.filename = str(target)
        handle.readfile = stream
        handle.writefile = stream
        return handle

    def remove(self, path: str) -> int:
        try:
            self._realpath(path).unlink()
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno or 2)
        return paramiko.SFTP_OK

    def rename(self, oldpath: str, newpath: str) -> int:
        try:
            os.replace(self._realpath(oldpath), self._realpath(newpath))
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno or 2)
        return paramiko.SFTP_OK

    def mkdir(self, path: str, attr: paramiko.SFTPAttributes) -> int:
        try:
            self._realpath(path).mkdir()
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno or 2)
        return paramiko.SFTP_OK

    def rmdir(self, path: str) -> int:
        try:
            self._realpath(path).rmdir()
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno or 2)
        return paramiko.SFTP_OK


@dataclass
class FakeSftpServer:
    host: str
    port: int
    root: Path
    _listener: socket.socket
    _stop: threading.Event
    _thread: threading.Thread
    _transports: list[paramiko.Transport] = field(default_factory=list)

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def stop(self) -> None:
        self._stop.set()
        with contextlib.suppress(OSError):
            self._listener.close()
        for transport in list(self._transports):
            transport.close()
        self._thread.join(timeout=10)


def _host_key() -> paramiko.RSAKey:
    return paramiko.RSAKey.generate(2048)


def start_sftp_server(root: Path, *, host: str = "127.0.0.1") -> FakeSftpServer:
    root.mkdir(parents=True, exist_ok=True)
    (root / "incoming").mkdir(exist_ok=True)
    (root / "welcome.txt").write_text("fixture sftp\n", encoding="utf-8")

    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, 0))
    listener.listen(5)
    listener.settimeout(0.25)
    port = int(listener.getsockname()[1])
    stop = threading.Event()
    host_key = _host_key()
    transports: list[paramiko.Transport] = []
    lock = threading.Lock()

    def handle(client: socket.socket) -> None:
        transport = paramiko.Transport(client)
        transport.add_server_key(host_key)
        transport.set_subsystem_handler("sftp", paramiko.SFTPServer, _RootedSFTPServer, str(root))
        with lock:
            transports.append(transport)
        try:
            transport.start_server(server=_AuthServer())
            channel = transport.accept(timeout=20)
            if channel is None:
                return
            while transport.is_active() and not stop.is_set():
                time.sleep(0.05)
        except (OSError, EOFError, paramiko.SSHException):
            # EOFError: the client hung up mid-handshake (e.g. it only fetched the host key).
            pass
        finally:
            transport.close()
            with lock:
                if transport in transports:
                    transports.remove(transport)

    def serve() -> None:
        while not stop.is_set():
            try:
                client, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(
                target=handle, args=(client,), name="worktree-sftp-client", daemon=True
            ).start()

    thread = threading.Thread(target=serve, name="worktree-sftp", daemon=True)
    thread.start()
    return FakeSftpServer(host, port, root, listener, stop, thread, transports)


__all__ = ["PASSWORD", "USERNAME", "FakeSftpServer", "start_sftp_server"]
