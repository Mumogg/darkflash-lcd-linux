"""`darkflash-lcd` command line."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path

from . import __version__, ipc
from .config import config_path, load, save
from .device import find_hidraw
from .i18n import t
from .sensors import discover, read_all


def doctor(sys_root: Path = Path("/sys"), dev_root: Path = Path("/dev"),
           rules_dirs=(Path("/etc/udev/rules.d"), Path("/usr/lib/udev/rules.d"))) -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    node = find_hidraw(sys_root)
    if node is None:
        return [(False, t("doctor.usb_missing"))]
    checks.append((True, t("doctor.usb_ok", node=node)))
    path = str(dev_root / node)
    ok = os.access(path, os.W_OK)
    checks.append((ok, t("doctor.perm_ok" if ok else "doctor.perm_missing", path=path)))
    rule = any((d / "70-darkflash-lcd.rules").exists() for d in rules_dirs)
    checks.append((rule, t("doctor.rule_ok" if rule else "doctor.rule_missing")))
    try:
        st = ipc.request({"cmd": "status"})
        checks.append((True, t("doctor.daemon_ok", conn=t(f"status.{st['connection']}"))))
    except ConnectionError:
        checks.append((False, t("doctor.daemon_missing")))
    srcs = discover(sys_root=sys_root)
    checks.append((True, t("doctor.sensors", n=len(srcs), ids=", ".join(s.id for s in srcs[:8]))))
    return checks


def _sensors() -> list[dict]:
    try:
        return ipc.request({"cmd": "sensors"})["sensors"]
    except ConnectionError:
        srcs = discover()
        vals = read_all(srcs)
        return [{"id": s.id, "name": s.name, "kind": s.kind, "unit": s.unit, "value": vals[s.id]}
                for s in srcs]


def _send(msg: dict) -> int:
    try:
        r = ipc.request(msg)
    except ConnectionError:
        print(t("no_daemon"))
        return 1
    if not r.get("ok"):
        print(r.get("error"))
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="darkflash-lcd",
                                description="darkFlash DN240D/DN360D pump LCD for Linux")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("daemon", help="run the display service (used by systemd)")
    sub.add_parser("status")
    s = sub.add_parser("sensors")
    s.add_argument("--json", action="store_true")
    sh = sub.add_parser("show", help="show fixed values for a few seconds")
    sh.add_argument("values", nargs=4, type=float, metavar=("TEMP", "LEFT", "RIGHT", "BOTTOM"))
    sh.add_argument("--seconds", type=float, default=10)
    for name in ("test", "pause", "resume", "doctor"):
        sub.add_parser(name)
    c = sub.add_parser("config")
    csub = c.add_subparsers(dest="action", required=True)
    csub.add_parser("get")
    cs = csub.add_parser("set")
    cs.add_argument("key", choices=["field0", "field1", "field2", "field3", "unit", "interval_ms"])
    cs.add_argument("value")
    a = p.parse_args(argv)

    if a.cmd == "daemon":
        from .daemon import main as daemon_main
        return daemon_main()
    if a.cmd == "status":
        try:
            print(json.dumps(ipc.request({"cmd": "status"}), indent=2, ensure_ascii=False))
            return 0
        except ConnectionError:
            print(t("no_daemon"))
            return 1
    if a.cmd == "sensors":
        data = _sensors()
        if a.json:
            print(json.dumps(data, ensure_ascii=False))
        else:
            for s in data:
                v = "—" if s["value"] is None else f"{s['value']:.1f} {s['unit']}"
                print(f"{s['id']:<32} {v:>12}  {s['name']}")
        return 0
    if a.cmd == "show":
        v = a.values
        return _send({"cmd": "preview", "values": [round(v[0] * 10), round(v[1]), round(v[2]), round(v[3])],
                      "seconds": a.seconds})
    if a.cmd in ("test", "pause", "resume"):
        return _send({"cmd": a.cmd})
    if a.cmd == "doctor":
        checks = doctor()
        for ok, text in checks:
            print(("✔ " if ok else "✘ ") + text)
        return 0 if all(ok for ok, _ in checks) else 1
    if a.cmd == "config":
        path = config_path()
        cfg, err = load(path)
        if a.action == "get":
            print(err or path.read_text() if path.exists() else f"(defaults) {cfg}")
            return 0
        if a.key.startswith("field"):
            fields = list(cfg.fields)
            fields[int(a.key[-1])] = a.value
            cfg = replace(cfg, fields=tuple(fields))
        elif a.key == "unit":
            cfg = replace(cfg, unit=a.value.upper())
        else:
            cfg = replace(cfg, interval_ms=int(a.value))
        save(path, cfg)
        try:
            ipc.request({"cmd": "reload"})
        except ConnectionError:
            pass
        return 0
    return 1
