import json
import shutil
from pathlib import Path

from app.cli import main
from app.config import Settings
from app.matching.evaluation import evaluate


def test_demo_runs_without_cv_files_credentials_or_network(monkeypatch, tmp_path, capsys):
    examples = Path("examples").resolve()
    shutil.copytree(examples, tmp_path / "examples")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EMBEDDING_BACKEND", "tfidf")
    assert main(["demo"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["synthetic_demo"]
    assert len(output["ranking"]) >= 3
    assert output["delivery"]["sent"] == 0
    assert all("synthetic" in item["title"].lower() for item in output["ranking"])


def test_evaluation_reports_labels_and_confusion_matrix():
    output = evaluate(
        Settings(_env_file=None, embedding_backend="tfidf"),
        Path("examples/evaluation.json"),
        Path("examples/profiles.json"),
        Path("examples/jobicy_sample.json"),
    )
    assert output["examples"] == 22
    assert len(output["confusion_matrix_tn_fp_fn_tp"]) == 4
    assert "Illustrative" in output["label_status"]
