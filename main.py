from fastapi import FastAPI

from backend.controllers import api_router


def create_app() -> FastAPI:
    app = FastAPI(title="Voice Note Collector API")
    app.include_router(api_router)
    return app


app = create_app()
