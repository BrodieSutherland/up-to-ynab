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


async def test_fresh_database_reaches_head_matching_models():
    manager = DatabaseManager(MEMORY)
    await manager.migrate()

    assert await tables(manager) == {"alembic_version", "ledger_entries"}
    assert await version(manager) == "0002"
    async with manager.engine.connect() as conn:
        diff = await conn.run_sync(
            lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata)
        )
    assert diff == []
    await manager.close()


async def test_3_0_database_is_stamped_and_keeps_rows():
    manager = DatabaseManager(MEMORY)
    async with manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for ddl in LEGACY_DDL:
            await conn.execute(text(ddl))
        await conn.execute(text(INSERT_ROWS))

    await manager.migrate()

    assert await tables(manager) == {"alembic_version", "ledger_entries"}
    assert await version(manager) == "0002"
    assert await rows(manager) == [
        ("up-1", "forwarded", "ynab-1"),
        ("up-2", "skipped", None),
    ]
    await manager.close()


async def test_2_x_database_without_ledger_gets_it_and_loses_legacy_tables():
    manager = DatabaseManager(MEMORY)
    async with manager.engine.begin() as conn:
        for ddl in LEGACY_DDL:
            await conn.execute(text(ddl))

    await manager.migrate()

    assert await tables(manager) == {"alembic_version", "ledger_entries"}
    assert await version(manager) == "0002"
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

    assert await version(second) == "0002"
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
