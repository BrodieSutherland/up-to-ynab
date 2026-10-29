from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.pool import StaticPool

from database.connection import DatabaseManager
from database.migrate import migration_config
from database.models import Base

MEMORY = "sqlite+aiosqlite:///:memory:"

LEGACY_DDL = [
    "CREATE TABLE payee_category_mappings (id INTEGER PRIMARY KEY, payee TEXT)",
    "CREATE TABLE processed_transactions (id INTEGER PRIMARY KEY, up_id TEXT)",
]
# The 3.0 ledger_entries table, before reason_code existed.
LEDGER_3_0_DDL = (
    "CREATE TABLE ledger_entries ("
    "id INTEGER NOT NULL PRIMARY KEY, "
    "up_transaction_id VARCHAR(50) NOT NULL, "
    "status VARCHAR(20) NOT NULL, "
    "ynab_transaction_id VARCHAR(50), "
    "reason TEXT, "
    "attempts INTEGER NOT NULL, "
    "updated_at DATETIME NOT NULL)"
)
LEDGER_3_0_INDEX = (
    "CREATE UNIQUE INDEX ix_ledger_entries_up_transaction_id "
    "ON ledger_entries (up_transaction_id)"
)
INSERT_ROWS = (
    "INSERT INTO ledger_entries "
    "(up_transaction_id, status, ynab_transaction_id, attempts, updated_at) "
    "VALUES ('up-1', 'forwarded', 'ynab-1', 1, '2024-01-01 00:00:00'), "
    "('up-2', 'skipped', NULL, 1, '2024-01-02 00:00:00')"
)


async def tables(manager: DatabaseManager) -> set[str]:
    async with manager.engine.connect() as conn:
        return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))


async def version(manager: DatabaseManager) -> str:
    async with manager.engine.connect() as conn:
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        return result.scalar_one()


async def rows(manager: DatabaseManager) -> list[tuple]:
    async with manager.engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT up_transaction_id, status, ynab_transaction_id "
                "FROM ledger_entries ORDER BY id"
            )
        )
        return [tuple(r) for r in result]


async def reason_codes(manager: DatabaseManager) -> list:
    async with manager.engine.connect() as conn:
        result = await conn.execute(
            text("SELECT reason_code FROM ledger_entries ORDER BY id")
        )
        return [r[0] for r in result]


async def columns(manager: DatabaseManager) -> set[str]:
    async with manager.engine.connect() as conn:
        found = await conn.run_sync(lambda c: inspect(c).get_columns("ledger_entries"))
    return {c["name"] for c in found}


async def test_fresh_database_reaches_head_matching_models():
    manager = DatabaseManager(MEMORY)
    await manager.migrate()

    assert await tables(manager) == {
        "alembic_version",
        "ledger_entries",
        "webhook_secrets",
    }
    assert await version(manager) == "0004"
    async with manager.engine.connect() as conn:
        diff = await conn.run_sync(
            lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata)
        )
    assert diff == []
    await manager.close()


async def test_3_0_database_is_stamped_and_keeps_rows():
    manager = DatabaseManager(MEMORY)
    async with manager.engine.begin() as conn:
        await conn.execute(text(LEDGER_3_0_DDL))
        await conn.execute(text(LEDGER_3_0_INDEX))
        for ddl in LEGACY_DDL:
            await conn.execute(text(ddl))
        await conn.execute(text(INSERT_ROWS))

    await manager.migrate()

    assert await tables(manager) == {
        "alembic_version",
        "ledger_entries",
        "webhook_secrets",
    }
    assert await version(manager) == "0004"
    assert await rows(manager) == [
        ("up-1", "forwarded", "ynab-1"),
        ("up-2", "skipped", None),
    ]
    assert await reason_codes(manager) == [None, None]
    async with manager.engine.connect() as conn:
        diff = await conn.run_sync(
            lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata)
        )
    assert diff == []
    await manager.close()


