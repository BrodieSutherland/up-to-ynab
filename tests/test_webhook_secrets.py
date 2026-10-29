import pytest

from database.webhook_secrets import SqlWebhookSecretStore
from tests.fakes.webhook_secrets import InMemoryWebhookSecretStore


@pytest.fixture(params=["sql", "memory"])
def store(request, database):
    if request.param == "sql":
        return SqlWebhookSecretStore(database.get_session)
    return InMemoryWebhookSecretStore()


async def test_empty_store_has_no_secrets(store):
    assert await store.all() == {}


async def test_saved_secrets_are_listed(store):
    await store.save("w1", "s1")
    await store.save("w2", "s2")

    assert await store.all() == {"w1": "s1", "w2": "s2"}


async def test_saving_again_replaces_the_secret(store):
    await store.save("w1", "s1")
    await store.save("w1", "s2")

    assert await store.all() == {"w1": "s2"}


async def test_delete_removes_only_that_secret(store):
    await store.save("w1", "s1")
    await store.save("w2", "s2")

    await store.delete("w1")

    assert await store.all() == {"w2": "s2"}


async def test_deleting_an_unknown_id_is_a_no_op(store):
    await store.delete("nope")

    assert await store.all() == {}
