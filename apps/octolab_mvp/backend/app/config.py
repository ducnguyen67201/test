"""Application configuration from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Get the backend directory (parent of app/)
BACKEND_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str

    # Application metadata
    app_name: str = "OctoLab"
    app_version: str = "0.1.0"

    # Logging
    log_level: str = "INFO"

    # JWT Authentication
    secret_key: str  # JWT signing secret
    algorithm: str = "HS256"  # JWT algorithm
    access_token_expire_minutes: int = 30  # Token expiration in minutes

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# Global settings instance
settings = Settings()

