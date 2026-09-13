from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.controllers import api_router
from configuration.settings import settings
from backend.utils.web_security import SecurityHeadersMiddleware


def create_app() -> FastAPI:
    if settings.ENVIRONMENT == "prod":
        app = FastAPI(
            title="Voice Note Collector API",
            docs_url=None,
            redoc_url=None,
            openapi_url=None,
        )
    else:
        app = FastAPI(title="Voice Note Collector API")
    app.include_router(api_router)
    static_dir = Path(__file__).resolve().parent / "frontend" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.add_middleware(SecurityHeadersMiddleware)
    return app


app = create_app()
