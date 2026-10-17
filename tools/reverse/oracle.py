"""Run the original SendData2 on given values and print the 64-byte packet(s)."""
import sys, struct, json
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from ilvm import VM

import os
EXE = os.environ.get("DN_EXE") or sys.argv[1]


def make_vm():
    vm = VM(EXE)
    md = vm.md
    pid = {}
    for td in md.TypeDef:
        if "PrivateImplementationDetails" in str(td.TypeName):
            for f in td.FieldList:
                pid[str(f.row.Name)] = f.row_index
    def blob(name, n):
        rva = vm.blobs[pid[name]]
        return vm.pe.get_data(rva, n)
    duan = list(struct.unpack("<60i", blob("DC2A712D256B788681382ABEBF98CAA0F46EAC19DACE990D3D2F78719361BCC1", 240)))
    wei = list(blob("5C5A4C2C9CC939C1780DD1720FF6951074C1F2E1D3AC9684002D55429F29F3DE", 60))
    show60 = list(struct.unpack("<61i", blob("C6378DD9B5E4E419984EF8468B65AE06ED2213EAE0A7808A8E6A7DC20AE679AC", 244)))
    vm.fields.update({
        "frmMain::lcd_buf": [0] * 16,
        "frmMain::kedu60duan": duan,
        "frmMain::kedu60wei": wei,
        "ClsMain::Show60_Index": show60,
    })
    sent = []
    send_rid = vm.by_name["frmMain::send_usb_data"]
    orig = vm.run
    def run(rid, args):
        if rid == send_rid:
            sent.append(bytes(int(x) & 0xFF for x in args[1][: args[2]]))
            return True
        return orig(rid, args)
    vm.run = run
    return vm, sent, dict(duan=duan, wei=wei, show60=show60)


def packet(vm, sent, values, extra=None):
    va = [0] * 20
    for k, v in enumerate(values):
        va[k] = v
    vm.fields["frmMain::ValueArray"] = va
    for k, v in (extra or {}).items():
        vm.fields[k] = v
    vm.call("frmMain::SendData2", None, va)
    return sent[-1]


if __name__ == "__main__":
    vm, sent, tables = make_vm()
    if sys.argv[2] == "tables":
        print(json.dumps(tables))
    else:
        vals = [int(x) for x in sys.argv[2].split(",")]
        p = packet(vm, sent, vals)
        print(p.hex(" "))
        print("reads:", sorted(vm.reads))
