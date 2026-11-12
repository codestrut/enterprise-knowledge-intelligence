"""Serve the built EKIP single-page frontend and normalize its API prefix."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


FRONTEND_PAGE_PATHS = frozenset(
    {
        "/",
        "/library",
        "/workspace",
        "/platform",
        "/tenant/settings",
        "/403",
        "/forbidden",
    }
)


def configure_unified_frontend(app: FastAPI, frontend_dist: Path) -> None:
    """Mount built assets and route browser pages/API-prefixed requests."""

    frontend_dist = Path(frontend_dist)

    assets_directory = frontend_dist / "assets"
    if assets_directory.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(assets_directory)),
            name="frontend-assets",
        )

    images_directory = frontend_dist / "images"
    if images_directory.is_dir():
        app.mount(
            "/images",
            StaticFiles(directory=str(images_directory)),
            name="frontend-images",
        )

    @app.middleware("http")
    async def unified_frontend_and_api_paths(request: Request, call_next):
        path = request.scope.get("path", "/")

        if (
            request.method == "GET"
            and path in FRONTEND_PAGE_PATHS
            and "text/html" in request.headers.get("accept", "").lower()
        ):
            index_file = frontend_dist / "index.html"
            if index_file.is_file():
                return FileResponse(index_file)

        if path == "/api":
            rewritten_path = "/"
        elif path.startswith("/api/"):
            rewritten_path = path[4:]
        else:
            rewritten_path = None

        if rewritten_path is not None:
            request.scope["path"] = rewritten_path
            request.scope["raw_path"] = rewritten_path.encode("utf-8")

        return await call_next(request)
