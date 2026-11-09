"""Validated data models for Kitchen Manager."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import math
from typing import Any


class ModelValidationError(ValueError):
    """Raised when persisted or newly created model data is invalid."""


class DataSource(StrEnum):
    """Origin of a product record."""

    MANUAL = "manual"
    OPEN_FOOD_FACTS = "open_food_facts"


class StorageLocation(StrEnum):
    """Where household stock is stored."""

    FRIDGE = "fridge"
    FREEZER = "freezer"
    CUPBOARD = "cupboard"
    OTHER = "other"


class VerificationStatus(StrEnum):
    """How precisely an inventory quantity is known."""

    UNVERIFIED = "unverified"
    ESTIMATED = "estimated"
    VERIFIED = "verified"


def _now() -> str:
    """Return a timezone-aware timestamp."""
    return datetime.now(UTC).isoformat()


def _validate_text(value: Any, field_name: str) -> str:
    """Validate a required, trimmed string."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ModelValidationError(f"{field_name} must be a non-empty trimmed string")
    return value


def _validate_optional_text(value: Any, field_name: str) -> str | None:
    """Validate an optional, trimmed string."""
    if value is None:
        return None
    return _validate_text(value, field_name)


def _validate_timestamp(value: Any, field_name: str) -> str:
    """Validate an ISO timestamp that includes timezone information."""
    value = _validate_text(value, field_name)
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as err:
        raise ModelValidationError(f"{field_name} must be an ISO timestamp") from err
    if timestamp.utcoffset() is None:
        raise ModelValidationError(f"{field_name} must include a timezone")
    return value


def _validate_timestamp_order(
    created_at: str, updated_at: str, field_name: str
) -> None:
    """Ensure a record's modification time is not before its creation time."""
    if datetime.fromisoformat(updated_at) < datetime.fromisoformat(created_at):
        raise ModelValidationError(f"{field_name}.updated_at is before created_at")


def _validate_number(value: Any, field_name: str, *, allow_zero: bool) -> float:
    """Validate a finite, non-negative number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelValidationError(f"{field_name} must be a number")
    try:
        is_finite = math.isfinite(value)
    except OverflowError as err:
        raise ModelValidationError(f"{field_name} must be finite") from err
    if not is_finite or value < 0 or (not allow_zero and value == 0):
        qualifier = "positive" if not allow_zero else "non-negative"
        raise ModelValidationError(f"{field_name} must be finite and {qualifier}")
    return float(value)


def _validate_enum[T: StrEnum](enum_type: type[T], value: Any, field_name: str) -> T:
    """Validate and normalize an enum value."""
    try:
        return enum_type(value)
    except (ValueError, TypeError) as err:
        raise ModelValidationError(f"{field_name} has an unsupported value") from err


@dataclass(slots=True)
class Ingredient:
    """A generic ingredient shared by multiple commercial products."""

    id: str
    name: str
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.id = _validate_text(self.id, "ingredient.id")
        self.name = _validate_text(self.name, "ingredient.name")
        self.created_at = _validate_timestamp(self.created_at, "ingredient.created_at")
        self.updated_at = _validate_timestamp(self.updated_at, "ingredient.updated_at")
        _validate_timestamp_order(self.created_at, self.updated_at, "ingredient")

    def to_dict(self) -> dict[str, Any]:
        """Serialize this ingredient."""
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> Ingredient:
        """Deserialize and validate an ingredient."""
        if not isinstance(value, dict):
            raise ModelValidationError("ingredient must be an object")
        try:
            return cls(**value)
        except TypeError as err:
            raise ModelValidationError("ingredient has an invalid shape") from err


@dataclass(slots=True)
class Product:
    """A barcode-addressable commercial product."""

    id: str
    name: str
    brand: str | None = None
    barcode: str | None = None
    package_size: float | None = None
    package_unit: str | None = None
    ingredient_id: str | None = None
    data_source: DataSource = DataSource.MANUAL
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.id = _validate_text(self.id, "product.id")
        self.name = _validate_text(self.name, "product.name")
        self.brand = _validate_optional_text(self.brand, "product.brand")
        self.barcode = _validate_optional_text(self.barcode, "product.barcode")
        self.ingredient_id = _validate_optional_text(
            self.ingredient_id, "product.ingredient_id"
        )
        self.data_source = _validate_enum(
            DataSource, self.data_source, "product.data_source"
        )
        if self.package_size is not None:
            self.package_size = _validate_number(
                self.package_size, "product.package_size", allow_zero=False
            )
        self.package_unit = _validate_optional_text(
            self.package_unit, "product.package_unit"
        )
        if (self.package_size is None) != (self.package_unit is None):
            raise ModelValidationError(
                "product.package_size and product.package_unit must be set together"
            )
        self.created_at = _validate_timestamp(self.created_at, "product.created_at")
        self.updated_at = _validate_timestamp(self.updated_at, "product.updated_at")
        _validate_timestamp_order(self.created_at, self.updated_at, "product")

    def to_dict(self) -> dict[str, Any]:
        """Serialize this product."""
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> Product:
        """Deserialize and validate a product."""
        if not isinstance(value, dict):
            raise ModelValidationError("product must be an object")
        try:
            return cls(**value)
        except TypeError as err:
            raise ModelValidationError("product has an invalid shape") from err


@dataclass(slots=True)
class InventoryItem:
    """The current quantity and storage details for a product."""

    product_id: str
    quantity: float
    unit: str
    location: StorageLocation = StorageLocation.OTHER
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.product_id = _validate_text(self.product_id, "inventory.product_id")
        self.quantity = _validate_number(
            self.quantity, "inventory.quantity", allow_zero=True
        )
        self.unit = _validate_text(self.unit, "inventory.unit")
        self.location = _validate_enum(
            StorageLocation, self.location, "inventory.location"
        )
        self.verification_status = _validate_enum(
            VerificationStatus,
            self.verification_status,
            "inventory.verification_status",
        )
        self.updated_at = _validate_timestamp(
            self.updated_at, "inventory.updated_at"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize this inventory item."""
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> InventoryItem:
        """Deserialize and validate an inventory item."""
        if not isinstance(value, dict):
            raise ModelValidationError("inventory item must be an object")
        try:
            return cls(**value)
        except TypeError as err:
            raise ModelValidationError("inventory item has an invalid shape") from err


