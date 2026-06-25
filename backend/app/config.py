from functools import lru_cache
from pathlib import Path
from typing import List
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env next to backend/ regardless of uvicorn cwd (fixes wrong DATABASE_URL).
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_secret_key: str = "dev-secret-key-change-in-production"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"

    # Database components — align with backend/.env.example and docs/dbeaver_postgres_connection.md
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = ""  # set in .env; never commit real secrets
    postgres_db: str = "neurographiq_kg_v3_wb"
    postgres_db_candidate: str = "neurographiq_kg_v3_candidate"

    # Full URLs (override components when set in .env)
    database_url: str = "postgresql+psycopg_async://postgres@127.0.0.1:5432/neurographiq_kg_v3_wb"
    candidate_database_url: str = (
        "postgresql://postgres@127.0.0.1:5432/neurographiq_kg_v3_candidate"
    )
    final_database_url: str = (
        "postgresql+psycopg_async://postgres@127.0.0.1:5432/neurographiq_kg_v3_candidate"
    )

    def build_database_url(self, *, database: str | None = None, async_driver: bool = True) -> str:
        """Build URL from POSTGRES_* (for docs/scripts); password URL-encoded."""
        db = database or self.postgres_db
        user = quote_plus(self.postgres_user)
        pwd = quote_plus(self.postgres_password) if self.postgres_password else ""
        auth = f"{user}:{pwd}@" if pwd else f"{user}@"
        scheme = "postgresql+psycopg_async" if async_driver else "postgresql"
        return f"{scheme}://{auth}{self.postgres_host}:{self.postgres_port}/{db}"

    @property
    def final_database_url_async(self) -> str:
        url = self.final_database_url
        if url.startswith("postgresql://") and "+psycopg" not in url:
            return url.replace("postgresql://", "postgresql+psycopg_async://", 1)
        return url

    # File Storage
    upload_dir: str = "./data/uploads"
    archive_dir: str = "./data/archive"

    # LLM - DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_default_model: str = "deepseek-chat"

    # LLM - Kimi (Moonshot)
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_default_model: str = "moonshot-v1-8k"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # SQLAlchemy echo (verbose SQL); keep false to avoid dev slowdown
    db_echo: bool = False

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",")]


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def get_deepseek_runtime_config():
    """Return DeepSeek config with local runtime overrides applied."""
    from app.services.settings_service import get_deepseek_runtime_config as _get_runtime

    return _get_runtime()
