"""Tests for catalogue and inventory engine operations."""

import asyncio
from collections.abc import Callable
from copy import deepcopy
from typing import Any, TypeVar

import pytest

from custom_components.kitchen_manager.inventory import (
    InventoryEngine,
    InventoryError,
)
from custom_components.kitchen_manager.models import (
    KitchenManagerData,
    ModelValidationError,
    TransactionType,
)

_Result = TypeVar("_Result")


class MemoryStorage:
    """Atomic in-memory implementation of the storage interface for unit tests."""

    def __init__(self) -> None:
        self._data = KitchenManagerData()
        self._lock = asyncio.Lock()

    @property
    def data(self) -> KitchenManagerData:
        return KitchenManagerData.from_dict(self._data.to_dict())

    async def async_update(
        self, mutator: Callable[[KitchenManagerData], tuple[_Result, bool]]
    ) -> _Result:
        async with self._lock:
            snapshot = self.data
            result, changed = mutator(snapshot)
            if changed:
                snapshot.validate()
                self._data = KitchenManagerData.from_dict(snapshot.to_dict())
            return deepcopy(result)


@pytest.fixture
def engine() -> InventoryEngine:
    """Create an inventory engine backed by isolated test storage."""
    return InventoryEngine(MemoryStorage())


async def _create_product(
    engine: InventoryEngine, *, name: str = "Milk", **kwargs: Any
) -> dict[str, Any]:
    """Create a product used by an inventory test."""
    return await engine.async_create_product(name=name, **kwargs)


async def test_create_and_search_products_with_shared_ingredient(
    engine: InventoryEngine,
) -> None:
    """Allow multiple brands to share one generic ingredient."""
    first = await _create_product(
        engine, name="Chopped tomatoes", brand="Brand A", ingredient_name="Tomatoes"
    )
    second = await _create_product(
        engine, name="Chopped tomatoes", brand="Brand B", ingredient_name="tomatoes"
    )

    assert first["ingredient_id"] == second["ingredient_id"]
    matches = engine.find_products("TOMATO")
    assert {item["brand"] for item in matches} == {"Brand A", "Brand B"}
    assert engine.find_products("Brand B")[0]["id"] == second["id"]


async def test_duplicate_barcode_and_product_are_rejected(
    engine: InventoryEngine,
) -> None:
    """Prevent accidentally creating a duplicate product or barcode."""
    await _create_product(engine, barcode="123")

    with pytest.raises(InventoryError, match="Barcode"):
        await _create_product(engine, name="Another product", barcode="123")
    with pytest.raises(InventoryError, match="matching product"):
        await _create_product(engine)


async def test_catalogue_includes_unstocked_products_and_reorder_status(
    engine: InventoryEngine,
) -> None:
    """List zero-stock products and flag quantities below optional thresholds."""
    unstocked = await _create_product(
        engine, name="Eggs", reorder_threshold=6, description="Free range"
    )
    stocked = await _create_product(
        engine, name="Milk", reorder_threshold=2
    )
    await engine.async_change_stock(
        TransactionType.ADD,
        product_id=stocked["id"],
        quantity=1,
        location="fridge",
    )

    all_products = engine.list_products()
    eggs = next(row for row in all_products if row["product"]["id"] == unstocked["id"])
    milk = next(row for row in all_products if row["product"]["id"] == stocked["id"])

    assert eggs["low_stock"]
    assert eggs["total_quantity"] == 0
    assert eggs["product"]["description"] == "Free range"
    assert milk["low_stock"]
    assert milk["total_quantity"] == 1
    assert len(engine.list_products("MILK")) == 1


async def test_product_update_can_clear_optional_fields(
    engine: InventoryEngine,
) -> None:
    """Clear optional metadata without losing product identity or stock."""
    product = await _create_product(
        engine,
        brand="Brand",
        description="Fresh",
        barcode="123",
        package_size=1,
        package_unit="L",
        reorder_threshold=2,
    )

    updated = await engine.async_update_product(
        product_id=product["id"],
        clear_fields=[
            "brand",
            "barcode",
            "description",
            "package",
            "reorder_threshold",
        ],
    )

    assert updated["brand"] is None
    assert updated["barcode"] is None
    assert updated["description"] is None
    assert updated["package_size"] is None
    assert updated["package_unit"] is None
    assert updated["reorder_threshold"] is None


