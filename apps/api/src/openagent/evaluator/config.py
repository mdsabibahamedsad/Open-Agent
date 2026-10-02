"""Evaluator production configuration (MP20). Secure defaults; production
startup refuses silently-unsafe combinations."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EvaluatorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    EVALUATION_ENABLED: bool = Field(default=True)
    DEFAULT_EVALUATION_TIMEOUT: int = Field(default=300, ge=5)
    MAX_CORRECTION_CYCLES: int = Field(default=3, ge=1, le=10)
    MAX_EVALUATION_RETRIES: int = Field(default=2, ge=0, le=5)
    DEFAULT_QUALITY_THRESHOLD: float = Field(default=0.7, ge=0.0, le=1.0)
    DEFAULT_CONFIDENCE_THRESHOLD: float = Field(default=0.6, ge=0.0, le=1.0)
    MAX_EVALUATION_COST: float = Field(default=5.0, ge=0.0)
    MAX_EVALUATION_TOKENS: int = Field(default=50_000, ge=0)
    ENABLE_LLM_EVALUATION: bool = Field(default=True)
    ENABLE_MULTI_EVALUATOR: bool = Field(default=True)
    ENABLE_SELF_CORRECTION: bool = Field(default=True)
    EVALUATOR_DISAGREEMENT_POLICY: str = Field(default="CONSERVATIVE_FAIL")
    ALLOW_SELF_EVALUATION: bool = Field(default=False)

    def validate_production(self) -> list[str]:
        errors: list[str] = []
        if self.MAX_CORRECTION_CYCLES > 10:
            errors.append("MAX_CORRECTION_CYCLES is unreasonably high")
        if self.DEFAULT_QUALITY_THRESHOLD <= 0:
            errors.append("DEFAULT_QUALITY_THRESHOLD must be positive in production")
        if self.ALLOW_SELF_EVALUATION:
            errors.append("ALLOW_SELF_EVALUATION requires an explicit policy override; "
                          "refusing silent enable")
        if self.EVALUATOR_DISAGREEMENT_POLICY not in (
                "CONSERVATIVE_FAIL", "HUMAN_REVIEW", "SECOND_REVIEW", "MORE_EVIDENCE"):
            errors.append("EVALUATOR_DISAGREEMENT_POLICY is unknown")
        return errors
