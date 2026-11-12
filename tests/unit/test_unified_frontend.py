from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.unified_frontend import configure_unified_frontend


def test_browser_routes_serve_the_single_page_application(tmp_path):
    (tmp_path / "index.html").write_text("<html>EKIP SPA</html>", encoding="utf-8")
    app = FastAPI()
    configure_unified_frontend(app, tmp_path)

    @app.get("/tenant/settings")
    def tenant_settings_api():
        return {"source": "api"}

    client = TestClient(app)
    response = client.get("/tenant/settings", headers={"Accept": "text/html"})

    assert response.status_code == 200
    assert response.text == "<html>EKIP SPA</html>"


def test_api_prefix_rewrites_to_existing_backend_routes(tmp_path):
    app = FastAPI()
    configure_unified_frontend(app, tmp_path)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/tenant/settings")
    def tenant_settings_api():
        return {"source": "api"}

    client = TestClient(app)
    health_response = client.get("/api/health", headers={"Accept": "application/json"})
    settings_response = client.get(
        "/api/tenant/settings", headers={"Accept": "application/json"}
    )

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}
    assert settings_response.status_code == 200
    assert settings_response.json() == {"source": "api"}


def test_built_assets_are_mounted_when_present(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("window.EKIP = true;", encoding="utf-8")
    app = FastAPI()
    configure_unified_frontend(app, tmp_path)

    response = TestClient(app).get("/assets/app.js")

    assert response.status_code == 200
    assert response.text == "window.EKIP = true;"
