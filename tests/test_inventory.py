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
    DataSource,
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
    assert {item["location_name"] for item in stock} == {
        "Fridge",
        "garage fridge",
    }


async def test_storage_locations_create_rename_and_persist(
    engine: InventoryEngine,
) -> None:
    """Keep location identifiers stable while names and product associations persist."""
    location = await engine.async_create_location(name="Pantry")
    product = await _create_product(
        engine,
        name="Rice",
        default_storage_location=location["id"],
    )
    await engine.async_change_stock(
        TransactionType.ADD,
        product_id=product["id"],
        quantity=2,
    )

    renamed = await engine.async_rename_location(
        location_id=location["id"],
        name="Food cupboard",
    )
    catalogue = next(
        row for row in engine.list_products() if row["product"]["id"] == product["id"]
    )

    assert renamed == {"id": location["id"], "name": "Food cupboard"}
    assert catalogue["product"]["default_storage_location"] == location["id"]
    assert catalogue["product"]["default_storage_location_name"] == "Food cupboard"
    assert catalogue["stock"][0]["location"] == location["id"]
    assert catalogue["stock"][0]["location_name"] == "Food cupboard"
    assert any(
        row["id"] == location["id"] and row["name"] == "Food cupboard"
        for row in engine.list_location_records()
    )


async def test_storage_location_names_are_case_insensitively_unique(
    engine: InventoryEngine,
) -> None:
    """Prevent duplicate location labels that differ only by case."""
    await engine.async_create_location(name="Pantry")

    with pytest.raises(InventoryError, match="already exists"):
        await engine.async_create_location(name="pAnTrY")


async def test_referenced_storage_location_cannot_be_deleted(
    engine: InventoryEngine,
) -> None:
    """Keep locations referenced by products, stock, or transaction history."""
    location = await engine.async_create_location(name="Pantry")
    product = await _create_product(
        engine,
        name="Rice",
        default_storage_location=location["id"],
    )
    await engine.async_change_stock(
        TransactionType.ADD,
        product_id=product["id"],
        quantity=1,
    )

    with pytest.raises(InventoryError, match="still used"):
        await engine.async_delete_location(location["id"])

    await engine.async_update_product(
        product_id=product["id"],
        default_storage_location="cupboard",
    )
    with pytest.raises(InventoryError, match="still used"):
        await engine.async_delete_location(location["id"])


async def test_unused_storage_location_can_be_deleted(engine: InventoryEngine) -> None:
    """Allow removal of a location with no product or stock references."""
    location = await engine.async_create_location(name="Temporary")

    await engine.async_delete_location(location["id"])

    assert location["id"] not in {
        row["id"] for row in engine.list_location_records()
    }


async def test_legacy_location_labels_are_registered_without_case_duplicates(
    engine: InventoryEngine,
) -> None:
    """Preserve old callers that submit a location label instead of a managed ID."""
    product = await _create_product(
        engine,
        name="Beans",
        default_storage_location="Pantry",
    )
    await engine.async_change_stock(
        TransactionType.ADD,
        product_id=product["id"],
        quantity=1,
        location="pantry",
    )

    assert len(
        [row for row in engine.list_location_records() if row["name"].casefold() == "pantry"]
    ) == 1


async def test_product_groups_can_be_created_renamed_and_deleted_safely(
    engine: InventoryEngine,
) -> None:
    group = await engine.async_create_product_group(name="Lentils")
    renamed = await engine.async_update_product_group(
        group_id=group["id"],
        name="Pulses",
    )
    product = await _create_product(
        engine,
        name="Sainsbury's Lentils",
        brand="Sainsbury's",
        group_id=group["id"],
    )

    assert renamed["id"] == group["id"]
    assert renamed["name"] == "Pulses"
    assert engine.list_products()[0]["product"]["group_name"] == "Pulses"
    with pytest.raises(InventoryError, match="still contains"):
        await engine.async_delete_product_group(group["id"])

    await engine.async_update_product(
        product_id=product["id"],
        clear_fields=["group"],
    )
    await engine.async_delete_product_group(group["id"])
    assert engine.list_product_groups() == []


async def test_product_group_names_are_case_insensitively_unique(
    engine: InventoryEngine,
) -> None:
    await engine.async_create_product_group(name="Baked Beans")

    with pytest.raises(InventoryError, match="already exists"):
        await engine.async_create_product_group(name="baked beans")


