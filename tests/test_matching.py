from pathlib import Path

import numpy as np
import pytest

from app.config import ScoreWeights
from app.matching.classifiers import classify_seniority
from app.matching.embeddings import cosine_matrix
from app.matching.geography import geographic_eligibility
from app.matching.scoring import score_job
from app.matching.skills import extract_skills
from app.processing.normalizer import normalize_arbeitnow
from app.schemas.job import Job
from app.schemas.profile import load_profile
from tests.test_processing import posting


def candidate():
    return load_profile(Path("profiles/default.json"))


def job_for_scope(scope="Worldwide", **changes):
    job = normalize_arbeitnow(
        posting(
            title="Junior Python Developer",
            description="Python SQL FastAPI. Master required.",
        )
    )
    return Job.model_validate(job.model_dump() | {"remote_eligibility": scope} | changes)


@pytest.mark.parametrize(
    "scope,expected",
    [
        ("Worldwide", "eligible"),
        ("EMEA", "eligible"),
        ("Africa", "eligible"),
        ("Algeria", "eligible"),
        ("Europe", "ineligible"),
        ("EU only", "ineligible"),
        ("USA, Canada", "ineligible"),
        ("Worldwide except Algeria", "ineligible"),
        ("Worldwide excluding Africa", "ineligible"),
        ("unknown", "unknown"),
        ("Flexible", "unknown"),
    ],
)
def test_geographic_scopes(scope, expected):
    assert geographic_eligibility(job_for_scope(scope), candidate()).status == expected


def test_description_residence_restriction_overrides_worldwide():
    job = job_for_scope(description="Python. Candidates must be based in France.")
    assert geographic_eligibility(job, candidate()).status == "ineligible"


def test_work_authorization_is_never_invented():
    job = job_for_scope(description="Must be authorized to work in France.")
    assert geographic_eligibility(job, candidate()).status == "unknown"


def test_local_algerian_jobs_are_eligible():
    job = job_for_scope("unknown", location="Constantine, Algeria", remote_type="onsite")
    assert geographic_eligibility(job, candidate()).status == "eligible"


def test_skill_boundaries_aliases_and_accents():
    skills = extract_skills("JavaScript, FastAPI, Py Torch, apprentissage profond, C++")
    assert "JavaScript" in skills and "Java" not in skills
    assert "C++" in skills and "C" not in skills
    assert "PyTorch" in skills and "Deep Learning" in skills


def test_cosine_is_math_not_probability():
    scores = cosine_matrix(np.array([[1.0, 0.0], [0.0, 0.0]]), np.array([[1.0, 0.0], [-1.0, 0.0]]))
    np.testing.assert_allclose(scores, [[1, -1], [0, 0]])
    with pytest.raises(ValueError):
        cosine_matrix(np.array([[np.nan]]), np.array([[1.0]]))


def test_scoring_formula_and_hard_geographic_constraint():
    result = score_job(job_for_scope(), candidate(), 0.8, ScoreWeights())
    assert result.total_score == 93
    assert result.eligible_for_notification
    blocked = score_job(job_for_scope("US only"), candidate(), 1.0, ScoreWeights())
    assert not blocked.eligible_for_notification
    assert blocked.geographic_status == "ineligible"


def test_senior_role_does_not_pass_even_with_perfect_semantic_similarity():
    result = score_job(
        job_for_scope(title="Senior Python Developer"), candidate(), 1, ScoreWeights()
    )
    assert not result.eligible_for_notification
    assert result.experience_score == 0


def test_experience_detects_requirements_not_company_age():
    assert classify_seniority(job_for_scope(description="Founded 20 years ago. Python."))[1] is None
    assert classify_seniority(job_for_scope(description="Minimum 5+ years of experience."))[1] == 5
    assert classify_seniority(job_for_scope(description="3 ans d'expérience en Python."))[1] == 3
