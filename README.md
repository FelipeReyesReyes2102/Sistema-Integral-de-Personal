# SIP-O · Sistema Integral de Personal

Aplicación web de O-tek para gestionar vacaciones, permisos de llegada tarde / salida temprana / salida intermedia y
consultas con el médico de planta.

- **Backend:** Python 3 + FastAPI + SQLAlchemy (`backend/`)
- **Frontend:** React 18 + Vite (`frontend/`)
- **Base de datos:** PostgreSQL

## Tipos de usuario

| Rol | Puede |
|---|---|
| **Super administrador** | Todo lo del administrador + configuración de la conexión con Microsoft y alta/edición de otros super administradores. Siempre debe quedar al menos uno activo. |
| **Administrador** | Todo lo de un empleado + validar/rechazar solicitudes, gestionar empleados, turnos, grupos, festivos, tabla de antigüedad, ajustes de saldo y ver el calendario de todo el personal. Se rige por las reglas de oficinas. |
| **Oficinas** | Solicitar vacaciones y permisos, ver su saldo y calendario. |
| **Planta** | Igual que oficinas, con días de 12 h y días laborales según su grupo/turno. |
| **Médico de planta** | Registra consultas médicas (paciente filtrado por tipo de usuario, síntomas, diagnóstico, medicamentos recetados, indicaciones y resultado). Para sus propias vacaciones se rige como oficinas. |

### Sedes

- Cada sede (por ejemplo *O-tek México*, *O-Tek Colombia - Medellín*) tiene su propio personal, administradores,
  turnos, grupos, rotación, festivos, avisos a caseta y zona horaria.
- La sede de cada empleado se toma de su **Ubicación del trabajo** en Microsoft Entra ID; el super administrador
  puede crear las sedes con **Configuración → Sedes → Importar desde Microsoft**.
- **Super administrador:** ve todas las sedes, crea y edita sedes y es el único que cambia a un empleado de sede.
- **Administrador:** solo su sede y las adicionales que le asigne un super administrador (en el empleado:
  *Sedes adicionales que administra*). Con varias sedes, el menú muestra un selector de sede.
- Los jefes solo tienen a cargo personas de su propia sede. Los cumpleaños se muestran por sede.
- El servidor de correo y la tabla de antigüedad son comunes (los cambia el super administrador); los datos que
  existían antes de las sedes quedaron en *O-tek México*.

### Inicio de sesión

Con **correo o número de nómina** y contraseña (o con la cuenta de Microsoft cuando esté configurada).

Para crear o promover un super administrador (la contraseña se pide en consola o se toma de
`SUPERADMIN_PASSWORD`; no se guarda en el código):

```bash
python -m app.crear_superadmin --email nombre@o-tek.com --nombre "Nombre Apellido" --nomina 0001
```

### Rotación de turnos

En *Turnos → Rotación de turnos* (administrador):

- **Activada:** se eligen los turnos que rotan y su orden (p. ej. Día → Noche), la fecha de inicio (define el día
  de cambio), cada cuántas semanas se cambia, y qué grupos rotan con su turno del primer periodo (p. ej.
  Grupo A en Día y Grupo B en Noche). Cada periodo los grupos avanzan al siguiente turno del orden. Una tarea
  interna revisa cada 10 minutos y actualiza el turno de cada empleado el día del cambio.
- **Desactivada:** se elige un turno único y todos los integrantes de los grupos quedan en ese turno.
- **Aviso semanal:** si se activa, cada viernes a la hora indicada cada empleado de los grupos que rotan recibe
  por correo su turno de la semana siguiente (indica si hay cambio). También hay un botón para enviarlo ya.
- Cada empleado ve en *Mis vacaciones* la tarjeta **Mi turno** con el turno de esta semana, el de la próxima y
  las siguientes seis semanas.
- Si el backend corre con varios procesos, deja las tareas en uno solo (`SIP_TAREAS=0` en los demás).

### Avisos a caseta por correo

En *Configuración → Avisos por correo a caseta* (administrador y super administrador) se capturan los correos
del personal de caseta, los tipos de permiso que se avisan y el método de envío:

- **Microsoft 365 (recomendado):** usa la conexión con Microsoft; requiere el permiso de aplicación
  `Mail.Send` con consentimiento de administrador y un buzón remitente (p. ej. `avisos@o-tek.com`).
- **SMTP:** servidor, puerto, seguridad, usuario y contraseña (se guarda cifrada).

