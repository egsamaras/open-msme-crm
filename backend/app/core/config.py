from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-only-change-me-0123456789abcdef0123456789"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    environment: Literal["development", "test", "production"] = "development"

    database_url: str = "postgresql+asyncpg://crm:crm@localhost:5432/crm"
    checkpoint_database_url: str = "postgresql://crm:crm@localhost:5432/crm"

    jwt_secret: str = _DEV_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 8 * 60
    cookie_name: str = "crm_session"
    cookie_secure: bool = False

    cors_origins: list[str] = ["http://localhost:5173"]

    llm_provider: Literal["mock", "anthropic", "openai_compatible"] = "mock"
    llm_model: str = "claude-sonnet-5-5"
    llm_base_url: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    default_currency: str = "BHD"
    ubo_threshold_pct: Decimal = Decimal("25")

    ews_balance_drop_pct: Decimal = Decimal("25")
    ews_utilization_pct: Decimal = Decimal("90")
    ews_utilization_days: int = 30
    ews_doc_expiry_days: int = 30

    seed_password: str = "demo1234"

    @field_validator("jwt_secret", mode="before")
    @classmethod
    def _blank_secret_means_dev_default(cls, v: object) -> object:
        # `JWT_SECRET=` in .env must never mean "sign with an empty key".
        return _DEV_SECRET if v in (None, "") else v

    @field_validator("llm_base_url", "anthropic_api_key", "openai_api_key", mode="before")
    @classmethod
    def _blank_is_none(cls, v: object) -> object:
        return None if v == "" else v

    @property
    def is_dev(self) -> bool:
        return self.environment == "development"

    @model_validator(mode="after")
    def _refuse_dev_secret_in_production(self) -> "Settings":
        if self.environment == "production" and (
            self.jwt_secret == _DEV_SECRET or len(self.jwt_secret) < 32
        ):
            raise ValueError("Set JWT_SECRET (32+ characters) before running in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
