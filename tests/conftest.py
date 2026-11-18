import pytest

from alembic import command
from app.cli import migration_config
from app.config import Settings
from app.database.session import create_database_engine


@pytest.fixture(autouse=True)
def isolated_profiles(tmp_path, monkeypatch):
    # Tests never depend on the user's private CVs or credentials.
    monkeypatch.setenv("PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.delenv("PROFILES_JSON", raising=False)


@pytest.fixture
def db(tmp_path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        search_scope="legacy",
        results_report_path=tmp_path / "results.html",
    )
    command.upgrade(migration_config(settings), "head")
    engine = create_database_engine(settings)
    yield engine, settings
    engine.dispose()
