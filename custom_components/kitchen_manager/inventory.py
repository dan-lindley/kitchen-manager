"""Product catalogue and inventory operations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import json
import math
import re
from typing import Any, Protocol, TypeVar
from uuid import uuid4

from .models import (
    DataSource,
    Ingredient,
    InventoryItem,
    KitchenManagerData,
    ModelValidationError,
    OperationRecord,
    Product,
    StorageLocationRecord,
    StorageLocation,
    StockTransaction,
    TransactionType,
    VerificationStatus,
    validate_storage_location,
)


class InventoryError(ValueError):
    """Raised when a requested catalogue or inventory operation is invalid."""


_Result = TypeVar("_Result")


class InventoryStorage(Protocol):
    """Storage interface used by the inventory engine."""

    @property
    def data(self) -> KitchenManagerData:
        """Return a detached data snapshot."""

    async def async_update(
        self, mutator: Callable[[KitchenManagerData], tuple[_Result, bool]]
    ) -> _Result:
        """Apply and persist one serialized update."""


def _quantity(value: Any, field: str, *, allow_zero: bool = False) -> float:
    """Validate a finite quantity."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InventoryError(f"{field} must be a number")
    try:
        finite = math.isfinite(value)
    except OverflowError as err:
        raise InventoryError(f"{field} must be finite") from err
    if not finite or value < 0 or (not allow_zero and value == 0):
        requirement = "non-negative" if allow_zero else "greater than zero"
        raise InventoryError(f"{field} must be finite and {requirement}")
    return float(value)


def _location(value: str) -> StorageLocation | str:
    """Validate a standard or user-defined storage location."""
    try:
        return validate_storage_location(value)
    except ModelValidationError as err:
        raise InventoryError(str(err)) from err


def _product_dict(product: Product) -> dict[str, Any]:
    """Serialize a product for an action response."""
    return product.to_dict()


def _resolve_location(data: KitchenManagerData, value: str) -> str:
    """Resolve a stable location ID or a case-insensitive display name."""
    if not isinstance(value, str) or not value.strip():
        raise InventoryError("Select a configured storage location.")
    if value in data.locations:
        return value
    matching = [
        item.id
        for item in data.locations.values()
        if item.name.casefold() == value.strip().casefold()
    ]
    if matching:
        return matching[0]
    raise InventoryError(f"Unknown storage location: {value}")


def _resolve_or_create_location(data: KitchenManagerData, value: str) -> str:
    """Keep legacy inventory calls compatible without creating name duplicates."""
    try:
        return _resolve_location(data, value)
    except InventoryError:
        name = value.strip()
        if not name:
            raise
        identifier = _location_identifier(name, data.locations)
        location = StorageLocationRecord(identifier, name)
        data.locations[identifier] = location
        return identifier


def _location_identifier(name: str, locations: dict[str, StorageLocationRecord]) -> str:
    """Create a stable, readable ID that does not depend on later renaming."""
    identifier = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "location"
    identifier = identifier[:48]
    base = identifier
    suffix = 2
    while identifier in locations:
        identifier = f"{base[:48]}-{suffix}"
        suffix += 1
    return identifier


