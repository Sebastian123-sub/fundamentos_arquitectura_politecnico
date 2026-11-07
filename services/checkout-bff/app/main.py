"""Servicio Checkout BFF (P06 - PiShop Cloud).

Servicio compuesto que implementa el patrón Saga por Orquestación,
agregador BFF para vista móvil (vitrina) y manejo estricto de idempotencia.
"""
import asyncio
import socket
import uuid
from contextlib import asynccontextmanager
from typing import Dict, List, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.saga import orquestar_checkout
from app.schemas import (
    CheckoutRequest,
    CheckoutResponse,
    ErrorResponse,
    VitrinaItem,
)
from app.settings import get_settings

settings = get_settings()
INSTANCE_ID = f"{settings.service_name}-{uuid.uuid4().hex[:5]}"
HOST = socket.gethostname()

# Estado del ciclo de vida
ESTADO = {"arranco": False, "config_version": 0}

# Almacenes en memoria para idempotencia y estado de pedidos
IDEMPOTENCIA_STORE: Dict[str, CheckoutResponse] = {}
PEDIDOS_ESTADO_STORE: Dict[str, CheckoutResponse] = {}

# Control de concurrencia: locks por clave de idempotencia
_locks: Dict[str, asyncio.Lock] = {}
_master_lock = asyncio.Lock()


async def _obtener_lock(clave: str) -> asyncio.Lock:
    """Retorna un lock específico para la clave de idempotencia protegiendo contra race conditions."""
    async with _master_lock:
        if clave not in _locks:
            _locks[clave] = asyncio.Lock()
        return _locks[clave]


# Cliente HTTP global del proceso
_http_client: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http_client
    if not hasattr(app.state, "http_client") or app.state.http_client is None:
        _http_client = httpx.AsyncClient(timeout=settings.http_timeout_seconds)
        app.state.http_client = _http_client
    ESTADO["arranco"] = True
    yield
    if _http_client:
        await _http_client.aclose()
        _http_client = None
    ESTADO["arranco"] = False


app = FastAPI(
    title=settings.service_name,
    version="1.0.0",
    description="Checkout BFF - Orquestador Saga y Agregador Móvil",
    lifespan=lifespan,
)


def get_http_client() -> httpx.AsyncClient:
    """Permite inyectar dobles de prueba (mock transport) o usar el cliente del lifespan."""
    if hasattr(app.state, "http_client") and app.state.http_client:
        return app.state.http_client
    if _http_client:
        return _http_client
    return httpx.AsyncClient(timeout=settings.http_timeout_seconds)


# =============================================================
# MANEJADORES DE ERROR UNIFORMES ({"detalle": "...", "codigo": "..."})
# =============================================================

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    codigo = "RECURSO_NO_ENCONTRADO" if exc.status_code == 404 else "ERROR_HTTP"
    return JSONResponse(
        status_code=exc.status_code,
        content={"detalle": str(exc.detail), "codigo": codigo},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detalle": f"Datos de petición inválidos: {str(exc.errors())}",
            "codigo": "VALIDACION_INVALIDA",
        },
    )


# =============================================================
# SONDAS DE SALUD (Semana 4)
# =============================================================

@app.get("/health/live", tags=["salud"])
def live() -> dict[str, str]:
    """Barata, local, NUNCA toca dependencias."""
    return {"status": "alive", "instance": INSTANCE_ID}


@app.get("/health/startup", tags=["salud"])
def startup(resp: Response) -> dict[str, bool]:
    if not ESTADO["arranco"]:
        resp.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"started": ESTADO["arranco"]}


@app.get("/health/ready", tags=["salud"])
def ready(resp: Response) -> dict[str, object]:
    """Verifica dependencias y versión de configuración."""
    ok = ESTADO["arranco"] and (ESTADO["config_version"] > 0 or settings.app_env == "dev")
    if not ok:
        resp.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"ready": ok, "config_version": ESTADO["config_version"], "instance": INSTANCE_ID}


# =============================================================
# ENDPOINTS DE NEGOCIO (Contrato P06)
# =============================================================

