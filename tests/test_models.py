"""Tests for Kitchen Manager data model validation."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.kitchen_manager.models import (
    Ingredient,
    InventoryItem,
    KitchenManagerData,
    ModelValidationError,
    Product,
    StorageLocation,
    VerificationStatus,
)


def test_product_requires_package_size_and_unit_together() -> None:
    """Reject incomplete package details."""
    with pytest.raises(ModelValidationError, match="must be set together"):
        Product(id="tomatoes", name="Chopped tomatoes", package_size=400)


def test_inventory_rejects_negative_quantity() -> None:
    """Reject stock quantities below zero."""
    with pytest.raises(ModelValidationError, match="non-negative"):
        InventoryItem(product_id="milk", quantity=-1, unit="carton")


def test_data_rejects_duplicate_barcodes_and_unknown_references() -> None:
    """Enforce unique barcodes and valid ingredient/product references."""
    first = Product(id="first", name="First", barcode="123")
    second = Product(id="second", name="Second", barcode="123")
    with pytest.raises(ModelValidationError, match="barcodes must be unique"):
        KitchenManagerData(products={first.id: first, second.id: second}).validate()

    item = InventoryItem(product_id="missing", quantity=1, unit="piece")
    with pytest.raises(ModelValidationError, match="unknown product"):
        KitchenManagerData(inventory={item.product_id: item}).validate()


def test_inventory_supports_estimates_and_storage_location() -> None:
    """Accept an approximate quantity and supported storage metadata."""
    item = InventoryItem(
        product_id="milk",
        quantity=1.5,
        unit="carton",
        location=StorageLocation.FRIDGE,
        verification_status=VerificationStatus.ESTIMATED,
    )
    assert item.quantity == 1.5
    assert item.verification_status is VerificationStatus.ESTIMATED


def test_data_rejects_timezone_naive_timestamps() -> None:
    """Require timestamps to include a timezone."""
    with pytest.raises(ModelValidationError, match="must include a timezone"):
        Ingredient(
            id="tomatoes",
            name="Chopped tomatoes",
            created_at=datetime.now().isoformat(),
        )


def test_data_revalidates_mutated_records_before_saving() -> None:
    """Reject invalid changes made after a model was constructed."""
    product = Product(id="milk", name="Milk")
    product.name = ""
    data = KitchenManagerData(products={product.id: product})

    with pytest.raises(ModelValidationError, match="product.name"):
        data.to_dict()


def test_record_rejects_modification_before_creation() -> None:
    """Reject timestamps that describe an impossible record history."""
    created_at = datetime.now(UTC)
    with pytest.raises(ModelValidationError, match="updated_at is before"):
        Ingredient(
            id="tomatoes",
            name="Chopped tomatoes",
            created_at=created_at.isoformat(),
            updated_at=(created_at - timedelta(seconds=1)).isoformat(),
        )


@pytest.mark.parametrize("quantity", [True, float("nan"), float("inf"), -1])
def test_inventory_rejects_invalid_quantity_values(quantity: float | bool) -> None:
    """Reject booleans, non-finite quantities, and negative stock."""
    with pytest.raises(ModelValidationError):
        InventoryItem(product_id="milk", quantity=quantity, unit="carton")


def test_data_rejects_unknown_top_level_fields() -> None:
    """Prevent unrecognized persisted fields from being dropped on the next save."""
    with pytest.raises(ModelValidationError, match="invalid shape"):
        KitchenManagerData.from_dict(
            {
                "schema_version": 1,
                "ingredients": {},
                "products": {},
                "inventory": {},
                "unrecognized": {"future_data": True},
            }
        )
