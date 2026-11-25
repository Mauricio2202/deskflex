import re
import sqlite3
from pathlib import Path

from flask import current_app, g

from . import mapa, payments


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        path = Path(current_app.config["DATABASE"])
        path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None: controlamos las transacciones a mano (BEGIN IMMEDIATE)
        conn = sqlite3.connect(path, isolation_level=None, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def _reconstruir_reservas(db, schema: str):
    """Bases creadas con versiones anteriores tienen un CHECK de estado más corto (sin 'pendiente'/'expirada').
    SQLite no permite cambiarlo con ALTER, así que se reconstruye la tabla conservando todos los datos."""
    ddl = re.search(r"CREATE TABLE IF NOT EXISTS reservas \(.*?\n\);", schema, re.S).group(0)
    ddl = ddl.replace("IF NOT EXISTS reservas", "reservas_nueva")
    cols = [r["name"] for r in db.execute("PRAGMA table_info(reservas)")]
    db.execute("PRAGMA foreign_keys = OFF")
    db.execute("BEGIN")
    try:
        db.execute(ddl)
        lista = ", ".join(cols)
        db.execute(f"INSERT INTO reservas_nueva ({lista}) SELECT {lista} FROM reservas")
        db.execute("DROP TABLE reservas")
        db.execute("ALTER TABLE reservas_nueva RENAME TO reservas")
        db.execute("CREATE INDEX IF NOT EXISTS idx_reservas_fecha ON reservas (fecha, estado)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_reservas_usuario ON reservas (usuario_id)")
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        db.execute("PRAGMA foreign_keys = ON")


def init_db():
    db = get_db()
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    sql_reservas = (db.execute("SELECT sql FROM sqlite_master WHERE name = 'reservas'").fetchone() or {"sql": ""})["sql"] or ""
    if sql_reservas and "'pendiente'" not in sql_reservas:
        db.executescript("PRAGMA foreign_keys = ON;")
        _reconstruir_reservas(db, schema)
    db.executescript(schema)
    # Migraciones de columnas para bases creadas con versiones anteriores
    for tabla, col, ddl in [("reservas", "asiento", "INTEGER"), ("reservas", "integrantes", "INTEGER"),
                            ("reservas", "expira_en", "TEXT"), ("reservas", "total_cent", "INTEGER NOT NULL DEFAULT 0"),
                            ("espacios", "precio_hora", "INTEGER NOT NULL DEFAULT 0"),
                            ("espacios", "precio_dia", "INTEGER NOT NULL DEFAULT 0")]:
        if col not in {r["name"] for r in db.execute(f"PRAGMA table_info({tabla})")}:
            db.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {ddl}")
    seed_catalogos(db)


def seed_catalogos(db):
    """Catálogos que el sistema necesita siempre: dominios de correo, rangos BIN y precios."""
    for dom, publico in (("gmail.com", 1), ("hotmail.com", 1), ("deskflex.mx", 0)):
        db.execute("INSERT OR IGNORE INTO dominios_correo (dominio, publico) VALUES (?, ?)", (dom, publico))
    # Cuentas anteriores con otros dominios siguen pudiendo iniciar sesión (no se ofrecen al registrarse)
    for r in db.execute("SELECT DISTINCT substr(correo, instr(correo, '@') + 1) AS d FROM usuarios WHERE instr(correo, '@') > 0").fetchall():
        db.execute("INSERT OR IGNORE INTO dominios_correo (dominio, publico) VALUES (?, 0)", (r["d"],))
    for fila in payments.BINES_DEMO:
        db.execute("INSERT OR IGNORE INTO bines (prefijo, marca, banco) VALUES (?,?,?)", fila)
    for e in db.execute("SELECT id, numero FROM espacios WHERE precio_hora = 0").fetchall():
        h, d = mapa.precios(e["numero"])
        db.execute("UPDATE espacios SET precio_hora = ?, precio_dia = ? WHERE id = ?", (h, d, e["id"]))


def init_app(app):
    app.teardown_appcontext(close_db)
