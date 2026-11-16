"""Local command line interface. JSON goes to stdout and logs go to stderr."""

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

import httpx
from alembic.config import Config
from alembic.util.exc import CommandError
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from alembic import command
from app.collectors.arbeitnow import ArbeitnowCollector
from app.collectors.base import CollectionResult
from app.collectors.jobicy import JobicyCollector
from app.config import Settings
from app.database.locking import execution_lock
from app.database.models import JobRecord
from app.database.repository import list_jobs
from app.database.session import create_database_engine, transaction
from app.matching.embeddings import EmbeddingError
from app.matching.evaluation import evaluate
from app.matching.service import match_jobs, ranking_output
from app.notifications.reporting import format_run_report
from app.notifications.service import notify_matches
from app.notifications.summary import create_summary_provider
from app.notifications.telegram import TelegramClient
from app.pipeline import PipelineSource, run_pipeline
from app.processing.jobicy import normalize_jobicy
from app.processing.normalizer import normalize_arbeitnow
from app.profiles import export_profiles, import_resumes, load_profiles

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def migration_config(settings: Settings) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.attributes["settings"] = settings
    return config


class FileCollector:
    """Read a synthetic or previously captured API envelope for offline validation."""

    name = "arbeitnow"

    def __init__(self, path: Path, source_name: str = "arbeitnow") -> None:
        self.path = path
        self.name = source_name

    def collect(self) -> CollectionResult:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        field = "jobs" if self.name == "jobicy" else "data"
        if not isinstance(payload, dict) or not isinstance(payload.get(field), list):
            raise ValueError("Input must contain the source's job array")
        records = payload[field]
        return CollectionResult(
            records=[row for row in records if isinstance(row, dict)],
            pages_fetched=1,
            malformed_records=sum(not isinstance(row, dict) for row in records),
        )


def _write_json(value: object) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=True, indent=2) + "\n")


def configured_sources(settings: Settings, client: httpx.Client, args) -> list[PipelineSource]:
    name = getattr(args, "source", "all")
    if getattr(args, "input", None):
        source = "arbeitnow" if name == "all" else name
        return [
            PipelineSource(
                FileCollector(args.input, source),
                normalize_jobicy if source == "jobicy" else normalize_arbeitnow,
            )
        ]
    sources = []
    if name in {"all", "arbeitnow"}:
        sources.append(PipelineSource(ArbeitnowCollector(settings, client), normalize_arbeitnow))
    if name == "jobicy" or (name == "all" and settings.enable_jobicy):
        sources.append(PipelineSource(JobicyCollector(settings, client), normalize_jobicy))
    return sources


