"""Tiny CIL interpreter for frmMain's display-encoding methods (oracle for tests)."""
import sys, math
import dnfile
from dncil.cil.body import CilMethodBody
from dncil.clr.token import Token, StringToken
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from ildump_lib import Reader  # noqa

class VM:
    def __init__(self, path):
        self.pe = pe = dnfile.dnPE(path)
        md = self.md = pe.net.mdtables
        self.owner, self.fowner = {}, {}
        for td in md.TypeDef:
            for m in td.MethodList:
                self.owner[m.row_index] = td.TypeName
            for f in td.FieldList:
                self.fowner[f.row_index] = td.TypeName
        self.bodies = {}
        self.by_name = {}
        for rid, row in enumerate(md.MethodDef, 1):
            self.by_name[f"{self.owner.get(rid)}::{row.Name}"] = rid
        # field RVA blobs
        self.blobs = {}
        for fr in md.FieldRva:
            fidx = fr.Field.row_index
            self.blobs[fidx] = fr.Rva
        self.fields = {}  # name -> value (instance + static, flat)
        self.reads = set()

    def fname(self, tok):
        return f"{self.fowner.get(tok.rid)}::{self.md.Field[tok.rid-1].Name}"

    def blob(self, tok, n):
        return self.pe.get_data(self.blobs[tok.rid], n)

    def body(self, rid):
        if rid not in self.bodies:
            b = CilMethodBody(Reader(self.pe, self.md.MethodDef[rid-1].Rva))
            ins = b.instructions
            self.bodies[rid] = (ins, {i.offset: k for k, i in enumerate(ins)}, b)
        return self.bodies[rid]

    def nargs(self, rid):
        sig = self.md.MethodDef[rid-1].Signature.value
        # sig[0]=callconv, sig[1]=param count (compressed, small)
        return sig[1] + (1 if sig[0] & 0x20 else 0), (sig[2] != 0x01)

    def call(self, name, *args):
        return self.run(self.by_name[name], list(args))

    def run(self, rid, args):
        ins, idx, b = self.body(rid)
        loc = [0] * 16
        st = []
        pc = 0
        def jump(t):
            return idx[t]
        while True:
            i = ins[pc]; op = i.opcode.name; arg = i.operand; pc += 1
            if op == "nop": continue
            if op.startswith("ldarg"):
                n = arg.index if hasattr(arg, "index") else (int(op.split(".")[1]) if "." in op and op[-1].isdigit() else arg)
                st.append(args[n] if not isinstance(n, object.__class__) else args[n]); continue
            if op.startswith("starg"):
                n = arg.index if hasattr(arg, "index") else arg
                args[n] = st.pop(); continue
            if op.startswith("ldloc"):
                n = arg.index if hasattr(arg, "index") else (int(op.split(".")[1]) if op[-1].isdigit() else arg)
                st.append(loc[n]); continue
            if op.startswith("stloc"):
                n = arg.index if hasattr(arg, "index") else (int(op.split(".")[1]) if op[-1].isdigit() else arg)
                loc[n] = st.pop(); continue
            if op.startswith("ldc.i4"):
                if op == "ldc.i4.m1": st.append(-1)
                elif op in ("ldc.i4", "ldc.i4.s"): st.append(arg)
                else: st.append(int(op.split(".")[2]))
                continue
            if op == "ldc.r8": st.append(float(arg)); continue
            if op == "dup": st.append(st[-1]); continue
            if op == "pop": st.pop(); continue
            if op in ("add", "sub", "mul", "div", "rem", "and", "or", "shl", "shr"):
                b2 = st.pop(); a = st.pop()
                if op == "add": r = a + b2
                elif op == "sub": r = a - b2
                elif op == "mul": r = a * b2
                elif op == "div": r = (a / b2) if isinstance(a, float) or isinstance(b2, float) else int(a / b2)
                elif op == "rem": r = math.fmod(a, b2) if isinstance(a, float) else a - int(a / b2) * b2
                elif op == "and": r = a & b2
                elif op == "or": r = a | b2
                elif op == "shl": r = a << b2
                else: r = a >> b2
                st.append(r); continue
            if op == "conv.u1": st.append(int(st.pop()) & 0xFF); continue
            if op == "conv.i4": st.append(int(st.pop())); continue
            if op == "conv.r8": st.append(float(st.pop())); continue
            if op == "newarr": st.append([0] * st.pop()); continue
            if op.startswith("ldelema"):
                n = st.pop(); a = st.pop(); st.append((a, n)); continue
            if op.startswith("ldelem"):
                n = st.pop(); a = st.pop(); st.append(a[n]); continue
            if op.startswith("stelem"):
                v = st.pop(); n = st.pop(); a = st.pop()
                a[n] = (int(v) & 0xFF) if op == "stelem.i1" else v; continue
            if op.startswith("ldind"):
                a, n = st.pop(); st.append(a[n]); continue
            if op.startswith("stind"):
                v = st.pop(); a, n = st.pop(); a[n] = v; continue
            if op == "ldfld":
                st.pop(); nm = self.fname(arg); self.reads.add(nm); st.append(self.fields.get(nm, 0)); continue
            if op == "stfld":
                v = st.pop(); st.pop(); self.fields[self.fname(arg)] = v; continue
            if op == "ldsfld":
                nm = self.fname(arg); self.reads.add(nm); st.append(self.fields.get(nm, 0)); continue
            if op == "stsfld":
                self.fields[self.fname(arg)] = st.pop(); continue
            if op in ("br", "br.s", "leave", "leave.s"): pc = jump(arg); continue
            if op in ("brtrue", "brtrue.s"):
                if st.pop(): pc = jump(arg)
                continue
            if op in ("brfalse", "brfalse.s"):
                if not st.pop(): pc = jump(arg)
                continue
            if op.split(".")[0] in ("blt", "ble", "bgt", "bge", "beq", "bne"):
                b2 = st.pop(); a = st.pop(); k = op.split(".")[0]
                c = {"blt": a < b2, "ble": a <= b2, "bgt": a > b2, "bge": a >= b2, "beq": a == b2, "bne": a != b2}[k]
                if c: pc = jump(arg)
                continue
            if op == "switch":
                v = st.pop()
                if 0 <= v < len(arg): pc = jump(arg[v])
                continue
            if op in ("call", "callvirt"):
                if arg.table == 0x06:
                    n, has_ret = self.nargs(arg.rid)
                    a = st[len(st)-n:]; del st[len(st)-n:]
                    r = self.run(arg.rid, a)
                    if has_ret: st.append(r)
                    continue
                r = self.md.MemberRef[arg.rid-1]
                if r.Name == "Ceiling": st.append(math.ceil(st.pop())); continue
                raise NotImplementedError(r.Name)
            if op == "ret":
                return st.pop() if st else None
            raise NotImplementedError(f"{op} at {i.offset:x}")
