import re

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import get_db
from ..security import (auditar, correo_desde_form, dominios, ip, limpiar_limite, limitado, safe_next)

bp = Blueprint("auth", __name__)

# Hash de relleno: se verifica aunque el correo no exista, para que el tiempo de respuesta no delate cuentas (A07)
_HASH_FALSO = generate_password_hash("relleno-para-igualar-tiempos")
_COMUNES = {"password123", "contraseña1", "1234567890", "qwertyuiop", "deskflex2026", "administrador1", "password1234"}


def _home_for(u):
    return url_for("admin.dashboard") if u["rol"] == "admin" else url_for("client.inicio")


def _iniciar_sesion(u):
    session.clear()                 # evita fijación de sesión
    session["uid"] = u["id"]
    session.permanent = True


def validar_password(pwd: str) -> str | None:
    if len(pwd) < 10 or len(pwd) > 128 or not re.search(r"[A-Za-z]", pwd) or not re.search(r"\d", pwd):
        return "La contraseña debe tener entre 10 y 128 caracteres, con letras y números."
    if pwd.lower() in _COMUNES:
        return "Esa contraseña es demasiado común. Elige otra."
    return None


def validar_telefono(tel: str) -> tuple[str, str | None]:
    limpio = re.sub(r"[\s\-().]", "", tel or "")
    if not re.fullmatch(r"\d{10}", limpio):
        return limpio, "Escribe tu teléfono a 10 dígitos."
    return limpio, None


@bp.route("/")
def raiz():
    if g.user:
        return redirect(_home_for(g.user))
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(safe_next(request.args.get("next")) or _home_for(g.user))
    sel = {"usuario": "", "dominio": None}
    if request.method == "POST":
        correo, err = correo_desde_form(request.form, solo_publicos=False)
        sel = {"usuario": (request.form.get("correo_usuario") or "")[:64], "dominio": request.form.get("dominio", type=int)}
        pwd = (request.form.get("password") or "")[:200]
        clave_cuenta, clave_ip = f"login|{ip()}|{correo}", f"login-ip|{ip()}"
        if limitado(clave_ip, 25, 300, registrar=False) or limitado(clave_cuenta, 6, 300, registrar=False):
            auditar("login_bloqueado", f"correo={correo}")
            flash("Demasiados intentos. Espera unos minutos e inténtalo de nuevo.", "error")
        else:
            u = get_db().execute("SELECT * FROM usuarios WHERE correo = ?", (correo,)).fetchone() if correo else None
            ok = check_password_hash(u["password_hash"] if u else _HASH_FALSO, pwd) and u is not None and not err
            if ok and not u["activo"]:
                flash("Tu cuenta está inactiva. Contacta a recepción.", "error")
            elif ok:
                limpiar_limite(clave_cuenta)
                _iniciar_sesion(u)
                auditar("login_ok", "", u["id"])
                return redirect(safe_next(request.args.get("next")) or _home_for(u))
            else:
                limitado(clave_cuenta, 6, 300)
                limitado(clave_ip, 25, 300)
                auditar("login_fallido", f"correo={correo or '(inválido)'}")
                flash("Correo o contraseña incorrectos.", "error")
    return render_template("auth/login.html", sel=sel, dominios=dominios(False), siguiente=safe_next(request.args.get("next")))


@bp.route("/registro", methods=["GET", "POST"])
def registro():
    if g.user:
        return redirect(_home_for(g.user))
    datos = {"nombre": "", "telefono": "", "correo_usuario": "", "dominio": None}
    errores = {}
    if request.method == "POST":
        datos.update(nombre=request.form.get("nombre", "").strip()[:80], telefono=request.form.get("telefono", ""),
                     correo_usuario=(request.form.get("correo_usuario") or "").strip()[:64],
                     dominio=request.form.get("dominio", type=int))
        pwd = (request.form.get("password") or "")[:200]
        if limitado(f"registro|{ip()}", 8, 3600):
            flash("Se hicieron demasiados registros desde esta conexión. Inténtalo más tarde.", "error")
            return render_template("auth/registro.html", datos=datos, errores=errores, dominios=dominios(True),
                                   siguiente=safe_next(request.args.get("next"))), 429
        correo, err = correo_desde_form(request.form, solo_publicos=True)
        if err:
            errores["correo"] = err
        if len(datos["nombre"]) < 3 or not re.fullmatch(r"[^<>{}$;]{3,80}", datos["nombre"]):
            errores["nombre"] = "Escribe tu nombre completo (sin símbolos especiales)."
        datos["telefono"], err = validar_telefono(datos["telefono"])
        if err:
            errores["telefono"] = err
        if err := validar_password(pwd):
            errores["password"] = err
        db = get_db()
        if "correo" not in errores and db.execute("SELECT 1 FROM usuarios WHERE correo = ?", (correo,)).fetchone():
            errores["correo"] = "Ya existe una cuenta con ese correo."
        if not errores:
            cur = db.execute(
                "INSERT INTO usuarios (nombre, correo, telefono, password_hash) VALUES (?,?,?,?)",
                (datos["nombre"], correo, datos["telefono"], generate_password_hash(pwd)))
            u = db.execute("SELECT * FROM usuarios WHERE id = ?", (cur.lastrowid,)).fetchone()
            _iniciar_sesion(u)
            auditar("registro", "", u["id"])
            flash(f"¡Bienvenido a DeskFlex, {datos['nombre'].split()[0]}! Tu cuenta está lista.", "success")
            return redirect(safe_next(request.args.get("next")) or url_for("client.inicio"))
    return render_template("auth/registro.html", datos=datos, errores=errores, dominios=dominios(True),
                           siguiente=safe_next(request.args.get("next")))


@bp.route("/salir", methods=["POST"])
def salir():
    if g.user:
        auditar("logout")
    session.clear()
    flash("Cerraste sesión. ¡Hasta pronto!", "info")
    return redirect(url_for("auth.login"))
