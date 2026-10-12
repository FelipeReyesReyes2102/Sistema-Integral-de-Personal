# Conexión con Microsoft Entra ID

La aplicación usa Microsoft para dos cosas:

1. **Inicio de sesión** con cuentas corporativas (OpenID Connect, *Authorization Code Flow + PKCE*).
   El backend es un **cliente confidencial**: canjea el código, valida el `id_token` y entrega al navegador
   solo una cookie de sesión `HttpOnly`. Ningún token de Microsoft llega al navegador ni se guarda en la base.
2. **Alta de empleados** (opcional): al escribir el correo en *Empleados → Nuevo* se consultan en
   Microsoft Graph el nombre, puesto, departamento, número de empleado, fecha de contratación, jefe y foto.

Solo pueden entrar usuarios **dados de alta previamente** por el administrador y **activos**. Las cuentas
de Microsoft desconocidas reciben HTTP 403 y no se registran automáticamente. Los roles y permisos se
leen siempre de la base de datos local.

## 1. Registrar la aplicación

Requiere un administrador de Microsoft Entra ID de la organización.

1. Entra a <https://entra.microsoft.com> → **Identidad → Aplicaciones → Registros de aplicaciones → Nuevo registro**.
2. **Nombre:** `SIP-O Sistema Integral de Personal`.
3. **Tipos de cuenta admitidos:** *Solo las cuentas de este directorio organizativo (inquilino único)*.
4. **URI de redirección:** plataforma **Web** (no *SPA*, porque el backend canjea el código con un secreto):
   - Desarrollo: `http://localhost:5173/api/auth/microsoft/callback`
   - Producción: `https://<tu-dominio>/api/auth/microsoft/callback`
5. Registra la aplicación y copia de **Información general**:
   - *Id. de aplicación (cliente)* → `MICROSOFT_CLIENT_ID`
   - *Id. de directorio (inquilino)* → `MICROSOFT_TENANT_ID`
6. En **Autenticación**:
   - *URL de cierre de sesión del canal frontal*: opcional.
   - Deja **desactivados** "Tokens de acceso" y "Tokens de id." (flujo implícito): no se usan.

## 2. Secreto del cliente

1. **Certificados y secretos → Secretos de cliente → Nuevo secreto**. Vigencia recomendada: 12 meses.
2. Copia el **Valor** (solo se muestra una vez) en `MICROSOFT_CLIENT_SECRET` del archivo `backend/.env`
   del servidor o en el administrador de secretos del entorno. **Nunca** lo subas al repositorio.
3. Agenda la renovación antes de que expire. Si vence, el inicio de sesión con Microsoft mostrará
   "Microsoft rechazó el inicio de sesión (invalid_client)" y `/api/health` seguirá mostrando la
   configuración como presente: revisa el secreto.
4. Alternativa más segura para producción: un certificado en lugar de secreto (requiere ajuste menor del
   código para firmar la *client assertion*).

## 3. Permisos de API (Microsoft Graph)

En **Permisos de API → Agregar un permiso → Microsoft Graph**:

| Permiso | Tipo | Para qué | Consentimiento de administrador |
|---|---|---|---|
| `openid`, `profile`, `email` | Delegado | Iniciar sesión e identificar al usuario | No (recomendado otorgarlo) |
| `User.Read` | Delegado | Leer la foto del propio usuario al entrar | No (recomendado otorgarlo) |
| `User.Read.All` | **Aplicación** | Buscar empleados por correo, su jefe y su foto al darlos de alta | **Sí, obligatorio** |

Después pulsa **Conceder consentimiento de administrador para <organización>**.

`User.Read.All` es necesario solo si activas `MICROSOFT_GRAPH_ENABLED=true`. Si no lo concedes, el botón
*Buscar en Microsoft* mostrará: "La aplicación no tiene el permiso User.Read.All con consentimiento de
administrador".

No se usa `offline_access`: la aplicación no guarda *refresh tokens* porque no actúa en nombre del usuario
después de iniciar sesión.

## 4. Capturar la configuración

**Opción A — desde la aplicación (recomendada):** entra como administrador a *Configuración → Conexión con
Microsoft*, captura los valores, pulsa **Guardar** y luego **Probar conexión**. La prueba verifica el
directorio, el Id. de aplicación y el secreto, el permiso `User.Read.All` y el formato de la URI de
redirección. Lo guardado ahí tiene prioridad sobre `.env`; el secreto se guarda cifrado con una llave
derivada de `SECRET_KEY` (si cambias `SECRET_KEY`, vuelve a capturar el secreto) y nunca se muestra de nuevo.
Por seguridad, la app no permite quitar el acceso con contraseña a los administradores hasta que hayas
iniciado sesión con Microsoft. *Volver a valores de .env* borra lo guardado en la aplicación.

