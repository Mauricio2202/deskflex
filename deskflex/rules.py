"""Reglas de negocio: ventanas de reserva, disponibilidad sin duplicados y validación de acceso."""
from __future__ import annotations

import re
import secrets
from datetime import date, datetime, time, timedelta
from datetime import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
        "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


class ReglaError(Exception):
    """Error de negocio con un mensaje apto para mostrar al usuario."""


# ---------- tiempo -----------------------------------------------------------
def now() -> datetime:
    try:
        tz = ZoneInfo(current_app.config["TIMEZONE"])
    except ZoneInfoNotFoundError:      # Windows sin tzdata: México no usa horario de verano (UTC-6)
        tz = timezone(timedelta(hours=-6))
    return datetime.now(tz).replace(tzinfo=None, microsecond=0)


def today() -> date:
    return now().date()


def fmt_hora(h: int) -> str:
    h = h % 24
    suf = "am" if h < 12 else "pm"
    return f"{(h % 12) or 12}:00 {suf}"


def fmt_rango(ini: int, fin: int) -> str:
    return f"{fmt_hora(ini)} – {fmt_hora(fin)}"


def fmt_fecha(d: date | str, corta: bool = False) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d)
    if corta:
        return f"{d.day:02d}/{d.month:02d}/{d.year}"
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def fmt_fecha_dia(d: date | str) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return f"{DIAS[d.weekday()].capitalize()} {d.day} de {MESES[d.month - 1]}"


def _dt(fecha: str, hora: int) -> datetime:
    return datetime.combine(date.fromisoformat(fecha), time(hora % 24))


# ---------- validación de ventanas ------------------------------------------
def validar_ventana(fecha_s: str, modo: str, inicio, fin) -> tuple[str, str, int, int]:
    cfg = current_app.config
    try:
        d = date.fromisoformat(str(fecha_s))
    except ValueError:
        raise ReglaError("Elige una fecha válida.")
    if modo not in ("hora", "dia"):
        raise ReglaError("Elige si reservas por hora o por día completo.")
    if modo == "dia":
        inicio, fin = cfg["OPEN_HOUR"], cfg["CLOSE_HOUR"]
    else:
        try:
            inicio, fin = int(inicio), int(fin)
        except (TypeError, ValueError):
            raise ReglaError("Elige un horario válido.")
        if inicio < cfg["OPEN_HOUR"] or fin > cfg["CLOSE_HOUR"] or fin <= inicio:
            raise ReglaError(f"El horario debe estar entre {fmt_hora(cfg['OPEN_HOUR'])} y {fmt_hora(cfg['CLOSE_HOUR'])}.")
    hoy = today()
    if d < hoy:
        raise ReglaError("No puedes reservar en una fecha pasada.")
    if d > hoy + timedelta(days=cfg["MAX_ADVANCE_DAYS"]):
        raise ReglaError(f"Solo puedes reservar con {cfg['MAX_ADVANCE_DAYS']} días de anticipación.")
    if d.weekday() in cfg["CLOSED_WEEKDAYS"]:
        raise ReglaError("El coworking permanece cerrado los domingos.")
    if d == hoy:
        h = now().hour
        if h >= cfg["CLOSE_HOUR"]:
            raise ReglaError("El coworking ya cerró por hoy.")
        if modo == "hora" and inicio < h:
            raise ReglaError("Ese horario ya pasó. Elige una hora desde ahora en adelante.")
    return d.isoformat(), modo, inicio, fin


# ---------- márgenes de montaje y desmontaje ---------------------------------
def margenes() -> tuple[int, int]:
    cfg = current_app.config
    return cfg["MONTAJE_MIN"], cfg["DESMONTAJE_MIN"]


def hueco_h() -> float:
    """Horas que deben separar dos reservas del mismo espacio: el desmontaje de una más el montaje de la
    siguiente (30 + 30 min = 1 h). Si BLOQUEAR_MARGENES = False, las reservas pueden ir pegadas."""
    cfg = current_app.config
    return (cfg["MONTAJE_MIN"] + cfg["DESMONTAJE_MIN"]) / 60 if cfg["BLOQUEAR_MARGENES"] else 0.0


def fmt_hm(dt: datetime) -> str:
    return f"{(dt.hour % 12) or 12}:{dt.minute:02d} {'am' if dt.hour < 12 else 'pm'}"


