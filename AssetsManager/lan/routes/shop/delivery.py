"""Commerce delivery, share-claim redemption, and delivery-rotation routes."""
from __future__ import annotations

import logging
import math
from pathlib import Path
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


# ── Share-claim delivery redemption ────────────────────────────
# The claim POST is bearer-free (the code itself is the credential), so it
# gets the same stricter per-IP failure throttling the security middleware
# applies to auth endpoints (10 failures / 5 minutes -> 429).  State is
# in-process only, matching the LAN middleware's memory-scoped limiters.
_CLAIM_MAX_FAILURES = 10
_CLAIM_WINDOW_SECONDS = 300

_claim_failures: dict[str, list[float]] = {}


def _claim_request_remote(request: web.Request) -> str:
    """Resolve the per-IP key used for share-claim brute-force limiting."""
    return str(getattr(request, "remote", "") or "")


def _claim_failures_for(remote: str, now: float) -> list[float]:
    """Return the recent failed-claim timestamps for one IP (pruning stale)."""
    recent = [
        ts for ts in _claim_failures.get(remote, []) if now - ts < _CLAIM_WINDOW_SECONDS
    ]
    if recent:
        _claim_failures[remote] = recent
    else:
        _claim_failures.pop(remote, None)
    return recent


def _claim_brute_force_allowed(remote: str, now: float) -> bool:
    return len(_claim_failures_for(remote, now)) < _CLAIM_MAX_FAILURES


def _claim_retry_after(remote: str, now: float) -> int:
    """Seconds until the oldest failure leaves the window (min 1)."""
    failures = _claim_failures_for(remote, now)
    if not failures:
        return _CLAIM_WINDOW_SECONDS
    return max(1, int(math.ceil(_CLAIM_WINDOW_SECONDS - (now - min(failures)))))


def _record_claim_failure(remote: str, now: float) -> None:
    _claim_failures_for(remote, now)  # prune stale entries first
    _claim_failures.setdefault(remote, []).append(now)


@commerce_required
async def handle_shop_claim_delivery(request: web.Request) -> web.Response:
    """Redeem a one-time share claim and bind the buyer receipt cookie.

    The claim is delivered over the credential-less delivery link
    (``delivery_url`` in the fulfill/rotate responses).  Every failure —
    unknown, already-used, revoked, or expired claim — answers a uniform 404
    so attackers cannot tell them apart; the redeemable credential itself
    only ever reaches the HttpOnly receipt cookie.
    """
    order_id = request.match_info["order_id"]
    remote = _package_function("_claim_request_remote")(request)
    now = time.time()
    if not _claim_brute_force_allowed(remote, now):
        retry_after = _claim_retry_after(remote, now)
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
            _record_claim_failure(remote, time.time())
            raise NotFoundError("delivery", "claim")
        _claim_failures.pop(remote, None)
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

    def mark_failed() -> None:
        if fail is None:
            return
        try:
            fail()
        except Exception:
            _log.exception("Could not persist failed delivery attempt")

    if target.is_file():
        try:
            response = web.FileResponse(
                target,
                headers={
                    "Content-Disposition": f'attachment; filename="{sanitize_filename(target.name)}"',
                    "Cache-Control": "private, no-store",
                },
            )
        except Exception:
            mark_failed()
            return _error_response(DeliveryPreparationError())
        if consume is not None:
            consume()
        return response
    fd, zip_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        result = await build_zip_async([(target, None)], zip_path)
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
