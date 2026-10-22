from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr


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
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_username: str = "oimogroup2027@gmail.com"
    smtp_password: SecretStr = SecretStr("")
    smtp_from_name: str = "Oimo"
    smtp_from: str = ""
    smtp_test_recipient: str = "oimogroup2027@gmail.com"
    public_app_url: str = ""
    freedompay_enabled: bool = False
    freedompay_merchant_id: str = ""
    freedompay_secret_key: SecretStr = SecretStr("")
    freedompay_test_mode: bool = True
    freedompay_api_base: str = "https://api.freedompay.kg"
    freedompay_init_path: str = "/init_payment"
    seller_legal_name: str = ""
    seller_tax_id: str = ""
    seller_address: str = ""
    seller_phone: str = ""
    seller_bank_details: str = ""
    seller_support_email: str = "support@oimopos.com"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
