"""Alembic environment for the app-state DB. Tables are declared in each module's repo.py."""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from src.app.core.config import Settings
from src.app.core.db import load_tables, make_engine, metadata

if context.config.config_file_name:
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)

load_tables()
url = context.config.get_main_option("sqlalchemy.url") or Settings.from_env().app_db_url


def run_offline() -> None:
    context.configure(url=make_engine(url).url, target_metadata=metadata, literal_binds=True,
                      render_as_batch=url.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = make_engine(url)
    with engine.connect() as con:
        context.configure(connection=con, target_metadata=metadata, render_as_batch=url.startswith("sqlite"),
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_offline() if context.is_offline_mode() else run_online()
