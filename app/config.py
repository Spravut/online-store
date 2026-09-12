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

    # --- партиционирование (лабораторная №3) ---
    # Таблица, за партициями которой следит job, и на сколько дней вперёд
    # они должны быть созданы.
    partition_table: str = "orders"
    partition_horizon_days: int = 3
    partition_granularity: str = "month"  # day | month

    # --- алертинг ---
    # Токен и chat_id берутся ТОЛЬКО из окружения или .env, в репозиторий
    # не попадают: .env в .gitignore, в .env.example лежат заглушки.
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    alerts_enabled: bool = True

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


settings = Settings()
