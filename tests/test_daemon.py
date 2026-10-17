import threading

import pytest

from darkflash_lcd import ipc
from darkflash_lcd.config import Config, save
from darkflash_lcd.daemon import Daemon
from darkflash_lcd.device import DeviceError, NotFound
from darkflash_lcd.sensors import Source


class FakeDevice:
    def __init__(self, fail_after=None):
        self.packets = []
        self.fail_after = fail_after
        self.path = "/dev/hidraw-fake"

    def write(self, p):
        if self.fail_after is not None and len(self.packets) >= self.fail_after:
            raise DeviceError("unplugged")
        self.packets.append(p)

    def close(self):
        pass


def sources(temp=42.5):
    return [
        Source("cpu.temp", "CPU", "temp", "°C", lambda: temp),
        Source("cpu.usage", "CPU %", "percent", "%", lambda: 12.0),
        Source("ram.usage", "RAM %", "percent", "%", lambda: 34.0),
        Source("cpu.freq", "MHz", "freq", "MHz", lambda: 1234.0),
    ]


def make(tmp_path, devices):
    it = iter(devices)

    def opener():
        d = next(it)
        if isinstance(d, Exception):
            raise d
        return d

    return Daemon(opener, sources, tmp_path / "config.toml")


def test_tick_writes_encoded_reading(tmp_path):
    dev = FakeDevice()
    d = make(tmp_path, [dev])
    d.tick()
    assert len(dev.packets) == 1
    assert dev.packets[0][5:8] == bytes([4, 2, 5])
    assert d.state["connection"] == "connected"


def test_not_found_is_reported_and_retried(tmp_path):
    dev = FakeDevice()
    d = make(tmp_path, [NotFound("x"), dev])
    d.tick()
    assert d.state["connection"] == "not_found"
    d._next_open = 0  # skip the 2 s back-off
    d.tick()
    assert d.state["connection"] == "connected" and dev.packets


def test_reconnects_after_write_error(tmp_path):
    first, second = FakeDevice(fail_after=1), FakeDevice()
    d = make(tmp_path, [first, second])
    d.tick()
    d.tick()  # write fails -> disconnected
    assert d.state["connection"] == "error"
    d._next_open = 0
    d.tick()
    assert second.packets and d.state["connection"] == "connected"


def test_missing_source_sends_zero_and_reports(tmp_path):
    save(tmp_path / "config.toml", Config(fields=("nope.temp", "cpu.usage", "ram.usage", "cpu.freq")))
    dev = FakeDevice()
    d = make(tmp_path, [dev])
    d.tick()
    assert dev.packets[0][5:8] == bytes([0, 0, 0])
    assert any("nope.temp" in e for e in d.state["errors"])


def test_reload_with_bad_config_keeps_previous(tmp_path):
    p = tmp_path / "config.toml"
    save(p, Config(interval_ms=300))
    d = make(tmp_path, [FakeDevice()])
    p.write_text("interval_ms = [")
    r = d.handle({"cmd": "reload"})
    assert r["ok"] is False and d.cfg.interval_ms == 300


def test_preview_overrides_values_then_expires(tmp_path, monkeypatch):
    dev = FakeDevice()
    d = make(tmp_path, [dev])
    now = [1000.0]
    monkeypatch.setattr("darkflash_lcd.daemon.time.monotonic", lambda: now[0])
    assert d.handle({"cmd": "preview", "values": [999, 1, 2, 3], "seconds": 5})["ok"]
    d.tick()
    assert dev.packets[-1][5:8] == bytes([9, 9, 9])
    now[0] += 6
    d.tick()
    assert dev.packets[-1][5:8] == bytes([4, 2, 5])


def test_pause_stops_writes(tmp_path):
    dev = FakeDevice()
    d = make(tmp_path, [dev])
    d.handle({"cmd": "pause"})
    d.tick()
    assert not dev.packets
    d.handle({"cmd": "resume"})
    d.tick()
    assert dev.packets


def test_sensors_command_lists_sources(tmp_path):
    d = make(tmp_path, [FakeDevice()])
    r = d.handle({"cmd": "sensors"})
    assert {s["id"] for s in r["sensors"]} >= {"cpu.temp", "cpu.freq"}
    assert r["sensors"][0]["value"] == 42.5


def test_unknown_command(tmp_path):
    assert make(tmp_path, [FakeDevice()]).handle({"cmd": "x"})["ok"] is False


