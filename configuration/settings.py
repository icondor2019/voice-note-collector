from __future__ import annotations

from typing import Any, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized application settings.

    NOTE: Keep all legacy variables available as attributes.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENVIRONMENT: str = "dev"

    # Application configuration
    APP_NAME: str = "voice-note-collector"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Server configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Supabase
    SUPABASE_URL: Optional[str] = None
    SUPABASE_KEY: Optional[str] = None

    # JWT
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # CORS
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["*"])
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: list[str] = Field(default_factory=lambda: ["*"])
    CORS_ALLOW_HEADERS: list[str] = Field(default_factory=lambda: ["*"])

    # Frontend
    FRONTEND_URL: str = ""
    # Empty by default to force configuration in production (legacy behavior/comment)
    API_BASE_URL: str = ""

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "app.log"

    # Providers
    OPENAI_API_KEY: Optional[str] = None

    # telegram
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_BOT_USER: Optional[str] = None

    # GROQ
    GROQ_API_KEY: Optional[str] = None
    GROQ_USER: Optional[str] = None

    @field_validator("CORS_ORIGINS", "CORS_ALLOW_METHODS", "CORS_ALLOW_HEADERS", mode="before")
    @classmethod
    def _split_csv_to_list(cls, v: Any) -> Any:
        if v is None:
            return v
        if isinstance(v, str):
            # Support legacy comma-separated values
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    def validate_config(self) -> None:
        """Legacy validations: ensure required variables are present."""

        required_vars = [
            "SUPABASE_URL",
            "SUPABASE_KEY",
            "SECRET_KEY",
        ]

        missing_vars: list[str] = []
        for var in required_vars:
            if not getattr(self, var, None):
                missing_vars.append(var)

        if missing_vars:
            raise ValueError(
                f"Las siguientes variables de entorno son requeridas: {', '.join(missing_vars)}"
            )


# Instance (requested pattern)
settings = Settings()

# Keep legacy behavior: validate on import, but do not crash.
try:
    settings.validate_config()
except ValueError as e:
    print(f"Error de configuración: {e}")
    print("Por favor, asegúrate de que el archivo .env esté configurado correctamente.")
