"""Servicio de Reportes (P10) - PiShop Cloud."""
# Crea un identificador distinto para reconocer esta ejecucion del servicio. P10
import uuid
# Tipos usados para describir la funcion que prepara y cierra la aplicacion. P10
from collections.abc import AsyncGenerator
# Permite ejecutar tareas especiales al arrancar y apagar FastAPI. P10
from contextlib import asynccontextmanager

# Herramientas de FastAPI para crear la aplicacion y leer solicitudes/respuestas. P10
from fastapi import FastAPI, Request, Response

# Base describe las tablas; engine permite conectarse a la base de datos. P10
from app.database import Base, engine
# Importa las direcciones web para crear y consultar reportes. P10
from app.routers.reportes import router as reportes_router
# Permite leer los valores de configuracion del servicio. P10
from app.settings import get_settings

# Carga la configuracion y prepara un identificador corto para esta instancia. P10
settings = get_settings()
INSTANCE_ID = f"{settings.service_name}-{uuid.uuid4().hex[:5]}"


# Esta funcion prepara la base de datos al iniciar y limpia la conexion al cerrar. P10
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Al comienzo, el servicio todavia no se considera listo. P10
    app.state.started = False
    # Guarda la version de configuracion actual (inicia en cero). P10
    app.state.config_version = 0
    try:
        # Abre una conexion para preparar la estructura de la base de datos. P10
        async with engine.begin() as conn:
            # Crea las tablas necesarias si aun no existen. P10
            await conn.run_sync(Base.metadata.create_all)
        # A partir de aqui, el servicio ya termino de prepararse. P10
        app.state.started = True
        # Mantiene la aplicacion funcionando hasta que se solicite apagarla. P10
        yield
    finally:
        # Al apagar, indica que el servicio ya no esta listo. P10
        app.state.started = False
        # Cierra de forma ordenada las conexiones a la base de datos. P10
        await engine.dispose()


# Crea la aplicacion web e indica su nombre, version y tareas de inicio/cierre. P10
app = FastAPI(title=settings.service_name, version="1.0.0", lifespan=lifespan)

# Agrega a la aplicacion las direcciones para manejar reportes. P10
app.include_router(reportes_router)


# Esta direccion permite comprobar que el servicio responde. P10
@app.get("/health", tags=["salud"])
def health_check() -> dict[str, str]:
    # Devuelve el estado, nombre e identificador de esta instancia. P10
    return {"status": "ok", "service": settings.service_name, "instance": INSTANCE_ID}


# Esta direccion comprueba que el servicio sigue activo. P10
@app.get("/health/live", tags=["salud"])
def live() -> dict[str, str]:
    # Responde con una señal sencilla de que el servicio esta vivo. P10
    return {"status": "alive", "instance": INSTANCE_ID}


# Esta direccion informa si el servicio termino de arrancar. P10
@app.get("/health/startup", tags=["salud"])
def startup(request: Request, resp: Response) -> dict[str, bool]:
    # Si aun no ha arrancado, comunica que el servicio no esta disponible. P10
    if not request.app.state.started:
        resp.status_code = 503
    # Informa si la preparacion ya termino. P10
    return {"started": request.app.state.started}


# Esta direccion informa si el servicio esta listo para recibir trabajo. P10
@app.get("/health/ready", tags=["salud"])
def ready(request: Request, resp: Response) -> dict[str, object]:
    # Lee la version de configuracion y el estado de inicio. P10
    config_version = request.app.state.config_version
    ok = request.app.state.started
    # Usa el codigo 503 mientras el servicio no este listo. P10
    if not ok:
        resp.status_code = 503
    # Devuelve el estado de preparacion y la identidad de esta instancia. P10
    return {"ready": ok, "config_version": config_version, "instance": INSTANCE_ID}