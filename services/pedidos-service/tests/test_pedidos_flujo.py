import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_live():
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"

def test_health_ready():
    response = client.get("/health/ready")
    assert response.status_code in [200, 503]

def test_health_startup():
    response = client.get("/health/startup")
    assert response.status_code in [200, 503]

def test_crear_y_obtener_pedido_flujo_completo():
    # 1. Crear un pedido válido
    payload = {
        "cliente_id": 42,
        "total": 150000.0
    }
    response = client.post("/v1/pedidos", json=payload)
    assert response.status_code in [200, 201]
    
    data = response.json()
    pedido_id = data.get("id")
    assert pedido_id is not None
    assert data["cliente_id"] == 42
    assert data["total"] == 150000.0
    assert data["estado"] == "PENDIENTE"

    # 2. Consultar el pedido creado por ID existente
    res_get = client.get(f"/v1/pedidos/{pedido_id}")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == pedido_id

    # 3. Consultar un pedido con ID inexistente (prueba de error 404)
    res_inexistente = client.get("/v1/pedidos/999999")
    assert res_inexistente.status_code == 404
    assert res_inexistente.json()["detail"] == "Pedido no encontrado"