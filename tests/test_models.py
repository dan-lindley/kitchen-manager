"""Tests for Kitchen Manager data model validation."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.kitchen_manager.models import (
    Ingredient,
    InventoryItem,
    KitchenManagerData,
    ModelValidationError,
    OperationRecord,
    Product,
    StorageLocation,
    StockTransaction,
    TransactionType,
    VerificationStatus,
)


def test_product_requires_package_size_and_unit_together() -> None:
    """Reject incomplete package details."""
    with pytest.raises(ModelValidationError, match="must be set together"):
        Product(id="tomatoes", name="Chopped tomatoes", package_size=400)


def test_product_accepts_reorder_threshold_and_description() -> None:
    """Keep optional household product metadata in the catalogue."""
    product = Product(
        id="milk",
        name="Milk",
        description="Whole milk",
        reorder_threshold=2,
    )

    assert product.reorder_threshold == 2
    assert product.description == "Whole milk"


@pytest.mark.parametrize("threshold", [-1, float("nan"), float("inf"), True])
def test_product_rejects_invalid_reorder_threshold(
    threshold: float | bool,
) -> None:
    """Reject invalid optional low-stock values."""
    with pytest.raises(ModelValidationError):
        Product(id="milk", name="Milk", reorder_threshold=threshold)


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
    key = KitchenManagerData.inventory_key(item.product_id, item.location)
    with pytest.raises(ModelValidationError, match="unknown product"):
        KitchenManagerData(inventory={key: item}).validate()


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


def test_v1_data_migrates_and_preserves_saved_location() -> None:
    """Keep Phase 1 product, inventory, and saved location data."""
    ingredient = Ingredient(id="tomatoes", name="Chopped tomatoes")
    product = Product(
        id="tomatoes-can",
        name="Chopped tomatoes",
        ingredient_id=ingredient.id,
    )
    item = InventoryItem(
        product_id=product.id,
        quantity=3,
        unit="item",
        location=StorageLocation.FRIDGE,
    )
    old_data = {
        "schema_version": 1,
        "ingredients": {ingredient.id: ingredient.to_dict()},
        "products": {
            product.id: {
                key: value
                for key, value in product.to_dict().items()
                if key
                not in {
                    "description",
                    "reorder_threshold",
                    "default_storage_location",
                }
            }
        },
        "inventory": {product.id: item.to_dict()},
    }

    migrated = KitchenManagerData.from_dict(old_data)

    assert migrated.inventory[
        KitchenManagerData.inventory_key(product.id, StorageLocation.FRIDGE)
    ].quantity == 3
    assert migrated.inventory[
        KitchenManagerData.inventory_key(product.id, StorageLocation.FRIDGE)
    ].location is StorageLocation.FRIDGE
    assert migrated.transactions == []
    assert migrated.to_dict()["schema_version"] == 4
    assert (
        migrated.products[product.id].default_storage_location
        is StorageLocation.FRIDGE
    )


def test_v2_data_migrates_with_optional_product_metadata() -> None:
    """Preserve the complete Phase 2 inventory when adding product metadata."""
    product = Product(id="milk", name="Milk", barcode="123")
    item = InventoryItem(
        product_id=product.id, quantity=2, unit="item", location=StorageLocation.FRIDGE
    )
    product_data = product.to_dict()
    product_data.pop("description")
    product_data.pop("reorder_threshold")
    product_data.pop("default_storage_location")
    v2_data = {
        "schema_version": 2,
        "ingredients": {},
        "products": {product.id: product_data},
        "inventory": {
            KitchenManagerData.inventory_key(
                product.id, item.location
            ): item.to_dict()
        },
        "transactions": [],
        "operations": {},
    }

    migrated = KitchenManagerData.from_dict(v2_data)

    assert migrated.products[product.id].barcode == "123"
    assert migrated.products[product.id].description is None
    assert migrated.products[product.id].reorder_threshold is None
    assert migrated.inventory[
        KitchenManagerData.inventory_key(product.id, item.location)
    ].quantity == 2
    assert migrated.to_dict()["schema_version"] == 4
    assert (
        migrated.products[product.id].default_storage_location
        is StorageLocation.FRIDGE
    )


def test_v3_migration_infers_largest_stock_location_without_changing_records() -> None:
    """Choose the product default from the largest legacy stock location."""
    product = Product(id="milk", name="Milk")
    fridge = InventoryItem(
        product_id=product.id, quantity=2, unit="item", location="fridge"
    )
    pantry = InventoryItem(
        product_id=product.id, quantity=5, unit="item", location="pantry"
    )
    transactions = [
        StockTransaction(
            id="fridge-stock",
            product_id=product.id,
            operation=TransactionType.ADD,
            quantity_changed=2,
            previous_quantity=0,
            new_quantity=2,
            location="fridge",
        ),
        StockTransaction(
            id="pantry-stock",
            product_id=product.id,
            operation=TransactionType.ADD,
            quantity_changed=5,
            previous_quantity=0,
            new_quantity=5,
            location="pantry",
        ),
    ]
    product_data = product.to_dict()
    product_data.pop("default_storage_location")
    v3_data = {
        "schema_version": 3,
        "ingredients": {},
        "products": {product.id: product_data},
        "inventory": {
            KitchenManagerData.inventory_key(
                product.id, fridge.location
            ): fridge.to_dict(),
            KitchenManagerData.inventory_key(
                product.id, pantry.location
            ): pantry.to_dict(),
        },
        "transactions": [item.to_dict() for item in transactions],
        "operations": {},
    }

    migrated = KitchenManagerData.from_dict(v3_data)

    assert migrated.products[product.id].default_storage_location == "pantry"
    assert migrated.inventory[
        KitchenManagerData.inventory_key(product.id, "fridge")
    ].quantity == 2
    assert migrated.inventory[
        KitchenManagerData.inventory_key(product.id, "pantry")
    ].quantity == 5
    assert {item.id for item in migrated.transactions} == {
        "fridge-stock",
        "pantry-stock",
    }
    assert migrated.to_dict()["schema_version"] == 4


def test_product_supports_custom_storage_location() -> None:
    """Allow a household-specific location as a default and inventory location."""
    product = Product(
        id="pasta", name="Pasta", default_storage_location="baking cupboard"
    )
    stock = InventoryItem(
        product_id=product.id,
        quantity=1,
        unit="item",
        location="baking cupboard",
    )

    assert product.default_storage_location == "baking cupboard"
    assert stock.location == "baking cupboard"


def test_transaction_history_must_match_current_inventory() -> None:
    """Reject persisted stock and transaction records that disagree."""
    product = Product(id="milk", name="Milk")
    item = InventoryItem(
        product_id=product.id, quantity=2, unit="item", location=StorageLocation.FRIDGE
    )
    transaction = StockTransaction(
        id="transaction-1",
        product_id=product.id,
        operation=TransactionType.ADD,
        quantity_changed=1,
        previous_quantity=0,
        new_quantity=1,
        location=StorageLocation.FRIDGE,
    )
    data = KitchenManagerData(
        products={product.id: product},
        inventory={KitchenManagerData.inventory_key(product.id, item.location): item},
        transactions=[transaction],
    )

    with pytest.raises(ModelValidationError, match="does not match"):
        data.validate()


def test_idempotency_record_must_match_its_stock_transaction() -> None:
    """Reject malformed retries that could return a mismatched success response."""
    product = Product(id="milk", name="Milk")
    item = InventoryItem(
        product_id=product.id, quantity=2, unit="item", location=StorageLocation.FRIDGE
    )
    transaction = StockTransaction(
        id="transaction-1",
        product_id=product.id,
        operation=TransactionType.ADD,
        quantity_changed=2,
        previous_quantity=0,
        new_quantity=2,
        location=StorageLocation.FRIDGE,
        operation_id="delivery-1",
    )
    operation = OperationRecord(
        operation_id="delivery-1",
        fingerprint="{}",
        result={
            "product_id": product.id,
            "quantity": 2,
            "location": StorageLocation.FRIDGE.value,
            "transaction_id": transaction.id,
        },
    )
    data = KitchenManagerData(
        products={product.id: product},
        inventory={KitchenManagerData.inventory_key(product.id, item.location): item},
        transactions=[transaction],
        operations={operation.operation_id: operation},
    )
    data.validate()

    operation.result["transaction_id"] = []
    with pytest.raises(ModelValidationError, match="invalid transaction ID"):
        data.validate()