def main(argv: list[str] | None = None) -> int:
    """Run local setup, collection, inspection, or a real database connectivity check."""
    parser = argparse.ArgumentParser(description="AI Job Hunter: multi-profile Python matching")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="Apply Alembic migrations to the configured database")
    subparsers.add_parser("check-db", help="Execute SELECT 1 against the configured database")
    collect_parser = subparsers.add_parser("collect", help="Collect and persist Arbeitnow postings")
    collect_parser.add_argument(
        "--input", type=Path, help="Read an offline Arbeitnow JSON envelope"
    )
    collect_parser.add_argument("--source", choices=["all", "arbeitnow", "jobicy"], default="all")
    import_parser = subparsers.add_parser("import-cvs", help="Import private CV PDFs locally")
    import_parser.add_argument(
        "--manifest", type=Path, default=Path("profiles/resume_manifest.json")
    )
    export_parser = subparsers.add_parser(
        "export-profiles", help="Write a private cloud upload payload"
    )
    export_parser.add_argument("--output", type=Path, default=Path("private/profiles.json"))
    subparsers.add_parser(
        "profiles", help="Show orientation labels and skill counts without CV text"
    )
    subparsers.add_parser("doctor", help="Check setup without exposing secrets or sending messages")
    match_parser = subparsers.add_parser("match", help="Calculate explainable matches for each CV")
    match_parser.add_argument("--limit", type=int, default=20)
    match_parser.add_argument("--include-blocked", action="store_true")
    match_parser.add_argument("--output", type=Path)
    notify_parser = subparsers.add_parser(
        "notify", help="Preview Telegram messages; --send delivers"
    )
    notify_parser.add_argument("--send", action="store_true")
    run_parser = subparsers.add_parser(
        "run", help="Collect, match all CVs, and prepare/deliver Telegram"
    )
    run_parser.add_argument(
        "--notify", action="store_true", help="Send to configured Telegram chat"
    )
    run_parser.add_argument("--input", type=Path)
    run_parser.add_argument("--source", choices=["all", "arbeitnow", "jobicy"], default="all")
    demo_parser = subparsers.add_parser("demo", help="Synthetic demo with no network or secrets")
    demo_parser.add_argument("--semantic", action="store_true", help="Use the multilingual model")
    evaluation_parser = subparsers.add_parser("evaluate", help="Evaluate illustrative labels")
    evaluation_parser.add_argument("--dataset", type=Path, default=Path("examples/evaluation.json"))
    evaluation_parser.add_argument("--backend", choices=["sentence-transformer", "tfidf"])
    evaluation_parser.add_argument("--output", type=Path, default=Path("reports/evaluation.json"))
    jobs_parser = subparsers.add_parser("jobs", help="List active canonical jobs as JSON")
    jobs_parser.add_argument("--limit", type=int, default=20)
    subparsers.add_parser("stats", help="Inspect source record and canonical job counts")
    args = parser.parse_args(argv)
    engine = None
    try:
        settings = Settings(_env_file=args.env_file)
        logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("httpx2").setLevel(logging.WARNING)
        logging.getLogger("httpcore2").setLevel(logging.WARNING)
        if args.command == "evaluate":
            if args.backend:
                settings = settings.model_copy(update={"embedding_backend": args.backend})
            output = evaluate(
                settings,
                args.dataset,
                Path("examples/profiles.json"),
                Path("examples/jobicy_sample.json"),
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            _write_json({key: value for key, value in output.items() if key != "results"})
            return 0
        if args.command == "demo":
            from pydantic import SecretStr

            settings = settings.model_copy(
                update={
                    "database_url": SecretStr("sqlite:///data/demo.db"),
                    "migration_database_url": None,
                    "profiles_json": SecretStr(
                        Path("examples/profiles.json").read_text(encoding="utf-8")
                    ),
                    "embedding_backend": "sentence-transformer" if args.semantic else "tfidf",
                }
            )
            command.upgrade(migration_config(settings), "head")
            engine = create_database_engine(settings)
            with execution_lock(engine):
                report = run_pipeline(
                    settings,
                    engine,
                    [
                        PipelineSource(
                            FileCollector(Path("examples/jobicy_sample.json"), "jobicy"),
                            normalize_jobicy,
                        )
                    ],
                )
                matches = match_jobs(settings, engine)
                previews = notify_matches(settings, engine, matches)
            _write_json(
                {
                    "synthetic_demo": True,
                    "embedding_backend": settings.embedding_backend,
                    "collection": asdict(report),
                    "ranking": ranking_output(matches),
                    "delivery": asdict(previews),
                }
            )
            return report.exit_code
        if args.command == "import-cvs":
            imported = import_resumes(args.manifest, settings.profiles_dir)
            _write_json(
                {
                    "imported": [{"id": p.profile_id, "skills": len(p.skills)} for p in imported],
                    "directory": str(settings.profiles_dir),
                }
            )
            return 0
        if args.command == "export-profiles":
            if args.output.resolve().is_relative_to((PROJECT_ROOT / "private").resolve()) is False:
                raise ValueError("Export profiles under private/ to keep the payload out of Git")
            export_profiles(settings, args.output)
            logger.info("Private profiles exported; do not commit or paste their content publicly")
            return 0
        if args.command == "profiles":
            _write_json(
                [
                    {
                        "id": p.profile_id,
                        "name": p.name,
                        "skills_count": len(p.skills),
                        "resume_imported": bool(p.resume_sha256),
                    }
                    for p in load_profiles(settings)
                ]
            )
            return 0
        if args.command == "init-db":
            engine = create_database_engine(settings)
            with execution_lock(engine):
                command.upgrade(migration_config(settings), "head")
            logger.info("Database migrations applied")
            return 0
        engine = create_database_engine(settings)
        if args.command == "doctor":
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            _write_json(
                {
                    "database_connected": True,
                    "dialect": engine.dialect.name,
                    "profiles_loaded": len(load_profiles(settings)),
                    "embedding_backend": settings.embedding_backend,
                    "telegram_ready": bool(
                        settings.telegram_bot_token and settings.telegram_chat_id
                    ),
                    "qwen_ready": bool(
                        settings.llm_enabled and settings.qwen_api_key and settings.qwen_base_url
                    ),
                    "llm_provider": settings.llm_provider,
                    "llm_ready": bool(
                        settings.llm_enabled
                        and (
                            (settings.groq_api_key and settings.groq_base_url)
                            if settings.llm_provider == "groq"
                            else (settings.qwen_api_key and settings.qwen_base_url)
                        )
                    ),
                }
            )
            return 0
        if args.command == "check-db":
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            logger.info("Database connection verified (%s)", engine.dialect.name)
        elif args.command == "collect":
            with execution_lock(engine), httpx.Client() as client:
                report = run_pipeline(settings, engine, configured_sources(settings, client, args))
            _write_json(asdict(report))
            return report.exit_code
        elif args.command in {"match", "notify", "run"}:
            send = (args.command == "notify" and args.send) or (
                args.command == "run" and args.notify
            )
            if send and not (settings.telegram_bot_token and settings.telegram_chat_id):
                raise ValueError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID before sending")
            with execution_lock(engine), httpx.Client() as client:
                collection = None
                if args.command == "run":
                    collection = run_pipeline(
                        settings, engine, configured_sources(settings, client, args)
                    )
                matches = match_jobs(settings, engine)
                if args.command == "match":
                    if not 1 <= args.limit <= 1000:
                        parser.error("--limit must be between 1 and 1000")
                    output = ranking_output(
                        matches, limit=args.limit, include_blocked=args.include_blocked
                    )
                    if args.output:
                        args.output.parent.mkdir(parents=True, exist_ok=True)
                        args.output.write_text(
                            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
                        )
                    _write_json(output)
                else:
                    telegram = TelegramClient(settings, client) if send else None
                    delivery = notify_matches(
                        settings,
                        engine,
                        matches,
                        telegram=telegram,
                        provider=create_summary_provider(settings, client) if send else None,
                        dry_run=not send,
                    )
                    run_report = None
                    if collection is not None and telegram is not None:
                        run_report = telegram.send(
                            format_run_report(settings, collection, matches, delivery)
                        )
                    _write_json(
                        {
                            "collection": asdict(collection) if collection else None,
                            "matches_calculated": len(matches),
                            "delivery": asdict(delivery),
                            "dry_run": not send,
                            "run_report": asdict(run_report) if run_report is not None else None,
                        }
                    )
                    if (
                        delivery.failed
                        or delivery.uncertain
                        or (run_report is not None and run_report.status != "sent")
                    ):
                        return 2
                    if collection:
                        return collection.exit_code
        elif args.command == "jobs":
            if not 1 <= args.limit <= 1000:
                parser.error("--limit must be between 1 and 1000")
            with transaction(engine) as session:
                _write_json(list_jobs(session, limit=args.limit))
        elif args.command == "stats":
            with transaction(engine) as session:
                total = session.scalar(select(func.count()).select_from(JobRecord))
                canonical = session.scalar(
                    select(func.count())
                    .select_from(JobRecord)
                    .where(
                        JobRecord.status == "active",
                        JobRecord.duplicate_of_id.is_(None),
                    )
                )
            _write_json({"source_records": total, "active_canonical_jobs": canonical})
    except ValidationError as exc:
        # ValidationError's default repr can expose an invalid credential value.
        fields = [".".join(map(str, error["loc"])) for error in exc.errors(include_input=False)]
        logger.error("Validation failed for: %s", ", ".join(fields))
        return 1
    except (
        SQLAlchemyError,
        CommandError,
        OSError,
        ValueError,
        ImportError,
        EmbeddingError,
        RuntimeError,
    ) as exc:
        logger.error(
            "Operation failed (%s). Check configuration, run init-db, "
            "and see README troubleshooting.",
            type(exc).__name__,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    return 0
