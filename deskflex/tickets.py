"""Ticket de pago + pase de check-in (PDF) y tarjeta del código QR (SVG), ambos con el logo de DeskFlex."""
from __future__ import annotations

import base64
import struct
from pathlib import Path
from xml.sax.saxutils import escape

from . import qr
from .pdf import Pagina

_AQUI = Path(__file__).parent
NAVY, INDIGO, TEAL, GRIS, LINEA = "#0F172A", "#4F46E5", "#0F766E", "#475569", "#E2E8F0"


def _logo_pdf():
    raw = (_AQUI / "assets" / "logo_rgb.bin").read_bytes()
    w, h = struct.unpack(">II", raw[:8])
    return w, h, raw[8:]


def _logo_data_uri() -> str:
    return "data:image/png;base64," + base64.b64encode((_AQUI / "static" / "img" / "logo-mark.png").read_bytes()).decode()


def _envolver(texto: str, max_chars: int) -> list[str]:
    lineas, actual = [], ""
    for palabra in texto.split():
        if len(actual) + len(palabra) + 1 > max_chars and actual:
            lineas.append(actual)
            actual = palabra
        else:
            actual = f"{actual} {palabra}".strip()
    return lineas + ([actual] if actual else [])


def ticket_pdf(d: dict) -> bytes:
    """d: folio, espacio, fecha, cliente, ventana(dict de rules.ventana_acceso), integrantes, qr_url,
    pago (dict|None), demo(bool), invitacion(bool)."""
    p = Pagina()
    L, R = 48, 612 - 48
    p.rect(0, 0, 612, 96, fill=NAVY)
    p.rect(L - 5, 20, 50, 56, fill="#FFFFFF")
    p.imagen(_logo_pdf(), L, 24, 40, 43.5)
    p.texto(L + 52, 44, "DeskFlex México", 20, True, "#FFFFFF")
    p.texto(L + 52, 62, "Ticket de pago y pase de check-in", 10.5, False, "#CBD5E1")
    p.texto(R - 120, 44, "FOLIO", 8.5, True, "#5EEAD4")
    p.texto(R - 120, 64, d["folio"], 18, True, "#FFFFFF")

    y = 130
    def seccion(titulo):
        nonlocal y
        p.texto(L, y, titulo.upper(), 9, True, TEAL)
        p.linea(L, y + 6, 330, y + 6, LINEA)
        y += 24

    def fila(etq, val, negrita=False):
        nonlocal y
        p.texto(L, y, etq, 9.5, False, GRIS)
        p.texto(L + 118, y, val, 10.5, negrita)
        y += 18

    v = d["ventana"]
    seccion("Reserva")
    fila("Lugar", d["espacio"], True)
    fila("Fecha", d["fecha"])
    fila("Cliente", d["cliente"])
    if d.get("integrantes"):
        fila("Equipo", f"{d['integrantes']} personas ({d['integrantes']} asientos apartados)")
    y += 8
    seccion("Horario y acceso")
    fila("Horario reservado", v["reservado"], True)
    fila(f"Montaje ({v['montaje_min']} min)", v["montaje"])
    fila(f"Desmontaje y limpieza", v["desmontaje"])
    fila("Acceso permitido", v["acceso"], True)
    y += 8

    # Bloque QR (derecha)
    qx, qy, qs = 372, 130, 192
    p.rect(qx - 12, qy - 12, qs + 24, qs + 64, fill="#FFFFFF", stroke=LINEA, lw=1)
    p.qr(qr.matrix(d["qr_url"]), qx, qy, qs, NAVY, borde=2)
    p.texto(qx, qy + qs + 22, "Código de check-in", 10, True)
    p.texto(qx, qy + qs + 36, "Muéstralo en recepción", 8.5, False, GRIS)

    seccion("Pago")
    pg = d.get("pago")
    if pg:
        fila("Folio de pago", pg["folio_pago"], True)
        fila("Fecha de pago", pg["creado_en"][:16].replace("-", "/"))
        tarjeta = f"{pg['marca_txt']} •••• {pg['ultimos4']}" + (f"  ·  {pg['banco']}" if pg["banco"] else "")
        fila("Tarjeta", tarjeta)
        fila("Autorización", pg["autorizacion"])
        y += 6
        for etq, val, neg in (("Subtotal", pg["subtotal"], False), (f"IVA ({d['iva_pct']}%)", pg["iva"], False), ("TOTAL MXN", pg["total"], True)):
            p.texto(L, y, etq, 10, neg)
            p.texto(L + 118, y, val, 11 if neg else 10, neg, INDIGO if neg else NAVY)
            y += 18
    else:
        fila("Estado", "Sin pago registrado (reserva anterior al módulo de pagos)")

    y = max(y + 14, 420)
    p.linea(L, y, R, y, LINEA)
    y += 20
    notas = [
        f"El código QR es válido desde {v['desde'].strftime('%H:%M')} (montaje) hasta {v['hasta'].strftime('%H:%M')} (fin del desmontaje) del día de tu reserva.",
        "Usa el montaje para acomodar lo que necesites y el desmontaje para recoger y dejar limpio el espacio.",
    ]
    if d.get("invitacion"):
        notas.insert(1, "Este mismo QR sirve para todo el equipo: cada integrante debe abrir el enlace de invitación, registrarse en DeskFlex y elegir su asiento.")
        notas.append(f"Enlace de invitación: {d['qr_url']}")
    if d.get("demo"):
        notas.append("Pago de demostración: no se realizó ningún cargo real a la tarjeta.")
    for n in notas:
        for ln in _envolver(n, 98):
            p.texto(L, y, ln, 8.8, False, GRIS)
            y += 12
        y += 3
    p.texto(L, 792 - 40, "DeskFlex México · Control de acceso y reservas · Ciudad de México", 8, False, "#94A3B8")
    return p.a_bytes()


