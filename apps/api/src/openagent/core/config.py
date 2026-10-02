from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    OPENAGENT_ENV: str = Field(default="development")
    LOG_LEVEL: str = Field(default="info")
    API_URL: str = Field(default="http://localhost:8000")
    WEB_URL: str = Field(default="http://localhost:3000")

    # Database
    DATABASE_URL: str = Field(default="postgresql+asyncpg://openagent:openagent@localhost:5432/openagent")

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # Security
    SECRET_KEY: str = Field(default="", min_length=32)
    ENCRYPTION_KEY: str = Field(default="", min_length=32)

    # CORS
    CORS_ORIGINS: str = Field(default="http://localhost:3000,http://localhost:8000")

    # Authentication
    SESSION_COOKIE_NAME: str = Field(default="oa_session")
    SESSION_COOKIE_DOMAIN: str = Field(default="")
    SESSION_COOKIE_SECURE: bool = Field(default=False)
    SESSION_COOKIE_HTTP_ONLY: bool = Field(default=True)
    SESSION_COOKIE_SAME_SITE: str = Field(default="lax")
    SESSION_EXPIRE_DAYS: int = Field(default=7)
    SESSION_IDLE_TIMEOUT_MINUTES: int = Field(default=60)

    # Password Policy
    PASSWORD_MIN_LENGTH: int = Field(default=10)
    PASSWORD_MAX_LENGTH: int = Field(default=128)
    PASSWORD_REQUIRE_UPPERCASE: bool = Field(default=False)
    PASSWORD_REQUIRE_LOWERCASE: bool = Field(default=False)
    PASSWORD_REQUIRE_NUMBERS: bool = Field(default=False)
    PASSWORD_REQUIRE_SPECIAL: bool = Field(default=False)

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = Field(default=True)
    RATE_LIMIT_LOGIN_PER_MINUTE: int = Field(default=10)
    RATE_LIMIT_REGISTER_PER_HOUR: int = Field(default=5)
    RATE_LIMIT_PASSWORD_RESET_PER_HOUR: int = Field(default=3)
    RATE_LIMIT_EMAIL_VERIFICATION_PER_HOUR: int = Field(default=5)

    # Email
    SMTP_HOST: str = Field(default="")
    SMTP_PORT: int = Field(default=587)
    SMTP_USERNAME: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    SMTP_USE_TLS: bool = Field(default=True)
    SMTP_FROM_EMAIL: str = Field(default="noreply@openagent.local")
    SMTP_FROM_NAME: str = Field(default="OpenAgent")

    # Master Account
    MASTER_ACCOUNT_EMAIL: str = Field(default="")
    MASTER_ACCOUNT_PASSWORD: str = Field(default="")
    MASTER_ACCOUNT_DISPLAY_NAME: str = Field(default="Platform Owner")

    # Frontend URLs
    FRONTEND_VERIFY_EMAIL_URL: str = Field(default="http://localhost:3000/verify-email")
    FRONTEND_RESET_PASSWORD_URL: str = Field(default="http://localhost:3000/reset-password")

    # Internal worker service authentication (MP25: service token, short-lived
    # credentials are minted per task; the token itself is a bootstrap secret).
    WORKER_SERVICE_TOKEN: str = Field(default="")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def is_development(self) -> bool:
        return self.OPENAGENT_ENV == "development"

    @property
    def is_production(self) -> bool:
        return self.OPENAGENT_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()