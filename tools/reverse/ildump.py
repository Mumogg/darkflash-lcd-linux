import sys, re
import dnfile
from dncil.cil.body import CilMethodBody
from dncil.cil.body.reader import CilMethodBodyReaderBase
from dncil.cil.error import MethodBodyFormatError
from dncil.clr.token import Token, StringToken, InvalidToken

path, pattern = sys.argv[1], sys.argv[2]
pe = dnfile.dnPE(path)
md = pe.net.mdtables


class Reader(CilMethodBodyReaderBase):
    def __init__(self, pe, rva):
        self.pe = pe
        self.offset = pe.get_offset_from_rva(rva)

    def read(self, n):
        d = self.pe.get_data(self.pe.get_rva_from_offset(self.offset), n)
        self.offset += n
        return d

    def tell(self):
        return self.offset

    def seek(self, off):
        self.offset = off
        return off


def tname(row):
    try:
        return f"{row.TypeNamespace}.{row.TypeName}"
    except Exception:
        return "?"


# map methoddef index -> owning type name, fields likewise
meth_owner, field_owner = {}, {}
tds = list(md.TypeDef)
for i, td in enumerate(tds):
    for m in td.MethodList:
        meth_owner[m.row_index] = td.TypeName
    for f in td.FieldList:
        field_owner[f.row_index] = td.TypeName


def resolve(tok):
    if isinstance(tok, StringToken):
        return repr(pe.net.user_strings.get(tok.rid).value)
    if not isinstance(tok, Token):
        return str(tok)
    t, rid = tok.table, tok.rid
    try:
        if t == 0x06:
            return f"{meth_owner.get(rid,'?')}::{md.MethodDef[rid-1].Name}"
        if t == 0x04:
            return f"{field_owner.get(rid,'?')}::{md.Field[rid-1].Name}"
        if t == 0x0A:
            r = md.MemberRef[rid-1]
            par = r.Class.row
            pn = getattr(par, "TypeName", None) or getattr(par, "Name", "?")
            return f"{pn}::{r.Name}"
        if t == 0x01:
            return tname(md.TypeRef[rid-1])
        if t == 0x02:
            return tds[rid-1].TypeName
        if t == 0x2B:
            r = md.MethodSpec[rid-1]
            return f"spec:{getattr(r.Method.row,'Name','?')}"
        if t == 0x1B:
            return f"typespec#{rid}"
    except Exception as e:
        return f"tok{t:x}:{rid}({e})"
    return f"tok{t:x}:{rid}"


rx = re.compile(pattern)
for rid, row in enumerate(md.MethodDef, 1):
    full = f"{meth_owner.get(rid,'?')}::{row.Name}"
    if not rx.search(full) or not row.Rva:
        continue
    try:
        body = CilMethodBody(Reader(pe, row.Rva))
    except MethodBodyFormatError as e:
        print(full, "ERR", e)
        continue
    print(f"\n===== {full}")
    for ins in body.instructions:
        op = ins.operand
        if isinstance(op, (Token, StringToken)):
            op = resolve(op)
        elif isinstance(op, list):
            op = [hex(x) if isinstance(x, int) else x for x in op]
        elif isinstance(op, int):
            op = f"{op} (0x{op & 0xffffffff:x})"
        print(f"  {ins.offset:04x} {ins.opcode} {'' if op is None else op}")
