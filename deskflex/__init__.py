import os
import sqlite3
from pathlib import Path

from flask import Flask, g, redirect, render_template, request, session, url_for

from . import db as database
from . import rules
from .config import Config
from .security import check_csrf, csrf_token, load_user


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(Config)
    if config:
        app.config.update(config)
    database.init_app(app)

    with app.app_context():
        database.init_db()
        db = database.get_db()
        if app.config.get("SEED_DEMO", True) and not db.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone():
            from .seed import seed_demo
            seed_demo(db)

    from .views import admin, api, auth, client
    for bp in (auth.bp, client.bp, admin.bp, api.bp):
        app.register_blueprint(bp)

    if os.environ.get("DESKFLEX_BEHIND_PROXY") == "1":      # detrás de nginx/Caddy: respeta X-Forwarded-*
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    @app.before_request
    def _before():
        if app.config.get("FORCE_HTTPS") and not request.is_secure:
            return redirect(request.url.replace("http://", "https://", 1), code=301)
        load_user()
        check_csrf()

    # Política de seguridad de contenido (OWASP A02): sin scripts en línea; solo orígenes conocidos.
    CSP = ("default-src 'self'; script-src 'self' https://cdn.jsdelivr.net https://unpkg.com https://cdnjs.cloudflare.com; "
           "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
           "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; "
           "base-uri 'self'; form-action 'self'; object-src 'none'")

    @app.after_request
    def _headers(resp):
        h = resp.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "same-origin")
        h.setdefault("Content-Security-Policy", CSP)
        h.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=(), payment=(self)")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        h.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        if app.config.get("FORCE_HTTPS"):
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if not request.path.startswith("/static/"):      # páginas con datos personales o de pago: nunca en caché
            h["Cache-Control"] = "no-store, max-age=0"
            h["Pragma"] = "no-cache"
        return resp

    from . import mapa, payments

    def marca_logo(clave):
        """Si colocas el logo oficial de una marca en static/img/marcas/<clave>.svg|png se usa en lugar de la etiqueta."""
        for ext in ("svg", "png"):
            if (Path(app.static_folder) / "img" / "marcas" / f"{clave}.{ext}").exists():
                return url_for("static", filename=f"img/marcas/{clave}.{ext}")
        return None

    app.jinja_env.globals.update(
        marca_logo=marca_logo,
        mapa=mapa,
        ART_ESPACIOS={n: {'nombre': nm, 'tipo': t, 'capacidad': c} for n, nm, t, c in mapa.ESPACIOS})
    app.jinja_env.filters.update(
        hora=rules.fmt_hora, rango=lambda r: rules.fmt_rango(r["hora_inicio"], r["hora_fin"]),
        fecha=rules.fmt_fecha, fecha_corta=lambda d: rules.fmt_fecha(d, corta=True),
        fecha_dia=rules.fmt_fecha_dia, mxn=rules.fmt_mxn,
        iniciales=lambda n: "".join(p[0] for p in n.split()[:2]).upper(),
        primer_nombre=lambda n: n.split()[0],
    )

    @app.context_processor
    def _ctx():
        return dict(csrf_token=csrf_token, user=g.get("user"), endpoint=request.endpoint or "")

    def _error(code, titulo, texto):
        def handler(e):
            msg = getattr(e, "description", texto) if code == 400 else texto
            return render_template("error.html", code=code, titulo=titulo, texto=msg), code
        return handler

    app.register_error_handler(400, _error(400, "No pudimos procesar la solicitud", ""))
    app.register_error_handler(403, _error(403, "Zona restringida", "Esta sección es solo para el personal de DeskFlex."))
    app.register_error_handler(404, _error(404, "No encontramos esa página", "Puede que el enlace haya cambiado o que la reserva ya no exista."))
    app.register_error_handler(405, _error(405, "Acción no permitida", "Esa acción no está disponible desde aquí."))
    app.register_error_handler(413, _error(413, "Solicitud demasiado grande", "Reduce el tamaño de los datos enviados."))
    app.register_error_handler(429, _error(429, "Demasiadas solicitudes", "Espera un momento antes de intentarlo de nuevo."))

    # OWASP A10: los errores inesperados fallan de forma segura: se registran sin datos sensibles y el usuario
    # solo ve un mensaje genérico (nunca trazas ni detalles internos).
    @app.errorhandler(sqlite3.OperationalError)
    def _db_busy(e):
        app.logger.error("Error de base de datos: %s", type(e).__name__)
        return render_template("error.html", code=503, titulo="Servicio ocupado", texto="El sistema está muy ocupado. Inténtalo de nuevo en unos segundos."), 503

    @app.errorhandler(500)
    def _boom(e):
        return render_template("error.html", code=500, titulo="Algo salió mal", texto="Ocurrió un error inesperado. Ya quedó registrado; inténtalo de nuevo."), 500
    return app
