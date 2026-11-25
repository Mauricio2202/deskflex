-- Esquema DeskFlex México (SQLite). Tipos y restricciones pensados para migrar a PostgreSQL.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS usuarios (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre        TEXT    NOT NULL,
    correo        TEXT    NOT NULL UNIQUE,
    telefono      TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    rol           TEXT    NOT NULL DEFAULT 'cliente' CHECK (rol IN ('cliente','admin')),
    activo        INTEGER NOT NULL DEFAULT 1,
    creado_en     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS espacios (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    numero    INTEGER NOT NULL UNIQUE,
    nombre    TEXT    NOT NULL,
    tipo      TEXT    NOT NULL CHECK (tipo IN ('sala','fijo','hot')),
    capacidad INTEGER NOT NULL DEFAULT 1,
    activo    INTEGER NOT NULL DEFAULT 1,
    precio_hora INTEGER NOT NULL DEFAULT 0,    -- pesos MXN por hora (sin IVA)
    precio_dia  INTEGER NOT NULL DEFAULT 0     -- pesos MXN por día completo (sin IVA)
);

CREATE TABLE IF NOT EXISTS reservas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    folio       TEXT    UNIQUE,
    usuario_id  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    espacio_id  INTEGER NOT NULL REFERENCES espacios(id),
    fecha       TEXT    NOT NULL,              -- YYYY-MM-DD
    hora_inicio INTEGER NOT NULL,              -- 0-23
    hora_fin    INTEGER NOT NULL,              -- 1-24, > hora_inicio
    asiento     INTEGER,                       -- en desuso (reservas antiguas por silla); las salas ahora se reservan completas
    modo        TEXT    NOT NULL CHECK (modo IN ('hora','dia')),
    estado      TEXT    NOT NULL DEFAULT 'confirmada' CHECK (estado IN ('pendiente','confirmada','cancelada','expirada')),
    token       TEXT    NOT NULL UNIQUE,       -- el QR solo contiene este token
    creada_en   TEXT    NOT NULL DEFAULT (datetime('now')),
    integrantes INTEGER,                       -- solo salas de juntas: tamaño del equipo (= asientos apartados)
    expira_en   TEXT,                          -- reservas 'pendiente': límite para pagar (hora local)
    total_cent  INTEGER NOT NULL DEFAULT 0,    -- total con IVA en centavos de peso
    CHECK (hora_fin > hora_inicio)
);
CREATE INDEX IF NOT EXISTS idx_reservas_fecha ON reservas (fecha, estado);
CREATE INDEX IF NOT EXISTS idx_reservas_usuario ON reservas (usuario_id);

CREATE TABLE IF NOT EXISTS accesos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    reserva_id  INTEGER REFERENCES reservas(id) ON DELETE SET NULL,
    operador_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    codigo      TEXT,                          -- lo que se escaneó / tecleó
    resultado   TEXT    NOT NULL CHECK (resultado IN ('autorizado','denegado')),
    motivo      TEXT,
    registrado_en TEXT  NOT NULL               -- hora local CDMX 'YYYY-MM-DD HH:MM:SS'
);
CREATE INDEX IF NOT EXISTS idx_accesos_reserva ON accesos (reserva_id, resultado);

-- Asientos de una sala de juntas: cada integrante del equipo elige uno de los apartados
CREATE TABLE IF NOT EXISTS asientos_sala (
    reserva_id INTEGER NOT NULL REFERENCES reservas(id) ON DELETE CASCADE,
    asiento    INTEGER NOT NULL,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    unido_en   TEXT    NOT NULL,
    PRIMARY KEY (reserva_id, asiento),
    UNIQUE (reserva_id, usuario_id)
);

-- Pagos con tarjeta. NUNCA se guarda el número completo, el CVV ni la fecha de vencimiento (PCI DSS req. 3).
CREATE TABLE IF NOT EXISTS pagos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    reserva_id    INTEGER NOT NULL REFERENCES reservas(id) ON DELETE CASCADE,
    folio_pago    TEXT    UNIQUE,
    subtotal_cent INTEGER NOT NULL,
    iva_cent      INTEGER NOT NULL,
    total_cent    INTEGER NOT NULL,
    marca         TEXT,                        -- visa | mastercard | amex
    banco         TEXT,
    ultimos4      TEXT,
    autorizacion  TEXT,
    estado        TEXT    NOT NULL CHECK (estado IN ('aprobado','rechazado')),
    motivo        TEXT,
    creado_en     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pagos_reserva ON pagos (reserva_id, estado);

-- Catálogo de dominios de correo (combobox de registro e inicio de sesión)
CREATE TABLE IF NOT EXISTS dominios_correo (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    dominio TEXT    NOT NULL UNIQUE,
    publico INTEGER NOT NULL DEFAULT 1,        -- 1 = se ofrece al registrarse; 0 = solo para iniciar sesión (personal)
    activo  INTEGER NOT NULL DEFAULT 1
);

-- Rangos BIN (primeros dígitos) para reconocer la tarjeta y el banco emisor
CREATE TABLE IF NOT EXISTS bines (
    prefijo TEXT PRIMARY KEY,
    marca   TEXT NOT NULL,
    banco   TEXT
);

-- Bitácora de seguridad (OWASP A09). No contiene datos de tarjeta ni contraseñas.
CREATE TABLE IF NOT EXISTS auditoria (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha      TEXT    NOT NULL,
    usuario_id INTEGER,
    evento     TEXT    NOT NULL,
    detalle    TEXT,
    ip         TEXT
);
CREATE INDEX IF NOT EXISTS idx_auditoria_fecha ON auditoria (fecha);