@app.post(
    "/v1/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_200_OK,
    responses={
        422: {"model": ErrorResponse, "description": "Validación inválida o falta Idempotency-Key"},
    },
    tags=["checkout"],
)
async def checkout(
    payload: CheckoutRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Inicia la saga de checkout coordinando catálogo, inventario, pedidos y pagos.
    
    Exige obligatoriamente la cabecera `Idempotency-Key`. Peticiones repetidas con la misma
    clave devuelven exactamente la misma respuesta sin volver a ejecutar los pasos.
    """
    # Validación estricta de Idempotency-Key
    if not idempotency_key or not idempotency_key.strip():
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detalle": "La cabecera 'Idempotency-Key' es obligatoria para el checkout",
                "codigo": "IDEMPOTENCY_KEY_REQUERIDA",
            },
        )

    clave = idempotency_key.strip()
    lock = await _obtener_lock(clave)

    async with lock:
        # Si ya fue procesado, retornar la respuesta en caché sin reejecutar
        if clave in IDEMPOTENCIA_STORE:
            return IDEMPOTENCIA_STORE[clave]

        client = get_http_client()
        resultado = await orquestar_checkout(
            payload=payload,
            idempotency_key=clave,
            client=client,
            settings=settings,
        )

        # Almacenar resultado para idempotencia y consulta de estado
        IDEMPOTENCIA_STORE[clave] = resultado
        PEDIDOS_ESTADO_STORE[resultado.pedido_id] = resultado

        return resultado


@app.get(
    "/v1/checkout/{pedido_id}/estado",
    response_model=CheckoutResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Pedido no encontrado"},
    },
    tags=["checkout"],
)
def obtener_estado_checkout(pedido_id: str):
    """Consulta el estado del checkout y el detalle de pasos ejecutados para un pedido."""
    if pedido_id in PEDIDOS_ESTADO_STORE:
        return PEDIDOS_ESTADO_STORE[pedido_id]

    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "detalle": f"Pedido con ID '{pedido_id}' no encontrado",
            "codigo": "PEDIDO_NO_ENCONTRADO",
        },
    )


@app.get(
    "/v1/vitrina",
    response_model=List[VitrinaItem],
    tags=["vitrina"],
)
async def obtener_vitrina():
    """Agregador BFF para vista móvil:

    Consulta catálogo (filtrando publicados) y complementa con stock de inventario.
    Si inventario falla para un SKU, se degrada ese ítem asignando stock 0 sin tumbar la vitrina.
    """
    client = get_http_client()
    url_cat = f"{str(settings.catalogo_url).rstrip('/')}/v1/productos"

    productos_publicados = []
    try:
        resp_cat = await client.get(url_cat, timeout=settings.timeout_catalogo_seconds)
        if resp_cat.status_code == 200:
            data_cat = resp_cat.json()
            items = data_cat.get("items", []) if isinstance(data_cat, dict) else data_cat
            productos_publicados = [p for p in items if p.get("publicado") is True]
    except Exception:
        # Si catálogo no responde, la vitrina responde lista vacía degradada
        return []

    vitrina_items: List[VitrinaItem] = []
    for prod in productos_publicados:
        sku = prod.get("sku", "")
        nombre = prod.get("nombre", "")
        precio = float(prod.get("precio_cop", 0))
        stock_disp = 0

        # Consulta de stock resiliente (falla parcial -> degradación graciosa)
        try:
            url_inv = f"{str(settings.inventario_url).rstrip('/')}/v1/stock/{sku}"
            resp_inv = await client.get(url_inv, timeout=settings.timeout_inventario_seconds)
            if resp_inv.status_code == 200:
                data_inv = resp_inv.json()
                total_stock = data_inv.get("cantidad", 0)
                reservado = data_inv.get("reservado", 0)
                stock_disp = max(0, total_stock - reservado)
        except Exception:
            # Degradación controlada: el fallo de stock de un ítem no tumba la vitrina móvil
            stock_disp = 0

        vitrina_items.append(
            VitrinaItem(
                sku=sku,
                nombre=nombre,
                precio_cop=precio,
                stock_disponible=stock_disp,
            )
        )

    return vitrina_items
