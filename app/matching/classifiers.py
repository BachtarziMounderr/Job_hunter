"""Readable rule-based seniority, role and education compatibility."""

import re

from app.matching.skills import fold_text
from app.schemas.job import Job
from app.schemas.profile import CandidateProfile


def classify_role(title: str) -> str:
    value = fold_text(title)
    if re.search(
        r"\b(sales|marketing|recruiter|recruteur|customer success|account executive)\b", value
    ):
        if not re.search(r"\bdata (scientist|analyst|engineer)\b", value):
            return "other"
    if re.search(r"full[ -]?stack", value):
        return "full_stack"
    if re.search(
        r"\b(ai|ia|ml|nlp|machine learning|deep learning|computer vision|"
        r"intelligence artificielle|data scientist)\b",
        value,
    ):
        return "ai_ml"
    if re.search(r"\b(data|donnees|business intelligence|analyste de donnees)\b", value):
        return "data"
    if re.search(r"\b(front[ -]?end|react|vue|angular)\b", value):
        return "frontend"
    if re.search(
        r"\b(back[ -]?end|python|fastapi|software|logiciel|developpeur|developer|web)\b", value
    ):
        return "backend"
    return "other"


def role_compatible(job: Job, profile: CandidateProfile) -> bool:
    role = classify_role(job.title)
    targets = {classify_role(title) for title in profile.target_roles}
    return role != "other" and (role in targets or (role == "backend" and "full_stack" in targets))


def classify_seniority(job: Job) -> tuple[str, int | None]:
    title = fold_text(job.title + " " + job.experience_level)
    if re.search(
        r"\b(senior|sr\.?|lead|principal|staff|director|head|manager|expert|confirme|directeur)\b",
        title,
    ):
        level = "senior"
    elif re.search(r"\b(intern|internship|stagiaire|stage|apprentice|alternance)\b", title):
        level = "internship"
    elif re.search(r"\b(junior|jr\.?|entry[ -]?level|graduate|debutant)\b", title):
        level = "junior"
    elif re.search(r"\b(mid|midlevel|intermediate|intermediaire)\b", title):
        level = "mid"
    else:
        level = "unknown"
    text = fold_text(job.description)
    requirements = re.findall(
        r"\b(\d{1,2})(?:\s*[-–]\s*\d{1,2})?\s*\+?\s*(?:years?|ans?|annees?)"
        r"(?:\s+of)?\s+(?:professional\s+|relevant\s+|commercial\s+|d[' ]?)?"
        r"(?:experience|experiences)",
        text,
    )
    # Benefits/company age do not match the experience-specific expression.
    minimum = max(map(int, requirements)) if requirements else None
    return level, minimum


def experience_compatibility(job: Job, profile: CandidateProfile) -> tuple[float, str, bool]:
    level, minimum = classify_seniority(job)
    score = {"internship": 100, "junior": 100, "mid": 45, "senior": 0, "unknown": 50}[level]
    hard = level == "senior"
    if minimum is not None:
        gap = max(0, minimum - profile.freelance_experience_years)
        score = min(score if level != "unknown" else 100, max(0, 100 - 30 * gap))
        hard = hard or minimum >= max(5, profile.freelance_experience_years + 3)
    reason = f"Séniorité détectée : {level}"
    if minimum is not None:
        reason += (
            f" ; minimum observé : {minimum} ans, "
            f"profil : {profile.freelance_experience_years:g} ans freelance"
        )
    return float(score), reason, hard


def education_compatibility(job: Job, profile: CandidateProfile) -> tuple[float, str]:
    value = fold_text(job.description)
    required = None
    if re.search(r"\b(ph\.?d|doctorat|doctorate)\b", value):
        required = 3
    elif re.search(r"\b(master|msc|bac\s*\+\s*5)\b", value):
        required = 2
    elif re.search(r"\b(bachelor|licence|bsc|bac\s*\+\s*3)\b", value):
        required = 1
    if required is None:
        return 50, "Niveau de diplôme non indiqué"
    available = {"unknown": 0, "bachelor": 1, "master": 2, "doctorate": 3}.get(
        profile.education_level, 0
    )
    return (100 if available >= required else 25), "Comparaison des niveaux de diplôme détectés"
