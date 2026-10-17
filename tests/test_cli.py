import json

from darkflash_lcd import cli, i18n
from tests.test_device import make_sys


def test_i18n_spanish(monkeypatch):
    monkeypatch.setenv("LANG", "es_CR.UTF-8")
    assert i18n.t("doctor.usb_ok", node="x") != i18n.t("doctor.usb_ok", lang="en", node="x")


def test_doctor_reports_missing_usb(tmp_path):
    checks = cli.doctor(sys_root=make_sys(tmp_path, {}), dev_root=tmp_path, rules_dirs=())
    assert checks[0][0] is False


def test_doctor_reports_permission(tmp_path, monkeypatch):
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    sys_root = make_sys(tmp_path, {"hidraw6": "0003:00005131:00002007"})
    dev = tmp_path / "dev"
    dev.mkdir()
    (dev / "hidraw6").write_bytes(b"")
    (dev / "hidraw6").chmod(0o000)
    checks = cli.doctor(sys_root=sys_root, dev_root=dev, rules_dirs=())
    texts = " ".join(t for _, t in checks)
    assert checks[0][0] is True
    assert "udev" in texts


def test_sensors_command_without_daemon_reads_directly(capsys, monkeypatch):
    monkeypatch.setattr(cli.ipc, "request", lambda *a, **k: (_ for _ in ()).throw(ConnectionError()))
    assert cli.main(["sensors", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert any(s["id"] == "cpu.usage" for s in data)


def test_config_set_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(cli.ipc, "request", lambda *a, **k: {"ok": True})
    assert cli.main(["config", "set", "field1", "gpu.temp"]) == 0
    assert '"gpu.temp"' in (tmp_path / "darkflash-lcd" / "config.toml").read_text()


def test_show_requires_daemon(monkeypatch, capsys):
    monkeypatch.setattr(cli.ipc, "request", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("x")))
    assert cli.main(["show", "425", "1", "2", "3"]) == 1


def test_config_set_rejects_invalid_unit(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(cli.ipc, "request", lambda *a, **k: {"ok": True})
    assert cli.main(["config", "set", "unit", "K"]) == 1
    assert not (tmp_path / "darkflash-lcd" / "config.toml").exists()


def test_config_set_rejects_non_number_interval(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(cli.ipc, "request", lambda *a, **k: {"ok": True})
    assert cli.main(["config", "set", "interval_ms", "abc"]) == 1
    assert cli.main(["config", "set", "interval_ms", "50"]) == 1


def test_reload_command_reports_daemon_error(monkeypatch, capsys):
    monkeypatch.setattr(cli.ipc, "request", lambda *a, **k: {"ok": False, "error": "bad toml"})
    assert cli.main(["reload"]) == 1
    assert "bad toml" in capsys.readouterr().out


def test_config_set_reports_failed_reload(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(cli.ipc, "request", lambda *a, **k: {"ok": False, "error": "boom"})
    assert cli.main(["config", "set", "field1", "gpu.temp"]) == 1
    assert "boom" in capsys.readouterr().out
