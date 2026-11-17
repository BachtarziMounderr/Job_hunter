"""Structured, immutable scoring output; presentation providers never modify it."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MatchResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    total_score: float = Field(ge=0, le=100)
    semantic_score: float = Field(ge=0, le=100)
    skills_score: float = Field(ge=0, le=100)
    experience_score: float = Field(ge=0, le=100)
    education_score: float = Field(ge=0, le=100)
    location_score: float = Field(ge=0, le=100)
    geographic_status: Literal["eligible", "ineligible", "unknown"]
    eligible_for_notification: bool
    matched_skills: list[str]
    missing_skills: list[str]
    matching_reasons: list[str]
    incompatibility_reasons: list[str]
    role: str
    review_reasons: list[str] = Field(default_factory=list)
    exclusion_codes: list[str] = Field(default_factory=list)
