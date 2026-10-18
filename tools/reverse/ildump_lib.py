from dncil.cil.body.reader import CilMethodBodyReaderBase

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


