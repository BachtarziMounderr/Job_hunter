"""Explainable Algeria-only decisions, with explicit review instead of silent uncertainty."""

import re

from app.matching.classifiers import classify_role, classify_seniority, role_compatible
from app.matching.geography import GeographyDecision
from app.matching.skills import extract_skills, fold_text
from app.processing.locality import algeria_status
from app.schemas.job import Job
from app.schemas.profile import CandidateProfile


def local_geography(job: Job) -> GeographyDecision:
    state = algeria_status(job)
    return GeographyDecision(
        state,
        {"eligible": 100, "unknown": 50, "ineligible": 0}[state],
        {
            "eligible": "Poste explicitement situé en Algérie",
            "unknown": "Localisation algérienne à confirmer",
            "ineligible": "Poste situé hors d'Algérie",
        }[state],
    )


def local_role(job: Job, profile: CandidateProfile) -> tuple[bool, bool]:
    if role_compatible(job, profile):
        return True, False
    if classify_role(job.title) != "other":
        return False, False
    title = fold_text(job.title)
    if re.search(
        r"\b(sales|commercial|marketing|recruteur|recruiter|vente|financ|comptable)\b", title
    ):
        return False, False
    technical = re.search(
        r"ingenieur|engineer|develop|programmeur|analyst|informati|برمج|بيانات", title
    )
    shared = set(extract_skills(job.description)) & set(profile.skills)
    return bool(technical and len(shared) >= 2), bool(technical and len(shared) >= 2)


def local_experience(job: Job, profile: CandidateProfile) -> tuple[float, bool, list[str]]:
    requirements, explicit = required_skill_text(job.description)
    experience_job = job.model_copy(update={"description": requirements}) if explicit else job
    level, minimum = classify_seniority(experience_job)
    targets = set(profile.target_seniority)
    allowed = level in targets or (level == "junior" and "entry-level" in targets)
    review = []
    score = {"internship": 100, "junior": 100, "mid": 65, "senior": 0, "unknown": 50}[level]
    if minimum is not None:
        gap = max(0, minimum - profile.freelance_experience_years)
        score = max(0, 100 - 25 * gap)
        if gap >= 3:
            return score, True, review
        if gap > 0:
            review.append("Expérience demandée légèrement supérieure au profil")
        if level == "senior" and gap <= 0 and not allowed:
            review.append("Intitulé senior en contradiction avec l'expérience annoncée")
        return score, False, review
    if level == "unknown":
        review.append("Niveau d'expérience non précisé")
    elif not allowed:
        if level == "senior":
            return score, True, review
        review.append("Niveau à vérifier par rapport aux objectifs du profil")
    return float(score), False, review


def required_skill_text(description: str) -> tuple[str, bool]:
    required = False
    lines = []
    for line in description.splitlines():
        value = fold_text(line)
        header = re.search(
            r"^(requirements|qualifications|what you.bring|your profile|profil recherche|"
            r"votre profil|competences requises|must.have)",
            value,
        )
        if header:
            required = True
            if ":" in line and (inline := line.split(":", 1)[1].strip()):
                lines.append(inline)
            continue
        if re.search(
            r"^(nice.to.have|bonus|atouts?|avantages|benefits|we offer|what we offer|"
            r"responsabilit|missions|about us)",
            value,
        ):
            required = False
            continue
        if required and not re.search(
            r"nice.to.have|would be a plus|un atout|apprecie|souhaite|facultatif|bonus", value
        ):
            lines.append(line)
    return ("\n".join(lines), True) if lines else (description, False)
