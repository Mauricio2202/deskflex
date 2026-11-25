from datetime import timedelta

from flask import (Blueprint, Response, abort, current_app, flash, g, jsonify, redirect,
                   render_template, request, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .. import mapa, payments, qr, rules, tickets
from ..db import get_db
from ..security import auditar, client_required, limitado, login_required
from .auth import validar_password, validar_telefono

bp = Blueprint("client", __name__)

SELECT_RESERVA = """
    SELECT r.*, e.nombre || CASE WHEN r.asiento IS NOT NULL THEN ' · asiento ' || r.asiento ELSE '' END AS espacio,
           e.numero AS esp_numero, e.tipo AS esp_tipo, e.capacidad AS esp_capacidad, u.nombre AS cliente,
           EXISTS (SELECT 1 FROM accesos a WHERE a.reserva_id = r.id AND a.resultado = 'autorizado') AS con_acceso,
           EXISTS (SELECT 1 FROM pagos p WHERE p.reserva_id = r.id AND p.estado = 'aprobado') AS pagada,
           (SELECT COUNT(*) FROM asientos_sala s WHERE s.reserva_id = r.id) AS n_unidos
    FROM reservas r JOIN espacios e ON e.id = r.espacio_id JOIN usuarios u ON u.id = r.usuario_id
"""


def qr_url(r) -> str:
    """Salas de juntas: el QR abre la invitación (cada integrante se registra y elige asiento) y en recepción
    se valida con el mismo código. Escritorios: el QR lleva directo al check-in."""
    base = request.host_url.rstrip("/")
    if r["esp_tipo"] == "sala":
        return base + url_for("client.invitacion", token=r["token"])
    return base + url_for("admin.checkin", codigo=r["token"])


def decorar(r):
    """Añade estado visible, ventanas de montaje/desmontaje, QR y montos a una fila de reserva."""
    d = dict(r)
    d["estado_clave"], d["estado_txt"] = rules.estado_visible(r, bool(r["con_acceso"]))
    d["v"] = rules.ventana_acceso(r)
    d["es_sala"] = r["esp_tipo"] == "sala"
    d["qr_url"] = qr_url(r)
    d["qr"] = qr.svg(d["qr_url"], label=f"Código QR de la reserva {r['folio']}")
    d["total_txt"] = rules.fmt_mxn(r["total_cent"])
    d["segundos"] = rules.segundos_para_pagar(r)
    return d


def _mia_o_admin(r):
    return r and (g.user["rol"] == "admin" or r["usuario_id"] == g.user["id"])


def _datos_pago(db, rid):
    p = db.execute("SELECT * FROM pagos WHERE reserva_id = ? AND estado = 'aprobado' ORDER BY id DESC", (rid,)).fetchone()
    if not p:
        return None
    d = dict(p)
    d.update(marca_txt=payments.REDES.get(p["marca"], p["marca"] or ""), subtotal=rules.fmt_mxn(p["subtotal_cent"]),
             iva=rules.fmt_mxn(p["iva_cent"]), total=rules.fmt_mxn(p["total_cent"]))
    return d


def _datos_ticket(r, pago):
    return dict(folio=r["folio"], espacio=r["espacio"], fecha=rules.fmt_fecha(r["fecha"]), cliente=r["cliente"],
                ventana=r["v"], integrantes=r["integrantes"] if r["es_sala"] else None, qr_url=r["qr_url"], pago=pago,
                demo=current_app.config.get("PAGOS_DEMO", True), invitacion=r["es_sala"],
                iva_pct=int(current_app.config["IVA"] * 100))


@bp.route("/inicio")
@client_required
def inicio():
    db = get_db()
    rules.expirar_pendientes(db)
    ahora = rules.now()
    filas = db.execute(SELECT_RESERVA + " WHERE r.usuario_id = ? AND r.estado IN ('confirmada','pendiente') ORDER BY r.fecha, r.hora_inicio",
                       (g.user["id"],)).fetchall()
    proximas = [decorar(r) for r in filas if rules.estado_visible(r, bool(r["con_acceso"]))[0] in ("pendiente", "confirmada", "encurso", "usada")]
    h = ahora.hour
    libres, estados = None, None
    cfg = current_app.config
    if cfg["OPEN_HOUR"] <= h < cfg["CLOSE_HOUR"] and ahora.weekday() not in cfg["CLOSED_WEEKDAYS"]:
        disp = rules.disponibilidad(db, ahora.date().isoformat(), h, h + 1)
        libres = sum(1 for v in disp.values() if v != "ocupado")
        total = len(disp)
        estados = disp
    else:
        total = db.execute("SELECT COUNT(*) c FROM espacios WHERE activo=1").fetchone()["c"]
    espacios = {r["numero"]: dict(r) for r in db.execute("SELECT * FROM espacios WHERE activo = 1")}
    return render_template("client/inicio.html", proxima=proximas[0] if proximas else None,
                           n_proximas=len(proximas), libres=libres, total=total, estados=estados,
                           espacios=espacios, formas=mapa.FORMAS)


@bp.route("/reservar", methods=["GET", "POST"])
@client_required
def reservar():
    db = get_db()
    cfg = current_app.config
    if request.method == "POST":
        f = request.form
        try:
            num = int(f.get("espacio", ""))
            esp = db.execute("SELECT id FROM espacios WHERE numero = ? AND activo = 1", (num,)).fetchone()
            if not esp:
                raise rules.ReglaError("Selecciona un espacio en el mapa.")
            rid = rules.crear_reserva(db, g.user["id"], esp["id"], f.get("fecha"), f.get("modo"), f.get("inicio"), f.get("fin"),
                                      integrantes=f.get("integrantes"), tiene_equipo=f.get("tiene_equipo") == "1")
        except ValueError:
            flash("Selecciona un espacio en el mapa.", "error")
        except rules.ReglaError as e:
            flash(str(e), "error")
        else:
            folio = db.execute("SELECT folio FROM reservas WHERE id = ?", (rid,)).fetchone()["folio"]
            auditar("reserva_creada", folio)
            flash(f"Lugar apartado por {cfg['PAGO_MINUTOS']} minutos. Completa el pago para confirmar tu reserva.", "info")
            return redirect(url_for("client.pago", folio=folio))
    hoy = rules.today()
    d = hoy
    if rules.now().hour >= cfg["CLOSE_HOUR"]:
        d += timedelta(days=1)
    while d.weekday() in cfg["CLOSED_WEEKDAYS"]:
        d += timedelta(days=1)
    espacios = {r["numero"]: dict(r) for r in db.execute("SELECT * FROM espacios WHERE activo = 1")}
    return render_template("client/reservar.html", espacios=espacios, formas=mapa.FORMAS,
                           inicial=d.isoformat(), hoy=hoy.isoformat(),
                           maximo=(hoy + timedelta(days=cfg["MAX_ADVANCE_DAYS"])).isoformat(),
                           cerrados=list(cfg["CLOSED_WEEKDAYS"]),
                           apertura=cfg["OPEN_HOUR"], cierre=cfg["CLOSE_HOUR"], min_equipo=cfg["SALA_MIN_INTEGRANTES"],
                           salas={n: dict(capacidad=espacios[n]["capacidad"], orden=mapa.ORDEN_ASIENTOS[n]) for n in (1, 2) if n in espacios},
                           montaje=cfg["MONTAJE_MIN"], desmontaje=cfg["DESMONTAJE_MIN"])


# ---- Pago ----------------------------------------------------------------------------------------
def _cargar_pendiente(folio):
    db = get_db()
    rules.expirar_pendientes(db)
    r = db.execute(SELECT_RESERVA + " WHERE r.folio = ? AND r.usuario_id = ?", (folio.upper(), g.user["id"])).fetchone()
    if not r:
        abort(404)
    return db, r


def _render_pago(r, errores=None, datos=None, codigo=200):
    esp = get_db().execute("SELECT * FROM espacios WHERE id = ?", (r["espacio_id"],)).fetchone()
    precio = rules.calcular_precio(esp, r["modo"], r["hora_inicio"], r["hora_fin"])
    return render_template("client/pago.html", r=decorar(r), precio=precio, errores=errores or {}, datos=datos or {},
                           aceptadas=payments.ACEPTADAS, iva_pct=int(current_app.config["IVA"] * 100),
                           intentos=current_app.config["PAGO_INTENTOS"],
                           demo=current_app.config.get("PAGOS_DEMO", True)), codigo


@bp.route("/reservas/<folio>/pago", methods=["GET", "POST"])
@client_required
def pago(folio):
    db, r = _cargar_pendiente(folio)
    if r["estado"] == "confirmada":
        flash("Esta reserva ya está pagada.", "info")
        return redirect(url_for("client.reserva", folio=r["folio"]))
    if r["estado"] != "pendiente":
        flash("El tiempo para pagar terminó y el lugar se liberó. Puedes volver a reservar.", "error")
        return redirect(url_for("client.reservar"))
    if request.method == "GET":
        return _render_pago(r)[0]

    cfg = current_app.config
    if limitado(f"pagoval|{g.user['id']}", 40, 300):      # freno general contra uso automatizado del formulario
        flash("Demasiados intentos seguidos. Espera un momento.", "error")
        return redirect(url_for("client.pago", folio=r["folio"]))
    f = request.form
    datos, errores = payments.validar_tarjeta(f.get("numero"), f.get("titular"), f.get("vencimiento"), f.get("cvv"), rules.today())
    keep = {"titular": datos["nombre"] or f.get("titular", "")[:60], "vencimiento": (f.get("vencimiento") or "")[:7]}
    if errores:
        return _render_pago(r, errores, keep, 422)[0], 422
    # Solo los intentos que llegan al banco cuentan para el límite (anti «card testing», PCI DSS / OWASP A06)
    if limitado(f"pago|{r['id']}", cfg["PAGO_INTENTOS"], 900):
        db.execute("UPDATE reservas SET estado = 'expirada' WHERE id = ? AND estado = 'pendiente'", (r["id"],))
        auditar("pago_bloqueado", r["folio"])
        flash("Demasiados intentos de pago. Liberamos el lugar; puedes volver a reservar.", "error")
        return redirect(url_for("client.reservar"))
    esp = db.execute("SELECT * FROM espacios WHERE id = ?", (r["espacio_id"],)).fetchone()
    precio = rules.calcular_precio(esp, r["modo"], r["hora_inicio"], r["hora_fin"])
    num = datos["numero"]
    banco, red, ult4 = payments.detectar_banco(db, num), datos["red"], num[-4:]
    res = payments.autorizar(num, precio["total_cent"])
    num = datos["numero"] = None          # PCI DSS: el número completo ya no se necesita
    ahora = rules.ahora_s()
    if not res["ok"]:
        db.execute("""INSERT INTO pagos (reserva_id, folio_pago, subtotal_cent, iva_cent, total_cent, marca, banco, ultimos4, estado, motivo, creado_en)
                      VALUES (?,?,?,?,?,?,?,?, 'rechazado', ?, ?)""",
                   (r["id"], None, precio["subtotal_cent"], precio["iva_cent"], precio["total_cent"], red, banco, ult4, res["motivo"], ahora))
        auditar("pago_rechazado", f"{r['folio']} ****{ult4}")
        flash(f"Pago rechazado: {res['motivo']} Prueba con otra tarjeta.", "error")
        return _render_pago(r, {}, keep, 402)[0], 402
    db.execute("BEGIN IMMEDIATE")
    try:
        vivo = db.execute("SELECT estado, expira_en FROM reservas WHERE id = ?", (r["id"],)).fetchone()
        if vivo["estado"] != "pendiente" or vivo["expira_en"] <= ahora:
            db.execute("ROLLBACK")      # el plazo venció justo ahora: no se confirma ni se cobra
            flash("El tiempo para pagar terminó antes de completar el cobro. No se hizo ningún cargo.", "error")
            return redirect(url_for("client.reservar"))
        db.execute("UPDATE reservas SET estado = 'confirmada', expira_en = NULL WHERE id = ?", (r["id"],))
        cur = db.execute("""INSERT INTO pagos (reserva_id, subtotal_cent, iva_cent, total_cent, marca, banco, ultimos4, autorizacion, estado, creado_en)
                            VALUES (?,?,?,?,?,?,?,?, 'aprobado', ?)""",
                         (r["id"], precio["subtotal_cent"], precio["iva_cent"], precio["total_cent"], red, banco, ult4, res["autorizacion"], ahora))
        db.execute("UPDATE pagos SET folio_pago = ? WHERE id = ?", (payments.folio_pago(cur.lastrowid), cur.lastrowid))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    auditar("pago_aprobado", f"{r['folio']} ****{ult4} {rules.fmt_mxn(precio['total_cent'])}")
    flash("¡Pago aprobado! Tu reserva quedó confirmada.", "success")
    return redirect(url_for("client.reserva", folio=r["folio"]))


@bp.route("/reservas/<folio>/pago/cancelar", methods=["POST"])
@client_required
def pago_cancelar(folio):
    db, r = _cargar_pendiente(folio)
    if r["estado"] == "pendiente":
        db.execute("UPDATE reservas SET estado = 'cancelada' WHERE id = ?", (r["id"],))
        flash("Liberamos el lugar. No se hizo ningún cargo.", "info")
    return redirect(url_for("client.reservar"))


# ---- Mis reservas, pase y descargas ---------------------------------------------------------------
@bp.route("/mis-reservas")
@client_required
def mis_reservas():
    db = get_db()
    rules.expirar_pendientes(db)
    filas = db.execute(SELECT_RESERVA + " WHERE r.usuario_id = ? ORDER BY r.fecha DESC, r.hora_inicio DESC", (g.user["id"],)).fetchall()
    todas = [decorar(r) for r in filas]
    activas = [r for r in todas if r["estado_clave"] in ("pendiente", "confirmada", "encurso", "usada")]
    activas.sort(key=lambda r: (r["fecha"], r["hora_inicio"]))
    historial = [r for r in todas if r["estado_clave"] not in ("pendiente", "confirmada", "encurso", "usada")]
    unidas = [decorar(r) | {"mi_asiento": r["mi_asiento"]} for r in db.execute(
        SELECT_RESERVA.replace("SELECT r.*,", "SELECT s.asiento AS mi_asiento, r.*,", 1).replace("FROM reservas r", "FROM asientos_sala s JOIN reservas r ON r.id = s.reserva_id", 1)
        + " WHERE s.usuario_id = ? AND r.usuario_id != ? AND r.estado = 'confirmada' ORDER BY r.fecha, r.hora_inicio",
        (g.user["id"], g.user["id"])).fetchall()]
    unidas = [u for u in unidas if u["estado_clave"] != "finalizada"]
    return render_template("client/mis_reservas.html", activas=activas, historial=historial, unidas=unidas)


@bp.route("/reservas/<folio>")
@login_required
def reserva(folio):
    db = get_db()
    rules.expirar_pendientes(db)
    r = db.execute(SELECT_RESERVA + " WHERE r.folio = ?", (folio.upper(),)).fetchone()
    if not _mia_o_admin(r):
        abort(404)
    if r["estado"] == "pendiente" and g.user["rol"] != "admin" and rules.segundos_para_pagar(r) > 0:
        return redirect(url_for("client.pago", folio=r["folio"]))
    d = decorar(r)
    miembros = []
    if d["es_sala"]:
        tomados = {s["asiento"]: s["nombre"] for s in db.execute(
            "SELECT s.asiento, u.nombre FROM asientos_sala s JOIN usuarios u ON u.id = s.usuario_id WHERE s.reserva_id = ?", (r["id"],))}
        miembros = [(a, tomados.get(a)) for a in mapa.asientos_apartados(r["esp_numero"], r["integrantes"] or 0)]
    return render_template("client/reserva.html", r=d, pago=_datos_pago(db, r["id"]), miembros=miembros,
                           iva_pct=int(current_app.config["IVA"] * 100))


def _reserva_pagada_o_404(folio):
    r = get_db().execute(SELECT_RESERVA + " WHERE r.folio = ?", (folio.upper(),)).fetchone()
    if not _mia_o_admin(r) or r["estado"] not in ("confirmada",):
        abort(404)
    return r


@bp.route("/reservas/<folio>/ticket")
@login_required
def ticket_html(folio):
    r = _reserva_pagada_o_404(folio)
    d = decorar(r)
    return render_template("client/ticket.html", r=d, pago=_datos_pago(get_db(), r["id"]),
                           iva_pct=int(current_app.config["IVA"] * 100), demo=current_app.config.get("PAGOS_DEMO", True))


@bp.route("/reservas/<folio>/ticket.pdf")
@login_required
def ticket_pdf(folio):
    r = _reserva_pagada_o_404(folio)
    d = decorar(r)
    resp = Response(tickets.ticket_pdf(_datos_ticket(d, _datos_pago(get_db(), r["id"]))), mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="DeskFlex-ticket-{r["folio"]}.pdf"'
    return resp


@bp.route("/reservas/<folio>/qr.svg")
@login_required
def reserva_qr(folio):
    r = _reserva_pagada_o_404(folio)
    d = decorar(r)
    resp = Response(tickets.qr_card_svg(_datos_ticket(d, None)), mimetype="image/svg+xml")
    resp.headers["Content-Disposition"] = f'attachment; filename="DeskFlex-QR-{r["folio"]}.svg"'
    return resp


@bp.route("/reservas/<folio>/cancelar", methods=["POST"])
@client_required
def cancelar(folio):
    db = get_db()
    r = db.execute("SELECT id FROM reservas WHERE folio = ? AND usuario_id = ?", (folio.upper(), g.user["id"])).fetchone()
    if not r:
        abort(404)
    try:
        rules.cancelar_reserva(db, r["id"], g.user["id"])
        auditar("reserva_cancelada", folio.upper())
        flash(f"Cancelamos la reserva {folio.upper()}. El espacio quedó libre.", "success")
    except rules.ReglaError as e:
        flash(str(e), "error")
    return redirect(url_for("client.mis_reservas"))


# ---- Invitación a una sala de juntas --------------------------------------------------------------
def _contexto_invitacion(db, token):
    r = db.execute(SELECT_RESERVA + " WHERE r.token = ? AND e.tipo = 'sala'", (token,)).fetchone()
    if not r:
        abort(404)
    reservados = mapa.asientos_apartados(r["esp_numero"], r["integrantes"] or 0)
    filas = db.execute("SELECT asiento, usuario_id FROM asientos_sala WHERE reserva_id = ?", (r["id"],)).fetchall()
    tomados = {f["asiento"]: f["usuario_id"] for f in filas}
    return r, reservados, tomados


@bp.route("/invitacion/<token>")
@login_required
def invitacion(token):
    if g.user["rol"] == "admin":
        return redirect(url_for("admin.checkin", codigo=token))
    db = get_db()
    rules.expirar_pendientes(db)
    r, reservados, tomados = _contexto_invitacion(db, token)
    d = decorar(r)
    mio = next((a for a, u in tomados.items() if u == g.user["id"]), None)
    abierta = r["estado"] == "confirmada" and d["estado_clave"] != "finalizada"
    sala = next(f for f in mapa.FORMAS if f["numero"] == r["esp_numero"])
    return render_template("client/invitacion.html", r=d, reservados=reservados, tomados=tomados, mio=mio, abierta=abierta,
                           sala=sala, es_organizador=r["usuario_id"] == g.user["id"], libres=len(reservados) - len(tomados))


@bp.route("/invitacion/<token>/asiento", methods=["POST"])
@login_required
def invitacion_asiento(token):
    if g.user["rol"] == "admin":
        abort(403)
    db = get_db()
    if limitado(f"asiento|{g.user['id']}", 20, 300):
        flash("Demasiados cambios seguidos. Espera un momento.", "error")
        return redirect(url_for("client.invitacion", token=token))
    db.execute("BEGIN IMMEDIATE")
    try:
        r, reservados, tomados = _contexto_invitacion(db, token)
        if r["estado"] != "confirmada" or rules.estado_visible(r, bool(r["con_acceso"]))[0] == "finalizada":
            raise rules.ReglaError("Esta reserva ya no está activa.")
        a = request.form.get("asiento", type=int)
        if a not in reservados:
            raise rules.ReglaError("Elige uno de los asientos apartados para el equipo.")
        if tomados.get(a) not in (None, g.user["id"]):
            raise rules.ReglaError(f"El asiento {a} acaba de ser elegido por otra persona. Elige otro.")
        db.execute("DELETE FROM asientos_sala WHERE reserva_id = ? AND usuario_id = ?", (r["id"], g.user["id"]))
        db.execute("INSERT INTO asientos_sala (reserva_id, asiento, usuario_id, unido_en) VALUES (?,?,?,?)",
                   (r["id"], a, g.user["id"], rules.ahora_s()))
        db.execute("COMMIT")
        flash(f"Listo: tu asiento es el {a}. Muestra el código QR en la entrada.", "success")
    except rules.ReglaError as e:
        db.execute("ROLLBACK")
        flash(str(e), "error")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return redirect(url_for("client.invitacion", token=token))


@bp.route("/api/invitacion/<token>")
@login_required
def invitacion_estado(token):
    """Asientos ya elegidos (solo números): el mapa de la invitación se actualiza en vivo."""
    _, reservados, tomados = _contexto_invitacion(get_db(), token)
    return jsonify(reservados=reservados, tomados=[a for a, u in tomados.items() if u != g.user["id"]],
                   mio=next((a for a, u in tomados.items() if u == g.user["id"]), None))


# ---- Perfil ----------------------------------------------------------------------------------------
@bp.route("/perfil")
@login_required
def perfil():
    return render_template("client/perfil.html")


@bp.route("/perfil/editar", methods=["GET", "POST"])
@login_required
def perfil_editar():
    errores, datos = {}, {"nombre": g.user["nombre"], "telefono": g.user["telefono"]}
    if request.method == "POST":
        datos = {"nombre": request.form.get("nombre", "").strip()[:80], "telefono": request.form.get("telefono", "")}
        if len(datos["nombre"]) < 3:
            errores["nombre"] = "Escribe tu nombre completo."
        datos["telefono"], err = validar_telefono(datos["telefono"])
        if err:
            errores["telefono"] = err
        nueva = request.form.get("password_nueva", "")
        if nueva:
            if not check_password_hash(g.user["password_hash"], request.form.get("password_actual", "")):
                errores["password_actual"] = "La contraseña actual no coincide."
            if err := validar_password(nueva):
                errores["password_nueva"] = err
        if not errores:
            db = get_db()
            db.execute("UPDATE usuarios SET nombre = ?, telefono = ? WHERE id = ?", (datos["nombre"], datos["telefono"], g.user["id"]))
            if nueva:
                db.execute("UPDATE usuarios SET password_hash = ? WHERE id = ?", (generate_password_hash(nueva), g.user["id"]))
                auditar("password_cambiada")
            flash("Guardamos los cambios de tu perfil.", "success")
            return redirect(url_for("client.perfil"))
    return render_template("client/perfil_editar.html", datos=datos, errores=errores)
