from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

ProviderName = Literal["template", "ollama", "openai_compatible", "anthropic", "openai"]


class DealInput(BaseModel):
    deal_name: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Set when backtesting an existing deal; it is excluded from its own comparables.",
    )
    account_name: Optional[str] = Field(default=None, max_length=255)
    industry: Optional[str] = Field(default=None, max_length=120)
    size_sqft: Optional[float] = Field(default=None, ge=0, le=5_000_000)
    lease_term_months: Optional[float] = Field(default=None, ge=0, le=600)
    gross_signing_rent_psf: Optional[float] = Field(default=None, ge=0, le=1_000)
    property_name: Optional[str] = Field(default=None, max_length=255)
    agent_name: Optional[str] = Field(default=None, max_length=120)
    notes: Optional[str] = Field(default=None, max_length=4000)

    @field_validator(
        "deal_name", "account_name", "industry", "property_name", "agent_name", "notes", mode="before"
    )
    @classmethod
    def _blank_to_none(cls, value):
        """Treat whitespace-only strings as missing so they never act as filters or features."""
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class LLMSelection(BaseModel):
    provider: ProviderName = "template"
    model: Optional[str] = Field(default=None, max_length=200)


class EvaluateRequest(BaseModel):
    deal: DealInput
    llm: LLMSelection = Field(default_factory=LLMSelection)


class BaselineMetrics(BaseModel):
    match_level: str
    n_comparables: int
    n_with_fee: int
    median_fee_sgd: Optional[float]
    mean_fee_sgd: Optional[float]
    fee_p25_sgd: Optional[float] = None
    fee_p75_sgd: Optional[float] = None
    median_size_sqft: Optional[float]
    median_lease_term_months: Optional[float]
    outcome_coverage: int
    win_rate_pct: Optional[float]


class Analogue(BaseModel):
    deal_name: str
    industry: Optional[str]
    size_sqft: Optional[float]
    lease_term_months: Optional[float]
    gross_fee_sgd: Optional[float]
    outcome: Optional[str]
    similarity: float


class Narrative(BaseModel):
    """Structured output the LLM must return. Numbers are never taken from the LLM."""

    winning_strategy: str = Field(description="Two to four sentences grounded in the provided metrics and analogues.")
    key_risks_and_mitigations: list[str] = Field(description="Each item formatted as 'Risk: ... Mitigation: ...'.")
    recommended_resources: list[str]
    referenced_historical_deals: list[str] = Field(
        description="Only aliases from the analogues list, such as HIST-01."
    )


class Qualification(BaseModel):
    pursue_recommendation: Optional[str]
    fit_score: Optional[int]
    framework_breakdown: dict[str, str]


class Estimates(BaseModel):
    win_probability_pct: Optional[float]
    estimated_fee_sgd: Optional[float]
    estimated_timeframe_days: Optional[int]
    confidence_level: Literal["HIGH", "MEDIUM", "LOW"]


class EffortAllocation(BaseModel):
    tier: str
    recommended_resources: list[str]
    max_recommended_hours: Optional[int]


class ClosingPlaybook(BaseModel):
    winning_strategy: str
    key_risks_and_mitigations: list[str]
    referenced_historical_deals: list[str]


class Evidence(BaseModel):
    baseline: BaselineMetrics
    analogues: list[Analogue]


class DealScorecard(BaseModel):
    deal_id: str
    qualification: Qualification
    estimates: Estimates
    effort_allocation: EffortAllocation
    closing_playbook: ClosingPlaybook
    evidence: Evidence
    data_gaps: list[str]
    warnings: list[str]
    narrative_source: Literal["llm", "template", "template_fallback"]
    llm_provider: str
    llm_model: Optional[str]
