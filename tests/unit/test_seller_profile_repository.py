import pytest

from AssetsManager.core.db_migrations import CURRENT_SCHEMA_VERSION, current_version
from AssetsManager.repositories.seller_profile_repository import SellerProfileRepository


def test_default_profile_is_safe_and_singleton(schema_db):
    assert current_version(schema_db) == CURRENT_SCHEMA_VERSION
    repository = SellerProfileRepository(schema_db)

    assert repository.get_profile() == {
        "store_name": "",
        "contact_email": "",
        "description": "",
        "accept_orders": True,
        "updated_at": repository.get_profile()["updated_at"],
    }
    assert schema_db.execute("SELECT COUNT(*), MIN(id), MAX(id) FROM seller_profile").fetchone() == (1, 1, 1)

def test_profile_round_trip_updates_only_profile_fields(schema_db):
    repository = SellerProfileRepository(schema_db)
    before = repository.get_profile()["updated_at"]

    updated = repository.update_profile({
        "store_name": "Store",
        "contact_email": "owner@example.com",
        "description": "A description",
        "accept_orders": False,
    })

    assert updated["store_name"] == "Store"
    assert updated["contact_email"] == "owner@example.com"
    assert updated["description"] == "A description"
    assert updated["accept_orders"] is False
    assert updated["updated_at"] >= before
    assert repository.get_profile() == updated
    assert schema_db.execute("SELECT COUNT(*) FROM seller_profile").fetchone()[0] == 1


def test_repository_rejects_unknown_persistence_fields(schema_db):
    repository = SellerProfileRepository(schema_db)

    with pytest.raises(ValueError, match="unknown seller profile field"):
        repository.update_profile({"id": 2})
