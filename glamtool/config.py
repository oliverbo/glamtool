from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Default to real process environment variables.
    # An env file can still be passed explicitly at runtime.
    model_config = SettingsConfigDict(env_file=None, env_file_encoding="utf-8")

    ghost_url: str
    ghost_content_key: str


def load_settings(env_file: Optional[Path] = None) -> Settings:
    if env_file is None:
        return Settings()
    return Settings(_env_file=env_file)
