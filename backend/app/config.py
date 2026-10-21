from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)

    database_url: str = "postgresql://ashkana:ashkana_local@db:5432/ashkana"
    cors_origins: str = "http://127.0.0.1:8000,http://localhost:8000"
    platform_initial_login: str = "platform"
    platform_initial_password: str = "ChangeMe-Platform-2026"
    employee_pin_key: str = ""
    session_days: int = 7
    session_cookie_secure: bool = False
    openai_api_key: str = ""
    invoice_photo_model: str = "gpt-4.1"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
