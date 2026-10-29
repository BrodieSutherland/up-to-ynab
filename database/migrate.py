"""Run Alembic migrations on a connection the app already owns."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Connection

import migrations


def migration_config(connection: Connection) -> Config:
    """Alembic config with no ini file, bound to the given connection."""
    config = Config()
    config.set_main_option("script_location", str(Path(migrations.__file__).parent))
    config.attributes["connection"] = connection
    return config


def upgrade_to_head(connection: Connection) -> None:
    """Upgrade to head, first stamping an unversioned 3.0 database at 0001."""
    config = migration_config(connection)
    tables = set(inspect(connection).get_table_names())
    if "ledger_entries" in tables and "alembic_version" not in tables:
        command.stamp(config, "0001")
    command.upgrade(config, "head")
