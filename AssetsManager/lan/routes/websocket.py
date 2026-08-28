"""WebSocket route."""
import asyncio
from typing import Any, Awaitable, cast

from aiohttp import WSMsgType, web

from AssetsManager.lan.auth import verify_auth_token, verify_key, verify_token_async
from AssetsManager.lan.principal import principal_for_request
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import (
    get_auth_token,
    get_lan,
    get_request_principal,
)


async def _close_quietly(ws, **kwargs):
    try:
        await ws.close(**kwargs)
    except Exception:
        pass


def _authorization_validator(request, lan, principal):
    """Bind the socket to canonical identity and credential authority."""
    token = get_auth_token(request)

    async def token_is_revoked() -> bool:
        if not token:
            return False
        checker = getattr(lan, "is_auth_token_revoked_async", None)
        if callable(checker):
            try:
                return bool(await cast(Awaitable[Any], checker(token)))
            except Exception:
                return True
        checker = getattr(lan, "is_auth_token_revoked", None)
        if not callable(checker):
            return False
        try:
            return bool(await asyncio.to_thread(checker, token))
        except Exception:
            # An unavailable durable revocation source must not keep an
            # existing socket authorized.
            return True

    if principal.kind == "user":
        expected = principal.user_profile or {}
        expected_id = int(expected.get("id", 0))
        expected_name = principal.display_name
        expected_role = principal.role
        services = getattr(lan, "services", None)
        auth_service = getattr(services, "auth_service", None)
        if auth_service is None:
            auth_service = getattr(lan, "_auth_service", None)

        async def validate_user():
            if await token_is_revoked():
                return False
            if auth_service is None:
                return False
            if token:
                current = auth_service.verify_user_token(token)
            else:
                current = next(
                    (user for user in auth_service.list_users()
                     if int(user.get("id", 0)) == expected_id),
                    None,
                )
            if not current or not current.get("is_active", True):
                return False
            current_principal = principal_for_request("user", user=current)
            return (
                int(current.get("id", 0)) == expected_id
                and current_principal.display_name == expected_name
                and current_principal.role == expected_role
                and current_principal.capabilities.realtime
            )

        return validate_user
    if principal.kind == "access_key":
        async def validate_access_key():
            if await token_is_revoked() or not token or not getattr(lan, "access_key_hash", None):
                return False
            # L2/Q1: PBKDF2 is CPU-heavy (~50k rounds) and must not run on the
            # event loop during socket admission / periodic re-authorization.
            return await asyncio.to_thread(verify_key, token, lan.access_key_hash)

        return validate_access_key
    if principal.kind == "password":
        async def validate_password():
            password_hash = getattr(lan, "password_hash", None)
            if await token_is_revoked() or not token or not password_hash:
                return False
            return await verify_token_async(token, password_hash)

        return validate_password
    if principal.kind == "local_ui" and token:
        secret = (
            getattr(lan, "local_ui_auth_secret", None)
            or getattr(lan, "token_secret", None)
        )
        async def validate_local_ui():
            return bool(
                not await token_is_revoked()
                and secret
                and verify_auth_token(token, secret)
            )

        return validate_local_ui
    # Tokenless local middleware contexts have no external credential to
    # expire; they remain explicitly identified and can still be manager-closed.
    return lambda: principal.capabilities.realtime


def _authorization_authority(principal):
    """Return the canonical mutable authority that owns this socket.

    User credentials can be revoked independently and are keyed by user id.
    Access-key and password snapshots are immutable for a running server, while
    the local-UI signing secret is bound to the current authentication config.  Their
    shared process authorities are invalidated by ``WebSocketManager.close_all``
    during the restart/teardown that rotates those credential snapshots.
    """
    if principal.kind == "user":
        profile = principal.user_profile or {}
        return ("user", int(profile.get("id", 0)))
    if principal.kind in {"access_key", "password", "local_ui"}:
        return (principal.kind,)
    return None


