"""The only process that writes to the display."""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import ipc
from .config import config_path, load
from .device import Device, DeviceError, NotFound, PermissionDenied
from .fields import to_reading
from .protocol import Encoder, Reading, closing_packet
from .sensors import Source, discover, read_all

log = logging.getLogger("darkflash-lcd")
RETRY_S = 2.0
TEST_FRAMES = [Reading(888, 188, 188, 8888), Reading(0, 0, 0, 0), Reading(1888, 199, 199, 9999)]


class Daemon:
    def __init__(self, open_device: Callable[[], Device],
                 sources_factory: Callable[[], list[Source]], cfg_path: Path) -> None:
        self._open = open_device
        self._sources_factory = sources_factory
        self.cfg_path = cfg_path
        self.cfg, err = load(cfg_path)
        self.sources = {s.id: s for s in sources_factory()}
        self.enc = Encoder()
        self.dev: Device | None = None
        self._next_open = 0.0
        self._preview: tuple[Reading, float] | None = None
        self._test_until = 0.0
        self._lock = threading.Lock()
        self.state: dict = {"connection": "not_found", "values": {}, "reading": None,
                            "errors": [err] if err else [], "paused": False, "device": None}

    # ---- device ----
    def _ensure_device(self) -> bool:
        if self.dev is not None:
            return True
        if time.monotonic() < self._next_open:
            return False
        try:
            self.dev = self._open()
            self.state.update(connection="connected", device=self.dev.path)
            log.info("display connected at %s", self.dev.path)
            return True
        except NotFound:
            conn = "not_found"
        except PermissionDenied as e:
            conn = "no_permission"
            self.state["device"] = e.path
        except DeviceError:
            conn = "error"
        if self.state["connection"] != conn:
            log.warning("display unavailable: %s", conn)
        self.state["connection"] = conn
        self._next_open = time.monotonic() + RETRY_S
        return False

    # ---- one refresh ----
    def tick(self) -> None:
        with self._lock:
            ids = list(self.cfg.fields)
            vals = read_all([self.sources[i] for i in ids if i in self.sources])
            errors = [f"unknown sensor: {i}" for i in ids if i not in self.sources]
            errors += [f"sensor read failed: {i}" for i in ids if i in vals and vals[i] is None]
            reading = to_reading([vals.get(i) for i in ids],
                                 [self.sources[i].kind if i in self.sources else None for i in ids],
                                 self.cfg.unit)
            now = time.monotonic()
            if now < self._test_until:
                reading = TEST_FRAMES[int(now * 2) % len(TEST_FRAMES)]
            elif self._preview and now < self._preview[1]:
                reading = self._preview[0]
            else:
                self._preview = None
            self.state.update(values={i: vals.get(i) for i in ids}, reading=reading.__dict__,
                              errors=errors)
            if self.state["paused"] or not self._ensure_device():
                return
            try:
                self.dev.write(self.enc.encode(reading))
            except DeviceError as e:
                log.warning("%s", e)
                self.dev = None
                self.state["connection"] = "error"
                self._next_open = time.monotonic() + RETRY_S

    # ---- IPC ----
    def handle(self, msg: dict) -> dict:
        cmd = msg.get("cmd")
        if cmd == "status":
            return {"ok": True, **self.state, "config": self.cfg.__dict__ | {"fields": list(self.cfg.fields)}}
        if cmd == "reload":
            cfg, err = load(self.cfg_path)
            if err:
                return {"ok": False, "error": err}
            with self._lock:
                self.cfg = cfg
                self.sources = {s.id: s for s in self._sources_factory()}
            return {"ok": True}
        if cmd == "sensors":
            vals = read_all(list(self.sources.values()))
            return {"ok": True, "sensors": [
                {"id": s.id, "name": s.name, "kind": s.kind, "unit": s.unit, "value": vals[s.id]}
                for s in self.sources.values()]}
        if cmd == "preview":
            v = [int(x) for x in msg["values"]]
            self._preview = (Reading(*v), time.monotonic() + float(msg.get("seconds", 5)))
            return {"ok": True}
        if cmd == "test":
            self._test_until = time.monotonic() + 6
            return {"ok": True}
        if cmd in ("pause", "resume"):
            self.state["paused"] = cmd == "pause"
            return {"ok": True}
        return {"ok": False, "error": f"unknown command: {cmd}"}

    def run(self, stop: threading.Event) -> None:
        try:
            while True:  # always at least one refresh
                self.tick()
                if stop.wait(self.cfg.interval_ms / 1000):
                    break
        finally:
            if self.dev is not None:
                try:
                    self.dev.write(closing_packet())
                except DeviceError:
                    pass
                self.dev.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    d = Daemon(Device.open, discover, config_path())
    try:
        srv = ipc.serve(ipc.socket_path(), d.handle)
    except RuntimeError as e:
        log.error("%s", e)
        return 1
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    log.info("darkflash-lcd daemon started")
    try:
        d.run(stop)
    finally:
        srv.shutdown()
        srv.server_close()
        ipc.socket_path().unlink(missing_ok=True)
    return 0