def test_ipc_roundtrip(tmp_path):
    sock = tmp_path / "s.sock"
    srv = ipc.serve(sock, lambda m: {"ok": True, "echo": m})
    try:
        assert ipc.request({"cmd": "status"}, sock)["echo"] == {"cmd": "status"}
    finally:
        srv.shutdown()
        srv.server_close()


def test_request_without_daemon_raises(tmp_path):
    with pytest.raises(ConnectionError):
        ipc.request({"cmd": "status"}, tmp_path / "none.sock")


def test_stale_socket_is_replaced(tmp_path):
    sock = tmp_path / "s.sock"
    sock.write_text("")  # leftover file from a crash, nobody listening
    srv = ipc.serve(sock, lambda m: {"ok": True})
    try:
        assert ipc.request({"cmd": "status"}, sock)["ok"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_second_server_refuses_when_first_alive(tmp_path):
    sock = tmp_path / "s.sock"
    srv = ipc.serve(sock, lambda m: {"ok": True})
    try:
        with pytest.raises(RuntimeError):
            ipc.serve(sock, lambda m: {"ok": True})
    finally:
        srv.shutdown()
        srv.server_close()


def test_run_loop_stops_and_sends_closing_packet(tmp_path):
    dev = FakeDevice()
    d = make(tmp_path, [dev])
    stop = threading.Event()
    t = threading.Thread(target=d.run, args=(stop,))
    t.start()
    stop.set()
    t.join(timeout=3)
    assert not t.is_alive()
    assert dev.packets[-1][1] == 15


def test_test_pattern_holds_each_frame_two_seconds(tmp_path, monkeypatch):
    dev = FakeDevice()
    d = make(tmp_path, [dev])
    now = [1000.0]
    monkeypatch.setattr("darkflash_lcd.daemon.time.monotonic", lambda: now[0])
    d.handle({"cmd": "test"})
    for _ in range(4):  # 0.0, 0.5, 1.0, 1.5 s -> same frame
        d.tick()
        now[0] += 0.5
    d.tick()  # 2.0 s -> next frame
    first = {p[5:20] for p in dev.packets[:4]}
    assert len(first) == 1
    assert dev.packets[4][5:20] not in first


def test_startup_config_error_survives_tick(tmp_path):
    (tmp_path / "config.toml").write_text("interval_ms = [")
    d = make(tmp_path, [FakeDevice()])
    d.tick()
    assert d.state["config_error"]
    assert d.handle({"cmd": "status"})["config_error"]


def test_failed_reload_shows_in_status_until_fixed(tmp_path):
    p = tmp_path / "config.toml"
    d = make(tmp_path, [FakeDevice()])
    p.write_text("interval_ms = [")
    d.handle({"cmd": "reload"})
    d.tick()
    assert d.handle({"cmd": "status"})["config_error"]
    save(p, Config())
    assert d.handle({"cmd": "reload"})["ok"]
    assert d.handle({"cmd": "status"})["config_error"] is None


def test_request_with_no_reply_raises_connection_error(tmp_path):
    import socket as s
    import threading as th

    sock = tmp_path / "mute.sock"
    srv = s.socket(s.AF_UNIX, s.SOCK_STREAM)
    srv.bind(str(sock))
    srv.listen(1)

    def accept_and_close():
        conn, _ = srv.accept()
        conn.recv(1024)
        conn.close()

    t = th.Thread(target=accept_and_close)
    t.start()
    try:
        with pytest.raises(ConnectionError):
            ipc.request({"cmd": "status"}, sock)
    finally:
        t.join()
        srv.close()


def test_fallback_socket_dir_is_private(tmp_path, monkeypatch):
    import stat
    import tempfile

    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    path = ipc.socket_path()
    mode = (path.parent).stat().st_mode
    assert path.parent.parent == tmp_path
    assert stat.S_IMODE(mode) == 0o700


def test_fallback_socket_dir_rejects_shared_dir(tmp_path, monkeypatch):
    import os
    import tempfile

    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    d = tmp_path / f"darkflash-lcd-{os.getuid()}"
    d.mkdir()
    d.chmod(0o777)
    with pytest.raises(RuntimeError):
        ipc.socket_path()
    with pytest.raises(ConnectionError):
        ipc.request({"cmd": "status"})
