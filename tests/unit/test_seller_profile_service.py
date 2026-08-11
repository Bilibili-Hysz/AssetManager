from pathlib import Path

import pytest

from AssetsManager.domain.errors import ValidationError
from AssetsManager.repositories.seller_profile_repository import SellerProfileRepository
from AssetsManager.application.seller_profile_service import (
    MAX_DESCRIPTION_LENGTH,
    MAX_STORE_NAME_LENGTH,
    SellerProfileService,
)


def _service(schema_db):
    return SellerProfileService(repository=SellerProfileRepository(schema_db))


def test_service_trims_and_persists_profile_values(schema_db, temp_dir):
    service = _service(schema_db)

    profile = service.update_profile(temp_dir, {
        "store_name": "  My Store  ",
        "contact_email": " owner@example.com ",
        "description": "  Welcome  ",
        "accept_orders": False,
    })

    assert profile["store_name"] == "My Store"
    assert profile["contact_email"] == "owner@example.com"
    assert profile["description"] == "Welcome"
    assert profile["accept_orders"] is False
    assert service.get_profile(Path(temp_dir))["store_name"] == "My Store"


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"store_name": 42}, "store_name"),
        ({"contact_email": "not-an-email"}, "contact_email"),
        ({"accept_orders": 1}, "accept_orders"),
        ({"unknown": "value"}, "profile"),
    ],
)
def test_service_rejects_invalid_profile_input(schema_db, temp_dir, payload, field):
    with pytest.raises(ValidationError, match=field):
        _service(schema_db).update_profile(temp_dir, payload)


def test_service_enforces_text_limits(schema_db, temp_dir):
    service = _service(schema_db)

    with pytest.raises(ValidationError, match="store_name"):
        service.update_profile(temp_dir, {"store_name": "x" * (MAX_STORE_NAME_LENGTH + 1)})
    with pytest.raises(ValidationError, match="description"):
        service.update_profile(temp_dir, {"description": "x" * (MAX_DESCRIPTION_LENGTH + 1)})


def test_service_allows_empty_contact_email_and_partial_updates(schema_db, temp_dir):
    service = _service(schema_db)

    service.update_profile(temp_dir, {"store_name": "Store", "accept_orders": False})
    profile = service.update_profile(temp_dir, {"contact_email": ""})

    assert profile["store_name"] == "Store"
    assert profile["contact_email"] == ""
    assert profile["accept_orders"] is False
