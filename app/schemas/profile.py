"""Load the candidate's configurable profile without inferring work authorization."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CandidateProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1)
    residence_country: str = Field(pattern=r"^[A-Z]{2}$")
    work_authorization_countries: list[str] = Field(default_factory=list)
    languages: list[str]
    education: list[str]
    freelance_experience_years: float = Field(ge=0)
    skills: list[str]
    projects: list[str]
    target_roles: list[str]
    target_seniority: list[str]
    preferred_cities: list[str]
    remote_policy: str
    profile_id: str | None = Field(default=None, pattern=r"^[a-z0-9_-]+$")
    resume_text: str = Field(default="", max_length=20000)
    resume_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    education_level: str = "master"
    enabled: bool = True

    @field_validator("work_authorization_countries")
    @classmethod
    def validate_country_codes(cls, value: list[str]) -> list[str]:
        if any(len(code) != 2 or not code.isupper() for code in value):
            raise ValueError("Work authorization countries must use uppercase ISO alpha-2 codes")
        return sorted(set(value))


def load_profile(path: Path) -> CandidateProfile:
    """Validate a UTF-8 JSON profile; errors are handled by the caller."""
    return CandidateProfile.model_validate_json(path.read_text(encoding="utf-8"))
