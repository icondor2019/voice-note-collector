from fastapi import FastAPI

from backend.controllers import api_router
from configuration.settings import settings


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
    return app


app = create_app()