Al **autorizar** un permiso se envía (en segundo plano) un correo con el empleado, nómina, departamento, tipo,
fecha, horario y quién autorizó; si un permiso autorizado se **cancela**, también se avisa. Cada envío queda en
*Últimos envíos* con su estado y se puede reintentar. Un fallo de correo nunca bloquea la autorización.

### Servicio médico

- Las consultas **no se solicitan**: las registra el médico en *Consultas médicas*.
- El empleado ve en su calendario los días que fue al médico y puede abrir lo que registró el doctor.
- La información clínica (síntomas, diagnóstico y medicamentos) la ven el paciente, el médico y el
  administrador (cada consulta que abre el administrador queda en la auditoría). El jefe solo ve que hubo
  consulta y su horario.

### Jefes

Cualquier empleado puede ser **jefe** (casilla *Es jefe* en Empleados), y cada empleado tiene un **jefe directo**.

- Al pedir vacaciones o un permiso, el empleado elige al **jefe que aprueba** (por defecto, su jefe directo).
- El jefe tiene la sección **Por aprobar**, donde valida o rechaza las solicitudes que le asignaron, y
  **Mi equipo**, con su personal a cargo: días otorgados, tomados, solicitados y restantes del periodo, vencimiento,
  próximas vacaciones y el detalle de cada persona (en modo de solo lectura).
- El administrador ve y puede resolver **todas** las solicitudes en *Todas las solicitudes*.

### Calendario y formularios

- Cada tipo de evento tiene su color (vacaciones, home office, llegada tarde, salida temprana, salida durante
  la jornada, consulta médica y festivo); el estado se distingue por intensidad (aprobado sólido, pendiente
  tenue, borrador contorno). Vista **Año** o **Mes** y botón **Hoy**.
- **Clic en un evento** abre sus especificaciones; clic en días libres selecciona un rango.
- El panel **Registros** de la tarjeta del periodo (y la leyenda) muestra el conteo por categoría; al hacer clic
  se resalta esa categoría en el calendario y se filtra la lista.
- **Home office:** se solicita por rango de fechas (cuenta solo días laborales), lo aprueba el jefe, no descuenta
  vacaciones ni horas.
- **Calendario general (administrador):** todo el personal por mes con vacaciones, permisos, home office y
  consultas médicas; filtros por tipo de usuario, grupo y búsqueda; clic en una celda para ver los detalles.
  El administrador también ve las consultas médicas en *Todas las solicitudes* (cada consulta abierta queda
  en la auditoría).

- En *Mis vacaciones* se hace clic en el primer y el último día del calendario; la barra superior muestra los días
  naturales y laborales y permite **Solicitar vacaciones** (o **Solicitar permiso** si es un solo día).
- Clic en el nombre de un mes lo amplía a pantalla de mes (con festivos, descansos y solicitudes en cada día).
- Los formularios siguen el formato O-tek: *Solicitud de vacaciones* y *Permisos de salida o ingreso*, con
  **firma** dibujada (obligatoria para enviar). El jefe ve la firma en *Por aprobar*.

## Acceso y conexión con Microsoft

- **Sesión segura:** el backend entrega una cookie `HttpOnly` (`sip_session`) y un token CSRF; el navegador
  no guarda tokens. Las sesiones expiran a las `SESSION_HOURS` horas y se cierran al desactivar al usuario.
- **Microsoft Entra ID:** inicio de sesión con la cuenta corporativa (Authorization Code + PKCE, validación
  completa del `id_token`). Solo entran usuarios registrados y activos; los demás reciben 403.
- **Alta con Microsoft:** en *Empleados → Nuevo*, al escribir el correo y pulsar *Buscar en Microsoft* se
  cargan nombre, puesto, departamento, número de empleado, fecha de ingreso, jefe y foto.
- **Contraseña:** se conserva para el personal de planta. Con `PASSWORD_LOGIN_ROLES=planta` las oficinas y
  los administradores solo pueden entrar con Microsoft.
- **Auditoría:** accesos, rechazos y cambios de usuarios quedan en la tabla `auditoria`.

La conexión se captura en *Configuración → Conexión con Microsoft* (con botón **Probar conexión**) o en
`backend/.env`. Guía completa de configuración en Entra ID: [docs/MICROSOFT_ENTRA.md](docs/MICROSOFT_ENTRA.md).

El logo oficial está en `frontend/public/logo-otek.png` (y el ícono de pestaña, recortado del mismo logo, en `favicon.png`).

## Reglas de vacaciones

