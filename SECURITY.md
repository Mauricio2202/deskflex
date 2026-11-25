# Seguridad — DeskFlex México

## OWASP Top 10 (edición 2025) — qué se aplicó y dónde

| # | Categoría | Medidas |
|---|---|---|
| A01 | Control de acceso roto | Roles (cliente/admin) verificados en servidor; cada reserva/ticket/QR se valida contra su dueño (sin IDOR); invitaciones por token aleatorio; `next` de login solo acepta rutas internas (`safe_next`). |
| A02 | Configuración de seguridad incorrecta | CSP estricta (sin scripts en línea), `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, COOP/CORP, HSTS con HTTPS, `no-store` en páginas dinámicas, cookies `HttpOnly`/`SameSite`/`Secure`, debug apagado por defecto, enlace a 127.0.0.1. |
| A03 | Fallos en la cadena de suministro | Dependencias mínimas (Flask, Werkzeug, tzdata) con versión mínima fijada; QR y PDF escritos a mano (sin librerías). Único recurso externo: jsQR por CDN (opcional) listado en la CSP. |
| A04 | Fallos criptográficos | Contraseñas con scrypt/pbkdf2 (Werkzeug); `SECRET_KEY` desde entorno o generada con `secrets`; tokens con `secrets.token_urlsafe`; HTTPS en producción. |
| A05 | Inyección | Todas las consultas SQL parametrizadas; el dominio del correo se elige de la tabla `dominios_correo` por id; el usuario del correo se valida con lista blanca de caracteres; Jinja con autoescape + CSP contra XSS. |
| A06 | Diseño inseguro | Límites de intentos (login, registro, validación y pago), reserva pendiente de 3 min con expiración, transacciones `BEGIN IMMEDIATE` contra doble reserva, reglas de negocio validadas en servidor (equipo mínimo, márgenes, cupos). |
| A07 | Fallas de autenticación | Mensajes genéricos, hash ficticio para igualar tiempos, `session.clear()` al iniciar sesión, sesión de 2 h, contraseña ≥ 10 con letras y números y lista de contraseñas comunes, bloqueo temporal por cuenta (6/5 min) y por IP (25). |
| A08 | Fallos de integridad | Token CSRF obligatorio en todos los POST (no vacío y comparado en tiempo constante); sin deserialización insegura. |
| A09 | Registro y alertas | Tabla `auditoria` y pantalla `/admin/auditoria` (inicios de sesión, fallos, reservas, pagos, acciones del personal). Nunca se registran contraseñas ni datos de tarjeta. |
| A10 | Condiciones excepcionales | Manejadores de error genéricos (400/403/404/405/413/429/500/503) sin trazas; el pago falla cerrado con rollback. |

## PCI DSS (alcance de este prototipo)
- El número completo (PAN), el CVV y el vencimiento **se validan en memoria y nunca se guardan ni se escriben en bitácoras**. Solo se conserva marca, banco, últimos 4 dígitos y número de autorización.
- Campo CVV de tipo contraseña, `autocomplete="off"`, páginas de pago con `no-store`.
- Límite de intentos por reserva (4) y general (40/5 min) contra pruebas de tarjetas.
- Comunicación cifrada: activar `DESKFLEX_HTTPS=1` y servir tras TLS 1.2+.
- **Importante:** el autorizador es simulado. Para procesar pagos reales la forma recomendada de reducir el alcance PCI (SAQ A) es usar campos/redirección alojados por un procesador certificado, de modo que el servidor de DeskFlex nunca reciba el PAN.

## Límites conocidos
- Limitador de intentos en memoria (un solo proceso).
- jsQR se carga desde CDN salvo que se guarde localmente.
- Tabla BIN de demostración (no representa rangos reales de cada banco).
- Sin 2FA ni recuperación de contraseña por correo.
- Esta lista es una guía de diseño; no sustituye una auditoría o certificación PCI/OWASP formal.
