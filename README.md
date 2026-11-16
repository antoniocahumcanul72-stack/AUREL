# AUREL Watches — Alta relojería

Tienda educativa de relojes con diseño premium. **No procesa pagos reales.** Proyecto original, sin cuentas ni credenciales configuradas y sin historial Git.

## Funciones

- Catálogo de relojes, filtros, búsqueda, detalle, disponibilidad, alertas de pocas unidades y agotados.
- Registro/inicio de sesión con contraseñas cifradas (hash), sesión y formularios protegidos con token CSRF.
- Carrito, eliminación de artículos y total de compra.
- Reserva de inventario durante 5 minutos, contador, confirmación de compra simulada, cancelación y vencimiento.
- QR por reserva que abre una URL de verificación pública con artículos y estado, sin revelar datos personales.
- Historial de reservas y compras simuladas.
- Panel administrador con CRUD de relojes, stock, ocultar artículos y contadores.
- API pública JSON de lectura en `/api/productos`.
- MongoDB Atlas, Gunicorn, `.env.example`, `render.yaml` y `Procfile`.

## 1. Preparación en Windows / VS Code

Descomprime y abre la carpeta `AUREL_Watches` (la que contiene `app.py`). En PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Abre `.env` y cambia `MONGO_URI`, `SECRET_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`. La URI debe tener la contraseña real del usuario de Atlas, codificada si contiene caracteres especiales. **Nunca compartas ni subas `.env`**. Configura Database Access y Network Access en Atlas.

## 2. Iniciar y probar

```powershell
.\.venv\Scripts\python.exe -c "from app import client; print(client.admin.command('ping'))"
.\.venv\Scripts\python.exe setup_admin.py
.\.venv\Scripts\python.exe seed_demo.py
.\.venv\Scripts\python.exe app.py
```

Abre `http://127.0.0.1:5000`. Entra con el correo/contraseña de administrador de `.env`. Crea una cuenta normal para probar carrito, reserva, QR y confirmación. Las reservas vencidas dejan de bloquear stock por su fecha de expiración, incluso si nadie abre la página; su estado se marca `expired` al consultar las páginas de reservas o al iniciar otra reserva. No hay tarea programada de limpieza.

## 3. GitHub

Desde la carpeta del proyecto:

```powershell
git init
git status
git add .
git status
git commit -m "Proyecto AUREL Watches"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/AUREL_Watches.git
git push -u origin main
```

**Antes del commit comprueba que `.env` y `.venv` no aparezcan en los archivos preparados.** Crea el repositorio vacío en GitHub sin README adicional.

## 4. Render

- Crea un **Web Service** conectado al repositorio, rama `main`, runtime Python.
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 90`
- Environment Variables: `MONGO_URI`, `MONGO_DB`, `SECRET_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `PUBLIC_BASE_URL` (URL pública real de Render, p. ej. `https://tu-app.onrender.com`), `FLASK_DEBUG=0`.
- `PUBLIC_BASE_URL` debe coincidir con el dominio final para que el QR abra el sitio publicado. Si no se configura, se usa el dominio de la petición que generó el QR.
- **El administrador se crea localmente** ejecutando `setup_admin.py` con el mismo Atlas al que Render se conecta. No ejecutes `setup_admin.py` como parte del inicio web.
- Atlas debe autorizar conexiones desde Render. Mantén los accesos de red lo más restringidos posible.

## Consideraciones

- El bloqueo de producto evita la mayoría de conflictos de inventario entre solicitudes normales, pero **no sustituye transacciones MongoDB** ni garantiza consistencia ante caída del proceso a mitad de una confirmación. Para producción comercial real se requieren transacciones, idempotencia, auditoría y pruebas de carga.
- La aplicación usa una base de datos propia; no se incluyen datos de clientes ni contraseñas.
- Las imágenes de demostración son ilustraciones CSS; agrega URLs HTTPS propias desde el panel administrador. En Render, archivos subidos al disco local no serían persistentes; usa almacenamiento externo para imágenes.
- El QR contiene un enlace público con token aleatorio. Quien tenga el QR podrá consultar el estado y artículos de esa reserva. No es prueba de pago ni autorización de entrega.
- Los relojes de ejemplo y la marca AUREL son ficticios.