def ventana_acceso(r) -> dict:
    """Ventanas de tiempo de una reserva: montaje, horario reservado y desmontaje/limpieza."""
    mon, des = margenes()
    ini, fin = _dt(r["fecha"], r["hora_inicio"]), _dt(r["fecha"], r["hora_fin"])
    d_mon, d_des = timedelta(minutes=mon), timedelta(minutes=des)
    return {
        "desde": ini - d_mon, "inicio": ini, "fin": fin, "hasta": fin + d_des,
        "montaje_min": mon, "desmontaje_min": des,
        "montaje": f"{fmt_hm(ini - d_mon)} – {fmt_hm(ini)}",
        "reservado": f"{fmt_hm(ini)} – {fmt_hm(fin)}",
        "desmontaje": f"{fmt_hm(fin)} – {fmt_hm(fin + d_des)}",
        "acceso": f"{fmt_hm(ini - d_mon)} – {fmt_hm(fin + d_des)}",
    }


def ahora_s() -> str:
    return now().strftime("%Y-%m-%d %H:%M:%S")


def expirar_pendientes(db):
    """Libera los lugares cuyo plazo de pago ya venció."""
    db.execute("UPDATE reservas SET estado = 'expirada' WHERE estado = 'pendiente' AND expira_en <= ?", (ahora_s(),))


# reservas que bloquean un espacio: confirmadas, o pendientes de pago cuyo plazo no ha vencido
ACTIVA = "(estado = 'confirmada' OR (estado = 'pendiente' AND expira_en > ?))"


# ---------- precios -----------------------------------------------------------
def calcular_precio(esp, modo: str, inicio: int, fin: int) -> dict:
    """Subtotal + IVA = total, en centavos. El día completo usa la tarifa diaria."""
    horas = fin - inicio
    sub = (esp["precio_dia"] if modo == "dia" else esp["precio_hora"] * horas) * 100
    iva = round(sub * current_app.config["IVA"])
    return {"horas": horas, "subtotal_cent": sub, "iva_cent": iva, "total_cent": sub + iva}


def fmt_mxn(cent: int) -> str:
    return f"${cent / 100:,.2f}"


# ---------- disponibilidad ---------------------------------------------------
def disponibilidad_completa(db, fecha: str, inicio: int, fin: int):
    """(estados, precios). estados[numero] = libre | ocupado. Cada reserva bloquea además sus márgenes
    de montaje y desmontaje. precios[numero] = total en centavos para la ventana pedida."""
    expirar_pendientes(db)
    gap = hueco_h()
    ocupados = {r["espacio_id"] for r in db.execute(
        f"""SELECT DISTINCT espacio_id FROM reservas
            WHERE fecha = ? AND {ACTIVA} AND hora_inicio < ? AND ? < hora_fin""",
        (fecha, ahora_s(), fin + gap, inicio - gap))}
    estados, precios = {}, {}
    modo = "dia" if (inicio, fin) == (current_app.config["OPEN_HOUR"], current_app.config["CLOSE_HOUR"]) else "hora"
    for e in db.execute("SELECT * FROM espacios WHERE activo = 1"):
        estados[e["numero"]] = "ocupado" if e["id"] in ocupados else "libre"
        precios[e["numero"]] = calcular_precio(e, modo, inicio, fin)["total_cent"]
    return estados, precios


def disponibilidad(db, fecha: str, inicio: int, fin: int) -> dict[int, str]:
    return disponibilidad_completa(db, fecha, inicio, fin)[0]


def horas_ocupadas_por_usuario(db, usuario_id: int, fecha: str) -> list[tuple[int, int]]:
    return [(r["hora_inicio"], r["hora_fin"]) for r in db.execute(
        f"SELECT hora_inicio, hora_fin FROM reservas WHERE usuario_id = ? AND fecha = ? AND {ACTIVA}",
        (usuario_id, fecha, ahora_s()))]


# ---------- altas, cambios y cancelaciones ----------------------------------
def _hay_choque_espacio(db, espacio_id, fecha, inicio, fin, excluir_id):
    gap = hueco_h()
    return db.execute(
        f"""SELECT folio FROM reservas WHERE espacio_id = ? AND fecha = ? AND {ACTIVA}
            AND hora_inicio < ? AND ? < hora_fin AND id != ?""",
        (espacio_id, fecha, ahora_s(), fin + gap, inicio - gap, excluir_id or -1)).fetchone()


