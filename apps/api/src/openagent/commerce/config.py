"""MP24: billing settings — BILLING_MODE + fee policy defaults.

``BILLING_MODE=disabled`` (default): self-hosted works, paid flows raise.
``BILLING_MODE=mock``: deterministic MockBillingProvider for local dev/tests,
clearly labelled test mode, never a real payment.
``BILLING_MODE=live``: requires explicit provider configuration; startup
fails closed otherwise (no silent fallback to mock).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from openagent.commerce.types import BillingMode


class CommerceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True,
                                      extra="ignore")

    BILLING_MODE: str = Field(default=BillingMode.DISABLED)
    BILLING_PROVIDER: str = Field(default="")
    BILLING_WEBHOOK_SECRET: str = Field(default="")
    BILLING_WEBHOOK_SKEW_SECONDS: int = Field(default=300)
    BILLING_SUCCESS_URL: str = Field(default="http://localhost:3000/settings/billing?status=success")
    BILLING_CANCEL_URL: str = Field(default="http://localhost:3000/settings/billing?status=cancelled")

    # Creator revenue defaults (overridable per marketplace/product in DB).
    PLATFORM_FEE_BPS: int = Field(default=0)
    PAYOUT_MINIMUM_MINOR: int = Field(default=0)
    PAYOUT_SETTLEMENT_DAYS: int = Field(default=7)
    REFUND_HOLD_DAYS: int = Field(default=7)

    # Registry defaults (domain is configurable; never hard-coded).
    PUBLIC_REGISTRY_URL: str = Field(default="")

    def normalized_mode(self) -> str:
        return str(self.BILLING_MODE or BillingMode.DISABLED).lower()

    def validate_production(self) -> list[str]:
        problems: list[str] = []
        mode = self.normalized_mode()
        if mode not in (BillingMode.DISABLED, BillingMode.MOCK, BillingMode.LIVE):
            problems.append(f"unknown BILLING_MODE={self.BILLING_MODE!r}")
        if mode == BillingMode.LIVE and not self.BILLING_PROVIDER:
            problems.append("BILLING_MODE=live requires BILLING_PROVIDER")
        if mode == BillingMode.LIVE and not self.BILLING_WEBHOOK_SECRET:
            problems.append("BILLING_MODE=live requires BILLING_WEBHOOK_SECRET")
        if not 0 <= self.PLATFORM_FEE_BPS <= 10000:
            problems.append("PLATFORM_FEE_BPS must be 0..10000")
        return problems


@lru_cache
def get_commerce_settings() -> CommerceSettings:
    return CommerceSettings()
