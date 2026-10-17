"""JSON-lines over a Unix socket between the daemon and the CLI/GUI."""

from __future__ import annotations

import json
import os
import socket
import socketserver
import stat
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path


def _private_fallback_dir() -> Path:
    """Per-user dir in /tmp for when XDG_RUNTIME_DIR is unset; must be ours and 0700."""
    d = Path(tempfile.gettempdir()) / f"darkflash-lcd-{os.getuid()}"
    try:
        d.mkdir(mode=0o700)
    except FileExistsError:
        pass
    st = os.lstat(d)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise RuntimeError(f"refusing to use {d}: not a private directory owned by you")
    return d


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else _private_fallback_dir()
    return base / "darkflash-lcd.sock"


def request(msg: dict, path: Path | None = None, timeout: float = 2.0) -> dict:
    try:
        path = path or socket_path()
    except RuntimeError as e:
        raise ConnectionError(str(e)) from e
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(path))
            s.sendall(json.dumps(msg).encode() + b"\n")
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
    except OSError as e:
        raise ConnectionError(f"darkflash-lcd daemon not reachable at {path}: {e}") from e
    try:
        return json.loads(buf)
    except ValueError as e:
        raise ConnectionError(f"darkflash-lcd daemon at {path} closed without a valid reply") from e


def _alive(path: Path) -> bool:
    try:
        request({"cmd": "status"}, path, timeout=0.5)
        return True
    except ConnectionError:
        return False


def serve(path: Path, handler: Callable[[dict], dict]) -> socketserver.BaseServer:
    if path.exists():
        if _alive(path):
            raise RuntimeError(f"another darkflash-lcd daemon is already running ({path})")
        path.unlink()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            line = self.rfile.readline()
            try:
                reply = handler(json.loads(line))
            except Exception as e:  # noqa: BLE001 — never kill the server on a bad message
                reply = {"ok": False, "error": str(e)}
            self.wfile.write(json.dumps(reply).encode() + b"\n")

    srv = socketserver.ThreadingUnixStreamServer(str(path), Handler)
    srv.daemon_threads = True
    os.chmod(path, 0o600)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
