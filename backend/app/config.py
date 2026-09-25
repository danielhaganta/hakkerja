from functools import lru_cache
from pathlib import Path

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives at the repo root, while commands run from backend/.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    database_url: PostgresDsn


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # fields are filled from the environment
