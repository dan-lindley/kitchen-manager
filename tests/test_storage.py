"""Tests for persistent integration storage."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from custom_components.kitchen_manager.const import DOMAIN, STORAGE_VERSION
from custom_components.kitchen_manager.inventory import InventoryEngine
from custom_components.kitchen_manager.models import (
    Ingredient,
    InventoryItem,
    KitchenManagerData,
    Product,
    StorageLocation,
    TransactionType,
)
from custom_components.kitchen_manager.storage import (
    KitchenManagerStorage,
    KitchenManagerStorageError,
)


def _make_data(quantity: float) -> KitchenManagerData:
    """Build a valid inventory snapshot for storage tests."""
    ingredient = Ingredient(id="tomatoes", name="Chopped tomatoes")
    product = Product(
        id="tomatoes-brand-a",
        name="Chopped tomatoes",
        brand="Brand A",
        barcode="0123456789012",
        package_size=400,
        package_unit="g",
        ingredient_id=ingredient.id,
    )
    item = InventoryItem(product_id=product.id, quantity=quantity, unit="can")
    return KitchenManagerData(
        ingredients={ingredient.id: ingredient},
        products={product.id: product},
        inventory={
            KitchenManagerData.inventory_key(product.id, item.location): item
        },
    )


async def test_data_survives_storage_reload(hass: HomeAssistant) -> None:
    """Persist validated data and load it through a fresh Store instance."""
    expected = _make_data(quantity=2)

    await KitchenManagerStorage(hass).async_save(expected)
    restored = await KitchenManagerStorage(hass).async_load()

    assert restored.to_dict() == expected.to_dict()


async def test_v1_store_data_is_migrated_and_persisted(
    hass: HomeAssistant,
) -> None:
    """Upgrade the Phase 1 schema and persist the migrated document."""
    old_data = _make_data(quantity=3).to_dict()
    old_data["schema_version"] = 1
    old_data.pop("transactions")
    old_data.pop("operations")
    product_id = next(iter(old_data["products"]))
    legacy_inventory_item = next(iter(old_data["inventory"].values()))
    old_data["inventory"] = {
        product_id: legacy_inventory_item
    }
    await Store(
        hass, STORAGE_VERSION, DOMAIN, atomic_writes=True
    ).async_save(old_data)

    restored = await KitchenManagerStorage(hass).async_load()
    persisted = await Store(
        hass, STORAGE_VERSION, DOMAIN, atomic_writes=True
    ).async_load()

    inventory_key = KitchenManagerData.inventory_key(
        product_id, StorageLocation.OTHER
    )
    assert restored.inventory[inventory_key].quantity == 3
    assert restored.inventory[inventory_key].location is StorageLocation.OTHER
    assert persisted is not None
    assert persisted["schema_version"] == 2


async def test_concurrent_stock_updates_are_persisted_without_lost_writes(
    hass: HomeAssistant,
) -> None:
    """Serialize concurrent engine operations through the production Store."""
    engine = InventoryEngine(KitchenManagerStorage(hass))
    product = await engine.async_create_product(name="Milk")
    await asyncio.gather(
        *(
            engine.async_change_stock(
                TransactionType.ADD,
                product_id=product["id"],
                quantity=1,
                location="fridge",
            )
            for _ in range(10)
        )
    )

    persisted = await KitchenManagerStorage(hass).async_load()
    item = persisted.inventory[
        KitchenManagerData.inventory_key(
            product["id"], StorageLocation.FRIDGE
        )
    ]
    assert item.quantity == 10
    assert len(persisted.transactions) == 10


async def test_corrupt_storage_fails_closed(hass: HomeAssistant) -> None:
    """Never start with an empty inventory after Home Assistant quarantines a file."""
    storage = KitchenManagerStorage(hass)
    path = Path(storage._store.path)
    await hass.async_add_executor_job(
        lambda: path.parent.mkdir(parents=True, exist_ok=True)
    )
    await hass.async_add_executor_job(lambda: path.write_text("{", encoding="utf-8"))

    with pytest.raises(KitchenManagerStorageError, match="corrupt or unreadable"):
        await storage.async_load()

    corrupt_files = await hass.async_add_executor_job(
        lambda: list(path.parent.glob(f"{path.name}.corrupt.*"))
    )
    assert len(corrupt_files) == 1


async def test_unverified_write_does_not_replace_runtime_data(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detect Store's logged-but-swallowed write errors and keep the prior snapshot."""
    storage = KitchenManagerStorage(hass)
    original = _make_data(quantity=2)
    await storage.async_save(original)

    monkeypatch.setattr(storage._store, "async_save", AsyncMock())
    replacement = _make_data(quantity=5)

    with pytest.raises(KitchenManagerStorageError, match="could not be verified"):
        await storage.async_save(replacement)

    assert storage.data.to_dict() == original.to_dict()
    restored = await KitchenManagerStorage(hass).async_load()
    assert restored.to_dict() == original.to_dict()


async def test_exposed_data_is_a_detached_snapshot(hass: HomeAssistant) -> None:
    """Keep edits to a returned object from mutating committed runtime data."""
    storage = KitchenManagerStorage(hass)
    original = _make_data(quantity=2)
    await storage.async_save(original)

    snapshot = storage.data
    snapshot.inventory["tomatoes-brand-a"].quantity = 9

    assert storage.data.inventory["tomatoes-brand-a"].quantity == 2
