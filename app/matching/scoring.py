"""Deterministic weighted scoring, independent from embedding and I/O providers."""

import math
from datetime import UTC, datetime, timedelta

from app.config import ScoreWeights
from app.matching.classifiers import (
    classify_role,
    education_compatibility,
    experience_compatibility,
    role_compatible,
)
from app.matching.geography import geographic_eligibility
from app.matching.local_policy import (
    local_experience,
    local_geography,
    local_role,
    required_skill_text,
)
from app.matching.skills import skill_compatibility
from app.schemas.job import Job
from app.schemas.match import MatchResult
from app.schemas.profile import CandidateProfile


def score_job(
    job: Job,
    profile: CandidateProfile,
    cosine_similarity: float,
    weights: ScoreWeights,
    *,
    local_only: bool = False,
    age_limit_days: int = 45,
) -> MatchResult:
    """Produce explainable sub-scores; hard constraints cannot be offset by similarity."""
    if not math.isfinite(cosine_similarity):
        raise ValueError("Cosine similarity must be finite")
    semantic = max(0.0, min(1.0, cosine_similarity)) * 100
    skill_text = job.title + " " + job.description
    explicit_requirements = False
    if local_only:
        skill_text, explicit_requirements = required_skill_text(job.description)
    skills, matched, missing = skill_compatibility(profile.skills, skill_text)
    experience, experience_reason, too_senior = experience_compatibility(job, profile)
    education, education_reason = education_compatibility(job, profile)
    geography = geographic_eligibility(job, profile)
    role_ok = role_compatible(job, profile)
    review_reasons, exclusions = [], []
    if local_only:
        geography = local_geography(job)
        experience, too_senior, review_reasons = local_experience(job, profile)
        experience_reason = f"Compatibilité d'expérience : {experience:g}/100"
        if too_senior:
            experience_reason += " ; exigence supérieure au profil"
        role_ok, role_uncertain = local_role(job, profile)
        if role_uncertain:
            review_reasons.append("Métier déduit de la description : intitulé à vérifier")
        if not job.description_complete:
            review_reasons.append("Alerte partielle : description complète non disponible")
        if job.published_at and job.published_at < datetime.now(UTC) - timedelta(
            days=age_limit_days
        ):
            review_reasons.append(
                "Publication ancienne mais offre encore listée : activité du recrutement à vérifier"
            )
        if not explicit_requirements:
            review_reasons.append("Compétences obligatoires non distinguées des mentions générales")
        if geography.status != "eligible":
            exclusions.append("geography")
        if not role_ok:
            exclusions.append("role")
        if too_senior:
            exclusions.append("experience")
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
        eligible_for_notification=geography.status == "eligible"
        and not too_senior
        and role_ok
        and not review_reasons,
        matched_skills=matched,
        missing_skills=missing,
        matching_reasons=reasons,
        incompatibility_reasons=incompatibilities,
        role=classify_role(job.title),
        review_reasons=review_reasons,
        exclusion_codes=exclusions,
    )
