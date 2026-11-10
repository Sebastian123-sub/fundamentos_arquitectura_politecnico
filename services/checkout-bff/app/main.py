"""Servicio Checkout BFF (P06 - PiShop Cloud).

Servicio compuesto que implementa:
1. Patrón Saga por Orquestación (coordinando Catálogo, Inventario, Pedidos y Pagos).
2. Manejo estricto de Idempotencia y control de concurrencia mediante asyncio.Lock.
3. Agregador Backend For Frontend (BFF) para la vista móvil (/v1/vitrina) con degradación graciosa.
4. Sondas de salud estándar para orquestación en contenedores (/health/live, /health/ready, /health/startup).
"""
# Manejo de tareas asíncronas y bloqueos de concurrencia
import asyncio
# Obtención del hostname del servidor/contenedor
import socket
# Generación de identificadores únicos para instancias
import uuid
# Administrador de contexto para el ciclo de vida de la aplicación FastAPI
from contextlib import asynccontextmanager
# Tipado estático para diccionarios, listas y valores opcionales
from typing import Dict, List, Optional

# Cliente HTTP asíncrono para llamadas entre microservicios
import httpx
# Clases centrales del framework FastAPI para enrutamiento, cabeceras y respuestas
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
# Manejador de excepciones cuando falla la validación del esquema Pydantic
from fastapi.exceptions import RequestValidationError
# Respuesta en formato JSON estándar
from fastapi.responses import JSONResponse

# Función que ejecuta la secuencia de la saga y sus compensaciones
from app.saga import orquestar_checkout
# Esquemas Pydantic para peticiones, respuestas y errores
from app.schemas import (
    CheckoutRequest,
    CheckoutResponse,
    ErrorResponse,
    VitrinaItem,
)
# Carga de la configuración del entorno
from app.settings import get_settings

# Instancia singleton de configuraciones externalizadas
settings = get_settings()
# Identificador único de esta réplica en ejecución (ej. checkout-bff-a1b2c)
INSTANCE_ID = f"{settings.service_name}-{uuid.uuid4().hex[:5]}"
# Nombre del host de la máquina o pod que ejecuta este proceso
HOST = socket.gethostname()

# Diccionario de estado interno para las sondas de ciclo de vida (startup y readiness)
ESTADO = {"arranco": False, "config_version": 0}

# Almacén en memoria para idempotencia: guarda respuestas por 'Idempotency-Key'
IDEMPOTENCIA_STORE: Dict[str, CheckoutResponse] = {}
# Almacén en memoria para consultar el estado del checkout por 'pedido_id'
PEDIDOS_ESTADO_STORE: Dict[str, CheckoutResponse] = {}

# Diccionario de Locks asíncronos por cada clave de idempotencia
_locks: Dict[str, asyncio.Lock] = {}
# Bloqueo maestro para proteger el acceso concurrente al diccionario de locks
_master_lock = asyncio.Lock()


async def _obtener_lock(clave: str) -> asyncio.Lock:
    """Retorna un lock específico para la clave de idempotencia dada.
    
    Protege contra race conditions cuando llegan peticiones concurrentes idénticas
    con la misma Idempotency-Key en el mismo instante de tiempo.
    """
    async with _master_lock:
        # Si la clave no tiene un lock asociado aún, se crea uno nuevo
        if clave not in _locks:
            _locks[clave] = asyncio.Lock()
        # Retorna el lock correspondiente a esa clave
        return _locks[clave]


