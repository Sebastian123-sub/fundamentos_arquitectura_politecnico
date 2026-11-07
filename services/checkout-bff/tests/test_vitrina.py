"""Pruebas del agregador BFF para móvil: GET /v1/vitrina."""
import httpx
from fastapi.testclient import TestClient

from app.main import app


def test_vitrina_solo_campos_movil():
    """Verifica que la vitrina filtre solo los productos publicados y retorne únicamente los campos requeridos para móvil."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/productos":
            return httpx.Response(200, json={
                "items": [
                    {"sku": "CAFE-500G", "nombre": "Café Colombiano", "precio_cop": 28000.0, "publicado": True, "descripcion_larga": "Detalle que no necesita el móvil"},
                    {"sku": "MOLINO", "nombre": "Molino Manual", "precio_cop": 85000.0, "publicado": False},  # No publicado -> se debe omitir
                ]
            })
        if "/v1/stock/CAFE-500G" in path:
            return httpx.Response(200, json={"sku": "CAFE-500G", "cantidad": 20, "reservado": 3})

        return httpx.Response(404)

    with TestClient(app) as c:
        app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        resp = c.get("/v1/vitrina")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        item = items[0]

        # Solo debe contener los 4 campos esperados para la vista móvil
        campos_esperados = {"sku", "nombre", "precio_cop", "stock_disponible"}
        assert set(item.keys()) == campos_esperados
        assert item["sku"] == "CAFE-500G"
        assert item["nombre"] == "Café Colombiano"
        assert item["precio_cop"] == 28000.0
        assert item["stock_disponible"] == 17  # 20 - 3 = 17


def test_vitrina_degradacion_si_inventario_falla():
    """Falla parcial: Si inventario falla para un SKU, se degrada a stock 0 sin tumbar toda la vitrina."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/productos":
            return httpx.Response(200, json=[
                {"sku": "TAZA-1", "nombre": "Taza PiShop", "precio_cop": 15000.0, "publicado": True}
            ])
        if "/v1/stock/TAZA-1" in path:
            # Simular inventario caído o timeout
            raise httpx.ConnectError("No se puede conectar con inventario-service")

        return httpx.Response(404)

    with TestClient(app) as c:
        app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        resp = c.get("/v1/vitrina")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["sku"] == "TAZA-1"
        assert items[0]["stock_disponible"] == 0  # Degrada graciosamente