@dataclass(slots=True)
class KitchenManagerData:
    """The complete, validated local data set."""

    ingredients: dict[str, Ingredient] = field(default_factory=dict)
    products: dict[str, Product] = field(default_factory=dict)
    inventory: dict[str, InventoryItem] = field(default_factory=dict)

    def validate(self) -> None:
        """Validate record keys, references, and unique barcodes."""
        for collection_name in ("ingredients", "products", "inventory"):
            collection = getattr(self, collection_name)
            if not isinstance(collection, dict):
                raise ModelValidationError(f"{collection_name} must be an object")

        for key, ingredient in self.ingredients.items():
            if not isinstance(key, str) or not isinstance(ingredient, Ingredient):
                raise ModelValidationError("ingredients contains an invalid record")
            Ingredient.from_dict(ingredient.to_dict())
            if key != ingredient.id:
                raise ModelValidationError("ingredient key does not match its id")
        for key, product in self.products.items():
            if not isinstance(key, str) or not isinstance(product, Product):
                raise ModelValidationError("products contains an invalid record")
            Product.from_dict(product.to_dict())
            if key != product.id:
                raise ModelValidationError("product key does not match its id")
            if product.ingredient_id and product.ingredient_id not in self.ingredients:
                raise ModelValidationError(
                    f"product {product.id} references an unknown ingredient"
                )
        barcodes = [
            product.barcode
            for product in self.products.values()
            if product.barcode is not None
        ]
        if len(barcodes) != len(set(barcodes)):
            raise ModelValidationError("product barcodes must be unique")
        for key, item in self.inventory.items():
            if not isinstance(key, str) or not isinstance(item, InventoryItem):
                raise ModelValidationError("inventory contains an invalid record")
            InventoryItem.from_dict(item.to_dict())
            if key != item.product_id:
                raise ModelValidationError(
                    "inventory key does not match its product id"
                )
            if item.product_id not in self.products:
                raise ModelValidationError(
                    f"inventory references unknown product {item.product_id}"
                )

    def to_dict(self) -> dict[str, Any]:
        """Validate and serialize the complete data set."""
        self.validate()
        return {
            "schema_version": 1,
            "ingredients": {
                key: item.to_dict() for key, item in self.ingredients.items()
            },
            "products": {key: item.to_dict() for key, item in self.products.items()},
            "inventory": {
                key: item.to_dict() for key, item in self.inventory.items()
            },
        }

    @classmethod
    def from_dict(cls, value: Any) -> KitchenManagerData:
        """Deserialize and validate the complete data set."""
        version = value.get("schema_version") if isinstance(value, dict) else None
        if isinstance(version, bool) or not isinstance(version, int) or version != 1:
            raise ModelValidationError("unsupported Kitchen Manager data version")
        expected_keys = {"schema_version", "ingredients", "products", "inventory"}
        if set(value) != expected_keys:
            raise ModelValidationError("Kitchen Manager data has an invalid shape")

        records: dict[str, dict[str, Any]] = {}
        for name in ("ingredients", "products", "inventory"):
            collection = value.get(name)
            if not isinstance(collection, dict):
                raise ModelValidationError(f"{name} must be an object")
            if not all(isinstance(key, str) for key in collection):
                raise ModelValidationError(f"{name} keys must be strings")
            records[name] = collection

        data = cls(
            ingredients={
                key: Ingredient.from_dict(item)
                for key, item in records["ingredients"].items()
            },
            products={
                key: Product.from_dict(item)
                for key, item in records["products"].items()
            },
            inventory={
                key: InventoryItem.from_dict(item)
                for key, item in records["inventory"].items()
            },
        )
        data.validate()
        return data
