"""Prevent destructive test fixtures from targeting application databases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url


DATABASE_ENV_KEYS = ("TEST_DATABASE_URL", "DATABASE_URL", "ASYNC_DATABASE_URL")
ALLOW_DESTRUCTIVE_TEST_DB = "MEDAXIS_ALLOW_DESTRUCTIVE_TEST_DB"
POSTGRES_TEST_DATABASE_PREFIX = "medaxis_test_"


@dataclass(frozen=True)
class TestDatabaseTarget:
    """Sanitized database identity safe to show in test output."""

    backend: str
    database: str
    host: str | None = None


def _identity(url: str) -> tuple[object, ...]:
    parsed = make_url(url)
    return (
        parsed.drivername,
        parsed.username,
        parsed.password,
        parsed.host,
        parsed.port,
        parsed.database,
        tuple(sorted(parsed.query.items())),
    )


def resolve_test_database(environment: Mapping[str, str]) -> TestDatabaseTarget:
    """Validate all database settings before a fixture creates or drops tables."""
    missing = [key for key in DATABASE_ENV_KEYS if not environment.get(key, "").strip()]
    if missing:
        raise ValueError(
            "Set TEST_DATABASE_URL, DATABASE_URL, and ASYNC_DATABASE_URL to the "
            "same isolated test database before running database-backed tests."
        )

    urls = [environment[key].strip() for key in DATABASE_ENV_KEYS]
    try:
        identities = [_identity(url) for url in urls]
    except Exception as exc:
        raise ValueError("A test database URL is invalid; no database was opened.") from exc
    if any(identity != identities[0] for identity in identities[1:]):
        raise ValueError(
            "TEST_DATABASE_URL, DATABASE_URL, and ASYNC_DATABASE_URL must identify "
            "the same test database."
        )

    parsed = make_url(urls[0])
    if parsed.drivername.startswith("sqlite"):
        if parsed.database != ":memory:":
            raise ValueError(
                "Only in-memory SQLite is allowed; database-backed MedAxis tests "
                "must use an isolated PostgreSQL database."
            )
        return TestDatabaseTarget(backend="sqlite", database=parsed.database)

    if parsed.drivername != "postgresql+asyncpg":
        raise ValueError(
            "PostgreSQL test databases must use the postgresql+asyncpg driver."
        )
    if not (parsed.database or "").startswith(POSTGRES_TEST_DATABASE_PREFIX):
        raise ValueError(
            f"PostgreSQL test database names must use the {POSTGRES_TEST_DATABASE_PREFIX} prefix."
        )
    if environment.get(ALLOW_DESTRUCTIVE_TEST_DB) != "1":
        raise ValueError(
            f"Set {ALLOW_DESTRUCTIVE_TEST_DB}=1 to acknowledge that pytest drops tables "
            "in the named isolated test database."
        )

    return TestDatabaseTarget(
        backend="postgresql",
        database=parsed.database or "",
        host=parsed.host,
    )


def validate_demo_environment(
    database_url: str,
    api_url: str,
    web_url: str,
) -> TestDatabaseTarget:
    """Keep synthetic browser E2E writes inside local demo services and a demo DB."""
    try:
        parsed_api = urlsplit(api_url)
        parsed_web = urlsplit(web_url)
    except Exception as exc:
        raise ValueError("The synthetic demo target configuration is invalid.") from exc

    target = validate_demo_database(database_url)

    for label, parsed in (("API", parsed_api), ("web", parsed_web)):
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(f"Synthetic browser E2E {label} URL must target loopback HTTP.")

    return target


def validate_demo_database(database_url: str) -> TestDatabaseTarget:
    """Require the synthetic demo server's own database write boundary."""
    try:
        database = make_url(database_url)
    except Exception as exc:
        raise ValueError("The synthetic demo database URL is invalid.") from exc

    if (
        database.drivername != "postgresql+asyncpg"
        or not (database.database or "").startswith("medaxis_demo_e2e_")
        or database.host not in {"127.0.0.1", "localhost"}
    ):
        raise ValueError(
            "Synthetic demo server requires a loopback PostgreSQL database named "
            "medaxis_demo_e2e_*."
        )

    return TestDatabaseTarget(
        backend="postgresql",
        database=database.database or "",
        host=database.host,
    )


def resolve_demo_redis_mode(environment: Mapping[str, str], redis_url: str) -> str:
    """Allow the demo harness to use only an explicitly local real Redis."""
    mode = environment.get("DEMO_REDIS_LOCK_MODE", "substitute").strip().lower()
    if mode == "substitute":
        return mode
    if mode != "redis":
        raise ValueError(
            "DEMO_REDIS_LOCK_MODE must be either 'substitute' or 'redis'."
        )

    try:
        target = make_url(redis_url)
    except Exception as exc:
        raise ValueError("The synthetic demo Redis URL is invalid.") from exc
    if target.drivername != "redis" or target.host not in {"127.0.0.1", "localhost"}:
        raise ValueError(
            "Real Redis mode for the synthetic demo requires loopback Redis."
        )
    return mode


def repository_migration_head(alembic_ini: Path) -> str:
    """Resolve the current source migration head without connecting to a database."""
    script = ScriptDirectory.from_config(Config(str(alembic_ini)))
    head = script.get_current_head()
    if head is None:
        raise ValueError("The repository does not define an Alembic migration head.")
    return head