async def test_group_totals_only_combine_compatible_package_sizes(
    engine: InventoryEngine,
) -> None:
    group = await engine.async_create_product_group(name="Lentils")
    products = [
        await _create_product(
            engine,
            name="Sainsbury's Lentils",
            brand="Sainsbury's",
            barcode="01167117",
            package_size=400,
            package_unit="g",
            group_id=group["id"],
        ),
        await _create_product(
            engine,
            name="Freshona Lentils",
            brand="Freshona",
            barcode="4056489844693",
            package_size=400,
            package_unit="g",
            group_id=group["id"],
        ),
        await _create_product(
            engine,
            name="Small Lentils",
            brand="Small",
            package_size=200,
            package_unit="g",
            group_id=group["id"],
        ),
    ]
    for product, quantity, location in zip(
        products, [2, 3, 3], ["cupboard", "cupboard", "fridge"], strict=True
    ):
        await engine.async_change_stock(
            TransactionType.ADD,
            product_id=product["id"],
            quantity=quantity,
            location=location,
        )

    summary = engine.list_product_groups()[0]

    assert summary["variant_count"] == 3
    assert summary["variant_ids"] == sorted(product["id"] for product in products)
    assert summary["stock_totals"] == [
        {
            "quantity": 3,
            "unit": "item",
            "package_size": 200.0,
            "package_unit": "g",
        },
        {
            "quantity": 5,
            "unit": "item",
            "package_size": 400.0,
            "package_unit": "g",
        },
    ]
    assert set(summary["locations"]) == {"cupboard", "fridge"}


async def test_group_totals_update_after_barcode_stock_change_and_lookup_exactly(
    engine: InventoryEngine,
) -> None:
    group = await engine.async_create_product_group(name="Milk")
    first = await _create_product(
        engine,
        name="Whole milk",
        brand="Farm",
        barcode="0123",
        package_size=1,
        package_unit="L",
        group_id=group["id"],
    )
    await _create_product(
        engine,
        name="Oat milk",
        brand="Oat",
        barcode="01234",
        package_size=1,
        package_unit="L",
        group_id=group["id"],
    )
    assert engine.find_product_by_barcode("0123")["id"] == first["id"]
    assert engine.find_product_by_barcode("123") is None

    await engine.async_change_stock(
        TransactionType.ADD,
        barcode="0123",
        quantity=2,
    )

    summary = engine.list_product_groups()[0]
    assert summary["stock_totals"][0]["quantity"] == 2
    assert summary["variant_count"] == 2
    reloaded = InventoryEngine(engine.storage)
    assert reloaded.list_product_groups()[0]["stock_totals"][0]["quantity"] == 2


async def test_unknown_barcode_registration_saves_variant_and_stock_atomically(
    engine: InventoryEngine,
) -> None:
    group = await engine.async_create_product_group(name="Baked Beans")
    registered = await engine.async_register_barcode_product(
        name="Baked beans",
        brand="Freshona",
        barcode="4012345678901",
        package_size=400,
        package_unit="g",
        group_id=group["id"],
        quantity=3,
        data_source=DataSource.OPEN_FOOD_FACTS,
        operation_id="scan-baked-beans-1",
    )
    retry = await engine.async_register_barcode_product(
        name="Ignored duplicate scan details",
        barcode="4012345678901",
        quantity=3,
        group_id=group["id"],
        data_source=DataSource.OPEN_FOOD_FACTS,
        operation_id="scan-baked-beans-1",
    )

    assert registered["product"]["id"] == retry["product"]["id"]
    assert registered["product"]["data_source"] == DataSource.OPEN_FOOD_FACTS
    assert registered["stock"]["quantity"] == 3
    assert retry["stock"] == registered["stock"]
    assert len(engine.list_products()) == 1
    assert len(engine._storage.data.transactions) == 1


async def test_registering_a_known_barcode_adds_stock_to_existing_variant(
    engine: InventoryEngine,
) -> None:
    group = await engine.async_create_product_group(name="Milk")
    product = await _create_product(
        engine,
        name="Whole milk",
        brand="Farm",
        barcode="012345",
        package_size=1,
        package_unit="L",
        group_id=group["id"],
        default_storage_location="fridge",
    )

    result = await engine.async_register_barcode_product(
        name="Different lookup name",
        brand="Other brand",
        barcode="012345",
        quantity=2,
    )

    assert result["existing_variant"]
    assert result["product"]["id"] == product["id"]
    assert result["product"]["brand"] == "Farm"
    assert result["stock"]["location"] == "fridge"
    assert engine.list_product_groups()[0]["stock_totals"][0]["quantity"] == 2
    assert len(engine.list_products()) == 1


async def test_products_can_be_moved_between_groups_or_left_ungrouped(
    engine: InventoryEngine,
) -> None:
    first_group = await engine.async_create_product_group(name="Pasta")
    second_group = await engine.async_create_product_group(name="Wholegrain pasta")
    product = await _create_product(
        engine,
        name="Spaghetti",
        group_id=first_group["id"],
    )

    await engine.async_update_product(
        product_id=product["id"],
        group_id=second_group["id"],
    )
    moved = next(
        row for row in engine.list_products() if row["product"]["id"] == product["id"]
    )
    assert moved["product"]["group_id"] == second_group["id"]

    await engine.async_update_product(
        product_id=product["id"],
        clear_fields=["group"],
    )
    ungrouped = next(
        row for row in engine.list_products() if row["product"]["id"] == product["id"]
    )
    assert ungrouped["product"]["group_id"] is None
    assert ungrouped["product"]["group_name"] is None


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
