"""Escritor de PDF mínimo (sin dependencias): una página con texto, rectángulos, líneas, una imagen RGB y
un código QR vectorial. Usa las fuentes estándar Helvetica / Helvetica-Bold (WinAnsi)."""
from __future__ import annotations

import zlib


def _esc(s: str) -> bytes:
    b = s.encode("cp1252", "replace")
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _rgb(c) -> str:
    if isinstance(c, str):
        c = tuple(int(c.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return " ".join(f"{v:.3f}" for v in c)


class Pagina:
    def __init__(self, w: float = 612, h: float = 792):
        self.w, self.h = w, h
        self.ops: list[str] = []
        self.imagenes: list[tuple[int, int, bytes]] = []

    def _y(self, y):
        return self.h - y

    def rect(self, x, y, w, h, fill=None, stroke=None, lw=0.8):
        if fill:
            self.ops.append(f"{_rgb(fill)} rg {x:.2f} {self._y(y + h):.2f} {w:.2f} {h:.2f} re f")
        if stroke:
            self.ops.append(f"{_rgb(stroke)} RG {lw} w {x:.2f} {self._y(y + h):.2f} {w:.2f} {h:.2f} re S")

    def linea(self, x1, y1, x2, y2, color="#CBD5E1", lw=0.8):
        self.ops.append(f"{_rgb(color)} RG {lw} w {x1:.2f} {self._y(y1):.2f} m {x2:.2f} {self._y(y2):.2f} l S")

    def texto(self, x, y, s, size=10, negrita=False, color="#0F172A"):
        """(x, y) = esquina izquierda de la línea base."""
        fuente = "F2" if negrita else "F1"
        self.ops.append(f"BT /{fuente} {size} Tf {_rgb(color)} rg {x:.2f} {self._y(y):.2f} Td ({_esc(s).decode('latin-1')}) Tj ET")

    def imagen(self, datos: tuple[int, int, bytes], x, y, w, h):
        """datos = (ancho_px, alto_px, bytes RGB comprimidos con zlib)."""
        self.imagenes.append(datos)
        n = len(self.imagenes)
        self.ops.append(f"q {w:.2f} 0 0 {h:.2f} {x:.2f} {self._y(y + h):.2f} cm /Im{n} Do Q")

    def qr(self, matriz, x, y, tam, color="#0F172A", borde=0):
        n = len(matriz)
        m = tam / (n + 2 * borde)
        self.ops.append(f"{_rgb(color)} rg")
        for j, fila in enumerate(matriz):
            i = 0
            while i < n:
                if fila[i]:
                    k = i
                    while k < n and fila[k]:
                        k += 1
                    self.ops.append(f"{x + (i + borde) * m:.3f} {self._y(y + (j + borde + 1) * m):.3f} {(k - i) * m + 0.15:.3f} {m + 0.15:.3f} re f")
                    i = k
                else:
                    i += 1

    def a_bytes(self) -> bytes:
        objs: list[bytes] = []

        def add(b: bytes) -> int:
            objs.append(b)
            return len(objs)

        contenido = "\n".join(self.ops).encode("latin-1")
        cat = add(b"")          # 1 catálogo (se rellena después)
        pages = add(b"")        # 2 árbol de páginas
        pag = add(b"")          # 3 página
        cont = add(b"<< /Length %d >>\nstream\n" % len(contenido) + contenido + b"\nendstream")
        f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        xobj = []
        for i, (iw, ih, z) in enumerate(self.imagenes, 1):
            num = add(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB /BitsPerComponent 8 "
                      b"/Filter /FlateDecode /Length %d >>\nstream\n" % (iw, ih, len(z)) + z + b"\nendstream")
            xobj.append(f"/Im{i} {num} 0 R")
        objs[cat - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages
        objs[pages - 1] = b"<< /Type /Pages /Kids [%d 0 R] /Count 1 >>" % pag
        objs[pag - 1] = (f"<< /Type /Page /Parent {pages} 0 R /MediaBox [0 0 {self.w:.0f} {self.h:.0f}] /Contents {cont} 0 R "
                         f"/Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> /XObject << {' '.join(xobj)} >> >> >>").encode()
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offs = []
        for i, o in enumerate(objs, 1):
            offs.append(len(out))
            out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        for o in offs:
            out += b"%010d 00000 n \n" % o
        out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, cat, xref)
        return bytes(out)
