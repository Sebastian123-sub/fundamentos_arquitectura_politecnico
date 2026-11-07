"""Pruebas de las tres sondas de salud (Semana 4)."""
from fastapi.testclient import TestClient
from app.main import app


def test_las_tres_sondas():
    """Verifica que /health/live, /health/startup y /health/ready respondan correctamente."""
    with TestClient(app) as c:
        resp_live = c.get("/health/live")
        assert resp_live.status_code == 200
        assert resp_live.json().get("status") == "alive"

        resp_startup = c.get("/health/startup")
        assert resp_startup.status_code == 200
        assert resp_startup.json().get("started") is True

        resp_ready = c.get("/health/ready")
        assert resp_ready.status_code == 200
        assert resp_ready.json().get("ready") is True
        assert "config_version" in resp_ready.json()