**Opción B — variables de entorno (`backend/.env`):**

```env
MICROSOFT_AUTH_ENABLED=true
MICROSOFT_TENANT_ID=<id del inquilino>
MICROSOFT_CLIENT_ID=<id de la aplicación>
MICROSOFT_CLIENT_SECRET=<valor del secreto>
MICROSOFT_REDIRECT_URI=https://<tu-dominio>/api/auth/microsoft/callback
MICROSOFT_POST_LOGOUT_REDIRECT_URI=https://<tu-dominio>/login
MICROSOFT_SCOPES=openid profile email User.Read
MICROSOFT_GRAPH_ENABLED=true

FRONTEND_ORIGINS=https://<tu-dominio>
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_SAMESITE=lax
# El personal de planta sigue entrando con contraseña; oficinas y administradores, con Microsoft
PASSWORD_LOGIN_ROLES=planta
```

`MICROSOFT_REDIRECT_URI` debe coincidir **exactamente** con la registrada en Entra ID.

Comprueba la configuración (sin revelar credenciales):

```bash
curl https://<tu-dominio>/api/health
```

## 5. Cómo funciona el recorrido

1. El botón *Iniciar sesión con Microsoft* abre `GET /api/auth/microsoft/login`.
2. El backend genera `state`, `nonce` y el par PKCE, los guarda en la tabla `flujos_oauth` (un solo uso,
   10 minutos), liga el `state` al navegador con una cookie `HttpOnly` y redirige a Microsoft.
3. Microsoft regresa a `GET /api/auth/microsoft/callback?code=…&state=…`.
4. El backend comprueba el `state`, canjea el código (con secreto y `code_verifier`) y valida el `id_token`:
   firma (llaves públicas del inquilino), `iss`, `aud`, `tid`, `exp` y `nonce`.
5. Identifica al usuario por `oid` (Object ID) o por correo (`preferred_username`/`email`/`upn`, en
   minúsculas). Si no está registrado o está inactivo → **403**. La primera vez guarda su `oid`.
6. Crea la sesión (tabla `sesiones`, solo el hash del token) y responde con las cookies `sip_session`
   (`HttpOnly`) y `sip_csrf` (para el encabezado `X-CSRF-Token`).
7. `GET /api/auth/me` devuelve el usuario. `POST /api/auth/logout` cierra la sesión local y devuelve la URL
   para cerrar también la sesión de Microsoft.

Todos los accesos y rechazos quedan en la tabla `auditoria` (sin tokens).

## 6. Producción

- Sirve el frontend y la API **en el mismo dominio** (la API bajo `/api`) para que la cookie de sesión
  sea de primera parte. Ejemplo con Nginx:

```nginx
server {
    listen 443 ssl;
    server_name vacaciones.o-tek.com;
    # ssl_certificate ...; ssl_certificate_key ...;

    root /var/www/sip-o/dist;          # resultado de `npm run build`
    location / { try_files $uri /index.html; }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

- Ejecuta el backend con `uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers`.
- `SESSION_COOKIE_SECURE=true` (HTTPS) y un `SECRET_KEY` largo y aleatorio.
- Registra la URI de redirección de producción en Entra ID.
- Al desactivar un empleado se cierran todas sus sesiones abiertas.

## 7. Solución de problemas

| Mensaje | Causa probable |
|---|---|
| "Tu cuenta de Microsoft no está registrada…" | El correo no existe en *Empleados*. Dalo de alta. |
| "Este correo está vinculado a otra cuenta de Microsoft" | El empleado tiene guardado otro Object ID (p. ej. se recreó su cuenta). Edita el usuario y vuelve a buscarlo en Microsoft para actualizarlo. |
| "La solicitud de inicio de sesión expiró…" | Pasaron más de 10 minutos, se reutilizó el enlace o el navegador bloquea cookies. |
| `AADSTS50011` en la pantalla de Microsoft | La URI de redirección no coincide con la registrada. |
| "Microsoft rechazó el inicio de sesión (invalid_client)" | Secreto incorrecto o vencido. |
| "…no tiene el permiso User.Read.All…" | Falta el permiso de aplicación o el consentimiento de administrador. |
