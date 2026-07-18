from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    ghost_url: str
    ghost_content_key: str
    ghost_admin_key: str | None = None


settings = Settings()
