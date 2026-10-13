import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from . import config_dinamica, rotacion
from .config import settings
from .database import SessionLocal, engine
from .migraciones import actualizar_esquema
from .routers import (
    auth, calendario, catalogos, configuracion, consultas, correo, equipo, permisos,
    rotacion as rotacion_router, sedes, usuarios, vacaciones,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # En producción las migraciones se ejecutan aparte (python -m app.migrar); en desarrollo, al iniciar.
    if os.environ.get("SIP_MIGRAR_AL_INICIAR", "1") == "1":
        actualizar_esquema(engine)
    _refrescar_config(forzar=True)
    tarea = None
    if os.environ.get("SIP_TAREAS", "1") == "1":  # SIP_TAREAS=0 para desactivarlas (p. ej. en workers extra)
        tarea = asyncio.create_task(_tareas_programadas())
    yield
    if tarea:
        tarea.cancel()


async def _tareas_programadas():
    """Cada 10 minutos: sincroniza la rotación de turnos y envía el aviso semanal de los viernes."""
    while True:
        try:
            await run_in_threadpool(rotacion.tarea_programada)
        except Exception:  # noqa: BLE001 - la tarea nunca debe tumbar el servidor
            logging.getLogger("sip.tareas").exception("Error en tarea programada")
        await asyncio.sleep(600)


def _refrescar_config(forzar: bool = False):
    with SessionLocal() as db:
        config_dinamica.refrescar(db, forzar=forzar)


app = FastAPI(title="Vacaciones y Permisos", version="1.1.0", lifespan=lifespan)

# CORS restringido a los orígenes configurados (FRONTEND_ORIGINS); se envían cookies, nunca "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)

for r in (auth, sedes, usuarios, catalogos, vacaciones, permisos, calendario, equipo, configuracion, consultas, correo,
          rotacion_router):
    app.include_router(r.router)


@app.middleware("http")
async def config_actualizada(request: Request, call_next):
    """Relee la configuración guardada en la aplicación como máximo cada 30 s (útil con varios workers)."""
    if time.monotonic() - config_dinamica._ultima >= config_dinamica.INTERVALO:
        await run_in_threadpool(_refrescar_config)
    return await call_next(request)


@app.get("/api/health")
def health():
    """Estado del servicio. Indica qué está configurado sin revelar credenciales."""
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        bd = "ok"
    except Exception:  # noqa: BLE001
        bd = "error"
    return {
        "ok": bd == "ok",
        "base_datos": bd,
        "microsoft_login_configurado": settings.microsoft_configurado,
        "microsoft_graph_configurado": settings.graph_configurado,
        "password_login": settings.password_login_enabled,
        "cookie_segura": settings.session_cookie_secure,
    }
