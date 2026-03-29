---
name: configuration-management
description: Defines how to manage environment variables and configuration using Pydantic Settings
---

# FastAPI Configuration Management

This skill defines how environment variables and configuration must be handled.

---

## Core Principle

All environment variables must be accessed through a centralized settings module.

---

## Implementation

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    SUPABASE_URL: str
    SUPABASE_KEY: str
    GROQ_API_KEY: str

    class Config:
        env_file = ".env"


settings = Settings()