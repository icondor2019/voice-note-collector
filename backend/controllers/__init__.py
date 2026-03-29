from fastapi import APIRouter

from backend.controllers.health_controller import router as health_router
from backend.controllers.sources_controller import router as sources_router
from backend.controllers.telegram_controller import router as telegram_router
from backend.controllers.voice_notes_controller import router as voice_notes_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(telegram_router)
api_router.include_router(sources_router)
api_router.include_router(voice_notes_router)

__all__ = ["api_router"]
