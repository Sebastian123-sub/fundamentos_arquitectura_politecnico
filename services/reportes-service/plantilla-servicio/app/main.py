"""Plantilla de servicio PiShop Cloud.

Copie esta carpeta a services/<su-servicio>/ y complete los routers.
Ya incluye: lifespan (punto de auto-registro), tres sondas de salud con
semántica diferenciada y settings externalizados.
"""
import socket
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from app.settings import get_settings

settings = get_settings()
INSTANCE_ID = f"{settings.service_name}-{uuid.uuid4().hex[:5]}"
HOST = socket.gethostname()

# Estado de ciclo de vida. `config_version` > 0 cuando se aplicó una configuración
# (por el cliente de config-service) -- criterio 3 del reto 4.1.
ESTADO = {"arranco": False, "config_version": 0}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # TODO (P09/P10): registrar en Consul aquí y arrancar el polling del config-service.
    ESTADO["arranco"] = True
    yield
    # TODO: dar de baja en Consul (deregister) y detener el polling.
    ESTADO["arranco"] = False


app = FastAPI(title=settings.service_name, version="1.0.0", lifespan=lifespan)


@app.get("/health/live", tags=["salud"])
def live() -> dict[str, str]:
    """Barata, local, NUNCA toca dependencias."""
    return {"status": "alive", "instance": INSTANCE_ID}


@app.get("/health/startup", tags=["salud"])
def startup(resp: Response) -> dict[str, bool]:
    if not ESTADO["arranco"]:
        resp.status_code = 503
    return {"started": ESTADO["arranco"]}


@app.get("/health/ready", tags=["salud"])
def ready(resp: Response) -> dict[str, object]:
    """Verifica dependencias y que se haya aplicado una versión de configuración.

    En la plantilla se acepta config_version == 0 solo si PISHOP_APP_ENV=dev,
    para poder trabajar sin config-service. En qa/stg/prod devuelve 503.
    """
    ok = ESTADO["arranco"] and (ESTADO["config_version"] > 0 or settings.app_env == "dev")
    if not ok:
        resp.status_code = 503
    return {"ready": ok, "config_version": ESTADO["config_version"], "instance": INSTANCE_ID}
