from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения. Читаются из переменных окружения или из .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://shop:shop@localhost:5432/shop"
    run_migrations: bool = True

    db_pool_min_size: int = 2
    db_pool_max_size: int = 10

    app_title: str = "Shop API"
    app_version: str = "1.0.0"


settings = Settings()
