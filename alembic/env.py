from sqlalchemy import create_engine

from alembic import context
from trajectory.db import default_database_url, metadata

target_metadata = metadata


def run_migrations_online() -> None:
    url = context.config.get_main_option("sqlalchemy.url") or default_database_url()
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
