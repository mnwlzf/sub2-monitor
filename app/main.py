from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import SessionLocal, ensure_schema
from app.models.all import (  # noqa: F401
    AuthSession,
    NotificationRecipient,
    NotificationSetting,
    PlatformSnapshot,
    RelayPlatform,
    User,
)
from app.services.auth import bootstrap_first_user, delete_expired_sessions
from app.services.scheduler import MonitorScheduler

monitor_scheduler = MonitorScheduler()
NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_schema()
    with SessionLocal() as db:
        bootstrap_first_user(db, get_settings())
        delete_expired_sessions(db)
    monitor_scheduler.start()
    yield
    await monitor_scheduler.stop()


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def mount_frontend(application: FastAPI, dist_dir: Path) -> None:
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        application.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @application.exception_handler(StarletteHTTPException)
    async def spa_fallback(request: Request, exc: StarletteHTTPException):
        if (
            exc.status_code == 404
            and not request.url.path.startswith("/api")
            and dist_dir.joinpath("index.html").exists()
        ):
            return FileResponse(dist_dir / "index.html", headers=NO_CACHE_HEADERS)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @application.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        requested = dist_dir / full_path
        if full_path and requested.exists() and requested.is_file():
            return FileResponse(requested)
        index_file = dist_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file, headers=NO_CACHE_HEADERS)
        return JSONResponse(
            {
                "detail": "Frontend is not built yet. Run `cd frontend && npm run build`.",
            },
            status_code=404,
        )


mount_frontend(app, settings.frontend_dist)


def run() -> None:
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.env == "development")


if __name__ == "__main__":
    run()