async def test_2_x_database_without_ledger_gets_it_and_loses_legacy_tables():
    manager = DatabaseManager(MEMORY)
    async with manager.engine.begin() as conn:
        for ddl in LEGACY_DDL:
            await conn.execute(text(ddl))

    await manager.migrate()

    assert await tables(manager) == {
        "alembic_version",
        "ledger_entries",
        "webhook_secrets",
    }
    assert await version(manager) == "0004"
    await manager.close()


async def test_migrating_twice_is_a_no_op(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    first = DatabaseManager(url)
    await first.migrate()
    async with first.engine.begin() as conn:
        await conn.execute(text(INSERT_ROWS))
    await first.close()

    second = DatabaseManager(url)
    await second.migrate()
    await second.migrate()

    assert await version(second) == "0004"
    assert await rows(second) == [
        ("up-1", "forwarded", "ynab-1"),
        ("up-2", "skipped", None),
    ]
    await second.close()


async def test_downgrade_to_base_removes_the_schema():
    manager = DatabaseManager(MEMORY)
    await manager.migrate()

    async with manager.engine.begin() as conn:
        await conn.run_sync(lambda c: command.downgrade(migration_config(c), "base"))

    assert await tables(manager) == {"alembic_version"}
    async with manager.engine.connect() as conn:
        result = await conn.execute(text("SELECT count(*) FROM alembic_version"))
        assert result.scalar_one() == 0
    await manager.close()


async def test_file_database_uses_a_normal_pool_with_independent_sessions(tmp_path):
    manager = DatabaseManager(f"sqlite+aiosqlite:///{tmp_path / 'pool.db'}")
    await manager.migrate()
    assert not isinstance(manager.engine.sync_engine.pool, StaticPool)

    insert = text(
        "INSERT INTO ledger_entries "
        "(up_transaction_id, status, attempts, updated_at) "
        "VALUES (:id, 'forwarded', 1, '2024-01-01 00:00:00')"
    )
    async with manager.get_session() as committed:
        await committed.execute(insert, {"id": "kept"})
    try:
        async with manager.get_session() as doomed:
            await doomed.execute(insert, {"id": "discarded"})
            raise RuntimeError("roll back this session only")
    except RuntimeError:
        pass

    assert [r[0] for r in await rows(manager)] == ["kept"]
    await manager.close()


async def test_memory_database_keeps_the_static_pool():
    manager = DatabaseManager(MEMORY)
    assert isinstance(manager.engine.sync_engine.pool, StaticPool)
    await manager.close()


async def test_downgrade_to_0002_drops_only_webhook_secrets():
    manager = DatabaseManager(MEMORY)
    await manager.migrate()
    async with manager.engine.begin() as conn:
        await conn.execute(text(INSERT_ROWS))
        await conn.run_sync(lambda c: command.downgrade(migration_config(c), "0002"))

    assert await tables(manager) == {"alembic_version", "ledger_entries"}
    assert await version(manager) == "0002"
    assert len(await rows(manager)) == 2

    await manager.migrate()

    assert await version(manager) == "0004"
    assert "webhook_secrets" in await tables(manager)
    await manager.close()


async def test_downgrade_to_0003_drops_reason_code_and_keeps_rows():
    manager = DatabaseManager(MEMORY)
    await manager.migrate()
    async with manager.engine.begin() as conn:
        await conn.execute(text(INSERT_ROWS))
        await conn.execute(
            text("UPDATE ledger_entries SET reason_code = 'mirror_side' WHERE id = 2")
        )
        await conn.run_sync(lambda c: command.downgrade(migration_config(c), "0003"))

    assert await version(manager) == "0003"
    assert "reason_code" not in await columns(manager)
    assert await rows(manager) == [
        ("up-1", "forwarded", "ynab-1"),
        ("up-2", "skipped", None),
    ]

    await manager.migrate()

    assert "reason_code" in await columns(manager)
    assert await reason_codes(manager) == [None, None]
    await manager.close()
