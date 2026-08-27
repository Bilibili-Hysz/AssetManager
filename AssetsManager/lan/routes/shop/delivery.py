"""Commerce delivery, share-claim redemption, and delivery-rotation routes."""
from __future__ import annotations

import asyncio
import logging
import math
from pathlib import Path
import threading
import time
from typing import Any, Callable

from aiohttp import web

from AssetsManager.domain.errors import (
    DeliveryPreparationError,
    NotFoundError,
    OperationNotPermitted,
    PathEscapeError,
    ValidationError,
)
from AssetsManager.lan.routes.commerce_policy import (
    commerce_required,
    seller_gate,
)
from AssetsManager.lan.routes.shop._common import (
    _buyer_response,
    _delivery_request_key,
    _error_response,
    _get_order_receipt,
    _package_function,
    _set_order_receipt_cookie,
)


_log = logging.getLogger(__name__)


async def handle_order_delivery_rotate(request: web.Request) -> web.Response:
    """Recover a lost seller delivery response without revoking old links."""
    disabled = seller_gate()
    if disabled is not None:
        return disabled
    if await _package_function("require_seller")(request) is None:
        return _error_response("Seller authentication required", status=403, code="forbidden")
    try:
        body = (
            await _package_function("_json_body")(request)
            if request.can_read_body and (request.content_length or 0) > 0
            else {}
        )
        order, token, share_claim = _package_function("get_commerce_services")(request).orders.rotate_delivery(
            _package_function("get_lan")(request).library_root,
            request.match_info["order_id"],
            max_downloads=body.get("max_downloads"),
            expires_in=body.get("expires_in"),
        )
        return web.json_response(
            {
                "order": order,
                "delivery_token": token,
                "share_claim": share_claim,
                "delivery_url": f"/api/shop/delivery/{request.match_info['order_id']}",
                "rotated": True,
            },
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        return _error_response(exc)


# ── Share-claim: reserved-slot POST throttling under `_claim_lock`; success
# clears the bucket. ─────────────────────────────────────────────────────────
_CLAIM_MAX_FAILURES = 10
_CLAIM_WINDOW_SECONDS = 300
_CLAIM_MAX_ACTIVE_KEYS = 5000

_claim_lock = threading.Lock()
_claim_failures: dict[str, list[float]] = {}


def _claim_request_remote(request: web.Request) -> str:
    """Resolve the security middleware's scoped claim-failure bucket."""
    from AssetsManager.lan.security import SECURITY_BUCKET_KEY

    try:
        bucket_key = request.get(SECURITY_BUCKET_KEY)
    except Exception:
        bucket_key = None
    return str(bucket_key or getattr(request, "remote", "") or "")


def _prune_claim_state_locked(remote: str, now: float) -> None:
    stamps = _claim_failures.get(remote)
    if stamps is not None:
        recent = [ts for ts in stamps if now - ts < _CLAIM_WINDOW_SECONDS]
        if recent:
            _claim_failures[remote] = recent
        else:
            _claim_failures.pop(remote, None)
    for key in [
        k for k, v in _claim_failures.items()
        if not v or now - max(v) >= _CLAIM_WINDOW_SECONDS
    ]:
        _claim_failures.pop(key, None)


def _reserve_claim_attempt(remote: str, now: float | None = None) -> bool:
    """Claim one slot (False when over budget); reinsert = LRU refresh."""
    timestamp = time.time() if now is None else float(now)
    remote = str(remote or "")
    with _claim_lock:
        _prune_claim_state_locked(remote, timestamp)
        bucket = _claim_failures.pop(remote, None)
        if bucket is None and len(_claim_failures) >= _CLAIM_MAX_ACTIVE_KEYS:
            _claim_failures.pop(next(iter(_claim_failures)), None)
        if bucket is None:
            bucket = []
        if len(bucket) >= _CLAIM_MAX_FAILURES:
            _claim_failures[remote] = bucket
            return False
        bucket.append(timestamp)
        _claim_failures[remote] = bucket
        return True


def _clear_claim_failures(remote: str) -> None:
    with _claim_lock:
        _claim_failures.pop(str(remote or ""), None)


def _claim_retry_after(remote: str, now: float | None = None) -> int:
    timestamp = time.time() if now is None else float(now)
    with _claim_lock:
        _prune_claim_state_locked(str(remote or ""), timestamp)
        bucket = _claim_failures.get(str(remote or ""))
        if not bucket:
            return _CLAIM_WINDOW_SECONDS
        return max(1, int(math.ceil(_CLAIM_WINDOW_SECONDS - (timestamp - min(bucket)))))


@commerce_required
async def handle_shop_claim_delivery(request: web.Request) -> web.Response:
    """Redeem a one-time share claim and bind the buyer receipt cookie.
    Every failure (unknown/used/revoked/expired) answers a uniform 404; the
    claim code reaches only the HttpOnly receipt cookie.
    """
    order_id = request.match_info["order_id"]
    remote = _package_function("_claim_request_remote")(request)
    # Reserve up front: even an empty claim spends one window slot.
    if not _reserve_claim_attempt(remote):
        retry_after = _claim_retry_after(remote)
        return _error_response(
            "Too many claim attempts. Please try again later.",
            status=429,
            code="rate_limited",
            extra={"retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )
    try:
        body = await _package_function("_json_body")(request)
        claim = str(body.get("claim") or "").strip()
        if not claim:
            raise ValidationError("claim", "must not be empty")
        result = _package_function("get_commerce_services")(request).orders.claim_share_delivery(
            _package_function("get_lan")(request).library_root, order_id, claim
        )
        if result is None:
            raise NotFoundError("delivery", "claim")
        _clear_claim_failures(remote)
        _order, receipt = result
        response = _buyer_response({"ok": True}, request=request)
        _set_order_receipt_cookie(response, request, order_id, receipt)
        return response
    except Exception as exc:
        return _error_response(exc)


async def handle_order_delivery_revoke(request: web.Request) -> web.Response:
    """Revoke every delivery token of a fulfilled order (seller-only)."""
    disabled = seller_gate()
    if disabled is not None:
        return disabled
    seller = await _package_function("require_seller")(request)
    if seller is None:
        return _error_response("Seller authentication required", status=403, code="forbidden")
    try:
        order = _package_function("get_commerce_services")(request).orders.revoke_delivery(
            _package_function("get_lan")(request).library_root,
            request.match_info["order_id"],
            seller=seller,
        )
        return web.json_response(
            {"order": order, "revoked": True},
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        return _error_response(exc)


@commerce_required
async def handle_delivery(request: web.Request) -> web.Response:
    try:
        order, target = _package_function("get_commerce_services")(request).orders.resolve_delivery(
            _package_function("get_lan")(request).library_root, request.match_info["token"], consume=False
        )
        return web.json_response({
            "order": order,
            "filename": target.name,
            "is_directory": target.is_dir(),
            "download_url": f"/api/shop/delivery/{request.match_info['token']}/download",
        }, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return _error_response(exc)

async def _delivery_file_response(
    request: web.Request | None,
    target: Path,
    *,
    consume: Callable[[], object] | None = None,
    fail: Callable[[], object] | None = None,
) -> web.StreamResponse:
    """Prepare a file/ZIP and consume delivery quota only after preparation."""
    import os
    import tempfile

    from AssetsManager.lan.routes._helpers import build_zip_async, sanitize_filename
    from AssetsManager.lan.routes.downloads import _file_response_with_cleanup
    from AssetsManager.lan.safe_open import SafeOpenError, read_safe_file

    def mark_failed() -> None:
        if fail is None:
            return
        try:
            fail()
        except Exception:
            _log.exception("Could not persist failed delivery attempt")

    if target.is_file():
        try:
            body, _identity = await asyncio.to_thread(
                read_safe_file,
                target.parent,
                target,
            )
            response = web.Response(
                body=body,
                headers={
                    "Content-Disposition": f'attachment; filename="{sanitize_filename(target.name)}"',
                    "Cache-Control": "private, no-store",
                },
            )
        except (SafeOpenError, OSError, ValueError):
            mark_failed()
            return _error_response(DeliveryPreparationError())
        if consume is not None:
            consume()
        return response
    fd, zip_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        result = await build_zip_async(request, [(target, None)], zip_path)
    except Exception:
        mark_failed()
        try:
            os.unlink(zip_path)
        except OSError:
            pass
        return _error_response(DeliveryPreparationError())
    if result is None:
        mark_failed()
        try:
            os.unlink(zip_path)
        except OSError:
            pass
        return _error_response(DeliveryPreparationError())
    try:
        if consume is not None:
            consume()
    except BaseException:
        try:
            os.unlink(zip_path)
        except OSError:
            pass
        raise
    return _file_response_with_cleanup(
        request, zip_path, filename=sanitize_filename(f"{target.name}.zip")
    )


@commerce_required
async def handle_order_delivery(request: web.Request) -> web.StreamResponse:
    """Consume delivery quota through the order-scoped HttpOnly receipt."""
    order_id = request.match_info["order_id"]
    try:
        orders = _package_function("get_commerce_services")(request).orders
        root = _package_function("get_lan")(request).library_root
        receipt = _get_order_receipt(request, order_id)
        request_key = _delivery_request_key(request)
        resolve_kwargs: dict[str, Any] = {"consume": False}
        if request_key is not None:
            resolve_kwargs["request_key"] = request_key
        _, target = orders.resolve_delivery_by_receipt(
            root, order_id, receipt, **resolve_kwargs
        )
        consume_kwargs: dict[str, Any] = {"consume": True}
        if request_key is not None:
            consume_kwargs["request_key"] = request_key
        fail = None if request_key is None else lambda: orders.fail_delivery_attempt_by_receipt(
            root, order_id, receipt, request_key=request_key
        )
        return await _delivery_file_response(
            request,
            target,
            consume=lambda: orders.resolve_delivery_by_receipt(
                root, order_id, receipt, **consume_kwargs
            ),
            fail=fail,
        )
    except (ValidationError, NotFoundError, PathEscapeError, OperationNotPermitted) as exc:
        return _error_response(exc)


@commerce_required
async def handle_delivery_download(request: web.Request) -> web.StreamResponse:
    """Consume one slot, then reuse the existing guarded file/ZIP delivery."""
    try:
        orders = _package_function("get_commerce_services")(request).orders
        root = _package_function("get_lan")(request).library_root
        token = request.match_info["token"]
        request_key = _delivery_request_key(request)
        resolve_kwargs: dict[str, Any] = {"consume": False}
        if request_key is not None:
            resolve_kwargs["request_key"] = request_key
        _, target = orders.resolve_delivery(root, token, **resolve_kwargs)
        consume_kwargs: dict[str, Any] = {"consume": True}
        if request_key is not None:
            consume_kwargs["request_key"] = request_key
        fail = None if request_key is None else lambda: orders.fail_delivery_attempt(
            root, token, request_key=request_key
        )
        return await _delivery_file_response(
            request,
            target,
            consume=lambda: orders.resolve_delivery(
                root, token, **consume_kwargs
            ),
            fail=fail,
        )
    except (ValidationError, NotFoundError, PathEscapeError, OperationNotPermitted) as exc:
        return _error_response(exc)
