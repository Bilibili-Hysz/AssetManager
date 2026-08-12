from __future__ import annotations

import json

from AssetsManager.application.gallery_service import GalleryTraversalLimitError
from AssetsManager.application.shop_authorization import ShopAuthorizationConfigError
from AssetsManager.domain.errors import (
    DeliveryPreparationError,
    NotFoundError,
    OperationNotPermitted,
    PriceChangedError,
    ValidationError,
)
from AssetsManager.lan.routes._errors import error_response


def payload(response):
    return json.loads(response.body)


def test_validation_error_has_stable_machine_contract():
    response = error_response(ValidationError("line_id", "must be an integer"))
    assert response.status == 400
    assert payload(response) == {
        "error": "Validation error on 'line_id': must be an integer",
        "code": "validation_error",
        "field": "line_id",
        "details": {},
    }


def test_known_commerce_not_found_and_conflict_errors_are_structured():
    missing = error_response(NotFoundError("cart line", "17"))
    assert missing.status == 404
    assert payload(missing)["code"] == "cart_line_not_found"
    assert payload(missing)["field"] == "line_id"

    changed = error_response(PriceChangedError(42))
    assert changed.status == 409
    assert payload(changed)["code"] == "price_changed"
    assert payload(changed)["item_id"] == 42


def test_expired_receipt_and_delivery_quota_use_terminal_statuses():
    receipt = error_response(OperationNotPermitted("Order receipt has expired"))
    assert receipt.status == 410
    assert payload(receipt)["code"] == "receipt_expired"

    quota = error_response(OperationNotPermitted("Download limit reached"))
    assert quota.status == 410
    assert payload(quota)["code"] == "delivery_quota_exhausted"


def test_delivery_preparation_failure_keeps_a_specific_no_store_contract():
    response = error_response(DeliveryPreparationError())
    assert response.status == 500
    assert payload(response) == {
        "error": "Failed to create delivery",
        "code": "delivery_prepare_failed",
        "details": {},
    }


def test_unknown_commerce_failure_does_not_leak_exception_text():
    response = error_response(RuntimeError("database password should not leak"))
    assert response.status == 500
    assert payload(response) == {
        "error": "Internal server error",
        "code": "internal_error",
        "details": {},
    }


def test_plain_message_keeps_text_with_explicit_code():
    response = error_response("Browse access required", status=403, code="forbidden")
    assert response.status == 403
    assert payload(response) == {
        "error": "Browse access required",
        "code": "forbidden",
        "details": {},
    }


def test_plain_message_with_field_and_extra_keys():
    response = error_response(
        "Path escape detected", status=400, code="path_escape_detected", field="path"
    )
    assert payload(response)["field"] == "path"

    extra = error_response(
        "Out of stock", status=409, code="stock_exhausted", extra={"item_id": 7}
    )
    assert payload(extra)["item_id"] == 7


def test_gallery_traversal_limit_keeps_its_status_and_code():
    response = error_response(
        GalleryTraversalLimitError("Gallery traversal time budget exceeded", status=429)
    )
    assert response.status == 429
    body = payload(response)
    assert body["code"] == "gallery_traversal_limit"
    assert body["error"] == "Gallery traversal time budget exceeded"


def test_shop_authorization_config_error_keeps_its_specific_code():
    # The historical shop.py mapping overwrote this 503 branch in the final
    # status >= 500 rewrite; the canonical contract preserves the intent.
    response = error_response(ShopAuthorizationConfigError())
    assert response.status == 503
    assert payload(response) == {
        "error": "Shop authorization configuration is invalid",
        "code": "shop_authorization_config_invalid",
        "details": {},
    }