def qr_card_svg(d: dict) -> str:
    """Tarjeta descargable del QR con el logo de DeskFlex encima (el QR queda intacto para que se lea bien)."""
    m = qr.matrix(d["qr_url"])
    n, borde, esc = len(m), 2, 8
    tam = (n + 2 * borde) * esc
    trazo = []
    for j, fila in enumerate(m):
        i = 0
        while i < n:
            if fila[i]:
                k = i
                while k < n and fila[k]:
                    k += 1
                trazo.append(f"M{(i + borde) * esc},{(j + borde) * esc}h{(k - i) * esc}v{esc}h-{(k - i) * esc}z")
                i = k
            else:
                i += 1
    W = max(tam + 64, 420)
    ox = (W - tam) // 2
    H = 110 + tam + 150
    v = d["ventana"]
    e = lambda s: escape(str(s))
    lineas = [(d["espacio"], 700, 17, "#0F172A"), (f"{d['fecha']} · {v['reservado']}", 600, 14, "#334155"),
              (f"Acceso permitido: {v['acceso']}", 600, 13, "#0F766E")]
    if d.get("integrantes"):
        lineas.insert(1, (f"Equipo de {d['integrantes']} personas", 600, 14, "#334155"))
    textos = "".join(f'<text x="{W // 2}" y="{110 + tam + 40 + i * 24}" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" '
                     f'font-weight="{w}" font-size="{s}" fill="{c}">{e(t)}</text>' for i, (t, w, s, c) in enumerate(lineas))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
            f'role="img" aria-label="Código QR de la reserva {e(d["folio"])}">'
            f'<rect width="{W}" height="{H}" rx="22" fill="#FFFFFF" stroke="#CBD5E1" stroke-width="2"/>'
            f'<image href="{_logo_data_uri()}" x="{W // 2 - 128}" y="24" width="40" height="43.5"/>'
            f'<text x="{W // 2 - 76}" y="46" font-family="Arial,Helvetica,sans-serif" font-weight="700" font-size="22" fill="#0F172A">DeskFlex</text>'
            f'<text x="{W // 2 - 76}" y="64" font-family="Arial,Helvetica,sans-serif" font-weight="600" font-size="12" fill="#475569">MÉXICO · Check-in</text>'
            f'<text x="{W - 28}" y="46" text-anchor="end" font-family="Courier New,monospace" font-weight="700" font-size="16" fill="#4F46E5">{e(d["folio"])}</text>'
            f'<g transform="translate({ox},96)" shape-rendering="crispEdges"><rect width="{tam}" height="{tam}" fill="#fff"/>'
            f'<path d="{"".join(trazo)}" fill="#0F172A"/></g>{textos}</svg>')
