# Reverse-engineering tools

These scripts were used to port the display protocol from the official Windows
app ("darkFlash DN-D Setup.msi") and to prove the Linux port is byte-exact.
You only need them if you want to re-check the work or support a new model.

1. Extract the installer and the cabinet inside it:
   ```bash
   7z x "darkFlash DN-D Setup.msi" -omsi
   7z x msi/_1B03C2AE69C4D96BB1FADDD943F56C3C -ocab   # the large cabinet stream
   ```
   The .NET executable (`ComputereMonitor`, ~10 MB, "Mono/.Net assembly") is the
   one you want; `file cab/*` finds it.
2. `python3 -m venv venv && venv/bin/pip install dnfile dncil`
3. Dump IL of methods matching a regex:
   `venv/bin/python ildump.py <exe> "SendData2|TM1721_show"`
4. Compare a `protocol.py` against the original `SendData2`, running it in the
   tiny IL interpreter (`ilvm.py`):
   ```bash
   DN_EXE=<exe> venv/bin/python verify.py ../../src/darkflash_lcd <seed> golden.json
   ```
   Prints `cases N mismatches 0` when the port matches; writes the first 400
   packets as a fixture.

`ilvm.py` implements only the CIL opcodes those display methods use.
