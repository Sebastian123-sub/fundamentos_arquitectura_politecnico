"""Servicio de Pagos (P04) - PiShop Cloud.

Gestiona cobros, reembolsos, integración con pasarela mediante ACL e idempotencia.
"""
import socket
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Response, status, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import get_settings
from app.database import engine, get_session
from app.models import Base, PagoModel, ReembolsoModel
from app.schemas import PagoCrear, PagoLeer, ReembolsoLeer
from app.acl import PasarelaACL

settings = get_settings()
INSTANCE_ID = f"{settings.service_name}-{uuid.uuid4().hex[:5]}"
HOST = socket.gethostname()

# Estado de ciclo de vida
ESTADO = {"arranco": False, "config_version": 1}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Crear tablas al arrancar (desarrollo local con SQLite)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ESTADO["arranco"] = True
    yield
    # Limpieza al apagar
    ESTADO["arranco"] = False
    await engine.dispose()

app = FastAPI(
    title=settings.service_name,
    version="1.0.0",
    lifespan=lifespan
)

# --- Sondas de Salud (Requisito Semana 4) ---
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
async def ready(resp: Response) -> dict[str, object]:
    """Verifica dependencias (base de datos) y configuración."""
    db_ok = True
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
    except Exception:
        db_ok = False

    # Validación estricta de configuración y dependencias
    config_ok = ESTADO["config_version"] > 0 and settings is not None
    
    ok = ESTADO["arranco"] and db_ok and config_ok
    if not ok:
        resp.status_code = 503
    return {"ready": ok, "config_version": ESTADO["config_version"], "instance": INSTANCE_ID}


# --- Simulador de Pasarela (Requisito P04) ---
@app.post("/_simulador/pasarela/cobrar", tags=["Simulador"])
def simular_pasarela(datos: dict) -> dict[str, str]:
    modo = datos.get("modo", "ok")
    if modo == "rechaza":
        return {"status": "DECLINED", "reason": "Fondos insuficientes"}
    elif modo == "lenta":
        return {"status": "TIMEOUT"}
    elif modo == "falla":
        raise HTTPException(status_code=503, detail="Pasarela caída")
    return {"status": "APPROVED", "authorization_code": str(uuid.uuid4())[:8]}


# --- Endpoints de Negocio (/v1/pagos) ---
@app.post(
    "/v1/pagos", 
    response_model=PagoLeer, 
    status_code=201, 
    responses={409: {"model": PagoLeer}},
    tags=["Pagos"]
)
async def crear_pago(
    datos: PagoCrear,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session)
):
    # 1. Verificar Idempotencia
    stmt = select(PagoModel).where(PagoModel.idempotency_key == idempotency_key)
    resultado = (await session.execute(stmt)).scalar_one_or_none()
    if resultado:
        return resultado

    # 2. Consultar pasarela mediante el adaptador ACL
    estado_dominio = await PasarelaACL.cobrar(float(datos.monto_cop), datos.medio)

    # 3. Guardar en Base de Datos
    pago_id = str(uuid.uuid4())
    nuevo_pago = PagoModel(
        id=pago_id,
        pedido_id=datos.pedido_id,
        monto_cop=datos.monto_cop,
        medio=datos.medio,
        estado=estado_dominio,
        idempotency_key=idempotency_key
    )
    session.add(nuevo_pago)
    await session.commit()
    await session.refresh(nuevo_pago)

    if estado_dominio == "RECHAZADO":
        response.status_code = status.HTTP_409_CONFLICT

    return nuevo_pago


@app.get("/v1/pagos/{pago_id}", response_model=PagoLeer, tags=["Pagos"])
async def obtener_pago(pago_id: str, session: AsyncSession = Depends(get_session)):
    pago = await session.get(PagoModel, pago_id)
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    return pago


@app.post("/v1/pagos/{pago_id}/reembolso", response_model=ReembolsoLeer, status_code=201, tags=["Pagos"])
async def reembolsar_pago(pago_id: str, session: AsyncSession = Depends(get_session)):
    pago = await session.get(PagoModel, pago_id)
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado para reembolsar")

    # Validación de negocio: Solo se pueden reembolsar pagos aprobados
    if pago.estado != "APROBADO":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se puede reembolsar un pago que no se encuentra aprobado."
        )

    stmt = select(ReembolsoModel).where(ReembolsoModel.pago_id == pago_id)
    reembolso_existente = (await session.execute(stmt)).scalar_one_or_none()
    if reembolso_existente:
        return reembolso_existente

    reembolso = ReembolsoModel(
        id=str(uuid.uuid4()),
        pago_id=pago_id,
        estado="COMPLETADO"
    )
    session.add(reembolso)
    await session.commit()
    await session.refresh(reembolso)

    return reembolso