class InventoryEngine:
    """Apply atomic catalogue and inventory operations to the persistent store."""

    def __init__(self, storage: InventoryStorage) -> None:
        """Initialize the inventory engine."""
        self._storage = storage

    @property
    def storage(self) -> InventoryStorage:
        """Expose the shared storage for companion data services."""
        return self._storage

    async def async_create_product(
        self,
        *,
        name: str,
        brand: str | None = None,
        barcode: str | None = None,
        description: str | None = None,
        package_size: float | None = None,
        package_unit: str | None = None,
        ingredient_name: str | None = None,
        reorder_threshold: float | None = None,
        default_storage_location: str = "cupboard",
    ) -> dict[str, Any]:
        """Create a product and reuse or create its generic ingredient."""
        product = Product(
            id=uuid4().hex,
            name=name,
            brand=brand,
            barcode=barcode,
            description=description,
            package_size=package_size,
            package_unit=package_unit,
            reorder_threshold=reorder_threshold,
            default_storage_location=_location(default_storage_location),
            data_source=DataSource.MANUAL,
        )
        if ingredient_name is not None:
            Ingredient(id="pending", name=ingredient_name)

        def mutate(data: KitchenManagerData) -> tuple[dict[str, Any], bool]:
            if product.barcode and any(
                item.barcode == product.barcode for item in data.products.values()
            ):
                raise InventoryError(f"Barcode {product.barcode} is already assigned")
            for existing in data.products.values():
                if (
                    existing.name.casefold() == product.name.casefold()
                    and (existing.brand or "").casefold()
                    == (product.brand or "").casefold()
                    and existing.package_size == product.package_size
                    and (existing.package_unit or "").casefold()
                    == (product.package_unit or "").casefold()
                ):
                    raise InventoryError(
                        f"A matching product already exists: {existing.id}"
                    )

            if ingredient_name is not None:
                normalized = ingredient_name.strip().casefold()
                ingredient = next(
                    (
                        item
                        for item in data.ingredients.values()
                        if item.name.casefold() == normalized
                    ),
                    None,
                )
                if ingredient is None:
                    ingredient_id = re.sub(
                        r"[^a-z0-9]+", "-", normalized
                    ).strip("-") or uuid4().hex
                    if ingredient_id in data.ingredients:
                        ingredient_id = f"{ingredient_id}-{uuid4().hex[:8]}"
                    ingredient = Ingredient(id=ingredient_id, name=ingredient_name)
                    data.ingredients[ingredient.id] = ingredient
                product.ingredient_id = ingredient.id

            product.default_storage_location = _resolve_or_create_location(
                data, str(product.default_storage_location)
            )
            data.products[product.id] = product
            return _product_dict(product), True

        return await self._storage.async_update(mutate)

    async def async_update_product(
        self,
        *,
        product_id: str,
        name: str | None = None,
        brand: str | None = None,
        barcode: str | None = None,
        description: str | None = None,
        package_size: float | None = None,
        package_unit: str | None = None,
        ingredient_name: str | None = None,
        reorder_threshold: float | None = None,
        default_storage_location: str | None = None,
        clear_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update product details without changing its inventory or history."""
        if all(
            value is None
            for value in (
                name,
                brand,
                barcode,
                description,
                package_size,
                package_unit,
                ingredient_name,
                reorder_threshold,
                default_storage_location,
            )
        ) and not clear_fields:
            raise InventoryError("At least one product field must be provided")
        allowed_clear_fields = {
            "brand",
            "barcode",
            "description",
            "package",
            "reorder_threshold",
            "ingredient",
        }
        clear_fields = clear_fields or []
        if (
            not isinstance(clear_fields, list)
            or any(
                not isinstance(field, str) or field not in allowed_clear_fields
                for field in clear_fields
            )
            or len(clear_fields) != len(set(clear_fields))
        ):
            raise InventoryError("clear_fields contains an unsupported field")
        conflicting_fields = {
            "brand": brand,
            "barcode": barcode,
            "description": description,
            "package": package_size is not None or package_unit is not None,
            "reorder_threshold": reorder_threshold,
            "ingredient": ingredient_name,
            "default_storage_location": default_storage_location,
        }
        if any(conflicting_fields[field] for field in clear_fields):
            raise InventoryError("Do not provide a value for a field being cleared")

        def mutate(data: KitchenManagerData) -> tuple[dict[str, Any], bool]:
            product = data.products.get(product_id)
            if product is None:
                raise InventoryError(f"Unknown product ID: {product_id}")
            updated = Product.from_dict(product.to_dict())
            if name is not None:
                updated.name = name
            if brand is not None:
                updated.brand = brand
            if barcode is not None:
                updated.barcode = barcode
            if description is not None:
                updated.description = description
            if "brand" in clear_fields:
                updated.brand = None
            if "barcode" in clear_fields:
                updated.barcode = None
            if "description" in clear_fields:
                updated.description = None
            if package_size is not None:
                updated.package_size = package_size
            if package_unit is not None:
                updated.package_unit = package_unit
            if "package" in clear_fields:
                updated.package_size = None
                updated.package_unit = None
            if reorder_threshold is not None:
                updated.reorder_threshold = reorder_threshold
            if default_storage_location is not None:
                updated.default_storage_location = _resolve_or_create_location(
                    data, default_storage_location
                )
            if "reorder_threshold" in clear_fields:
                updated.reorder_threshold = None
            if "ingredient" in clear_fields:
                updated.ingredient_id = None
            if ingredient_name is not None:
                Ingredient(id="pending", name=ingredient_name)
                normalized = ingredient_name.casefold()
                ingredient = next(
                    (
                        item
                        for item in data.ingredients.values()
                        if item.name.casefold() == normalized
                    ),
                    None,
                )
                if ingredient is None:
                    ingredient_id = re.sub(
                        r"[^a-z0-9]+", "-", normalized
                    ).strip("-") or uuid4().hex
                    if ingredient_id in data.ingredients:
                        ingredient_id = f"{ingredient_id}-{uuid4().hex[:8]}"
                    ingredient = Ingredient(id=ingredient_id, name=ingredient_name)
                    data.ingredients[ingredient.id] = ingredient
                updated.ingredient_id = ingredient.id

            if updated.barcode and any(
                item.id != updated.id and item.barcode == updated.barcode
                for item in data.products.values()
            ):
                raise InventoryError(f"Barcode {updated.barcode} is already assigned")
            if any(
                item.id != updated.id
                and item.name.casefold() == updated.name.casefold()
                and (item.brand or "").casefold() == (updated.brand or "").casefold()
                and item.package_size == updated.package_size
                and (item.package_unit or "").casefold()
                == (updated.package_unit or "").casefold()
                for item in data.products.values()
            ):
                raise InventoryError("A matching product already exists")

            updated.updated_at = datetime.now(UTC).isoformat()
            Product.from_dict(updated.to_dict())
            data.products[product_id] = updated
            return _product_dict(updated), True

        return await self._storage.async_update(mutate)

    @staticmethod
    def _find_products(
        data: KitchenManagerData, query: str
    ) -> list[Product]:
        """Find products by exact barcode or case-insensitive name/brand substring."""
        query = query.strip()
        if not query:
            raise InventoryError("Search term must not be empty")
        products = list(data.products.values())
        barcode_matches = [product for product in products if product.barcode == query]
        if barcode_matches:
            return barcode_matches
        needle = query.casefold()
        return [
            product
            for product in sorted(products, key=lambda item: item.name.casefold())
            if needle in product.name.casefold()
            or needle in (product.brand or "").casefold()
            or needle in (product.barcode or "").casefold()
        ]

    def find_products(self, query: str) -> list[dict[str, Any]]:
        """Find products by exact barcode or case-insensitive name/brand substring."""
        return [
            _product_dict(product)
            for product in self._find_products(self._storage.data, query)
        ]

    def list_products(self, query: str | None = None) -> list[dict[str, Any]]:
        """Return catalogue products with current stock and reorder status."""
        data = self._storage.data
        if query is None or not query.strip():
            products = sorted(
                data.products.values(), key=lambda item: item.name.casefold()
            )
        else:
            products = self._find_products(data, query)
        results = []
        for product in products:
            stock = sorted(
                (
                    {
                        **item.to_dict(),
                        "location_name": data.locations[str(item.location)].name,
                    }
                    for item in data.inventory.values()
                    if item.product_id == product.id
                ),
                key=lambda item: str(item["location"]),
            )
            total_quantity = sum(item["quantity"] for item in stock)
            threshold = product.reorder_threshold
            results.append(
                {
                    "product": {
                        **_product_dict(product),
                        "default_storage_location_name": data.locations[
                            str(product.default_storage_location)
                        ].name,
                    },
                    "ingredient_name": (
                        data.ingredients[product.ingredient_id].name
                        if product.ingredient_id is not None
                        else None
                    ),
                    "stock": stock,
                    "total_quantity": total_quantity,
                    "low_stock": (
                        threshold is not None and total_quantity < threshold
                    ),
                }
            )
        return results

    def list_locations(self) -> list[str]:
        """Return configured location names for legacy callers."""
        return [
            item["name"] for item in self.list_location_records()
        ]

    def list_location_records(self) -> list[dict[str, str]]:
        """Return configured locations with their stable IDs."""
        data = self._storage.data
        return [
            location.to_dict()
            for location in sorted(
                data.locations.values(), key=lambda item: item.name.casefold()
            )
        ]

    async def async_create_location(self, *, name: str) -> dict[str, str]:
        """Create a configured storage location with a unique display name."""
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise InventoryError("Enter a non-empty trimmed location name.")
        if len(name) > 64 or any(ord(char) < 32 for char in name):
            raise InventoryError("Location names must be at most 64 printable characters.")

        def mutate(data: KitchenManagerData) -> tuple[dict[str, str], bool]:
            if any(item.name.casefold() == name.casefold() for item in data.locations.values()):
                raise InventoryError(f"A location named {name} already exists.")
            identifier = _location_identifier(name, data.locations)
            location = StorageLocationRecord(identifier, name)
            data.locations[identifier] = location
            return location.to_dict(), True

        return await self._storage.async_update(mutate)

    async def async_rename_location(
        self, *, location_id: str, name: str
    ) -> dict[str, str]:
        """Rename a configured location without changing its stable ID."""
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise InventoryError("Enter a non-empty trimmed location name.")
        if len(name) > 64 or any(ord(char) < 32 for char in name):
            raise InventoryError("Location names must be at most 64 printable characters.")

        def mutate(data: KitchenManagerData) -> tuple[dict[str, str], bool]:
            location = data.locations.get(location_id)
            if location is None:
                raise InventoryError("That storage location no longer exists.")
            if any(
                item.id != location_id and item.name.casefold() == name.casefold()
                for item in data.locations.values()
            ):
                raise InventoryError(f"A location named {name} already exists.")
            if location.name == name:
                return location.to_dict(), False
            location.name = name
            return location.to_dict(), True

        return await self._storage.async_update(mutate)

    async def async_delete_location(self, location_id: str) -> None:
        """Delete a location only when no product or stock history references it."""

        def mutate(data: KitchenManagerData) -> tuple[None, bool]:
            if location_id not in data.locations:
                raise InventoryError("That storage location no longer exists.")
            referenced = any(
                str(product.default_storage_location) == location_id
                for product in data.products.values()
            ) or any(
                str(item.location) == location_id for item in data.inventory.values()
            ) or any(
                str(item.location) == location_id for item in data.transactions
            )
            if referenced:
                raise InventoryError(
                    "This location is still used by a product, stock record, or "
                    "transaction. Reassign or remove those references first."
                )
            del data.locations[location_id]
            return None, True

        await self._storage.async_update(mutate)

    def _resolve_product(
        self,
        data: KitchenManagerData,
        *,
        product_id: str | None,
        barcode: str | None,
    ) -> Product:
        """Resolve exactly one product by internal ID or barcode."""
        if bool(product_id) == bool(barcode):
            raise InventoryError("Provide exactly one of product_id or barcode")
        if product_id:
            product = data.products.get(product_id)
            if product is None:
                raise InventoryError(f"Unknown product ID: {product_id}")
            return product
        product = next(
            (item for item in data.products.values() if item.barcode == barcode),
            None,
        )
        if product is None:
            raise InventoryError(f"No product found for barcode: {barcode}")
        return product

    @staticmethod
    def _fingerprint(
        operation: TransactionType,
        product_id: str | None,
        barcode: str | None,
        quantity: float,
        location: StorageLocation | str | None,
    ) -> str:
        """Create a stable request fingerprint for duplicate detection."""
        return json.dumps(
            {
                "operation": operation.value,
                "product_id": product_id,
                "barcode": barcode,
                "quantity": quantity,
                "location": str(location) if location is not None else None,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    async def async_change_stock(
        self,
        operation: TransactionType,
        *,
        quantity: float,
        product_id: str | None = None,
        barcode: str | None = None,
        location: str | None = None,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Add, consume, or set stock in one location with idempotent writes."""
        quantity = _quantity(
            quantity, "quantity", allow_zero=operation is TransactionType.SET
        )
        requested_location = _location(location) if location is not None else None
        if operation_id is not None and not operation_id.strip():
            raise InventoryError("operation_id must not be empty")

        def mutate(data: KitchenManagerData) -> tuple[dict[str, Any], bool]:
            if bool(product_id) == bool(barcode):
                raise InventoryError("Provide exactly one of product_id or barcode")
            selected_requested_location = (
                _resolve_or_create_location(data, str(requested_location))
                if requested_location is not None
                else None
            )
            fingerprint = self._fingerprint(
                operation, product_id, barcode, quantity, selected_requested_location
            )
            if operation_id is not None and operation_id in data.operations:
                previous = data.operations[operation_id]
                if previous.fingerprint != fingerprint:
                    raise InventoryError(
                        f"operation_id {operation_id} was already used for "
                        "a different request"
                    )
                return previous.result, False

            product = self._resolve_product(
                data, product_id=product_id, barcode=barcode
            )
            selected_location = selected_requested_location
            if selected_location is None:
                if operation is not TransactionType.CONSUME:
                    selected_location = product.default_storage_location
                else:
                    stocked_locations = [
                        item
                        for item in data.inventory.values()
                        if item.product_id == product.id and item.quantity > 0
                    ]
                    if len(stocked_locations) > 1:
                        locations = ", ".join(
                            sorted(str(item.location) for item in stocked_locations)
                        )
                        raise InventoryError(
                            "Stock exists in multiple locations "
                            f"({locations}); specify location"
                        )
                    if not stocked_locations:
                        raise InventoryError(
                            f"Insufficient stock for {product.name}: no stock remains"
                        )
                    selected_location = stocked_locations[0].location

            assert selected_location is not None

            key = data.inventory_key(product.id, selected_location)
            item = data.inventory.get(key)
            previous_quantity = item.quantity if item is not None else 0.0
            if operation is TransactionType.ADD:
                new_quantity = previous_quantity + quantity
            elif operation is TransactionType.CONSUME:
                quantities_equal = math.isclose(
                    previous_quantity, quantity, rel_tol=1e-12, abs_tol=0
                )
                if quantity > previous_quantity and not quantities_equal:
                    raise InventoryError(
                        f"Insufficient stock for {product.name} in "
                        f"{selected_location}: {previous_quantity:g} available, "
                        f"{quantity:g} requested"
                    )
                new_quantity = (
                    0.0
                    if quantities_equal
                    else previous_quantity - quantity
                )
            else:
                new_quantity = quantity
            if not math.isfinite(new_quantity):
                raise InventoryError("Resulting stock quantity is not finite")

            timestamp = datetime.now(UTC).isoformat()
            if item is None:
                item = InventoryItem(
                    product_id=product.id,
                    quantity=new_quantity,
                    unit="item",
                    location=selected_location,
                    verification_status=VerificationStatus.VERIFIED,
                    updated_at=timestamp,
                )
                data.inventory[key] = item
            else:
                item.quantity = new_quantity
                item.updated_at = timestamp
                item.verification_status = VerificationStatus.VERIFIED

            transaction = StockTransaction(
                id=uuid4().hex,
                product_id=product.id,
                operation=operation,
                quantity_changed=new_quantity - previous_quantity,
                previous_quantity=previous_quantity,
                new_quantity=new_quantity,
                location=selected_location,
                timestamp=timestamp,
                operation_id=operation_id,
            )
            data.transactions.append(transaction)
            try:
                location_label = StorageLocation(selected_location).value
            except ValueError:
                location_label = data.locations[selected_location].name
            result = {
                "product_id": product.id,
                "product_name": product.name,
                "quantity": new_quantity,
                "unit": item.unit,
                "location": location_label,
                "location_id": selected_location,
                "transaction_id": transaction.id,
                "operation_id": operation_id,
            }
            if operation_id is not None:
                data.operations[operation_id] = OperationRecord(
                    operation_id=operation_id,
                    fingerprint=fingerprint,
                    result=result,
                )
            return result, True

        return await self._storage.async_update(mutate)

    def get_stock(
        self,
        *,
        product_id: str | None = None,
        barcode: str | None = None,
        search_term: str | None = None,
        location: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return products and quantities, including zero-stock products."""
        provided = sum(bool(value) for value in (product_id, barcode, search_term))
        if provided != 1:
            raise InventoryError(
                "Provide exactly one of product_id, barcode, or search_term"
            )
        data = self._storage.data
        selected_location = (
            _resolve_location(data, location) if location is not None else None
        )
        if search_term is not None:
            products = self._find_products(data, search_term)
        else:
            products = [
                self._resolve_product(
                    data, product_id=product_id, barcode=barcode
                )
            ]
        result = []
        for product in products:
            stock = [
                {
                    **item.to_dict(),
                    "location_name": data.locations[str(item.location)].name,
                }
                for item in data.inventory.values()
                if item.product_id == product.id
                and (selected_location is None or item.location == selected_location)
            ]
            result.append(
                {
                    "product": {
                        **_product_dict(product),
                        "default_storage_location_name": data.locations[
                            str(product.default_storage_location)
                        ].name,
                    },
                    "stock": sorted(stock, key=lambda item: str(item["location"])),
                }
            )
        return result

    def list_inventory(
        self, *, location: str | None = None, product_name: str | None = None
    ) -> list[dict[str, Any]]:
        """List positive stock rows with optional location and name filters."""
        needle = product_name.casefold().strip() if product_name else None
        data = self._storage.data
        selected_location = (
            _resolve_location(data, location) if location is not None else None
        )
        result = []
        for item in data.inventory.values():
            if item.quantity <= 0:
                continue
            if selected_location is not None and item.location != selected_location:
                continue
            product = data.products[item.product_id]
            if needle and needle not in product.name.casefold():
                continue
            result.append(
                {
                    "product": _product_dict(product),
                    "quantity": item.quantity,
                    "unit": item.unit,
                    "location": str(item.location),
                    "location_name": data.locations[str(item.location)].name,
                    "updated_at": item.updated_at,
                }
            )
        return sorted(
            result,
            key=lambda row: (
                row["product"]["name"].casefold(),
                row["location"],
            ),
        )

    def get_stock_history(
        self,
        *,
        limit: int,
        product_id: str | None = None,
        barcode: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return a bounded list of newest stock transactions."""
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 200
        ):
            raise InventoryError("limit must be an integer between 1 and 200")
        if product_id and barcode:
            raise InventoryError("Provide at most one of product_id or barcode")
        data = self._storage.data
        selected_product = (
            self._resolve_product(data, product_id=product_id, barcode=barcode)
            if product_id or barcode
            else None
        )
        transactions = [
            item
            for item in data.transactions
            if selected_product is None or item.product_id == selected_product.id
        ]
        return [
            item.to_dict()
            for item in sorted(
                transactions,
                key=lambda item: datetime.fromisoformat(item.timestamp),
                reverse=True,
            )[:limit]
        ]

    def summary(self) -> dict[str, Any]:
        """Return compact aggregate inventory information."""
        data = self._storage.data
        stocked = [item for item in data.inventory.values() if item.quantity > 0]
        return {
            "stocked_products": len({item.product_id for item in stocked}),
            "total_products": len(data.products),
            "locations_in_use": len({item.location for item in stocked}),
            "last_inventory_update": (
                max(
                    data.transactions,
                    key=lambda item: datetime.fromisoformat(item.timestamp),
                ).timestamp
                if data.transactions
                else None
            ),
        }