# Cliente HTTP global persistente para el ciclo de vida del proceso
_http_client: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Administra el ciclo de vida del servicio: inicializa recursos al arrancar y los libera al apagar."""
    global _http_client
    # Al arrancar: crea la sesión del cliente HTTP asíncrono reutilizable si no existe
    if not hasattr(app.state, "http_client") or app.state.http_client is None:
        _http_client = httpx.AsyncClient(timeout=settings.http_timeout_seconds)
        app.state.http_client = _http_client
    # Marca que el servicio ya completó su proceso de inicio
    ESTADO["arranco"] = True
    yield
    # Al apagar: cierra limpiamente el pool de conexiones HTTP abiertas
    if _http_client:
        await _http_client.aclose()
        _http_client = None
    # Marca que el servicio ya no está activo
    ESTADO["arranco"] = False


# Instancia principal de la aplicación FastAPI
app = FastAPI(
    title=settings.service_name,
    version="1.0.0",
    description="Checkout BFF - Orquestador Saga y Agregador Móvil",
    lifespan=lifespan,
)


def get_http_client() -> httpx.AsyncClient:
    """Provee el cliente HTTP adecuado; permite inyectar mocks en pruebas unitarias."""
    # Prioriza el cliente alojado en app.state (utilizado por TestClient con transporte simulado)
    if hasattr(app.state, "http_client") and app.state.http_client:
        return app.state.http_client
    # Usa el cliente global inicializado por el lifespan
    if _http_client:
        return _http_client
    # Respaldo de contingencia creando un cliente puntual
    return httpx.AsyncClient(timeout=settings.http_timeout_seconds)


# =============================================================
# MANEJADORES DE ERROR UNIFORMES ({"detalle": "...", "codigo": "..."})
# =============================================================

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    """Intercepta excepciones HTTP para normalizar el formato de respuesta del contrato."""
    codigo = "RECURSO_NO_ENCONTRADO" if exc.status_code == 404 else "ERROR_HTTP"
    return JSONResponse(
        status_code=exc.status_code,
        content={"detalle": str(exc.detail), "codigo": codigo},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Intercepta errores de validación de esquemas Pydantic y retorna HTTP 422 estandarizado."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detalle": f"Datos de petición inválidos: {str(exc.errors())}",
            "codigo": "VALIDACION_INVALIDA",
        },
    )


# =============================================================
# SONDAS DE SALUD (Semana 4 - Kubernetes Probes)
# =============================================================

@app.get("/health/live", tags=["salud"])
def live() -> dict[str, str]:
    """Sonda de vida (Liveness Probe): barata, local, NUNCA toca dependencias externas."""
    return {"status": "alive", "instance": INSTANCE_ID}


@app.get("/health/startup", tags=["salud"])
def startup(resp: Response) -> dict[str, bool]:
    """Sonda de inicio (Startup Probe): indica si el ciclo de vida del servicio ya arrancó."""
    if not ESTADO["arranco"]:
        # Si aún no terminó de arrancar, retorna HTTP 503
        resp.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"started": ESTADO["arranco"]}


@app.get("/health/ready", tags=["salud"])
def ready(resp: Response) -> dict[str, object]:
    """Sonda de preparación (Readiness Probe): verifica si puede recibir tráfico de usuarios."""
    # Está listo si ya arrancó y tiene configuración cargada (o si está en entorno de desarrollo 'dev')
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
    clave devuelven exactamente la misma respuesta almacenada sin volver a ejecutar los pasos.
    """
    # 1. Validación estricta de la presencia de la cabecera Idempotency-Key
    if not idempotency_key or not idempotency_key.strip():
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detalle": "La cabecera 'Idempotency-Key' es obligatoria para el checkout",
                "codigo": "IDEMPOTENCY_KEY_REQUERIDA",
            },
        )

    clave = idempotency_key.strip()
    # 2. Adquirir lock asíncrono para esta clave de idempotencia
    lock = await _obtener_lock(clave)

    async with lock:
        # Si la petición ya fue procesada previamente, retornar la respuesta en caché
        if clave in IDEMPOTENCIA_STORE:
            return IDEMPOTENCIA_STORE[clave]

        # Obtener el cliente HTTP compartido
        client = get_http_client()
        # 3. Invocar al orquestador de la saga hacia adelante y sus compensaciones
        resultado = await orquestar_checkout(
            payload=payload,
            idempotency_key=clave,
            client=client,
            settings=settings,
        )

        # 4. Almacenar el resultado en los repositorios de idempotencia y consulta de estado
        IDEMPOTENCIA_STORE[clave] = resultado
        PEDIDOS_ESTADO_STORE[resultado.pedido_id] = resultado

        # 5. Retornar la respuesta final de la saga
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
    """Consulta el estado del checkout y el detalle de pasos ejecutados para un pedido dado."""
    # Buscar si el pedido_id existe en el almacén de estados
    if pedido_id in PEDIDOS_ESTADO_STORE:
        return PEDIDOS_ESTADO_STORE[pedido_id]

    # Si no se encuentra registrado, retornar HTTP 404 estandarizado
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

    Consulta catálogo (filtrando publicados) y complementa concurrentemente con stock de inventario.
    Si inventario falla o da timeout para un SKU, se degrada ese ítem asignando stock 0 sin tumbar la vitrina móvil.
    """
    client = get_http_client()
    url_cat = f"{str(settings.catalogo_url).rstrip('/')}/v1/productos"

    productos_publicados = []
    try:
        # Obtener lista completa de productos desde el microservicio de catálogo
        resp_cat = await client.get(url_cat, timeout=settings.timeout_catalogo_seconds)
        if resp_cat.status_code == 200:
            data_cat = resp_cat.json()
            # Admite tanto formato lista directa como objeto contenedor con campo 'items'
            items = data_cat.get("items", []) if isinstance(data_cat, dict) else data_cat
            # Filtrar exclusivamente los productos marcados como publicados
            productos_publicados = [p for p in items if p.get("publicado") is True]
    except Exception:
        # Si catálogo no responde, degradar graciosamente devolviendo lista vacía
        return []

    vitrina_items: List[VitrinaItem] = []
    # Iterar cada producto publicado para complementar sus existencias
    for prod in productos_publicados:
        sku = prod.get("sku", "")
        nombre = prod.get("nombre", "")
        precio = float(prod.get("precio_cop", 0))
        stock_disp = 0

        # Consulta resiliente de stock en inventario-service por cada SKU
        try:
            url_inv = f"{str(settings.inventario_url).rstrip('/')}/v1/stock/{sku}"
            resp_inv = await client.get(url_inv, timeout=settings.timeout_inventario_seconds)
            if resp_inv.status_code == 200:
                data_inv = resp_inv.json()
                total_stock = data_inv.get("cantidad", 0)
                reservado = data_inv.get("reservado", 0)
                # Stock disponible neto = unidades totales menos unidades reservadas (no negativo)
                stock_disp = max(0, total_stock - reservado)
        except Exception:
            # Degradación controlada: el fallo en inventario de un producto no interrumpe la carga de la vitrina
            stock_disp = 0

        # Agregar el ítem consolidado a la respuesta de la vitrina
        vitrina_items.append(
            VitrinaItem(
                sku=sku,
                nombre=nombre,
                precio_cop=precio,
                stock_disponible=stock_disp,
            )
        )

    # Retorna la lista agregada adaptada para la aplicación cliente móvil
    return vitrina_items
