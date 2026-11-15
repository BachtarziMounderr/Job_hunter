"""Deterministic weighted scoring, independent from embedding and I/O providers."""

import math

from app.config import ScoreWeights
from app.matching.classifiers import (
    classify_role,
    education_compatibility,
    experience_compatibility,
    role_compatible,
)
from app.matching.geography import geographic_eligibility
from app.matching.skills import skill_compatibility
from app.schemas.job import Job
from app.schemas.match import MatchResult
from app.schemas.profile import CandidateProfile


def score_job(
    job: Job,
    profile: CandidateProfile,
    cosine_similarity: float,
    weights: ScoreWeights,
) -> MatchResult:
    """Produce explainable sub-scores; hard constraints cannot be offset by similarity."""
    if not math.isfinite(cosine_similarity):
        raise ValueError("Cosine similarity must be finite")
    semantic = max(0.0, min(1.0, cosine_similarity)) * 100
    skills, matched, missing = skill_compatibility(
        profile.skills, job.title + " " + job.description
    )
    experience, experience_reason, too_senior = experience_compatibility(job, profile)
    education, education_reason = education_compatibility(job, profile)
    geography = geographic_eligibility(job, profile)
    role_ok = role_compatible(job, profile)
    components = dict(
        semantic=semantic,
        skills=skills,
        experience=experience,
        education=education,
        location=geography.score,
    )
    total = sum(value * weights.model_dump()[key] for key, value in components.items())
    reasons = [geography.reason, experience_reason, education_reason]
    if matched:
        reasons.append("Compétences communes : " + ", ".join(matched))
    incompatibilities = []
    if geography.status != "eligible":
        incompatibilities.append(geography.reason)
    if too_senior:
        incompatibilities.append("Poste trop senior pour les objectifs configurés")
    if not role_ok:
        incompatibilities.append("Famille de métier hors des rôles cibles du profil")
    if missing:
        incompatibilities.append(
            "Compétences observées dans l'offre non attestées par ce CV : " + ", ".join(missing)
        )
    return MatchResult(
        total_score=round(total, 2),
        semantic_score=round(semantic, 2),
        skills_score=round(skills, 2),
        experience_score=experience,
        education_score=education,
        location_score=geography.score,
        geographic_status=geography.status,
        eligible_for_notification=geography.status == "eligible" and not too_senior and role_ok,
        matched_skills=matched,
        missing_skills=missing,
        matching_reasons=reasons,
        incompatibility_reasons=incompatibilities,
        role=classify_role(job.title),
    )
