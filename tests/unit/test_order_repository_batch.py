"""Batch query/update APIs of OrderRepository and their performance win.

The batch APIs replace per-order loops with ``WHERE id IN (...)`` /
``executemany`` statements executed inside one transaction, cutting
round trips for the I/O-heaviest commerce paths (checkout replay, checkout
group loading, seller bulk status changes).
"""
from __future__ import annotations

import time

import pytest

from AssetsManager.repositories.order_repository import OrderRepository
from AssetsManager.repositories.shop_repository import ShopRepository


def _seed_orders(
    schema_db,
    count: int,
    *,
    buyer_mod: int | None = None,
    with_receipt: bool = False,
) -> tuple[OrderRepository, list[int]]:
    """Create ``count`` pending orders on one item; returns (repo, order ids)."""
    shop = ShopRepository(schema_db)
    orders = OrderRepository(schema_db)
    item = shop.create_item(
        path="batch/item", title="Batch item", price_cents=100, currency="CNY"
    )
    ids: list[int] = []
    for i in range(count):
        kwargs: dict = {
            "item_id": item["id"],
            "buyer_name": f"Buyer {i}",
            "buyer_email": f"buyer{i}@example.com",
            "amount_cents": 100,
            "currency": "CNY",
        }
        if buyer_mod is not None:
            kwargs["buyer_owner_type"] = "user"
            # Authenticated user ids start at 1 (see ShopBuyerService._owner).
            kwargs["buyer_owner_key"] = str(i % buyer_mod + 1)
        if with_receipt:
            kwargs["receipt_token_hash"] = f"{i:064d}"
            kwargs["receipt_expires_at"] = time.time() + 3600.0
        ids.append(orders.create_order(**kwargs)["id"])
    return orders, ids


# --- get_orders_by_ids -------------------------------------------------------


def test_get_orders_by_ids_preserves_input_order_and_skips_missing(schema_db):
    orders, ids = _seed_orders(schema_db, 5)

    loaded = orders.get_orders_by_ids([ids[3], 999_999, ids[0], ids[3]])

    assert [order["id"] for order in loaded] == [ids[3], ids[0]]
    assert len(loaded) == 2
    # Parity with the single-order API for every returned row.
    for order in loaded:
        assert orders.get_order(order["id"]) == order


def test_get_orders_by_ids_empty_unknown_and_invalid_input(schema_db):
    orders, ids = _seed_orders(schema_db, 3)

    assert orders.get_orders_by_ids([]) == []
    assert orders.get_orders_by_ids([999_998, 999_999]) == []
    with pytest.raises(ValueError):
        orders.get_orders_by_ids([0])
    with pytest.raises(ValueError):
        orders.get_orders_by_ids([-1])
    with pytest.raises(ValueError):
        orders.get_orders_by_ids([ids[0], "not-an-int"])
    with pytest.raises(ValueError):
        orders.get_orders_by_ids([True])


# --- update_order_status_batch -----------------------------------------------


def test_update_order_status_batch_updates_many_with_audit_events(schema_db):
    orders, ids = _seed_orders(schema_db, 5)

    changed = orders.update_order_status_batch(
        [(ids[0], "confirmed"), (ids[1], "confirmed"), (ids[2], "revoked")]
    )

    assert changed == 3
    o0 = orders.get_order(ids[0])
    o1 = orders.get_order(ids[1])
    o2 = orders.get_order(ids[2])
    o3 = orders.get_order(ids[3])
    o4 = orders.get_order(ids[4])
    assert o0 is not None and o0["status"] == "confirmed"
    assert o1 is not None and o1["status"] == "confirmed"
    assert o2 is not None and o2["status"] == "revoked"
    assert o3 is not None and o3["status"] == "pending"
    assert o4 is not None and o4["status"] == "pending"
    # Every changed order carries one status_changed event with the real
    # pre-transition status, matching the single-order API's audit trail.
    confirmed_events = [
        event
        for event in orders.list_events(ids[0])
        if event["event_type"] == "status_changed"
    ]
    assert [(e["from_status"], e["to_status"]) for e in confirmed_events] == [
        ("pending", "confirmed")
    ]
    revoked_events = [
        event
        for event in orders.list_events(ids[2])
        if event["event_type"] == "status_changed"
    ]
    assert [(e["from_status"], e["to_status"]) for e in revoked_events] == [
        ("pending", "revoked")
    ]


