from flask import Blueprint, current_app, g, jsonify, request

from .. import payments, rules
from ..db import get_db
from ..security import limitado, login_required

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.route("/disponibilidad")
@login_required
def disponibilidad():
    """Estado de cada espacio para la ventana elegida + estado de cada hora del día."""
    db, cfg = get_db(), current_app.config
    fecha, modo = request.args.get("fecha", ""), request.args.get("modo", "hora")
    out = {"ok": True, "estados": None, "horas": [], "mensaje": None}
    try:
        f, _, ini, fin = rules.validar_ventana(fecha, "dia", None, None) if modo == "dia" else \
            rules.validar_ventana(fecha, "hora", request.args.get("inicio"), request.args.get("fin"))
    except rules.ReglaError as e:
        out["mensaje"] = str(e)
    else:
        out["estados"], precios = rules.disponibilidad_completa(db, f, ini, fin)
        out["precios"] = {n: rules.fmt_mxn(c) for n, c in precios.items()}
        out["ventana"] = {"fecha": f, "inicio": ini, "fin": fin, "texto": rules.fmt_rango(ini, fin),
                         "acceso": rules.ventana_acceso({"fecha": f, "hora_inicio": ini, "hora_fin": fin})["acceso"]}
    # Horas del día: pasadas o ya ocupadas por el propio usuario
    try:
        from datetime import date
        d = date.fromisoformat(fecha)
        propias = rules.horas_ocupadas_por_usuario(db, g.user["id"], d.isoformat())
        h_now = rules.now().hour if d == rules.today() else -1
        for h in range(cfg["OPEN_HOUR"], cfg["CLOSE_HOUR"]):
            estado = "pasada" if h < h_now else ("mia" if any(a <= h < b for a, b in propias) else "ok")
            out["horas"].append({"h": h, "texto": rules.fmt_hora(h), "estado": estado})
    except ValueError:
        pass
    return jsonify(out)


@bp.route("/bin")
@login_required
def bin_info():
    """Red y banco emisor a partir de los primeros dígitos (BIN). Solo se reciben 6-8 dígitos, nunca el número completo."""
    if limitado(f"bin|{g.user['id']}", 120, 60):
        return jsonify(red=None, banco=None), 429
    b = payments.solo_digitos(request.args.get("b", ""))[:8]
    red = payments.detectar_red(b) if b else None
    banco = payments.detectar_banco(get_db(), b) if len(b) >= 6 else None
    return jsonify(red=red, banco=banco, banco_id=payments.BANCO_ID.get(banco) if banco else None)
