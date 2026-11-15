"""Private PDF ingestion and portable multi-profile configuration."""

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader

from app.config import Settings
from app.matching.skills import extract_skills
from app.schemas.profile import CandidateProfile, load_profile


class ResumeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: Path
    profile_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    label: str
    target_roles: list[str]


class ResumeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_profile: Path
    resumes: list[ResumeSpec] = Field(min_length=1)


def sanitize_resume(text: str) -> str:
    """Remove contact/header lines; keep only professional content starting at Profile."""
    text = text.replace("\x00", "").replace("\u00ad", "")
    heading = re.search(r"(?im)^\s*(?:profile|profil|summary)\s*$", text)
    if heading:
        text = text[heading.end() :]
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email removed]", text)
    text = re.sub(r"(?:https?://|www\.)\S+", "[link removed]", text)
    text = re.sub(r"(?<!\w)\+?\d[\d ()-]{8,}\d", "[phone removed]", text)
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()[:20000]


def import_resumes(manifest_path: Path, output_dir: Path) -> list[CandidateProfile]:
    """Extract three orientations independently; no API or LLM reads the PDFs."""
    manifest = ResumeManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    base = load_profile(manifest.base_profile)
    profiles = []
    for spec in manifest.resumes:
        reader = PdfReader(spec.path)
        if reader.is_encrypted:
            raise ValueError("Encrypted resume: decrypt it locally before importing")
        text = sanitize_resume("\n".join(page.extract_text() or "" for page in reader.pages))
        if len(text) < 150:
            raise ValueError("Resume has no usable text; OCR is required before importing")
        profile = CandidateProfile.model_validate(
            base.model_dump()
            | {
                "name": spec.label,
                "profile_id": spec.profile_id,
                "target_roles": spec.target_roles,
                "skills": extract_skills(text),
                "resume_text": text,
                "resume_sha256": hashlib.sha256(spec.path.read_bytes()).hexdigest(),
            }
        )
        profiles.append(profile)
    output_dir.mkdir(parents=True, exist_ok=True)
    for profile in profiles:
        (output_dir / f"{profile.profile_id}.json").write_text(
            profile.model_dump_json(indent=2),
            encoding="utf-8",
        )
    return profiles


def load_profiles(settings: Settings) -> list[CandidateProfile]:
    """Prefer injected private profiles, then imported JSONs, then the public example."""
    if settings.profiles_json:
        raw = json.loads(settings.profiles_json.get_secret_value())
        if not isinstance(raw, list):
            raise ValueError("PROFILES_JSON must contain a JSON array")
        profiles = [CandidateProfile.model_validate(item) for item in raw]
    else:
        paths = sorted(settings.profiles_dir.glob("*.json"))
        profiles = (
            [load_profile(path) for path in paths]
            if paths
            else [load_profile(settings.profile_path)]
        )
    profiles = [profile for profile in profiles if profile.enabled]
    keys = [profile.profile_id or profile.name for profile in profiles]
    if (
        not profiles
        or len(set(keys)) != len(keys)
        or len({p.name for p in profiles}) != len(profiles)
    ):
        raise ValueError("Provide at least one enabled profile with unique identifiers and names")
    return profiles


def export_profiles(settings: Settings, path: Path) -> None:
    """Create a gitignored upload payload; never print private profile data to logs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([p.model_dump() for p in load_profiles(settings)], ensure_ascii=False),
        encoding="utf-8",
    )
