"""Datos iniciales y de demostración."""
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

from . import payments, rules
from .mapa import ESPACIOS

DEMO_USERS = [
    ("Administrador DeskFlex", "admin@deskflex.mx", "5555550100", "Admin2026!", "admin", 1),
    ("Carlos Pérez", "carlos.perez10@gmail.com", "5548961012", "Carlos2026!", "cliente", 1),
    ("Fernando Chávez", "fer15@hotmail.com", "5596120536", "DeskFlex2026!", "cliente", 1),
    ("Ana Lucía Torres", "ana.torres@hotmail.com", "5521347788", "DeskFlex2026!", "cliente", 1),
    ("Diego Ramírez", "diego.ramirez@gmail.com", "5533001122", "DeskFlex2026!", "cliente", 1),
    ("Mariana Solís", "mariana.solis@gmail.com", "5544556677", "DeskFlex2026!", "cliente", 0),
]


def seed_espacios(db):
    db.executemany("INSERT OR IGNORE INTO espacios (numero, nombre, tipo, capacidad) VALUES (?,?,?,?)", ESPACIOS)
    from .db import seed_catalogos
    seed_catalogos(db)          # precios por espacio, dominios de correo y rangos BIN


def _pago_demo(db, rid, ultimos4="1111", marca="visa", banco=None):
    """Pago aprobado de demostración (sin datos reales de tarjeta)."""
    r = db.execute("SELECT * FROM reservas WHERE id = ?", (rid,)).fetchone()
    e = db.execute("SELECT * FROM espacios WHERE id = ?", (r["espacio_id"],)).fetchone()
    pr = rules.calcular_precio(e, r["modo"], r["hora_inicio"], r["hora_fin"])
    db.execute("UPDATE reservas SET total_cent = ? WHERE id = ?", (pr["total_cent"], rid))
    cur = db.execute("""INSERT INTO pagos (reserva_id, subtotal_cent, iva_cent, total_cent, marca, banco, ultimos4, autorizacion, estado, creado_en)
                        VALUES (?,?,?,?,?,?,?,?, 'aprobado', ?)""",
                     (rid, pr["subtotal_cent"], pr["iva_cent"], pr["total_cent"], marca, banco, ultimos4, f"{100000 + rid * 7919 % 899999}", rules.ahora_s()))
    db.execute("UPDATE pagos SET folio_pago = ? WHERE id = ?", (payments.folio_pago(cur.lastrowid), cur.lastrowid))


def _dia_habil(offset: int) -> str:
    d = rules.today() + timedelta(days=offset)
    while d.weekday() in (6,):
        d += timedelta(days=1)
    return d.isoformat()


def seed_demo(db):
    seed_espacios(db)
    for nombre, correo, tel, pwd, rol, activo in DEMO_USERS:
        db.execute("INSERT OR IGNORE INTO usuarios (nombre, correo, telefono, password_hash, rol, activo) VALUES (?,?,?,?,?,?)",
                   (nombre, correo, tel, generate_password_hash(pwd), rol, activo))
    uid = {r["correo"]: r["id"] for r in db.execute("SELECT id, correo FROM usuarios")}
    eid = {r["numero"]: r["id"] for r in db.execute("SELECT id, numero FROM espacios")}
    if db.execute("SELECT COUNT(*) c FROM reservas").fetchone()["c"]:
        return
    carlos, fer, ana, diego = (uid["carlos.perez10@gmail.com"], uid["fer15@hotmail.com"],
                               uid["ana.torres@hotmail.com"], uid["diego.ramirez@gmail.com"])
    ahora = rules.now()
    h = min(max(ahora.hour, 7), 19)
    hoy_ok = ahora.hour <= 19 and ahora.date().weekday() != 6
    hoy = ahora.date().isoformat()
    ok = []
    dia1 = hoy if hoy_ok else _dia_habil(1)
    ini1 = h if hoy_ok else 9
    # DF-001: equipo de Carlos (6 personas) en la sala 1, ahora mismo (para probar el check-in) o el siguiente día hábil
    ok.append(rules.crear_reserva(db, carlos, eid[1], dia1, "hora", ini1, ini1 + 2, integrantes=6, tiene_equipo=True, confirmar=True))
    ok.append(rules.crear_reserva(db, fer, eid[6], _dia_habil(1), "dia", 7, 21, confirmar=True))
    ok.append(rules.crear_reserva(db, carlos, eid[25], _dia_habil(2), "hora", 9, 11, confirmar=True))
    ok.append(rules.crear_reserva(db, ana, eid[12], dia1, "dia", 7, 21, confirmar=True))
    ok.append(rules.crear_reserva(db, diego, eid[2], _dia_habil(2), "hora", 15, 17, integrantes=5, tiene_equipo=True, confirmar=True))
    ok.append(rules.crear_reserva(db, ana, eid[4], _dia_habil(3), "dia", 7, 21, confirmar=True))
    bancos = [("4111", "visa", None), ("4000", "visa", "BBVA"), ("4444", "mastercard", None)]
    for i, rid in enumerate(ok):
        _pago_demo(db, rid, *bancos[i % 3])
    # Integrantes de la sala 1 que ya eligieron asiento
    ahora_s = rules.ahora_s()
    for usuario, asiento in ((carlos, 1), (fer, 9), (ana, 2)):
        db.execute("INSERT INTO asientos_sala (reserva_id, asiento, usuario_id, unido_en) VALUES (?,?,?,?)", (ok[0], asiento, usuario, ahora_s))
    # Historial: reservas pasadas con su check-in
    for usuario, esp, dias, ini, fin in [(carlos, 14, -3, 8, 12), (fer, 19, -5, 7, 21), (diego, 1, -2, 10, 12)]:
        d = date.fromisoformat(_dia_habil(dias)) if dias > 0 else rules.today() + timedelta(days=dias)
        while d.weekday() == 6:
            d -= timedelta(days=1)
        sala = esp in (1, 2)
        cur = db.execute(
            "INSERT INTO reservas (usuario_id, espacio_id, fecha, hora_inicio, hora_fin, modo, token, integrantes) VALUES (?,?,?,?,?,?,?,?)",
            (usuario, eid[esp], d.isoformat(), ini, fin, "dia" if (ini, fin) == (7, 21) else "hora", f"hist-{usuario}-{esp}", 8 if sala else None))
        rid = cur.lastrowid
        db.execute("UPDATE reservas SET folio = ? WHERE id = ?", (f"DF-{rid:03d}", rid))
        _pago_demo(db, rid)
        db.execute("INSERT INTO accesos (reserva_id, operador_id, codigo, resultado, registrado_en) VALUES (?,?,?,?,?)",
                   (rid, uid["admin@deskflex.mx"], f"DF-{rid:03d}", "autorizado", f"{d.isoformat()} {ini:02d}:05:00"))
