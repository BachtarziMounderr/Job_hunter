"""The source-independent job contract. Unknown facts remain explicit."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class RemoteType(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class JobStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"


class Job(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid", frozen=True)

    source_name: str = Field(min_length=1, max_length=100)
    external_id: str = Field(min_length=1, max_length=512)
    title: str = Field(min_length=1, max_length=512)
    company: str | None = Field(default=None, min_length=1, max_length=512)
    description: str = ""
    location: str | None = None
    country: str | None = None
    remote_type: RemoteType = RemoteType.UNKNOWN
    remote_eligibility: str = "unknown"
    employment_type: list[str] = Field(default_factory=list)
    experience_level: str = "unknown"
    required_skills: list[str] = Field(default_factory=list)
    source_tags: list[str] = Field(default_factory=list)
    published_at: AwareDatetime | None = None
    application_url: HttpUrl
    first_seen_at: AwareDatetime = Field(default_factory=utc_now)
    last_seen_at: AwareDatetime = Field(default_factory=utc_now)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: JobStatus = JobStatus.ACTIVE

    @model_validator(mode="after")
    def check_timestamps(self) -> "Job":
        if self.last_seen_at < self.first_seen_at:
            raise ValueError("last_seen_at cannot precede first_seen_at")
        return self
