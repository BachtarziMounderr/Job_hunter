"""Reproducible evaluation harness; toy labels are not a scientific benchmark."""

import json
from pathlib import Path

from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

from app.config import Settings
from app.matching.embeddings import cosine_matrix, create_embedder
from app.matching.scoring import score_job
from app.matching.service import job_text, profile_text
from app.processing.jobicy import normalize_jobicy
from app.schemas.profile import CandidateProfile


def evaluate(settings: Settings, dataset: Path, profiles_path: Path, jobs_path: Path) -> dict:
    """Measure notification classification against explicit, inspectable binary labels."""
    data = json.loads(dataset.read_text(encoding="utf-8"))
    profiles = [
        CandidateProfile.model_validate(p)
        for p in json.loads(profiles_path.read_text(encoding="utf-8"))
    ]
    jobs = [
        normalize_jobicy(row) for row in json.loads(jobs_path.read_text(encoding="utf-8"))["jobs"]
    ]
    embedder = create_embedder(settings)
    vectors = embedder.encode([profile_text(p) for p in profiles] + [job_text(job) for job in jobs])
    scores = cosine_matrix(vectors[: len(profiles)], vectors[len(profiles) :])
    lookup = {}
    for i, profile in enumerate(profiles):
        for j, job in enumerate(jobs):
            lookup[(profile.profile_id, int(job.external_id))] = score_job(
                job,
                profile,
                float(scores[i, j]),
                settings.score_weights,
            )
    truth, predicted, details = [], [], []
    for example in data["examples"]:
        result = lookup[(example["profile_id"], example["job_id"])]
        prediction = (
            result.eligible_for_notification and result.total_score >= settings.minimum_match_score
        )
        truth.append(example["relevant"])
        predicted.append(prediction)
        details.append(example | {"predicted": prediction, "score": result.total_score})
    precision, recall, f1, _ = precision_recall_fscore_support(
        truth, predicted, average="binary", zero_division=0
    )
    return {
        "examples": len(truth),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "confusion_matrix_tn_fp_fn_tp": confusion_matrix(truth, predicted, labels=[False, True])
        .ravel()
        .tolist(),
        "embedding_version": embedder.version,
        "threshold": settings.minimum_match_score,
        "label_status": data["label_status"],
        "results": details,
    }