def test_update_order_status_batch_noops_and_revokes_receipts(schema_db):
    orders, ids = _seed_orders(schema_db, 3, with_receipt=True)

    changed = orders.update_order_status_batch(
        [
            (ids[0], "confirmed"),
            (999_999, "confirmed"),  # unknown id: skipped
            (ids[0], "confirmed"),  # duplicate id: last wins, now unchanged
            (ids[1], "revoked"),
        ]
    )

    assert changed == 2
    o0_after = orders.get_order(ids[0])
    assert o0_after is not None and o0_after["status"] == "confirmed"
    # Exactly one status_changed event for ids[0] despite the duplicate entry.
    assert (
        len(
            [
                e
                for e in orders.list_events(ids[0])
                if e["event_type"] == "status_changed"
            ]
        )
        == 1
    )
    # Revocation revokes the receipt in the same transaction.
    r1 = orders.get_receipt_state(ids[1])
    r0 = orders.get_receipt_state(ids[0])
    assert r1 is not None and r1["revoked_at"] is not None
    assert r0 is not None and r0["revoked_at"] is None

    assert orders.update_order_status_batch([]) == 0
    assert orders.update_order_status_batch([(999_997, "confirmed")]) == 0
    # An already-pending order kept pending is a no-op, not a change.
    assert orders.update_order_status_batch([(ids[2], "pending")]) == 0
    with pytest.raises(ValueError):
        orders.update_order_status_batch([(ids[0], "bogus")])


# --- get_orders_by_buyer_ids -------------------------------------------------


def test_get_orders_by_buyer_ids_groups_newest_first(schema_db):
    orders, ids = _seed_orders(schema_db, 6, buyer_mod=3)

    grouped = orders.get_orders_by_buyer_ids([1, 2, 4])

    assert set(grouped) == {1, 2}
    # Buyer 1 owns orders i=0 and i=3; newest (higher id) comes first.
    assert [order["id"] for order in grouped[1]] == [ids[3], ids[0]]
    assert [order["id"] for order in grouped[2]] == [ids[4], ids[1]]
    assert all(order["status"] == "pending" for order in grouped[1])


def test_get_orders_by_buyer_ids_empty_anonymous_scope_and_validation(schema_db):
    orders, ids = _seed_orders(schema_db, 2, buyer_mod=2)
    # Anonymous buyers are keyed by token hash, not an integer id; they must
    # never leak into the integer-id grouping.
    o0 = orders.get_order(ids[0])
    assert o0 is not None
    anonymous_id = orders.create_order(
        item_id=o0["item_id"],
        buyer_name="Guest",
        amount_cents=100,
        currency="CNY",
        buyer_owner_type="anonymous",
        buyer_owner_key="f" * 64,
    )["id"]

    assert orders.get_orders_by_buyer_ids([]) == {}
    assert orders.get_orders_by_buyer_ids([999_999]) == {}

    grouped = orders.get_orders_by_buyer_ids([1, 2])
    all_grouped_ids = [
        order["id"] for group in grouped.values() for order in group
    ]
    assert anonymous_id not in all_grouped_ids
    assert grouped[1][0]["id"] == ids[0]
    assert grouped[2][0]["id"] == ids[1]

    with pytest.raises(ValueError):
        orders.get_orders_by_buyer_ids([1, -2])


# --- batch vs loop performance ----------------------------------------------


@pytest.mark.perf
def test_batch_vs_loop_performance(schema_db):
    """100 ids load at least 3x faster through one IN query than 100 get_order calls."""
    orders, ids = _seed_orders(schema_db, 100)

    def best_of(fn, repeats: int = 7) -> float:
        best = float("inf")
        for _ in range(repeats):
            start = time.perf_counter()
            fn()
            best = min(best, time.perf_counter() - start)
        return best

    loop_elapsed = best_of(lambda: [orders.get_order(oid) for oid in ids])
    batch_elapsed = best_of(lambda: orders.get_orders_by_ids(ids))

    print(
        f"batch={batch_elapsed * 1e6:.1f}us loop={loop_elapsed * 1e6:.1f}us "
        f"ratio={loop_elapsed / batch_elapsed:.1f}x"
    )
    assert loop_elapsed > batch_elapsed * 3, (
        f"batch ({batch_elapsed * 1e6:.1f}us) is not 3x faster than the "
        f"per-order loop ({loop_elapsed * 1e6:.1f}us)"
    )
    # The batch load itself stays comfortably fast at this size.
    assert batch_elapsed < 0.1
