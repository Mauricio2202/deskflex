import os
import secrets
from datetime import timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def _secret_key() -> str:
    """OWASP A02/A04: la clave nunca va en el código. Se toma de SECRET_KEY o se genera una vez
    y se guarda en instance/secret.key (permisos 600)."""
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    f = BASE / "instance" / "secret.key"
    try:
        if f.exists():
            return f.read_text().strip()
        f.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_hex(32)
        f.write_text(key)
        try:
            f.chmod(0o600)
        except OSError:
            pass
        return key
    except OSError:
        return secrets.token_hex(32)      # solo en memoria: las sesiones se reinician con la app


HTTPS = os.environ.get("DESKFLEX_HTTPS") == "1"     # actívalo cuando el sitio se publique con HTTPS


class Config:
    # En producción define SECRET_KEY como variable de entorno.
    SECRET_KEY = _secret_key()
    DATABASE = os.environ.get("DESKFLEX_DB", str(BASE / "instance" / "deskflex.db"))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = HTTPS
    PREFERRED_URL_SCHEME = "https" if HTTPS else "http"
    FORCE_HTTPS = HTTPS
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)   # la sesión caduca tras 2 h sin actividad
    DEMO_HINT = True          # muestra las cuentas de demostración en el login (desactívalo en producción)
    MAX_CONTENT_LENGTH = 64 * 1024

    # Reglas de negocio del coworking
    TIMEZONE = "America/Mexico_City"
    OPEN_HOUR = 7            # primera hora reservable
    CLOSE_HOUR = 21          # el coworking cierra a las 21:00
    CLOSED_WEEKDAYS = (6,)   # domingo cerrado (0 = lunes)
    MAX_ADVANCE_DAYS = 60
    MONTAJE_MIN = 30         # acceso 30 min ANTES del inicio para acomodar lo necesario
    DESMONTAJE_MIN = 30      # y 30 min DESPUÉS del fin para recoger y limpiar
    BLOQUEAR_MARGENES = True # el espacio no se reserva a otra persona durante esos márgenes
    CHECKIN_EARLY_MIN = MONTAJE_MIN
    SALA_MIN_INTEGRANTES = 4 # las salas de juntas son para equipos de trabajo grandes
    PAGO_MINUTOS = 3         # tiempo para pagar antes de liberar el lugar
    IVA = 0.16
    PAGOS_DEMO = True        # el cobro es simulado: cámbialo a False al integrar un procesador real
    PAGO_INTENTOS = 4        # intentos de pago por reserva antes de liberar el lugar