async def handle_websocket(request):
    lan = get_lan(request)
    # Authentication is verified once by the application middleware, including
    # HttpOnly-cookie sessions used by browser WebSocket handshakes.
    principal = get_request_principal(request)
    token = get_auth_token(request) if hasattr(request, "headers") else ""
    if ("token" in request.query or "key" in request.query
            or principal is None
            or not principal.capabilities.realtime):
        return error_response("Unauthorized", status=401, code="unauthorized")

    ws = web.WebSocketResponse(autoping=False)
    await ws.prepare(request)
    runtime = getattr(lan, "runtime", None)
    if runtime is None:
        await lan.ws_manager.remove(ws)
        await _close_quietly(ws, code=1013, message=b"Runtime unavailable")
        return ws
    baseline = (runtime.epoch, runtime.revision)
    try:
        await ws.send_json({"type": "runtime_ready", "epoch": baseline[0],
                            "revision": baseline[1]})
    except Exception:
        await lan.ws_manager.remove(ws)
        await _close_quietly(ws)
        return ws
    services = getattr(lan, "services", None)
    online_users = getattr(services, "online_users", None)
    presence_id = None
    if online_users is not None:
        profile = principal.user_profile or {}
        presence_id = str(profile.get("id") or principal.kind)
    presence_published = False
    cleaned_up = False

    def publish_presence():
        nonlocal presence_published
        if online_users is not None and presence_id is not None:
            online_users.connect(
                presence_id,
                principal.display_name or principal.kind,
                request.remote or "unknown",
            )
            presence_published = True

    def cleanup_presence():
        nonlocal cleaned_up
        if cleaned_up:
            return
        cleaned_up = True
        if (presence_published and online_users is not None
                and presence_id is not None):
            online_users.disconnect(presence_id)

    authorize = _authorization_validator(request, lan, principal)
    authority = _authorization_authority(principal)
    if not await lan.ws_manager.add(
            ws, authorize=authorize, on_admission=publish_presence,
            on_remove=cleanup_presence, authority=authority, auth_token=token,
            admission_pending=True):
        cleanup_presence()
        return ws
    # Registration and this authoritative cursor re-read form the admission
    # barrier.  A broadcast that took its client snapshot before registration
    # is recovered here; one triggered after registration includes this socket.
    admitted_cursor = (runtime.epoch, runtime.revision)
    finish_admission = getattr(lan.ws_manager, "finish_admission", None)
    if finish_admission is not None:
        try:
            payload = None
            if admitted_cursor != baseline:
                payload = {
                    "type": "runtime_ready",
                    "epoch": admitted_cursor[0],
                    "revision": admitted_cursor[1],
                }
            if not await finish_admission(ws, payload):
                return ws
        except Exception:
            evict = getattr(lan.ws_manager, "evict", None)
            if evict is not None:
                await evict(ws)
            else:
                await lan.ws_manager.remove(ws)
                await _close_quietly(ws)
            return ws
    elif admitted_cursor != baseline:
        try:
            await ws.send_json({
                "type": "runtime_ready",
                "epoch": admitted_cursor[0],
                "revision": admitted_cursor[1],
            })
        except Exception:
            evict = getattr(lan.ws_manager, "evict", None)
            if evict is not None:
                await evict(ws)
            else:
                await lan.ws_manager.remove(ws)
                await _close_quietly(ws)
            return ws
    try:
        async for msg in ws:
            if msg.type is WSMsgType.PONG:
                lan.ws_manager.acknowledge_pong(ws, msg.data)
            elif msg.type is WSMsgType.PING:
                await ws.pong(msg.data)
    finally:
        evict = getattr(lan.ws_manager, "evict", None)
        if evict is not None:
            await evict(ws)
        else:
            # Keep lightweight test doubles and older integrations compatible.
            await lan.ws_manager.remove(ws)
    return ws
