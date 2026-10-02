from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    OPENAGENT_ENV: str = Field(default="development")
    LOG_LEVEL: str = Field(default="info")
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    DATABASE_URL: str = Field(default="postgresql+asyncpg://openagent:openagent@localhost:5432/openagent")

    WORKER_CONCURRENCY: int = Field(default=4)
    JOB_TIMEOUT: int = Field(default=300)
    WORKER_POLL_INTERVAL: float = Field(default=1.0)

    # Retry policy defaults
    DEFAULT_MAX_ATTEMPTS: int = Field(default=3)
    DEFAULT_BASE_DELAY_SECONDS: float = Field(default=1.0)
    DEFAULT_MAX_DELAY_SECONDS: float = Field(default=300.0)
    DEFAULT_BACKOFF_STRATEGY: str = Field(default="exponential_jitter")

    @property
    def is_development(self) -> bool:
        return self.OPENAGENT_ENV == "development"