- Los días se otorgan por año de servicio según la tabla (editable en *Configuración*): 1 año = 12, 2 = 14, 3 = 16,
  4 = 18, 5 = 20, 6‑10 = 22, 11‑15 = 24, 16‑20 = 26, 21‑25 = 28, 26‑30 = 30, 31‑36 = 32.
- **Oficinas:** 1 día = 8 h. Días laborales: lunes a viernes.
- **Planta:** se otorgan las mismas horas (días × 8 h), pero cada día consume **12 h**:
  año 1 = 12 × 8 = 96 h ÷ 12 = **8 días**. Los días laborales salen del
  ciclo del grupo (p. ej. 4×4 rotativo o días fijos de la semana).
- Los festivos y los días de descanso dentro del rango no se descuentan.
- **Bloque obligatorio:** en cada periodo se deben tomar **al menos una vez 6 días laborales seguidos** (oficinas)
  o **4** (planta). Se pueden pedir menos días, pero mientras no se haya solicitado ese bloque el sistema no deja
  pedir días sueltos que dejen el saldo por debajo del bloque. Ej.: quedan 8 días y no se han tomado los 6 seguidos:
  3 días no se permiten (quedarían 5), 2 sí (quedan 6). Si el saldo ya es menor al bloque, se toma completo de una vez.
- Flujo: **Borrador → Solicitado → Validado / Rechazado** (o Cancelado). Borrador y Solicitado ya apartan saldo.
- **Vigencia de 18 meses:** los días de cada periodo se pueden disfrutar durante 18 meses desde que se otorgan
  (`MESES_VIGENCIA_PERIODO`). Después, el saldo no usado del periodo anterior **se pierde** y se muestra como
  "días perdidos". La app avisa cuando un periodo con saldo está por vencer.
- Por defecto los días se otorgan **al cumplir** cada año de servicio (criterio LFT). Para otorgarlos desde el
  primer día del año, pon `VACACIONES_AL_CUMPLIR_ANIO=false` en `backend/.env`.

## Instalación

### 1. PostgreSQL

Crea la base de datos (con pgAdmin o psql):

```sql
CREATE USER vacaciones WITH PASSWORD 'vacaciones';
CREATE DATABASE vacaciones OWNER vacaciones;
```

O, si tienes Docker: `docker compose up -d`.

### 2. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # ajusta DATABASE_URL y SECRET_KEY
python -m app.seed              # crea tablas y datos iniciales
uvicorn app.main:app --reload --port 8000
```

Documentación interactiva de la API: http://localhost:8000/docs

Usuarios de ejemplo creados por `app.seed`:

| Correo | Contraseña | Rol |
|---|---|---|
| admin@empresa.com | Admin123 | Administrador |
| laura@empresa.com | Cambiar123 | Oficinas · Jefa de Carlos y María |
| medico@empresa.com | Cambiar123 | Médico de planta |
| ana@empresa.com | Cambiar123 | Oficinas (jefe: administrador) |
| carlos@empresa.com | Cambiar123 | Planta (Grupo A, turno Día) |
| maria@empresa.com | Cambiar123 | Planta (Grupo B, turno Noche) |

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Abre http://localhost:5173. Si el backend no está en el puerto 8000, define `API_URL` (p. ej.
`set API_URL=http://localhost:8010` antes de `npm run dev`).

### Pruebas

```bash
cd backend
.venv\Scripts\python -m pytest
```

Las pruebas usan SQLite temporal, no requieren PostgreSQL.

## Estructura

```
backend/app/
  reglas.py        Reglas puras: antigüedad, horas, ciclos de planta, validaciones
  services.py      Periodos, saldos y festivos (con BD)
  models.py        Tablas
  routers/         auth, usuarios, catalogos (turnos/grupos/festivos/reglas), vacaciones, permisos, calendario
  seed.py          Datos iniciales
frontend/src/
  pages/           MisVacaciones, Solicitudes, Empleados, Grupos, Turnos, Festivos, Configuracion, CalendarioEquipo
  components/      Layout, YearCalendar, VacacionesModal, PermisoModal, Modal
```

## Pendiente / siguientes pasos sugeridos

- Migraciones con Alembic (hoy `app/migraciones.py` crea tablas y agrega columnas nuevas automáticamente).
- Notificaciones por correo al enviar/validar solicitudes.
- Aprobación en dos niveles (jefe → RH) si se requiere.
- Traducción completa al inglés (hoy el selector ES/EN aplica a la pantalla de inicio).
