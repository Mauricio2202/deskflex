# DeskFlex México — Control de acceso y reservas para coworking

Mapa interactivo, reservas por hora/día completo, pasarela de pago con tarjeta (simulada), salas de juntas para equipos con invitación por QR, check-in y bitácora de seguridad.

## Ejecutar
    python -m venv .venv
    .venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
    pip install -r requirements.txt
    python run.py                     # http://127.0.0.1:5000

La base (SQLite) se crea sola en `instance/deskflex.db` con datos de demostración. Si ya tenías una base anterior, se **migra sola** al arrancar (conserva reservas y accesos; agrega pagos, dominios de correo, BIN, bitácora y precios).

## Cuentas de demostración
El correo se escribe como *usuario* + `@` + dominio elegido en la lista desplegable.

| Rol | Usuario | Dominio | Contraseña |
|---|---|---|---|
| Administrador | admin | deskflex.mx | Admin2026! |
| Cliente | carlos.perez10 | gmail.com | Carlos2026! |
| Cliente | ana.torres | hotmail.com | DeskFlex2026! |
| Cliente | diego.ramirez | gmail.com | DeskFlex2026! |
| Cliente | fer15 | hotmail.com | DeskFlex2026! |

El registro público ofrece gmail.com y hotmail.com; `deskflex.mx` es solo para personal. Los dominios viven en la tabla `dominios_correo` (el formulario envía su id, no texto libre).

## Qué incluye esta versión
1. **Salas de juntas solo para equipos.** Sin selección de asientos individuales. Al tocar una sala se pregunta *«¿Cuentas con un equipo de trabajo?»*: si no, se niega con el mensaje de que es exclusiva para equipos grandes; si sí, se captura el número de integrantes (mín. 4; capacidad Sala 1 = 18, Sala 2 = 10) y se muestran los asientos que se apartan. El backend valida lo mismo (no depende del navegador).
2. **Invitación por QR.** El QR de la sala es el acceso de todo el equipo y abre `/invitacion/<token>`: cada integrante inicia sesión o se registra y elige su asiento entre los apartados (mapa en vivo). Check-in: la sala admite tantas entradas como integrantes («entrada n de N»); un escritorio, una.
3. **Montaje y desmontaje.** Todo horario (sala o asiento) incluye 30 min antes para acomodar y 30 min después para recoger/limpiar. Aparece en el pase, el ticket (HTML y PDF) y en el check-in. Entre dos reservas del mismo lugar debe haber 1 h libre (configurable).
4. **Pasarela de pago** con 3 min para pagar (el lugar queda apartado y se libera solo). Valida Luhn, vencimiento y CVV; detecta VISA, Mastercard, American Express y los bancos BBVA, Citibanamex, HSBC, Banorte, Scotiabank, Inbursa, Banco Azteca y BanCoppel, y resalta su marca. Ticket de pago descargable (PDF) e imprimible, y QR de check-in descargable (SVG), ambos con el logo de DeskFlex.
5. **Correo con `@` fijo y dominio en combobox** (login y registro), con consultas parametrizadas.
6. **OWASP Top 10** — ver `SECURITY.md`.

## Precios (MXN, sin IVA; IVA 16 %)
| Espacio | Por hora | Día completo (8 h) |
|---|---|---|
| Sala de juntas 1 (18 personas) | $650 | $5,200 |
| Sala de juntas 2 (10 personas) | $380 | $3,040 |
| Escritorios fijos (3–9) | $110 | $880 |
| Hot desks (10–25) | $70 | $560 |

Se cambian en `deskflex/mapa.py` (`precios`) y se vuelven a sembrar al arrancar.

## Tarjetas de prueba (modo demostración)
VISA 4111 1111 1111 1111 · Mastercard 5555 5555 5555 4444 · Amex 3782 822463 10005 (CVV de 4) · BBVA 4000 1000 0000 0000 · Citibanamex 5100 1000 0000 0006 · HSBC 4000 2000 0000 0008 · Banorte 5100 2000 0000 0004 · Scotiabank 4000 3000 0000 0006 · Inbursa 5100 3000 0000 0002 · Banco Azteca 4000 4000 0000 0004 · BanCoppel 5100 4000 0000 0000.
Vencimiento futuro y CVV cualquiera. Terminan en **9995** → fondos insuficientes; **0119** → rechazo del banco.

> ⚠️ La pasarela es una **simulación**: no mueve dinero y los rangos BIN son de demostración. Para cobrar de verdad hay que integrar un procesador certificado PCI DSS (Conekta, Stripe, OpenPay, Mercado Pago…) con campos alojados por ellos, y cargar su tabla BIN oficial en `bines`. Con `PAGOS_DEMO = False` (config.py) desaparece la leyenda «Pago de demostración» de los tickets.

## Variables de entorno
| Variable | Uso |
|---|---|
| `SECRET_KEY` | Clave de sesión. Si falta se genera en `instance/secret.key` |
| `DESKFLEX_HTTPS=1` | Cookies `Secure`, HSTS y redirección a HTTPS |
| `DESKFLEX_BEHIND_PROXY=1` | Confía en `X-Forwarded-*` (detrás de nginx, etc.) |
| `DESKFLEX_DEBUG=1` | Depurador de Flask (**solo desarrollo**) |

Producción: define `SECRET_KEY`, `DESKFLEX_HTTPS=1`, pon `DEMO_HINT = False` en `deskflex/config.py` y sirve con un servidor WSGI (gunicorn/waitress) tras HTTPS. La cámara del check-in también exige HTTPS (o `127.0.0.1`).

## Logos oficiales de tarjetas y bancos
Por defecto se muestran etiquetas de texto. Si copias `visa.svg`, `mastercard.svg`, `amex.svg`, `bbva.svg`, `citibanamex.svg`, `hsbc.svg`, `banorte.svg`, `scotiabank.svg`, `inbursa.svg`, `azteca.svg`, `bancoppel.svg` (o .png) en `deskflex/static/img/marcas/`, se usan automáticamente. Los logos son marcas registradas de cada institución: obténlos de sus kits oficiales.

## Estructura
- `deskflex/rules.py`: reglas de negocio (precios, márgenes, equipos, pendientes/expiración, acceso)
- `deskflex/payments.py`: validación de tarjeta, marca/banco y autorizador simulado
- `deskflex/tickets.py`, `pdf.py`, `qr.py`: ticket PDF, QR con logo y generador de QR/PDF sin dependencias
- `deskflex/security.py`: CSRF, límites de intentos, bitácora, correo/dominios
- `deskflex/views/`: auth, cliente, admin, API · `mapa.py`: plano, asientos y precios
- `deskflex/schema.sql` + `db.py`: esquema, migraciones y catálogos

## Cámara del check-in
El decodificador usa `BarcodeDetector` del navegador o, si no existe, jsQR desde un CDN (permitido en la CSP). Para uso sin internet guarda `jsQR.js` en `deskflex/static/vendor/` y ajusta la CSP.

## Límites conocidos
SQLite (migrar a PostgreSQL para varias instancias), limitador de intentos en memoria (usar Redis con varios procesos), pasarela simulada, política de reembolso por cancelación no definida.
