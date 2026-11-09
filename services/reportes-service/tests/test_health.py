from fastapi.testclient import TestClient

from app.main import app


def test_las_tres_sondas():
    with TestClient(app) as c:   # `with` dispara el lifespan
        assert c.get("/health/live").status_code == 200
        assert c.get("/health/startup").status_code == 200
        r = c.get("/health/ready")
        assert r.status_code == 200 and "config_version" in r.json()


def test_crear_y_listar_reporte():
    with TestClient(app) as c:
        creado = c.post(
            "/reportes/",
            json={"titulo": "Reporte de prueba", "descripcion": "Prueba CRUD"},
        )
        assert creado.status_code == 200
        reporte = creado.json()

        listado = c.get("/reportes/")
        assert listado.status_code == 200
        assert reporte in listado.json()
