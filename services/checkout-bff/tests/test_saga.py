"""Pruebas unitarias completas de la Saga y compensaciones con dobles (httpx.MockTransport)."""
import pytest
import httpx
from fastapi.testclient import TestClient

from app.main import app, IDEMPOTENCIA_STORE, PEDIDOS_ESTADO_STORE, _locks


@pytest.fixture(autouse=True)
def limpiar_almacenes():
    """Limpia la memoria antes de cada prueba para garantizar aislamiento."""
    IDEMPOTENCIA_STORE.clear()
    PEDIDOS_ESTADO_STORE.clear()
    _locks.clear()
    app.state.http_client = None
    yield
    IDEMPOTENCIA_STORE.clear()
    PEDIDOS_ESTADO_STORE.clear()
    _locks.clear()
    app.state.http_client = None


def test_checkout_exito_completo():
    """Caso 1: Todos los pasos responden OK -> CONFIRMADO con 4 pasos."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/v1/productos/CAFE-500G" in path:
            return httpx.Response(200, json={"sku": "CAFE-500G", "nombre": "Café", "precio_cop": 20000, "publicado": True})
        if "/v1/reservas" in path:
            return httpx.Response(201, json={"reserva_id": "RES-101", "sku": "CAFE-500G", "cantidad": 2})
        if "/v1/pedidos" in path:
            return httpx.Response(201, json={"pedido_id": "PED-202", "estado": "CREADO"})
        if "/v1/pagos" in path:
            return httpx.Response(201, json={"pago_id": "PAG-303", "estado": "APROBADO"})
        return httpx.Response(404)

    with TestClient(app) as c:
        app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        payload = {
            "cliente_id": "CLI-01",
            "sku": "CAFE-500G",
            "cantidad": 2,
            "medio_pago": "tarjeta"
        }
        resp = c.post("/v1/checkout", json=payload, headers={"Idempotency-Key": "key-exito-1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["estado"] == "CONFIRMADO"
        assert data["pedido_id"] == "PED-202"
        assert len(data["pasos"]) == 4
        assert [p["paso"] for p in data["pasos"]] == ["catalogo", "inventario", "pedidos", "pagos"]
        assert all(p["resultado"] == "OK" for p in data["pasos"])


def test_checkout_falla_paso_1_catalogo_404():
    """Caso 2.1: Producto inexistente o no publicado en catálogo -> FALLIDO, sin compensaciones."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detalle": "No existe"})

    with TestClient(app) as c:
        app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        payload = {"cliente_id": "CLI-01", "sku": "NO-EXISTE", "cantidad": 1, "medio_pago": "tarjeta"}
        resp = c.post("/v1/checkout", json=payload, headers={"Idempotency-Key": "key-cat-404"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["estado"] == "FALLIDO"
        assert len(data["pasos"]) == 1
        assert data["pasos"][0]["paso"] == "catalogo"
        assert data["pasos"][0]["resultado"] == "FALLIDO"


def test_checkout_falla_paso_2_inventario_409_stock_insuficiente():
    """Caso 2.2: Inventario responde 409 (stock insuficiente) -> FALLIDO, sin compensaciones."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/v1/productos" in path:
            return httpx.Response(200, json={"sku": "TAZA", "precio_cop": 15000, "publicado": True})
        if "/v1/reservas" in path:
            return httpx.Response(409, json={"detalle": "Stock insuficiente"})
        return httpx.Response(404)

    with TestClient(app) as c:
        app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        payload = {"cliente_id": "CLI-01", "sku": "TAZA", "cantidad": 999, "medio_pago": "tarjeta"}
        resp = c.post("/v1/checkout", json=payload, headers={"Idempotency-Key": "key-inv-409"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["estado"] == "FALLIDO"
        nombres_pasos = [p["paso"] for p in data["pasos"]]
        assert nombres_pasos == ["catalogo", "inventario"]
        assert data["pasos"][1]["resultado"] == "FALLIDO"


def test_checkout_falla_paso_3_pedidos_caido_compensa_inventario():
    """Caso 2.3: Pedidos responde 500 -> FALLIDO, compensa liberando la reserva de inventario."""
    llamadas_compensacion = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/v1/productos" in path:
            return httpx.Response(200, json={"sku": "CAMISA", "precio_cop": 40000, "publicado": True})
        if request.method == "POST" and path == "/v1/reservas":
            return httpx.Response(201, json={"reserva_id": "RES-999"})
        if "/v1/pedidos" in path:
            return httpx.Response(500, json={"detalle": "Servicio de pedidos caído"})
        if "/v1/reservas/RES-999/liberar" in path:
            llamadas_compensacion.append(path)
            return httpx.Response(200, json={"detalle": "Liberado"})
        return httpx.Response(404)

    with TestClient(app) as c:
        app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        payload = {"cliente_id": "CLI-01", "sku": "CAMISA", "cantidad": 1, "medio_pago": "tarjeta"}
        resp = c.post("/v1/checkout", json=payload, headers={"Idempotency-Key": "key-ped-500"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["estado"] == "FALLIDO"

        nombres_pasos = [p["paso"] for p in data["pasos"]]
        assert "inventario_liberar" in nombres_pasos
        assert len(llamadas_compensacion) == 1
        paso_comp = next(p for p in data["pasos"] if p["paso"] == "inventario_liberar")
        assert paso_comp["resultado"] == "COMPENSADO"


def test_checkout_falla_paso_4_pago_rechazado_compensa_en_orden_inverso():
    """Caso 2.4: Pagos responde RECHAZADO -> FALLIDO, NO reembolsa, y compensa pedidos (cancelar) e inventario (liberar) en orden inverso."""
    orden_compensaciones = []
    llamadas_reembolso = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/v1/productos" in path:
            return httpx.Response(200, json={"sku": "LIBRO", "precio_cop": 50000, "publicado": True})
        if request.method == "POST" and path == "/v1/reservas":
            return httpx.Response(201, json={"reserva_id": "RES-888"})
        if request.method == "POST" and path == "/v1/pedidos":
            return httpx.Response(201, json={"pedido_id": "PED-777", "estado": "CREADO"})
        if request.method == "POST" and path == "/v1/pagos":
            return httpx.Response(200, json={"pago_id": "PAG-111", "estado": "RECHAZADO"})

        # Compensaciones
        if "/reembolso" in path:
            llamadas_reembolso.append(path)
            return httpx.Response(200, json={"estado": "REEMBOLSADO"})
        if "/v1/pedidos/PED-777/cancelar" in path:
            orden_compensaciones.append("pedidos_cancelar")
            return httpx.Response(200, json={"estado": "CANCELADO"})
        if "/v1/reservas/RES-888/liberar" in path:
            orden_compensaciones.append("inventario_liberar")
            return httpx.Response(200, json={"estado": "LIBERADO"})

        return httpx.Response(404)

    with TestClient(app) as c:
        app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        payload = {"cliente_id": "CLI-01", "sku": "LIBRO", "cantidad": 1, "medio_pago": "tarjeta"}
        resp = c.post("/v1/checkout", json=payload, headers={"Idempotency-Key": "key-pago-rechazado"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["estado"] == "FALLIDO"

        # Verificar que NO se llamó a reembolso porque el pago fue RECHAZADO
        assert len(llamadas_reembolso) == 0

        # Verificar que el detalle del paso pagos aclare que no requiere reembolso
        paso_pago = next(p for p in data["pasos"] if p["paso"] == "pagos")
        assert "no requiere reembolso" in paso_pago["detalle"]

        # Verificar orden inverso estricto de compensaciones: pedidos_cancelar -> inventario_liberar
        assert orden_compensaciones == ["pedidos_cancelar", "inventario_liberar"]


def test_checkout_timeout_en_pedidos_compensa():
    """Caso 3: Timeout simulado en llamadas salientes es tratado como fallo y dispara compensación."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/v1/productos" in path:
            return httpx.Response(200, json={"sku": "CAFE", "precio_cop": 10000, "publicado": True})
        if request.method == "POST" and path == "/v1/reservas":
            return httpx.Response(201, json={"reserva_id": "RES-TIMEOUT"})
        if "/v1/pedidos" in path:
            raise httpx.ReadTimeout("Timeout al comunicar con pedidos-service")
        if "/v1/reservas/RES-TIMEOUT/liberar" in path:
            return httpx.Response(200, json={"estado": "LIBERADO"})
        return httpx.Response(404)

    with TestClient(app) as c:
        app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        payload = {"cliente_id": "CLI-01", "sku": "CAFE", "cantidad": 1, "medio_pago": "nequi"}
        resp = c.post("/v1/checkout", json=payload, headers={"Idempotency-Key": "key-timeout"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["estado"] == "FALLIDO"
        pasos_nombres = [p["paso"] for p in data["pasos"]]
        assert "inventario_liberar" in pasos_nombres


def test_checkout_idempotencia_misma_clave():
    """Caso 4: Repetir la misma Idempotency-Key devuelve exactamente la misma respuesta sin repetir pasos."""
    contador_llamadas_pagos = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal contador_llamadas_pagos
        path = request.url.path
        if "/v1/productos" in path:
            return httpx.Response(200, json={"sku": "PROD", "precio_cop": 1000, "publicado": True})
        if "/v1/reservas" in path:
            return httpx.Response(201, json={"reserva_id": "RES-1"})
        if "/v1/pedidos" in path:
            return httpx.Response(201, json={"pedido_id": "PED-UNICO", "estado": "CREADO"})
        if "/v1/pagos" in path:
            contador_llamadas_pagos += 1
            return httpx.Response(201, json={"pago_id": "PAG-1", "estado": "APROBADO"})
        return httpx.Response(404)

    with TestClient(app) as c:
        app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        payload = {"cliente_id": "CLI-01", "sku": "PROD", "cantidad": 1, "medio_pago": "tarjeta"}
        headers = {"Idempotency-Key": "clave-repetida-100"}

        # Primera petición
        resp1 = c.post("/v1/checkout", json=payload, headers=headers)
        assert resp1.status_code == 200
        data1 = resp1.json()

        # Segunda petición con la misma clave
        resp2 = c.post("/v1/checkout", json=payload, headers=headers)
        assert resp2.status_code == 200
        data2 = resp2.json()

        assert data1 == data2
        assert data1["pedido_id"] == "PED-UNICO"
        assert contador_llamadas_pagos == 1  # No se volvió a ejecutar el pago


def test_checkout_concurrencia_idempotencia():
    """Caso 4.2: Dos llamadas concurrentes con la misma Idempotency-Key ejecutan la saga una sola vez."""
    import asyncio
    from httpx import ASGITransport, AsyncClient

    contador_pedidos = 0
    contador_pagos = 0

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal contador_pedidos, contador_pagos
        path = request.url.path
        if "/v1/productos" in path:
            return httpx.Response(200, json={"sku": "PROD-CONC", "precio_cop": 15000, "publicado": True})
        if "/v1/reservas" in path:
            return httpx.Response(201, json={"reserva_id": "RES-CONC"})
        if "/v1/pedidos" in path:
            contador_pedidos += 1
            await asyncio.sleep(0.05)
            return httpx.Response(201, json={"pedido_id": "PED-CONC-1", "estado": "CREADO"})
        if "/v1/pagos" in path:
            contador_pagos += 1
            await asyncio.sleep(0.05)
            return httpx.Response(201, json={"pago_id": "PAG-CONC-1", "estado": "APROBADO"})
        return httpx.Response(404)

    async def run_concurrent_test():
        app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

        payload = {"cliente_id": "CLI-CONC", "sku": "PROD-CONC", "cantidad": 2, "medio_pago": "nequi"}
        headers = {"Idempotency-Key": "clave-concurrente-test-123"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp1, resp2 = await asyncio.gather(
                client.post("/v1/checkout", json=payload, headers=headers),
                client.post("/v1/checkout", json=payload, headers=headers),
            )

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json() == resp2.json()
        assert resp1.json()["estado"] == "CONFIRMADO"
        assert resp1.json()["pedido_id"] == "PED-CONC-1"

        # Verificación estricta: exactamente UNA creación de pedido y UN cobro
        assert contador_pedidos == 1
        assert contador_pagos == 1

    asyncio.run(run_concurrent_test())


def test_checkout_falta_idempotency_key_da_422():
    """Caso 5: La ausencia de Idempotency-Key responde 422 con formato de error uniforme."""
    with TestClient(app) as c:
        payload = {"cliente_id": "CLI-01", "sku": "PROD", "cantidad": 1, "medio_pago": "tarjeta"}
        resp = c.post("/v1/checkout", json=payload)
        assert resp.status_code == 422
        data = resp.json()
        assert "detalle" in data
        assert data.get("codigo") == "IDEMPOTENCY_KEY_REQUERIDA"


def test_obtener_estado_checkout_existente_y_no_encontrado():
    """Caso 6: Consulta de estado por pedido_id (200 si existe, 404 con error uniforme si no)."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/v1/productos" in path:
            return httpx.Response(200, json={"sku": "PROD", "precio_cop": 1000, "publicado": True})
        if "/v1/reservas" in path:
            return httpx.Response(201, json={"reserva_id": "RES-X"})
        if "/v1/pedidos" in path:
            return httpx.Response(201, json={"pedido_id": "PED-ESTADO-1", "estado": "CREADO"})
        if "/v1/pagos" in path:
            return httpx.Response(201, json={"pago_id": "PAG-X", "estado": "APROBADO"})
        return httpx.Response(404)

    with TestClient(app) as c:
        app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        # Primero crear un pedido
        payload = {"cliente_id": "CLI-01", "sku": "PROD", "cantidad": 1, "medio_pago": "tarjeta"}
        c.post("/v1/checkout", json=payload, headers={"Idempotency-Key": "key-estado"})

        # Consultar existente
        resp_ok = c.get("/v1/checkout/PED-ESTADO-1/estado")
        assert resp_ok.status_code == 200
        assert resp_ok.json()["pedido_id"] == "PED-ESTADO-1"

        # Consultar no existente -> 404
        resp_404 = c.get("/v1/checkout/PED-INEXISTENTE/estado")
        assert resp_404.status_code == 404
        data_404 = resp_404.json()
        assert "detalle" in data_404
        assert data_404.get("codigo") == "PEDIDO_NO_ENCONTRADO"