async def test_default_location_is_used_and_can_be_overridden(
    engine: InventoryEngine,
) -> None:
    """Use a saved custom location for additions and honor one-off overrides."""
    product = await _create_product(
        engine,
        name="Pasta",
        default_storage_location="baking cupboard",
    )
    added = await engine.async_change_stock(
        TransactionType.ADD,
        product_id=product["id"],
        quantity=2,
    )
    override = await engine.async_change_stock(
        TransactionType.ADD,
        product_id=product["id"],
        quantity=1,
        location="utility room",
    )

    assert added["location"] == "baking cupboard"
    assert override["location"] == "utility room"
    assert set(engine.list_locations()) >= {
        "baking cupboard",
        "utility room",
    }


async def test_default_location_can_be_changed_without_modifying_stock(
    engine: InventoryEngine,
) -> None:
    """Changing the default affects future additions, not existing stock."""
    product = await _create_product(
        engine,
        name="Milk",
        default_storage_location="fridge",
    )
    first = await engine.async_change_stock(
        TransactionType.ADD,
        product_id=product["id"],
        quantity=2,
    )
    await engine.async_update_product(
        product_id=product["id"],
        default_storage_location="garage fridge",
    )
    next_addition = await engine.async_change_stock(
        TransactionType.ADD,
        product_id=product["id"],
        quantity=1,
    )
    stock = engine.get_stock(product_id=product["id"])[0]["stock"]

    assert first["location"] == "fridge"
    assert next_addition["location"] == "garage fridge"
    assert {str(item["location"]) for item in stock} == {
        "fridge",
        "garage fridge",
    }


async def test_add_consume_and_insufficient_stock(engine: InventoryEngine) -> None:
    """Persist stock transactions and prevent negative inventory."""
    product = await _create_product(engine)
    added = await engine.async_change_stock(
        TransactionType.ADD,
        product_id=product["id"],
        quantity=4,
        location="fridge",
    )
    consumed = await engine.async_change_stock(
        TransactionType.CONSUME,
        barcode=None,
        product_id=product["id"],
        quantity=1.5,
    )

    assert added["quantity"] == 4
    assert consumed["quantity"] == 2.5
    with pytest.raises(InventoryError, match="Insufficient stock"):
        await engine.async_change_stock(
            TransactionType.CONSUME,
            product_id=product["id"],
            quantity=3,
            location="fridge",
        )
    assert len(engine._storage.data.transactions) == 2


async def test_consume_handles_floating_point_rounding(engine: InventoryEngine) -> None:
    """Treat decimal-equivalent floating quantities as an exact depletion."""
    product = await _create_product(engine)
    await engine.async_change_stock(
        TransactionType.ADD,
        product_id=product["id"],
        quantity=0.3,
        location="fridge",
    )
    await engine.async_change_stock(
        TransactionType.CONSUME,
        product_id=product["id"],
        quantity=0.1 + 0.2,
        location="fridge",
    )

    assert engine.get_stock(product_id=product["id"])[0]["stock"][0]["quantity"] == 0


async def test_set_stock_tracks_previous_and_new_quantities(
    engine: InventoryEngine,
) -> None:
    """Corrections are recorded as set transactions."""
    product = await _create_product(engine)
    await engine.async_change_stock(
        TransactionType.ADD,
        product_id=product["id"],
        quantity=2,
        location="cupboard",
    )
    correction = await engine.async_change_stock(
        TransactionType.SET,
        product_id=product["id"],
        quantity=5,
        location="cupboard",
    )
    transaction = engine.get_stock_history(limit=1)[0]

    assert correction["quantity"] == 5
    assert transaction["operation"] is TransactionType.SET
    assert transaction["previous_quantity"] == 2
    assert transaction["new_quantity"] == 5


