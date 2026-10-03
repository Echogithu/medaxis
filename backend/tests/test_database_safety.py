"""测试数据库目标的安全校验。"""

import pytest
import subprocess
import sys
from pathlib import Path

import tests.database_safety as database_safety
from tests.database_safety import (
    resolve_test_database,
    validate_demo_database,
    validate_demo_environment,
    repository_migration_head,
)


def env_for(url: str) -> dict[str, str]:
    return {
        "TEST_DATABASE_URL": url,
        "DATABASE_URL": url,
        "ASYNC_DATABASE_URL": url,
    }


def test_allows_explicit_in_memory_sqlite_for_isolated_checks() -> None:
    url = "sqlite+aiosqlite:///:memory:"

    target = resolve_test_database(env_for(url))

    assert target.backend == "sqlite"
    assert target.database == ":memory:"


def test_rejects_missing_database_configuration() -> None:
    with pytest.raises(ValueError, match="TEST_DATABASE_URL"):
        resolve_test_database({})


def test_rejects_different_database_targets_without_disclosing_urls() -> None:
    env = env_for("postgresql+asyncpg://test:secret@localhost/medaxis_test_a")
    env["DATABASE_URL"] = "postgresql+asyncpg://test:secret@localhost/medaxis_test_b"

    with pytest.raises(ValueError, match="must identify the same") as error:
        resolve_test_database(env)

    assert "secret" not in str(error.value)


def test_rejects_file_sqlite_because_test_teardown_drops_all_tables() -> None:
    url = "sqlite+aiosqlite:///./medaxis.db"

    with pytest.raises(ValueError, match="in-memory SQLite"):
        resolve_test_database(env_for(url))


def test_rejects_postgres_database_without_test_name_and_explicit_opt_in() -> None:
    env = env_for("postgresql+asyncpg://test:secret@localhost/medaxis")

    with pytest.raises(ValueError, match="medaxis_test_ prefix"):
        resolve_test_database(env | {"MEDAXIS_ALLOW_DESTRUCTIVE_TEST_DB": "1"})

    isolated = env_for("postgresql+asyncpg://test:secret@localhost/medaxis_test_run")
    with pytest.raises(ValueError, match="MEDAXIS_ALLOW_DESTRUCTIVE_TEST_DB"):
        resolve_test_database(isolated)


def test_allows_named_postgres_test_database_only_with_explicit_opt_in() -> None:
    url = "postgresql+asyncpg://test:secret@localhost:5433/medaxis_test_run"

    target = resolve_test_database(
        env_for(url) | {"MEDAXIS_ALLOW_DESTRUCTIVE_TEST_DB": "1"}
    )

    assert target.backend == "postgresql"
    assert target.database == "medaxis_test_run"
    assert target.host == "localhost"
    assert "secret" not in repr(target)


def test_demo_e2e_requires_loopback_services_and_isolated_demo_database() -> None:
    target = validate_demo_environment(
        "postgresql+asyncpg://test:secret@localhost:5433/medaxis_demo_e2e_run",
        "http://127.0.0.1:8012/api/v1",
        "http://localhost:3002",
    )

    assert target.database == "medaxis_demo_e2e_run"


def test_demo_redis_mode_defaults_to_the_local_substitute() -> None:
    assert database_safety.resolve_demo_redis_mode({}, "") == "substitute"


def test_demo_redis_mode_accepts_only_loopback_real_redis() -> None:
    assert database_safety.resolve_demo_redis_mode(
        {"DEMO_REDIS_LOCK_MODE": "redis"}, "redis://127.0.0.1:6379/0"
    ) == "redis"


def test_demo_redis_mode_rejects_remote_real_redis() -> None:
    with pytest.raises(ValueError, match="loopback Redis"):
        database_safety.resolve_demo_redis_mode(
            {"DEMO_REDIS_LOCK_MODE": "redis"}, "redis://cache.example:6379/0"
        )


def test_demo_redis_mode_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="DEMO_REDIS_LOCK_MODE"):
        database_safety.resolve_demo_redis_mode(
            {"DEMO_REDIS_LOCK_MODE": "fake"}, "redis://127.0.0.1:6379/0"
        )


@pytest.mark.parametrize(
    "url",
    [
        "mysql://test:secret@localhost/medaxis_demo_e2e_run",
        "postgresql://test:secret@localhost/medaxis_demo_e2e_run",
        "postgresql+psycopg2://test:secret@localhost/medaxis_demo_e2e_run",
        "postgresql+asyncpg://test:secret@localhost/medaxis",
        "postgresql+asyncpg://test:secret@remote.example/medaxis_demo_e2e_run",
    ],
)
def test_demo_server_rejects_non_postgres_or_non_loopback_databases(url: str) -> None:
    with pytest.raises(ValueError):
        validate_demo_database(url)


def test_repository_migration_head_is_read_from_alembic_source() -> None:
    from pathlib import Path

    alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"

    assert repository_migration_head(alembic_ini)


def test_synthetic_demo_server_rejects_import_startup_mode() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import tests.patient_demo_server"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "python -m tests.patient_demo_server" in result.stderr


def test_synthetic_demo_server_rejects_direct_script_startup_mode() -> None:
    script = Path(__file__).with_name("patient_demo_server.py")
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "python -m tests.patient_demo_server" in result.stderr


@pytest.mark.parametrize(
    ("database_url", "api_url", "web_url"),
    [
        (
            "postgresql+asyncpg://test:secret@localhost:5433/medaxis",
            "http://127.0.0.1:8012/api/v1",
            "http://127.0.0.1:3002",
        ),
        (
            "postgresql+asyncpg://test:secret@localhost:5433/medaxis_demo_e2e_run",
            "https://remote.example/api/v1",
            "http://127.0.0.1:3002",
        ),
        (
            "postgresql+asyncpg://test:secret@localhost:5433/medaxis_demo_e2e_run",
            "http://127.0.0.1:8012/api/v1",
            "http://remote.example",
        ),
    ],
)
def test_demo_e2e_rejects_non_isolated_or_remote_targets(
    database_url: str, api_url: str, web_url: str
) -> None:
    with pytest.raises(ValueError):
        validate_demo_environment(database_url, api_url, web_url)
