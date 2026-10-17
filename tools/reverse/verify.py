import sys, random, json
sys.path.insert(0, __file__.rsplit("/", 1)[0]); sys.path.insert(0, sys.argv[1])
from oracle import make_vm, packet
from protocol import Encoder, Reading
vm, sent, _ = make_vm()
enc = Encoder()
vm.fields["frmMain::sendi"] = 0; vm.fields["frmMain::error_shandeng"] = 0
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 5)
bad = 0; golden = []
special = [(0,0,0,0),(425,12,34,1234),(999,199,199,9999),(1000,0,0,0),(1234,100,100,1000),(1234,5,5,5),(5,1,1,1),(50,10,10,10),(100,99,99,99),(1009,0,100,0)]
cases = special + [(random.choice([random.randint(0,999), random.randint(0,1300)]), random.randint(0,199), random.randint(0,199), random.randint(0,9999)) for _ in range(4000)]
for c in cases:
    v0, v1, v2, v3 = c
    want = packet(vm, sent, [v0, v1, v2, v3, int(v0/10), v2, 0])
    got = enc.encode(Reading(*c))
    if want != got:
        bad += 1
        if bad < 5: print("MISMATCH", c, "\n want", want.hex(" "), "\n got ", got.hex(" "))
    golden.append({"in": list(c), "out": want.hex()})
print("cases", len(cases), "mismatches", bad)
if len(sys.argv) > 3: json.dump(golden[:400], open(sys.argv[3], "w"))
