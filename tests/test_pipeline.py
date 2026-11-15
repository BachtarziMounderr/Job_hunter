import json
from dataclasses import dataclass

from sqlalchemy import func, select

from app.cli import FileCollector, main
from app.collectors.base import CollectionResult
from app.database.models import JobRecord
from app.database.session import transaction
from app.pipeline import PipelineSource, run_pipeline
from app.processing.normalizer import normalize_arbeitnow
from tests.test_processing import posting


@dataclass
class StubCollector:
    name: str = "arbeitnow"
    fail: bool = False

    def collect(self):
        if self.fail:
            raise RuntimeError("Simulated connector failure")
        return CollectionResult(records=[posting(), {"slug": "malformed"}], pages_fetched=1)


def test_connector_failure_does_not_stop_next_source(db):
    engine, settings = db
    report = run_pipeline(
        settings,
        engine,
        [
            PipelineSource(StubCollector(name="broken", fail=True), normalize_arbeitnow),
            PipelineSource(StubCollector(), normalize_arbeitnow),
        ],
    )
    assert report.sources_failed == 1
    assert report.sources_completed == 1
    assert report.invalid_records == 1
    assert report.inserted == 1
    assert report.exit_code == 2
    with transaction(engine) as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1


def test_offline_pipeline_is_idempotent(db):
    from pathlib import Path

    engine, settings = db
    source = PipelineSource(
        FileCollector(Path("examples/arbeitnow_sample.json")), normalize_arbeitnow
    )
    assert run_pipeline(settings, engine, [source]).inserted == 1
    report = run_pipeline(settings, engine, [source])
    assert report.inserted == 0
    assert report.updated == 1
    assert report.exit_code == 0


def test_cli_local_workflow(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    assert main(["init-db"]) == 0
    assert main(["check-db"]) == 0
    assert main(["collect", "--input", "examples/arbeitnow_sample.json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["inserted"] == 1
    assert main(["jobs", "--limit", "1"]) == 0
    jobs = json.loads(capsys.readouterr().out)
    assert "synthetic" in jobs[0]["title"]
    assert jobs[0]["remote_eligibility"] == "unknown"
    assert main(["stats"]) == 0
    assert json.loads(capsys.readouterr().out)["active_canonical_jobs"] == 1


def test_cli_does_not_echo_invalid_credentials(monkeypatch, caplog):
    monkeypatch.setenv("DATABASE_URL", "not-a-url-with-private-password")
    assert main(["check-db"]) == 1
    assert "private-password" not in caplog.text


def test_cli_missing_migrations_returns_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'empty.db'}")
    assert main(["collect", "--input", "examples/arbeitnow_sample.json"]) == 1


def test_database_failure_rolls_back_source_and_next_source_continues(db, monkeypatch):
    import app.pipeline as pipeline

    engine, settings = db
    original_save = pipeline.save_jobs
    calls = 0

    def failing_once(session, jobs):
        from sqlalchemy.exc import IntegrityError

        nonlocal calls
        calls += 1
        result = original_save(session, jobs)
        if calls == 1:
            raise IntegrityError("simulated", {}, RuntimeError("simulated conflict"))
        return result

    monkeypatch.setattr(pipeline, "save_jobs", failing_once)
    report = run_pipeline(
        settings,
        engine,
        [
            PipelineSource(StubCollector(), normalize_arbeitnow),
            PipelineSource(StubCollector(), normalize_arbeitnow),
        ],
    )
    assert report.sources_failed == 1
    assert report.sources_completed == 1
    assert report.inserted == 1
    assert report.updated == 0  # the failed source's insertion was rolled back


def test_partial_page_failure_persists_jobs_without_success_marker(db):
    from app.database.models import JobSource

    class PartialCollector:
        name = "arbeitnow"

        def collect(self):
            return CollectionResult(
                records=[posting()],
                pages_fetched=1,
                error="API returned HTTP 503",
            )

    engine, settings = db
    report = run_pipeline(
        settings,
        engine,
        [
            PipelineSource(PartialCollector(), normalize_arbeitnow),
        ],
    )
    assert report.inserted == 1
    assert report.sources_failed == 1
    assert report.exit_code == 2
    with transaction(engine) as session:
        assert session.scalar(select(JobSource)).last_success_at is None
