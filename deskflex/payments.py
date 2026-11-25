"""Pasarela de pago con tarjeta (simulada) alineada con PCI DSS.

Qué hace este módulo y qué NO hace:
  * Valida el número (Luhn), vencimiento y CVV, y reconoce la red (Visa, Mastercard, American Express)
    y el banco emisor (por rangos BIN en la tabla `bines`).
  * El número completo, el CVV y el vencimiento viven solo en memoria durante la petición: no se guardan,
    no se escriben en logs ni en la bitácora. De la tarjeta únicamente se conserva red, banco y últimos 4.
  * El «procesador» es un simulador para demostración. Para cobrar de verdad hay que sustituir
    `autorizar()` por la integración con un procesador certificado (Openpay, Conekta, Stripe, Mercado Pago…),
    idealmente con campos alojados (hosted fields) para que los datos de tarjeta nunca toquen este servidor.
"""
from __future__ import annotations

import re
import secrets
from datetime import date

REDES = {"visa": "VISA", "mastercard": "Mastercard", "amex": "American Express"}

# Tarjetas y bancos que acepta DeskFlex, en el orden en que se muestran
ACEPTADAS = [
    ("visa", "VISA"), ("mastercard", "Mastercard"), ("amex", "American Express"),
    ("bbva", "BBVA"), ("citibanamex", "Citibanamex"), ("hsbc", "HSBC"), ("banorte", "Banorte"),
    ("scotiabank", "Scotiabank"), ("inbursa", "Inbursa"), ("azteca", "Banco Azteca"), ("bancoppel", "BanCoppel"),
]
BANCO_ID = {n: i for i, n in ACEPTADAS}
BANCO_ID.update({"Banco Azteca": "azteca"})

# ⚠️ Rangos de DEMOSTRACIÓN (prefijos de prueba). En producción reemplázalos por la tabla BIN oficial
# que entregue el adquirente/procesador: basta con insertar filas en la tabla `bines`.
BINES_DEMO = [
    ("411111", "visa", None), ("555555", "mastercard", None), ("378282", "amex", None), ("371449", "amex", None),
    ("400010", "visa", "BBVA"), ("510010", "mastercard", "Citibanamex"),
    ("400020", "visa", "HSBC"), ("510020", "mastercard", "Banorte"),
    ("400030", "visa", "Scotiabank"), ("510030", "mastercard", "Inbursa"),
    ("400040", "visa", "Banco Azteca"), ("510040", "mastercard", "BanCoppel"),
]


def solo_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def luhn_ok(num: str) -> bool:
    if not num.isdigit():
        return False
    total, alt = 0, False
    for ch in reversed(num):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def detectar_red(num: str) -> str | None:
    if re.match(r"^4", num):
        return "visa"
    if re.match(r"^(5[1-5]|2(2[2-9][1-9]|2[3-9]\d|[3-6]\d\d|7[01]\d|720))", num):
        return "mastercard"
    if re.match(r"^3[47]", num):
        return "amex"
    return None


def detectar_banco(db, num: str) -> str | None:
    """Banco emisor por BIN (prefijo más largo que coincida; se envían como máximo 8 dígitos)."""
    for n in range(min(8, len(num)), 5, -1):
        r = db.execute("SELECT banco FROM bines WHERE prefijo = ?", (num[:n],)).fetchone()
        if r:
            return r["banco"]
    return None


def enmascarar(num: str) -> str:
    return "•••• •••• •••• " + num[-4:] if num else ""


def validar_tarjeta(num_raw: str, nombre: str, venc: str, cvv: str, hoy: date) -> tuple[dict, dict]:
    """Devuelve (datos_validados, errores). Los datos validados incluyen el número limpio SOLO para
    pasarlo al autorizador; quien llame debe descartarlo en cuanto termine."""
    err: dict[str, str] = {}
    num = solo_digitos(num_raw)
    red = detectar_red(num)
    largo = 15 if red == "amex" else 16
    if not num or red is None:
        err["numero"] = "Usamos VISA, Mastercard y American Express. Revisa el número de tu tarjeta."
    elif len(num) != largo or not luhn_ok(num):
        err["numero"] = "El número de tarjeta no es válido. Revísalo dígito por dígito."
    nombre = re.sub(r"\s+", " ", (nombre or "").strip())
    if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ' .-]{3,60}", nombre):
        err["nombre"] = "Escribe el nombre como aparece en la tarjeta."
    m = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(\d{2}|\d{4})\s*", venc or "")
    mes = anio = 0
    if m:
        mes, anio = int(m.group(1)), int(m.group(2))
        anio = anio + 2000 if anio < 100 else anio
    if not m or not (1 <= mes <= 12):
        err["venc"] = "Usa el formato MM/AA."
    elif (anio, mes) < (hoy.year, hoy.month):
        err["venc"] = "La tarjeta está vencida."
    elif anio > hoy.year + 20:
        err["venc"] = "Revisa el año de vencimiento."
    cvv = (cvv or "").strip()
    if not re.fullmatch(r"\d{4}" if red == "amex" else r"\d{3}", cvv):
        err["cvv"] = "El CVV tiene 4 dígitos." if red == "amex" else "El CVV tiene 3 dígitos."
    return {"numero": num, "red": red, "nombre": nombre}, err


def autorizar(num: str, total_cent: int) -> dict:
    """SIMULADOR del procesador. Termina en 9995 → fondos insuficientes; en 0119 → rechazo del banco."""
    if num.endswith("9995"):
        return {"ok": False, "motivo": "Fondos insuficientes."}
    if num.endswith("0119"):
        return {"ok": False, "motivo": "El banco emisor rechazó la operación."}
    return {"ok": True, "autorizacion": "".join(secrets.choice("0123456789") for _ in range(6))}


def folio_pago(rid: int) -> str:
    return f"PG-{rid:05d}"
