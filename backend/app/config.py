from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OLLADEX_", env_file=".env", extra="ignore")

    data_root: Path = Path("data")
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:14b"
    cors_origins: str = "http://localhost:5081,http://127.0.0.1:5081"
    command_timeout_seconds: int = 120
    max_file_bytes: int = 2_000_000

    @property
    def database_path(self) -> Path:
        return self.data_root / "olladex.sqlite3"


settings = Settings()