async def test_consume_requires_location_when_stock_is_split(
    engine: InventoryEngine,
) -> None:
    """Do not guess which location to consume from."""
    product = await _create_product(engine)
    for location in ("fridge", "freezer"):
        await engine.async_change_stock(
            TransactionType.ADD,
            product_id=product["id"],
            quantity=1,
            location=location,
        )

    with pytest.raises(InventoryError, match="multiple locations"):
        await engine.async_change_stock(
            TransactionType.CONSUME,
            product_id=product["id"],
            quantity=1,
        )
    consumed = await engine.async_change_stock(
        TransactionType.CONSUME,
        product_id=product["id"],
        quantity=1,
        location="freezer",
    )
    assert consumed["location"] == "freezer"


async def test_operation_retries_are_idempotent_and_conflicts_fail(
    engine: InventoryEngine,
) -> None:
    """Return original success for retries and reject changed requests."""
    product = await _create_product(engine)
    first = await engine.async_change_stock(
        TransactionType.ADD,
        product_id=product["id"],
        quantity=2,
        location="cupboard",
        operation_id="delivery-1",
    )
    expected = first.copy()
    first["quantity"] = 999
    retry = await engine.async_change_stock(
        TransactionType.ADD,
        product_id=product["id"],
        quantity=2,
        location="cupboard",
        operation_id="delivery-1",
    )

    assert retry == expected
    assert len(engine._storage.data.transactions) == 1
    with pytest.raises(InventoryError, match="different request"):
        await engine.async_change_stock(
            TransactionType.ADD,
            product_id=product["id"],
            quantity=3,
            location="cupboard",
            operation_id="delivery-1",
        )
    assert len(engine._storage.data.transactions) == 1


async def test_barcode_retry_returns_original_result_after_barcode_change(
    engine: InventoryEngine,
) -> None:
    """Resolve a saved idempotent retry before looking up its former barcode."""
    product = await _create_product(engine, barcode="old-code")
    original = await engine.async_change_stock(
        TransactionType.ADD,
        barcode="old-code",
        quantity=2,
        location="fridge",
        operation_id="barcode-retry",
    )
    await engine.async_update_product(
        product_id=product["id"], barcode="new-code"
    )

    retry = await engine.async_change_stock(
        TransactionType.ADD,
        barcode="old-code",
        quantity=2,
        location="fridge",
        operation_id="barcode-retry",
    )

    assert retry == original
    assert len(engine._storage.data.transactions) == 1


async def test_concurrent_additions_do_not_overwrite_each_other(
    engine: InventoryEngine,
) -> None:
    """Serialize concurrent read-modify-write stock updates."""
    product = await _create_product(engine)
    await asyncio.gather(
        *(
            engine.async_change_stock(
                TransactionType.ADD,
                product_id=product["id"],
                quantity=1,
                location="fridge",
            )
            for _ in range(20)
        )
    )
    result = engine.get_stock(product_id=product["id"])[0]["stock"][0]

    assert result["quantity"] == 20
    assert len(engine._storage.data.transactions) == 20


async def test_update_product_preserves_inventory_and_history(
    engine: InventoryEngine,
) -> None:
    """Product edits retain the same product ID and existing stock ledger."""
    product = await _create_product(engine)
    await engine.async_change_stock(
        TransactionType.ADD,
        product_id=product["id"],
        quantity=2,
        location="fridge",
    )
    updated = await engine.async_update_product(
        product_id=product["id"], name="Oat milk"
    )

    assert updated["name"] == "Oat milk"
    assert engine.get_stock(product_id=product["id"])[0]["stock"][0]["quantity"] == 2
    assert len(engine.get_stock_history(limit=10)) == 1


def test_model_rejects_bad_operation_record() -> None:
    """Fail closed if idempotency metadata is not valid."""
    with pytest.raises(ModelValidationError, match="operation.result"):
        from custom_components.kitchen_manager.models import OperationRecord

        OperationRecord(operation_id="x", fingerprint="{}", result=[])
