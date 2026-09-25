"""The Alembic history must build exactly the schema the modules declare (no drift)."""
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from src.app.core.config import ROOT
from src.app.core.db import load_tables, make_engine, metadata


def test_upgrade_head_matches_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    load_tables()
    with make_engine(url).connect() as con:
        diff = compare_metadata(MigrationContext.configure(con, opts={"compare_type": True}), metadata)
    assert diff == [], f"models changed without a migration: run `alembic revision --autogenerate` ({diff})"
    command.downgrade(cfg, "base")
