"""Commerce catalog/order/cart/delivery HTTP routes (subpackage).

Split from the former single ``shop.py`` module to keep each route group
focused while preserving every import and registered route behavior.
"""
from AssetsManager.lan.path_guard import PathGuardError, assert_under_root
from AssetsManager.lan.routes.commerce_policy import (
    commerce_gate,
    commerce_required,
    seller_gate,
    seller_is_enabled,
    seller_required,
)
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import get_lan, get_request_principal
from AssetsManager.lan.routes.image import serve_verified_image
from AssetsManager.lan.routes.shop._common import (
    CommerceServices,
    get_commerce_services,
    _error_response,
    _json_body,
    _item_id,
    _catalog_query_value,
    _order_limit,
    _receipt_cookie_name,
    _get_order_receipt,
    _delivery_request_key,
    _set_order_receipt_cookie,
    _principal_can_manage,
    _buyer_service,
    _buyer_owner,
    _buyer_response,
    _store_not_accepting_orders_response,
    require_seller,
    ORDER_RECEIPT_COOKIE_PREFIX,
)
from AssetsManager.lan.routes.shop.catalog import (
    handle_public_shop_item,
    handle_public_shop_catalog,
    handle_public_shop_item_by_path,
    handle_public_shop_item_media,
    handle_shop_items,
)
from AssetsManager.lan.routes.shop.cart import (
    handle_shop_buyer_orders,
    handle_shop_buyer_merge,
    handle_order_receipt_recover,
    handle_shop_cart,
    handle_shop_cart_checkout,
    handle_shop_cart_checkout_group,
    handle_shop_wishlist,
)
from AssetsManager.lan.routes.shop.orders import (
    handle_shop_order,
    handle_order_confirm,
    handle_order_fulfill,
    handle_order_revoke,
    handle_order_stats,
    handle_order_export,
)
from AssetsManager.lan.routes.shop.delivery import (
    _CLAIM_MAX_FAILURES,
    _CLAIM_WINDOW_SECONDS,
    _claim_failures,
    _claim_request_remote,
    _claim_retry_after,
    _clear_claim_failures,
    _delivery_file_response,
    _reserve_claim_attempt,
    handle_order_delivery_rotate,
    handle_order_delivery_revoke,
    handle_shop_claim_delivery,
    handle_delivery,
    handle_order_delivery,
    handle_delivery_download,
)


__all__ = [
    # Services and seller/catalog helpers (public imports by consumers).
    "CommerceServices",
    "get_commerce_services",
    "require_seller",
    "commerce_gate",
    "commerce_required",
    "seller_gate",
    "seller_is_enabled",
    "seller_required",
    # Former module-level import surface kept for monkeypatch compatibility.
    "get_lan",
    "get_request_principal",
    "error_response",
    "serve_verified_image",
    "PathGuardError",
    "assert_under_root",
    # Shared helper re-exports kept for compatibility with the former module.
    "_error_response",
    "_json_body",
    "_item_id",
    "_catalog_query_value",
    "_order_limit",
    "_receipt_cookie_name",
    "_get_order_receipt",
    "_delivery_request_key",
    "_set_order_receipt_cookie",
    "_principal_can_manage",
    "_buyer_service",
    "_buyer_owner",
    "_buyer_response",
    "_store_not_accepting_orders_response",
    "ORDER_RECEIPT_COOKIE_PREFIX",
    # Delivery/claim internals kept importable for the existing tests.
    "_delivery_file_response",
    "_CLAIM_MAX_FAILURES",
    "_CLAIM_WINDOW_SECONDS",
    "_claim_failures",
    "_claim_request_remote",
    "_reserve_claim_attempt",
    "_clear_claim_failures",
    "_claim_retry_after",
    # Catalog / public item handlers.
    "handle_public_shop_item",
    "handle_public_shop_catalog",
    "handle_public_shop_item_by_path",
    "handle_public_shop_item_media",
    "handle_shop_items",
    # Order handlers.
    "handle_shop_order",
    "handle_shop_buyer_orders",
    "handle_shop_buyer_merge",
    "handle_order_receipt_recover",
    "handle_order_confirm",
    "handle_order_fulfill",
    "handle_order_revoke",
    "handle_order_stats",
    "handle_order_export",
    # Cart / wishlist handlers.
    "handle_shop_cart",
    "handle_shop_cart_checkout",
    "handle_shop_cart_checkout_group",
    "handle_shop_wishlist",
    # Delivery handlers.
    "handle_delivery",
    "handle_order_delivery",
    "handle_delivery_download",
    "handle_shop_claim_delivery",
    "handle_order_delivery_rotate",
    "handle_order_delivery_revoke",
]
