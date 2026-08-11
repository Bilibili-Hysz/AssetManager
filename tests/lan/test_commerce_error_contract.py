from __future__ import annotations

import json

from AssetsManager.domain.errors import (
    DeliveryPreparationError,
    NotFoundError,
    OperationNotPermitted,
    PriceChangedError,
    ValidationError,
)
from AssetsManager.lan.routes.shop import _error_response


def payload(response):
    return json.loads(response.body)


def test_validation_error_has_stable_machine_contract():
    response = _error_response(ValidationError("line_id", "must be an integer"))
    assert response.status == 400
    assert payload(response) == {
        "error": "Validation error on 'line_id': must be an integer",
        "code": "validation_error",
        "field": "line_id",
        "details": {},
    }


def test_known_commerce_not_found_and_conflict_errors_are_structured():
    missing = _error_response(NotFoundError("cart line", "17"))
    assert missing.status == 404
    assert payload(missing)["code"] == "cart_line_not_found"
    assert payload(missing)["field"] == "line_id"

    changed = _error_response(PriceChangedError(42))
    assert changed.status == 409
    assert payload(changed)["code"] == "price_changed"
    assert payload(changed)["item_id"] == 42


def test_expired_receipt_and_delivery_quota_use_terminal_statuses():
    receipt = _error_response(OperationNotPermitted("Order receipt has expired"))
    assert receipt.status == 410
    assert payload(receipt)["code"] == "receipt_expired"

    quota = _error_response(OperationNotPermitted("Download limit reached"))
    assert quota.status == 410
    assert payload(quota)["code"] == "delivery_quota_exhausted"


def test_delivery_preparation_failure_keeps_a_specific_no_store_contract():
    response = _error_response(DeliveryPreparationError())
    assert response.status == 500
    assert payload(response) == {
        "error": "Failed to create delivery",
        "code": "delivery_prepare_failed",
        "details": {},
    }


def test_unknown_commerce_failure_does_not_leak_exception_text():
    response = _error_response(RuntimeError("database password should not leak"))
    assert response.status == 500
    assert payload(response) == {
        "error": "Internal server error",
        "code": "internal_error",
        "details": {},
    }
