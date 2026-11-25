import hmac
import re
import secrets
import time
from functools import wraps
from urllib.parse import urlparse

from flask import abort, flash, g, redirect, request, session, url_for

from .db import get_db

# ---- Límite de intentos (OWASP A06/A07): en memoria, por clave ------------------------------------
_golpes: dict[str, list[float]] = {}


def limitado(clave: str, maximo: int, ventana_s: int, registrar: bool = True) -> bool:
    """True si `clave` ya superó `maximo` eventos en los últimos `ventana_s` segundos."""
    ahora = time.time()
    recientes = [t for t in _golpes.get(clave, []) if ahora - t < ventana_s]
    bloqueado = len(recientes) >= maximo
    if registrar and not bloqueado:
        recientes.append(ahora)
    _golpes[clave] = recientes
    return bloqueado


def limpiar_limite(clave: str):
    _golpes.pop(clave, None)


def ip() -> str:
    return (request.remote_addr or "?")[:45]


# ---- Bitácora de seguridad (OWASP A09) ---------------------------------------------------------------
def auditar(evento: str, detalle: str = "", usuario_id: int | None = None):
    """Registra eventos relevantes. NUNCA recibir contraseñas, números de tarjeta ni CVV."""
    from . import rules
    uid = usuario_id if usuario_id is not None else (g.user["id"] if g.get("user") else None)
    try:
        get_db().execute("INSERT INTO auditoria (fecha, usuario_id, evento, detalle, ip) VALUES (?,?,?,?,?)",
                         (rules.ahora_s(), uid, evento[:40], (detalle or "")[:300], ip()))
    except Exception:       # la bitácora nunca debe tumbar la operación principal
        pass


# ---- Correo: usuario + "@" + dominio del catálogo (OWASP A05) -----------------------------------------
_LOCAL = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")


def correo_desde_form(form, solo_publicos: bool) -> tuple[str, str | None]:
    """Arma el correo con la parte local escrita por la persona y un dominio elegido del catálogo en la base
    de datos. El dominio se busca por su id (entero) con consulta parametrizada: no se acepta texto libre."""
    local = (form.get("correo_usuario") or "").strip().lower()
    if not _LOCAL.match(local) or ".." in local:
        return "", "Escribe tu usuario de correo (solo letras, números, punto, guion o guion bajo)."
    try:
        did = int(form.get("dominio", ""))
    except ValueError:
        return "", "Elige el dominio de tu correo."
    cond = " AND publico = 1" if solo_publicos else ""
    d = get_db().execute(f"SELECT dominio FROM dominios_correo WHERE id = ? AND activo = 1{cond}", (did,)).fetchone()
    if not d:
        return "", "Elige el dominio de tu correo."
    return f"{local}@{d['dominio']}", None


def dominios(solo_publicos: bool):
    cond = " AND publico = 1" if solo_publicos else ""
    return get_db().execute(f"SELECT id, dominio FROM dominios_correo WHERE activo = 1{cond} ORDER BY publico DESC, dominio").fetchall()


def csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(24)
    return session["_csrf"]


def check_csrf():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        esperado = session.get("_csrf", "")
        # Se exige un token no vacío: sin esto, un POST sin sesión ni token (ambos vacíos) pasaría la comparación.
        if not sent or not esperado or not hmac.compare_digest(sent, esperado):
            abort(400, "La sesión del formulario expiró. Recarga la página e inténtalo de nuevo.")


def load_user():
    g.user = None
    uid = session.get("uid")
    if uid:
        u = get_db().execute("SELECT * FROM usuarios WHERE id = ? AND activo = 1", (uid,)).fetchone()
        if u:
            g.user = u
        else:
            session.clear()


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            flash("Inicia sesión para continuar.", "info")
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*a, **kw)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*a, **kw):
        if g.user["rol"] != "admin":
            abort(403)
        return view(*a, **kw)
    return wrapped


def client_required(view):
    """Pantallas de cliente: un administrador es redirigido a su panel."""
    @wraps(view)
    @login_required
    def wrapped(*a, **kw):
        if g.user["rol"] == "admin":
            return redirect(url_for("admin.dashboard"))
        return view(*a, **kw)
    return wrapped


def safe_next(target: str | None) -> str | None:
    """Solo rutas internas (evita redirecciones abiertas, OWASP A01)."""
    if not target or len(target) > 300 or "\\" in target or any(c in target for c in "\r\n\t"):
        return None
    p = urlparse(target)
    return target if not p.netloc and not p.scheme and target.startswith("/") and not target.startswith("//") else None