def _validar_equipo(esp, tiene_equipo, integrantes) -> int | None:
    """Las salas de juntas son exclusivas para equipos de trabajo: hay que declararlo e indicar cuántos son."""
    if esp["tipo"] != "sala":
        return None
    minimo = current_app.config["SALA_MIN_INTEGRANTES"]
    if not tiene_equipo:
        raise ReglaError("Las salas de juntas son exclusivas para equipos de trabajo grandes. "
                         "Si vienes solo, reserva un escritorio fijo o un hot desk.")
    try:
        n = int(integrantes)
    except (TypeError, ValueError):
        raise ReglaError("Indica cuántas personas forman tu equipo.")
    if n < minimo:
        raise ReglaError(f"Las salas de juntas son para equipos de al menos {minimo} personas.")
    if n > esp["capacidad"]:
        raise ReglaError(f"{esp['nombre']} tiene {esp['capacidad']} asientos. Para {n} personas elige una sala más grande.")
    return n


def _guardar(db, reserva_id, usuario_id, espacio_id, fecha, modo, inicio, fin,
             tiene_equipo=False, integrantes=None, confirmar=False):
    """Valida y guarda dentro de una transacción inmediata: evita reservas duplicadas incluso con dos
    peticiones simultáneas. Las reservas nuevas quedan «pendientes» durante PAGO_MINUTOS (o confirmadas si
    `confirmar`, solo para datos de demostración). Devuelve el id de la reserva."""
    db.execute("BEGIN IMMEDIATE")
    try:
        esp = db.execute("SELECT * FROM espacios WHERE id = ? AND activo = 1", (espacio_id,)).fetchone()
        if not esp:
            raise ReglaError("Ese espacio no existe o no está disponible.")
        if reserva_id is None:
            n = _validar_equipo(esp, tiene_equipo, integrantes)
        else:
            n = db.execute("SELECT integrantes FROM reservas WHERE id = ?", (reserva_id,)).fetchone()["integrantes"]
            if esp["tipo"] == "sala" and (not n or n > esp["capacidad"]):
                raise ReglaError(f"{esp['nombre']} no tiene asientos suficientes para el equipo de esta reserva.")
            if esp["tipo"] != "sala":
                n = None
        db.execute("UPDATE reservas SET estado = 'expirada' WHERE estado = 'pendiente' AND expira_en <= ?", (ahora_s(),))
        if reserva_id is None:   # una persona solo mantiene un lugar apartado a la vez
            db.execute("UPDATE reservas SET estado = 'expirada' WHERE usuario_id = ? AND estado = 'pendiente'", (usuario_id,))
        choque_esp = _hay_choque_espacio(db, espacio_id, fecha, inicio, fin, reserva_id)
        if choque_esp:
            raise ReglaError(f"{esp['nombre']} no está disponible en ese horario (cada reserva incluye "
                             f"{margenes()[0]} min de montaje y {margenes()[1]} min de desmontaje). Elige otra hora u otro espacio.")
        choque = db.execute(
            f"""SELECT folio FROM reservas WHERE usuario_id = ? AND fecha = ? AND {ACTIVA}
                AND hora_inicio < ? AND ? < hora_fin AND id != ?""",
            (usuario_id, fecha, ahora_s(), fin, inicio, reserva_id or -1)).fetchone()
        if choque:
            raise ReglaError(f"Ya tienes la reserva {choque['folio']} que se cruza con ese horario.")
        if reserva_id is None:
            precio = calcular_precio(esp, modo, inicio, fin)
            estado = "confirmada" if confirmar else "pendiente"
            expira = None if confirmar else (now() + timedelta(minutes=current_app.config["PAGO_MINUTOS"])).strftime("%Y-%m-%d %H:%M:%S")
            cur = db.execute(
                """INSERT INTO reservas (usuario_id, espacio_id, fecha, hora_inicio, hora_fin, modo, token,
                                         integrantes, estado, expira_en, total_cent)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (usuario_id, espacio_id, fecha, inicio, fin, modo, secrets.token_urlsafe(16), n, estado, expira,
                 precio["total_cent"]))
            reserva_id = cur.lastrowid
            db.execute("UPDATE reservas SET folio = ? WHERE id = ?", (f"DF-{reserva_id:03d}", reserva_id))
        else:
            db.execute("UPDATE reservas SET espacio_id=?, fecha=?, hora_inicio=?, hora_fin=?, modo=?, integrantes=? WHERE id=?",
                       (espacio_id, fecha, inicio, fin, modo, n, reserva_id))
        db.execute("COMMIT")
        return reserva_id
    except Exception:
        db.execute("ROLLBACK")
        raise


def crear_reserva(db, usuario_id, espacio_id, fecha, modo, inicio, fin, integrantes=None,
                  tiene_equipo=False, confirmar=False) -> int:
    fecha, modo, inicio, fin = validar_ventana(fecha, modo, inicio, fin)
    return _guardar(db, None, usuario_id, espacio_id, fecha, modo, inicio, fin, tiene_equipo, integrantes, confirmar)


def editar_reserva(db, reserva_id, espacio_id, fecha, modo, inicio, fin) -> int:
    r = db.execute("SELECT * FROM reservas WHERE id = ?", (reserva_id,)).fetchone()
    if not r or r["estado"] != "confirmada":
        raise ReglaError("Solo se pueden editar reservas confirmadas.")
    nuevo = db.execute("SELECT tipo FROM espacios WHERE id = ?", (espacio_id,)).fetchone()
    actual = db.execute("SELECT tipo FROM espacios WHERE id = ?", (r["espacio_id"],)).fetchone()
    if nuevo and (nuevo["tipo"] == "sala") != (actual["tipo"] == "sala"):
        raise ReglaError("Una sala de juntas solo puede cambiarse por otra sala; un escritorio, por otro escritorio.")
    fecha, modo, inicio, fin = validar_ventana(fecha, modo, inicio, fin)
    return _guardar(db, reserva_id, r["usuario_id"], espacio_id, fecha, modo, inicio, fin)


def cancelar_reserva(db, reserva_id, usuario_id: int | None = None):
    """Cancela una reserva. Un cliente solo puede cancelar las suyas y antes de que inicien."""
    r = db.execute("SELECT * FROM reservas WHERE id = ?", (reserva_id,)).fetchone()
    if not r or (usuario_id is not None and r["usuario_id"] != usuario_id):
        raise ReglaError("No encontramos esa reserva.")
    if r["estado"] in ("cancelada", "expirada"):
        raise ReglaError("La reserva ya no estaba activa.")
    if usuario_id is not None and r["estado"] == "confirmada" and now() >= _dt(r["fecha"], r["hora_inicio"]):
        raise ReglaError("Una reserva que ya inició no se puede cancelar. Contacta a recepción.")
    db.execute("UPDATE reservas SET estado = 'cancelada' WHERE id = ?", (reserva_id,))


def segundos_para_pagar(r) -> int:
    if r["estado"] != "pendiente" or not r["expira_en"]:
        return 0
    return max(0, int((datetime.strptime(r["expira_en"], "%Y-%m-%d %H:%M:%S") - now()).total_seconds()))


def estado_visible(r, tiene_acceso: bool) -> tuple[str, str]:
    """(clave, etiqueta) del estado que ve el usuario, derivado de la hora actual."""
    if r["estado"] == "cancelada":
        return "cancelada", "Cancelada"
    if r["estado"] == "expirada":
        return "expirada", "Expirada sin pago"
    if r["estado"] == "pendiente":
        return ("pendiente", "Pendiente de pago") if segundos_para_pagar(r) > 0 else ("expirada", "Expirada sin pago")
    ahora = now()
    v = ventana_acceso(r)
    if ahora >= v["hasta"]:
        return "finalizada", "Finalizada"
    if tiene_acceso:
        return ("encurso", "Desmontaje") if ahora >= v["fin"] else ("usada", "Check-in hecho")
    if ahora >= v["fin"]:
        return "encurso", "Desmontaje"
    if ahora >= v["inicio"]:
        return "encurso", "En curso"
    if ahora >= v["desde"]:
        return "encurso", "Montaje"
    return "confirmada", "Confirmada"


# ---------- check-in ---------------------------------------------------------
_FOLIO = re.compile(r"^DF-\d+$", re.I)


def extraer_codigo(texto: str) -> str:
    """Acepta el folio, el token o la URL completa del QR (…/admin/checkin?codigo=TOKEN)."""
    from urllib.parse import parse_qs, urlsplit
    t = (texto or "").strip()
    if "codigo=" in t:
        vals = parse_qs(urlsplit(t).query).get("codigo")
        if vals:
            return vals[0].strip()
    t = re.split(r"[?#]", t)[0].rstrip("/")
    return t.rsplit("/", 1)[-1].strip()


def validar_acceso(db, texto: str, operador_id: int, forzar: bool = False) -> dict:
    """Valida un QR/folio, registra el resultado (autorizado o denegado) y lo devuelve.
    Ventana de acceso: desde el montaje (30 min antes) hasta el fin del desmontaje (30 min después).
    Individual: un solo ingreso. Sala de juntas: tantos ingresos como integrantes tenga el equipo."""
    expirar_pendientes(db)
    codigo = extraer_codigo(texto)
    r = None
    if codigo:
        col = "r.folio" if _FOLIO.match(codigo) else "r.token"
        r = db.execute(
            f"""SELECT r.*, u.nombre AS cliente, e.tipo AS esp_tipo,
                e.nombre AS espacio FROM reservas r
                JOIN usuarios u ON u.id = r.usuario_id JOIN espacios e ON e.id = r.espacio_id
                WHERE {col} = ?""", (codigo.upper() if col == "r.folio" else codigo,)).fetchone()
    ahora = now()
    ok, motivo, forzable, entrada = False, "", False, None
    if not r:
        motivo = "Código no reconocido."
    elif r["estado"] == "cancelada":
        motivo = "La reserva fue cancelada."
    elif r["estado"] == "expirada" or (r["estado"] == "pendiente" and segundos_para_pagar(r) == 0):
        motivo = "La reserva expiró sin pago."
    elif r["estado"] == "pendiente":
        motivo = "La reserva aún no está pagada."
    elif r["fecha"] != ahora.date().isoformat():
        motivo = f"La reserva es para el {fmt_fecha(r['fecha'])}, no para hoy ({fmt_fecha(ahora.date())})."
        forzable = True
    else:
        v = ventana_acceso(r)
        usados = db.execute("SELECT COUNT(*) c FROM accesos WHERE reserva_id = ? AND resultado = 'autorizado'",
                            (r["id"],)).fetchone()["c"]
        cupo = r["integrantes"] if (r["esp_tipo"] == "sala" and r["integrantes"]) else 1
        if ahora < v["desde"]:
            motivo = f"Aún no es hora de entrada. El montaje inicia a las {v['desde'].strftime('%H:%M')}."
            forzable = True
        elif ahora >= v["hasta"]:
            motivo = f"El horario de la reserva (con desmontaje) terminó a las {v['hasta'].strftime('%H:%M')}."
            forzable = True
        elif usados >= cupo:
            motivo = (f"Ya ingresaron los {cupo} integrantes del equipo." if cupo > 1
                      else f"Este código ya se usó.")
        else:
            ok, entrada = True, (f"{usados + 1} de {cupo}" if cupo > 1 else None)
    nota = None
    if not ok and forzar and forzable:
        ok, nota = True, f"Autorizado manualmente (motivo original: {motivo})"
    db.execute(
        "INSERT INTO accesos (reserva_id, operador_id, codigo, resultado, motivo, registrado_en) VALUES (?,?,?,?,?,?)",
        (r["id"] if r else None, operador_id, (codigo or "")[:64], "autorizado" if ok else "denegado",
         nota if ok else motivo, ahora.strftime("%Y-%m-%d %H:%M:%S")))
    res = {"ok": ok, "motivo": nota or motivo, "hora": ahora.strftime("%H:%M"), "forzable": bool(forzable and not ok),
           "codigo": codigo, "entrada": entrada}
    if r:
        v = ventana_acceso(r)
        res.update(folio=r["folio"], cliente=r["cliente"], espacio=r["espacio"],
                   fecha=fmt_fecha(r["fecha"]), horario=fmt_rango(r["hora_inicio"], r["hora_fin"]),
                   acceso=v["acceso"])
    return res
