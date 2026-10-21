from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "backend/.env"), extra="ignore")
    app_env: str = "development"
    supabase_url: str = ""
    supabase_secret_key: SecretStr = SecretStr("")
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    dispatcher_url: str = ""
    dispatcher_secret: SecretStr = SecretStr("")
    max_upload_bytes: int = 5_000_000
    max_pdf_pages: int = 5
    max_image_pixels: int = 20_000_000

    @property
    def configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_secret_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
