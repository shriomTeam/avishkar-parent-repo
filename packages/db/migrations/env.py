import os
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

from clinic_db import ALL_SCHEMAS, Base


def _load_root_env() -> None:
    """Read DATABASE_OWNER_URL from the repo-root .env if it isn't already set."""
    env_file = Path(__file__).resolve().parents[3] / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


_load_root_env()
DATABASE_URL = os.environ["DATABASE_OWNER_URL"]


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in ALL_SCHEMAS
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=Base.metadata,
        include_schemas=True,
        include_name=include_name,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            include_schemas=True,
            include_name=include_name,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
