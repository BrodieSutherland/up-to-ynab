from database.models import PayeeCategoryMapping
from forwarding.budget_index import LegacyIndexHolder
from services.category_service import CategoryService
from utils.filters import TransactionFilter


def holder(database):
    return LegacyIndexHolder(
        CategoryService(database.get_session),
        TransactionFilter(["Transfer to "]),
        "acct-1",
    )


async def test_current_index_carries_seeded_mappings(database):
    async with database.get_session() as session:
        session.add(
            PayeeCategoryMapping(
                payee_name="Test Merchant",
                category_id="cat-1",
                category_name="Test Category",
            )
        )

    index = await holder(database).current_for("any-up-account")

    assert index.account_id == "acct-1"
    assert dict(index.category_by_payee) == {"Test Merchant": "cat-1"}


async def test_rebuild_completes(database):
    await holder(database).rebuild()
