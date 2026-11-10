"""Validated data models for Kitchen Manager."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
import json
import math
import re
from typing import Any

from .const import DATA_SCHEMA_VERSION


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


@dataclass(slots=True)
class StorageLocationRecord:
    """A managed storage location with a stable identifier and editable label."""

    id: str
    name: str

    def __post_init__(self) -> None:
        self.id = _validate_text(self.id, "location.id", maximum=64)
        self.name = _validate_text(self.name, "location.name", maximum=64)
        if any(ord(char) < 32 for char in self.name):
            raise ModelValidationError("location.name must be printable")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> StorageLocationRecord:
        if not isinstance(value, dict):
            raise ModelValidationError("location must be an object")
        try:
            return cls(**value)
        except TypeError as err:
            raise ModelValidationError("location has an invalid shape") from err


def _default_locations() -> dict[str, StorageLocationRecord]:
    return {
        location.value: StorageLocationRecord(location.value, location.value.title())
        for location in StorageLocation
    }


class TransactionType(StrEnum):
    """Supported stock transaction types."""

    ADD = "add"
    CONSUME = "consume"
    SET = "set"


class MealEffort(StrEnum):
    """Preparation effort required for a meal."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PlannerMode(StrEnum):
    """How a planner date received its meal assignment."""

    FIXED = "fixed"
    RANDOM = "random"
    UNPLANNED = "unplanned"
    OVERRIDE = "override"


def _now() -> str:
    """Return a timezone-aware timestamp."""
    return datetime.now(UTC).isoformat()


def _validate_text(
    value: Any, field_name: str, *, maximum: int | None = None
) -> str:
    """Validate a required, trimmed string."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ModelValidationError(f"{field_name} must be a non-empty trimmed string")
    if maximum is not None and len(value) > maximum:
        raise ModelValidationError(f"{field_name} must be at most {maximum} characters")
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


def _validate_date(value: Any, field_name: str) -> str:
    """Validate an ISO calendar date."""
    value = _validate_text(value, field_name)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as err:
        raise ModelValidationError(f"{field_name} must be an ISO date") from err
    if parsed.isoformat() != value:
        raise ModelValidationError(f"{field_name} must be an ISO date")
    return value


def _validate_weekday(value: Any, field_name: str) -> int:
    """Validate a Monday-zero weekday integer."""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 6:
        raise ModelValidationError(f"{field_name} must be a weekday from 0 to 6")
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


def validate_storage_location(
    value: Any, field_name: str = "location"
) -> StorageLocation | str:
    """Validate a standard or user-defined storage location."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ModelValidationError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if len(value) > 64 or any(ord(char) < 32 for char in value):
        raise ModelValidationError(
            f"{field_name} must be at most 64 printable characters"
        )
    try:
        return StorageLocation(value)
    except ValueError:
        return value


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
    description: str | None = None
    package_size: float | None = None
    package_unit: str | None = None
    ingredient_id: str | None = None
    reorder_threshold: float | None = None
    default_storage_location: StorageLocation | str = StorageLocation.CUPBOARD
    data_source: DataSource = DataSource.MANUAL
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.id = _validate_text(self.id, "product.id")
        self.name = _validate_text(self.name, "product.name")
        self.brand = _validate_optional_text(self.brand, "product.brand")
        self.barcode = _validate_optional_text(self.barcode, "product.barcode")
        self.description = _validate_optional_text(
            self.description, "product.description"
        )
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
        if self.reorder_threshold is not None:
            self.reorder_threshold = _validate_number(
                self.reorder_threshold,
                "product.reorder_threshold",
                allow_zero=True,
            )
        self.default_storage_location = validate_storage_location(
            self.default_storage_location,
            "product.default_storage_location",
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
    location: StorageLocation | str = StorageLocation.OTHER
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.product_id = _validate_text(self.product_id, "inventory.product_id")
        self.quantity = _validate_number(
            self.quantity, "inventory.quantity", allow_zero=True
        )
        self.unit = _validate_text(self.unit, "inventory.unit")
        self.location = validate_storage_location(
            self.location, "inventory.location"
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
class StockTransaction:
    """An immutable audit record for a successful stock change."""

    id: str
    product_id: str
    operation: TransactionType
    quantity_changed: float
    previous_quantity: float
    new_quantity: float
    location: StorageLocation | str
    timestamp: str = field(default_factory=_now)
    operation_id: str | None = None

    def __post_init__(self) -> None:
        self.id = _validate_text(self.id, "transaction.id")
        self.product_id = _validate_text(self.product_id, "transaction.product_id")
        self.operation = _validate_enum(
            TransactionType, self.operation, "transaction.operation"
        )
        if isinstance(self.quantity_changed, bool) or not isinstance(
            self.quantity_changed, (int, float)
        ):
            raise ModelValidationError(
                "transaction.quantity_changed must be a number"
            )
        try:
            finite_change = math.isfinite(self.quantity_changed)
        except OverflowError as err:
            raise ModelValidationError(
                "transaction.quantity_changed must be finite"
            ) from err
        if not finite_change:
            raise ModelValidationError(
                "transaction.quantity_changed must be finite"
            )
        self.quantity_changed = float(self.quantity_changed)
        self.previous_quantity = _validate_number(
            self.previous_quantity, "transaction.previous_quantity", allow_zero=True
        )
        self.new_quantity = _validate_number(
            self.new_quantity, "transaction.new_quantity", allow_zero=True
        )
        self.location = validate_storage_location(
            self.location, "transaction.location"
        )
        self.timestamp = _validate_timestamp(self.timestamp, "transaction.timestamp")
        self.operation_id = _validate_optional_text(
            self.operation_id, "transaction.operation_id"
        )

        expected_change = {
            TransactionType.ADD: self.new_quantity - self.previous_quantity,
            TransactionType.CONSUME: self.new_quantity - self.previous_quantity,
            TransactionType.SET: self.new_quantity - self.previous_quantity,
        }[self.operation]
        if not math.isclose(
            self.quantity_changed, expected_change, rel_tol=1e-12, abs_tol=0
        ):
            raise ModelValidationError(
                "transaction.quantity_changed does not match previous "
                "and new quantities"
            )
        if self.operation is TransactionType.ADD and self.quantity_changed <= 0:
            raise ModelValidationError("add transactions must increase stock")
        if self.operation is TransactionType.CONSUME and self.quantity_changed >= 0:
            raise ModelValidationError("consume transactions must decrease stock")

    def to_dict(self) -> dict[str, Any]:
        """Serialize this transaction."""
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> StockTransaction:
        """Deserialize and validate a stock transaction."""
        if not isinstance(value, dict):
            raise ModelValidationError("transaction must be an object")
        try:
            return cls(**value)
        except TypeError as err:
            raise ModelValidationError("transaction has an invalid shape") from err


@dataclass(slots=True)
class OperationRecord:
    """The original request fingerprint and result for an idempotent operation."""

    operation_id: str
    fingerprint: str
    result: dict[str, Any]

    def __post_init__(self) -> None:
        self.operation_id = _validate_text(self.operation_id, "operation.operation_id")
        self.fingerprint = _validate_text(self.fingerprint, "operation.fingerprint")
        if not isinstance(self.result, dict):
            raise ModelValidationError("operation.result must be an object")

    def to_dict(self) -> dict[str, Any]:
        """Serialize this operation record."""
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> OperationRecord:
        """Deserialize and validate an operation record."""
        if not isinstance(value, dict):
            raise ModelValidationError("operation record must be an object")
        try:
            return cls(**value)
        except TypeError as err:
            raise ModelValidationError(
                "operation record has an invalid shape"
            ) from err


@dataclass(slots=True)
class MealIngredient:
    """A measured reference to a catalogue product used by a meal."""

    product_id: str
    quantity: float
    unit: str | None = None

    def validate(self) -> None:
        _validate_text(self.product_id, "meal ingredient product_id")
        _validate_number(self.quantity, "meal ingredient quantity", allow_zero=False)
        if self.unit is not None:
            _validate_text(self.unit, "meal ingredient unit", maximum=32)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> MealIngredient:
        if not isinstance(value, dict) or set(value) != {"product_id", "quantity", "unit"}:
            raise ModelValidationError("meal ingredient has an invalid shape")
        ingredient = cls(**value)
        ingredient.validate()
        return ingredient


@dataclass(slots=True)
class Meal:
    """A household recipe independent of current inventory quantities."""

    id: str
    name: str
    effort: MealEffort
    time_minutes: int
    eligible_weekdays: list[int] = field(default_factory=lambda: list(range(7)))
    ingredients: list[MealIngredient] = field(default_factory=list)
    instructions: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def validate(self) -> None:
        _validate_text(self.id, "meal id")
        _validate_text(self.name, "meal name", maximum=200)
        try:
            self.effort = MealEffort(self.effort)
        except (ValueError, TypeError) as err:
            raise ModelValidationError("meal effort must be low, medium, or high") from err
        if (
            isinstance(self.time_minutes, bool)
            or not isinstance(self.time_minutes, int)
            or self.time_minutes < 0
        ):
            raise ModelValidationError("meal time_minutes must be a non-negative integer")
        if not isinstance(self.eligible_weekdays, list) or not self.eligible_weekdays:
            raise ModelValidationError("meal must have at least one eligible weekday")
        weekdays = [_validate_weekday(day, "meal eligible weekday") for day in self.eligible_weekdays]
        if len(set(weekdays)) != len(weekdays):
            raise ModelValidationError("meal eligible weekdays must be unique")
        self.eligible_weekdays = sorted(weekdays)
        if not isinstance(self.ingredients, list):
            raise ModelValidationError("meal ingredients must be a list")
        for ingredient in self.ingredients:
            ingredient.validate()
        if self.instructions is not None:
            _validate_text(self.instructions, "meal instructions", maximum=20000)
        _validate_timestamp(self.created_at, "meal created_at")
        _validate_timestamp(self.updated_at, "meal updated_at")
        _validate_timestamp_order(self.created_at, self.updated_at, "meal")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "id": self.id,
            "name": self.name,
            "effort": str(self.effort),
            "time_minutes": self.time_minutes,
            "eligible_weekdays": self.eligible_weekdays,
            "ingredients": [item.to_dict() for item in self.ingredients],
            "instructions": self.instructions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: Any) -> Meal:
        expected = {
            "id", "name", "effort", "time_minutes", "eligible_weekdays",
            "ingredients", "instructions", "created_at", "updated_at",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ModelValidationError("meal has an invalid shape")
        try:
            effort = MealEffort(value["effort"])
        except (ValueError, TypeError) as err:
            raise ModelValidationError("meal effort must be low, medium, or high") from err
        if not isinstance(value["ingredients"], list):
            raise ModelValidationError("meal ingredients must be a list")
        if not isinstance(value["eligible_weekdays"], list):
            raise ModelValidationError("meal eligible weekdays must be a list")
        meal = cls(
            id=value["id"], name=value["name"], effort=effort,
            time_minutes=value["time_minutes"],
            eligible_weekdays=value["eligible_weekdays"],
            ingredients=[MealIngredient.from_dict(item) for item in value["ingredients"]],
            instructions=value["instructions"], created_at=value["created_at"],
            updated_at=value["updated_at"],
        )
        meal.validate()
        return meal


@dataclass(slots=True)
class RecurrenceRule:
    """A simple weekly, fortnightly, or four-week meal recurrence."""

    meal_id: str
    weekday: int
    interval_weeks: int
    anchor_date: str

    def validate(self) -> None:
        _validate_text(self.meal_id, "recurrence meal_id")
        _validate_weekday(self.weekday, "recurrence weekday")
        if (
            isinstance(self.interval_weeks, bool)
            or self.interval_weeks not in (1, 2, 4)
        ):
            raise ModelValidationError("recurrence interval must be 1, 2, or 4 weeks")
        _validate_date(self.anchor_date, "recurrence anchor_date")
        if date.fromisoformat(self.anchor_date).weekday() != self.weekday:
            raise ModelValidationError("recurrence anchor date must match its weekday")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> RecurrenceRule:
        if not isinstance(value, dict) or set(value) != {
            "meal_id", "weekday", "interval_weeks", "anchor_date"
        }:
            raise ModelValidationError("recurrence rule has an invalid shape")
        rule = cls(**value)
        rule.validate()
        return rule


@dataclass(slots=True)
class PlannerEntry:
    """A persisted choice or override for one calendar date."""

    date: str
    mode: PlannerMode
    meal_id: str | None
    meal_name: str | None
    updated_at: str = field(default_factory=_now)

    def validate(self) -> None:
        _validate_date(self.date, "planner date")
        try:
            self.mode = PlannerMode(self.mode)
        except (ValueError, TypeError) as err:
            raise ModelValidationError("planner mode is invalid") from err
        if self.meal_id is not None:
            _validate_text(self.meal_id, "planner meal_id")
            _validate_text(self.meal_name, "planner meal_name", maximum=200)
        elif self.meal_name is not None:
            raise ModelValidationError("unassigned planner entry cannot have a meal name")
        if self.mode == PlannerMode.UNPLANNED and self.meal_id is not None:
            raise ModelValidationError("unplanned entry cannot reference a meal")
        if self.mode not in (PlannerMode.UNPLANNED, PlannerMode.OVERRIDE) and self.meal_id is None:
            raise ModelValidationError("assigned planner entry must reference a meal")
        _validate_timestamp(self.updated_at, "planner updated_at")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "date": self.date,
            "mode": str(self.mode),
            "meal_id": self.meal_id,
            "meal_name": self.meal_name,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: Any) -> PlannerEntry:
        expected = {"date", "mode", "meal_id", "meal_name", "updated_at"}
        if not isinstance(value, dict) or set(value) != expected:
            raise ModelValidationError("planner entry has an invalid shape")
        try:
            mode = PlannerMode(value["mode"])
        except (ValueError, TypeError) as err:
            raise ModelValidationError("planner mode is invalid") from err
        entry = cls(
            date=value["date"],
            mode=mode,
            meal_id=value["meal_id"],
            meal_name=value["meal_name"],
            updated_at=value["updated_at"],
        )
        entry.validate()
        return entry


@dataclass(slots=True)
class KitchenManagerData:
    """The complete, validated local data set."""

    ingredients: dict[str, Ingredient] = field(default_factory=dict)
    products: dict[str, Product] = field(default_factory=dict)
    inventory: dict[str, InventoryItem] = field(default_factory=dict)
    transactions: list[StockTransaction] = field(default_factory=list)
    operations: dict[str, OperationRecord] = field(default_factory=dict)
    meals: dict[str, Meal] = field(default_factory=dict)
    recurrences: dict[str, RecurrenceRule] = field(default_factory=dict)
    planner: dict[str, PlannerEntry] = field(default_factory=dict)
    locations: dict[str, StorageLocationRecord] = field(default_factory=_default_locations)

    @staticmethod
    def inventory_key(product_id: str, location: StorageLocation | str) -> str:
        """Return the stable key for one product at one storage location."""
        return f"{product_id}::{location}"

    def validate(self) -> None:
        """Validate record keys, references, and unique barcodes."""
        for collection_name in ("ingredients", "products", "inventory", "locations"):
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
            if self.locations and str(product.default_storage_location) not in self.locations:
                raise ModelValidationError(
                    f"product {product.id} references an unknown storage location"
                )
        location_names: set[str] = set()
        for key, location in self.locations.items():
            if not isinstance(key, str) or not isinstance(location, StorageLocationRecord):
                raise ModelValidationError("locations contains an invalid record")
            StorageLocationRecord.from_dict(location.to_dict())
            if key != location.id:
                raise ModelValidationError("location key does not match its id")
            normalized_name = location.name.casefold()
            if normalized_name in location_names:
                raise ModelValidationError("storage location names must be unique")
            location_names.add(normalized_name)
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
            if key != self.inventory_key(item.product_id, item.location):
                raise ModelValidationError(
                    "inventory key does not match its product and location"
                )
            if item.product_id not in self.products:
                raise ModelValidationError(
                    f"inventory references unknown product {item.product_id}"
                )
            if self.locations and str(item.location) not in self.locations:
                raise ModelValidationError(
                    f"inventory references unknown location {item.location}"
                )
        if not isinstance(self.transactions, list):
            raise ModelValidationError("transactions must be a list")
        transaction_ids: set[str] = set()
        transactions_by_id: dict[str, StockTransaction] = {}
        for transaction in self.transactions:
            if not isinstance(transaction, StockTransaction):
                raise ModelValidationError("transactions contains an invalid record")
            StockTransaction.from_dict(transaction.to_dict())
            if transaction.id in transaction_ids:
                raise ModelValidationError("transaction IDs must be unique")
            transaction_ids.add(transaction.id)
            transactions_by_id[transaction.id] = transaction
            if transaction.product_id not in self.products:
                raise ModelValidationError(
                    f"transaction references unknown product {transaction.product_id}"
                )
            if self.locations and str(transaction.location) not in self.locations:
                raise ModelValidationError(
                    f"transaction references unknown location {transaction.location}"
                )
        prior_by_location: dict[str, float] = {}
        latest_by_location: dict[str, float] = {}
        seen_operation_ids: set[str] = set()
        for transaction in self.transactions:
            key = self.inventory_key(transaction.product_id, transaction.location)
            if key in prior_by_location and not math.isclose(
                transaction.previous_quantity,
                prior_by_location[key],
                rel_tol=1e-12,
                abs_tol=0,
            ):
                raise ModelValidationError(
                    "stock transaction history has a discontinuous quantity"
                )
            prior_by_location[key] = transaction.new_quantity
            latest_by_location[key] = transaction.new_quantity
            if transaction.operation_id is not None:
                if transaction.operation_id in seen_operation_ids:
                    raise ModelValidationError(
                        "operation IDs must be unique in transaction history"
                    )
                seen_operation_ids.add(transaction.operation_id)
        for key, quantity in latest_by_location.items():
            item = self.inventory.get(key)
            if item is None or not math.isclose(
                item.quantity, quantity, rel_tol=1e-12, abs_tol=0
            ):
                raise ModelValidationError(
                    "current inventory does not match the latest transaction"
                )
        if not isinstance(self.operations, dict):
            raise ModelValidationError("operations must be an object")
        for operation_id, operation in self.operations.items():
            if not isinstance(operation_id, str) or not isinstance(
                operation, OperationRecord
            ):
                raise ModelValidationError("operations contains an invalid record")
            OperationRecord.from_dict(operation.to_dict())
            if operation_id != operation.operation_id:
                raise ModelValidationError(
                    "operation key does not match its operation id"
                )
            transaction_id = operation.result.get("transaction_id")
            if not isinstance(transaction_id, str):
                raise ModelValidationError(
                    "operation result has an invalid transaction ID"
                )
            transaction = transactions_by_id.get(transaction_id)
            if (
                transaction is None
                or transaction.operation_id != operation_id
                or operation.result.get("product_id") != transaction.product_id
                or operation.result.get("quantity") != transaction.new_quantity
                or operation.result.get("location") != str(transaction.location)
            ):
                raise ModelValidationError(
                    "operation record does not match its stock transaction"
                )
        if seen_operation_ids != set(self.operations):
            raise ModelValidationError(
                "stock transactions and idempotency records do not match"
            )
        for collection_name in ("meals", "recurrences", "planner"):
            if not isinstance(getattr(self, collection_name), dict):
                raise ModelValidationError(f"{collection_name} must be an object")
        for meal_id, meal in self.meals.items():
            if not isinstance(meal_id, str) or not isinstance(meal, Meal):
                raise ModelValidationError("meals contains an invalid record")
            Meal.from_dict(meal.to_dict())
            if meal_id != meal.id:
                raise ModelValidationError("meal key does not match its id")
            for ingredient in meal.ingredients:
                if ingredient.product_id not in self.products:
                    raise ModelValidationError(
                        f"meal ingredient references unknown product: {ingredient.product_id}"
                    )
        recurrence_weekdays: set[int] = set()
        for meal_id, rule in self.recurrences.items():
            if not isinstance(meal_id, str) or not isinstance(rule, RecurrenceRule):
                raise ModelValidationError("recurrences contains an invalid record")
            RecurrenceRule.from_dict(rule.to_dict())
            if meal_id != rule.meal_id or meal_id not in self.meals:
                raise ModelValidationError("recurrence must reference an existing meal")
            if rule.weekday in recurrence_weekdays:
                raise ModelValidationError(
                    "only one recurring meal can be assigned per weekday"
                )
            recurrence_weekdays.add(rule.weekday)
        for day, entry in self.planner.items():
            if not isinstance(day, str) or not isinstance(entry, PlannerEntry):
                raise ModelValidationError("planner contains an invalid record")
            PlannerEntry.from_dict(entry.to_dict())
            if day != entry.date:
                raise ModelValidationError("planner key does not match its date")

    def to_dict(self) -> dict[str, Any]:
        """Validate and serialize the complete data set."""
        self.validate()
        return {
            "schema_version": DATA_SCHEMA_VERSION,
            "ingredients": {
                key: item.to_dict() for key, item in self.ingredients.items()
            },
            "products": {key: item.to_dict() for key, item in self.products.items()},
            "inventory": {
                key: item.to_dict() for key, item in self.inventory.items()
            },
            "transactions": [item.to_dict() for item in self.transactions],
            "operations": {
                key: item.to_dict() for key, item in self.operations.items()
            },
            "meals": {key: item.to_dict() for key, item in self.meals.items()},
            "recurrences": {
                key: item.to_dict() for key, item in self.recurrences.items()
            },
            "planner": {key: item.to_dict() for key, item in self.planner.items()},
            "locations": {
                key: item.to_dict() for key, item in self.locations.items()
            },
        }

    @classmethod
    def from_dict(cls, value: Any) -> KitchenManagerData:
        """Deserialize and validate the complete data set."""
        version = value.get("schema_version") if isinstance(value, dict) else None
        if isinstance(version, bool) or not isinstance(version, int):
            raise ModelValidationError("unsupported Kitchen Manager data version")
        if version == 1:
            return cls._migrate_v1_data(value)
        if version == 2:
            return cls._migrate_v2_data(value)
        if version == 3:
            return cls._migrate_v3_data(value)
        if version == 4:
            return cls._migrate_v4_data(value)
        if version == 5:
            return cls._migrate_v5_data(value)
        if version != DATA_SCHEMA_VERSION:
            raise ModelValidationError(
                f"unsupported Kitchen Manager data version: {version}"
            )
        expected_keys = {
            "schema_version",
            "ingredients",
            "products",
            "inventory",
            "transactions",
            "operations",
            "meals",
            "recurrences",
            "planner",
            "locations",
        }
        if set(value) != expected_keys:
            raise ModelValidationError("Kitchen Manager data has an invalid shape")

        records: dict[str, dict[str, Any]] = {}
        for name in (
            "ingredients",
            "products",
            "inventory",
            "operations",
            "meals",
            "recurrences",
            "planner",
            "locations",
        ):
            collection = value.get(name)
            if not isinstance(collection, dict):
                raise ModelValidationError(f"{name} must be an object")
            if not all(isinstance(key, str) for key in collection):
                raise ModelValidationError(f"{name} keys must be strings")
            records[name] = collection

        transactions = value["transactions"]
        if not isinstance(transactions, list):
            raise ModelValidationError("transactions must be a list")

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
            transactions=[
                StockTransaction.from_dict(item) for item in transactions
            ],
            operations={
                key: OperationRecord.from_dict(item)
                for key, item in records["operations"].items()
            },
            meals={
                key: Meal.from_dict(item) for key, item in records["meals"].items()
            },
            recurrences={
                key: RecurrenceRule.from_dict(item)
                for key, item in records["recurrences"].items()
            },
            planner={
                key: PlannerEntry.from_dict(item)
                for key, item in records["planner"].items()
            },
            locations={
                key: StorageLocationRecord.from_dict(item)
                for key, item in records["locations"].items()
            },
        )
        data.validate()
        return data

    @classmethod
    def _migrate_v1_data(cls, value: dict[str, Any]) -> KitchenManagerData:
        """Migrate Phase 1 inventory into per-location keys."""
        if set(value) != {"schema_version", "ingredients", "products", "inventory"}:
            raise ModelValidationError("version 1 data has an invalid shape")
        for name in ("ingredients", "products", "inventory"):
            if not isinstance(value[name], dict):
                raise ModelValidationError(f"{name} must be an object")

        migrated_inventory: dict[str, InventoryItem] = {}
        for product_id, raw_item in value["inventory"].items():
            item = InventoryItem.from_dict(raw_item)
            if product_id != item.product_id:
                raise ModelValidationError(
                    "legacy inventory key does not match its product id"
                )
            key = cls.inventory_key(item.product_id, item.location)
            migrated_inventory[key] = item

        data = cls(
            ingredients={
                key: Ingredient.from_dict(item)
                for key, item in value["ingredients"].items()
            },
            products={
                key: Product.from_dict(item)
                for key, item in value["products"].items()
            },
            inventory=migrated_inventory,
        )
        cls._infer_default_locations(data)
        cls._migrate_legacy_locations(data)
        data.validate()
        return data

    @classmethod
    def _migrate_v2_data(cls, value: dict[str, Any]) -> KitchenManagerData:
        """Add optional product description and reorder threshold fields."""
        expected_keys = {
            "schema_version",
            "ingredients",
            "products",
            "inventory",
            "transactions",
            "operations",
        }
        if set(value) != expected_keys:
            raise ModelValidationError("version 2 data has an invalid shape")
        for name in ("ingredients", "products", "inventory", "operations"):
            collection = value[name]
            if not isinstance(collection, dict):
                raise ModelValidationError(f"{name} must be an object")
            if not all(isinstance(key, str) for key in collection):
                raise ModelValidationError(f"{name} keys must be strings")
        if not isinstance(value["transactions"], list):
            raise ModelValidationError("transactions must be a list")

        data = cls(
            ingredients={
                key: Ingredient.from_dict(item)
                for key, item in value["ingredients"].items()
            },
            products={
                key: Product.from_dict(item)
                for key, item in value["products"].items()
            },
            inventory={
                key: InventoryItem.from_dict(item)
                for key, item in value["inventory"].items()
            },
            transactions=[
                StockTransaction.from_dict(item) for item in value["transactions"]
            ],
            operations={
                key: OperationRecord.from_dict(item)
                for key, item in value["operations"].items()
            },
        )
        cls._infer_default_locations(data)
        cls._migrate_legacy_locations(data)
        data.validate()
        return data

    @classmethod
    def _migrate_v3_data(cls, value: dict[str, Any]) -> KitchenManagerData:
        """Add a product default location without changing inventory records."""
        expected_keys = {
            "schema_version",
            "ingredients",
            "products",
            "inventory",
            "transactions",
            "operations",
        }
        if set(value) != expected_keys:
            raise ModelValidationError("version 3 data has an invalid shape")
        for name in ("ingredients", "products", "inventory", "operations"):
            collection = value[name]
            if not isinstance(collection, dict):
                raise ModelValidationError(f"{name} must be an object")
            if not all(isinstance(key, str) for key in collection):
                raise ModelValidationError(f"{name} keys must be strings")
        if not isinstance(value["transactions"], list):
            raise ModelValidationError("transactions must be a list")
        product_records = {}
        for key, raw_product in value["products"].items():
            if not isinstance(raw_product, dict):
                raise ModelValidationError("product must be an object")
            product_value = dict(raw_product)
            product_value["default_storage_location"] = StorageLocation.CUPBOARD
            product_records[key] = Product.from_dict(product_value)
        data = cls(
            ingredients={
                key: Ingredient.from_dict(item)
                for key, item in value["ingredients"].items()
            },
            products=product_records,
            inventory={
                key: InventoryItem.from_dict(item)
                for key, item in value["inventory"].items()
            },
            transactions=[
                StockTransaction.from_dict(item) for item in value["transactions"]
            ],
            operations={
                key: OperationRecord.from_dict(item)
                for key, item in value["operations"].items()
            },
        )
        cls._infer_default_locations(data)
        cls._migrate_legacy_locations(data)
        data.validate()
        return data

    @classmethod
    def _migrate_v4_data(cls, value: dict[str, Any]) -> KitchenManagerData:
        """Add empty meal and planner collections without touching inventory."""
        expected_keys = {
            "schema_version",
            "ingredients",
            "products",
            "inventory",
            "transactions",
            "operations",
        }
        if set(value) != expected_keys:
            raise ModelValidationError("version 4 data has an invalid shape")
        for name in ("ingredients", "products", "inventory", "operations"):
            collection = value[name]
            if not isinstance(collection, dict):
                raise ModelValidationError(f"{name} must be an object")
        if not isinstance(value["transactions"], list):
            raise ModelValidationError("transactions must be a list")
        data = cls(
            ingredients={
                key: Ingredient.from_dict(item)
                for key, item in value["ingredients"].items()
            },
            products={
                key: Product.from_dict(item)
                for key, item in value["products"].items()
            },
            inventory={
                key: InventoryItem.from_dict(item)
                for key, item in value["inventory"].items()
            },
            transactions=[
                StockTransaction.from_dict(item) for item in value["transactions"]
            ],
            operations={
                key: OperationRecord.from_dict(item)
                for key, item in value["operations"].items()
            },
        )
        cls._migrate_legacy_locations(data)
        data.validate()
        return data

    @classmethod
    def _migrate_v5_data(cls, value: dict[str, Any]) -> KitchenManagerData:
        """Add managed stable location IDs while preserving all inventory records."""
        expected_keys = {
            "schema_version",
            "ingredients",
            "products",
            "inventory",
            "transactions",
            "operations",
            "meals",
            "recurrences",
            "planner",
        }
        if not isinstance(value, dict) or set(value) != expected_keys:
            raise ModelValidationError("version 5 data has an invalid shape")
        for name in expected_keys - {"schema_version", "transactions"}:
            if not isinstance(value[name], dict):
                raise ModelValidationError(f"{name} must be an object")
        if not isinstance(value["transactions"], list):
            raise ModelValidationError("transactions must be a list")
        data = cls(
            ingredients={
                key: Ingredient.from_dict(item)
                for key, item in value["ingredients"].items()
            },
            products={
                key: Product.from_dict(item)
                for key, item in value["products"].items()
            },
            inventory={
                key: InventoryItem.from_dict(item)
                for key, item in value["inventory"].items()
            },
            transactions=[
                StockTransaction.from_dict(item) for item in value["transactions"]
            ],
            operations={
                key: OperationRecord.from_dict(item)
                for key, item in value["operations"].items()
            },
            meals={
                key: Meal.from_dict(item) for key, item in value["meals"].items()
            },
            recurrences={
                key: RecurrenceRule.from_dict(item)
                for key, item in value["recurrences"].items()
            },
            planner={
                key: PlannerEntry.from_dict(item) for key, item in value["planner"].items()
            },
        )
        cls._migrate_legacy_locations(data)
        data.validate()
        return data

    @staticmethod
    def _migrate_legacy_locations(data: KitchenManagerData) -> None:
        """Convert historical location labels into managed stable IDs."""
        names = [
            str(product.default_storage_location)
            for product in data.products.values()
        ] + [
            str(item.location) for item in data.inventory.values()
        ] + [
            str(transaction.location) for transaction in data.transactions
        ]
        aliases: dict[str, str] = {}
        location_map = {
            name.casefold(): identifier
            for identifier, name in (
                (record.id, record.name) for record in data.locations.values()
            )
        }
        for raw_name in names:
            normalized = raw_name.casefold()
            if normalized in location_map:
                aliases[raw_name] = location_map[normalized]
                continue
            identifier = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") or "location"
            identifier = identifier[:64]
            suffix = 2
            base_identifier = identifier
            while identifier in data.locations:
                identifier = f"{base_identifier[:58]}-{suffix}"
                suffix += 1
            record = StorageLocationRecord(identifier, raw_name)
            data.locations[identifier] = record
            location_map[normalized] = identifier
            aliases[raw_name] = identifier

        def resolve(value: Any) -> str:
            raw_name = str(value)
            return aliases.get(raw_name) or location_map[raw_name.casefold()]

        for product in data.products.values():
            product.default_storage_location = resolve(product.default_storage_location)

        original_inventory = list(data.inventory.values())
        merged_inventory: dict[str, InventoryItem] = {}
        for item in original_inventory:
            target = resolve(item.location)
            key = KitchenManagerData.inventory_key(item.product_id, target)
            existing = merged_inventory.get(key)
            if existing is None:
                item.location = target
                merged_inventory[key] = item
            else:
                existing.quantity += item.quantity
                if item.updated_at > existing.updated_at:
                    existing.updated_at = item.updated_at
                    existing.verification_status = item.verification_status
        data.inventory = merged_inventory

        original_transactions = sorted(
            data.transactions,
            key=lambda item: item.timestamp,
        )
        local_quantities: dict[tuple[str, str], float] = {}
        initial_quantities: dict[tuple[str, str], float] = {}
        for transaction in original_transactions:
            target = resolve(transaction.location)
            source_key = (transaction.product_id, str(transaction.location))
            aggregate_key = (transaction.product_id, target)
            if source_key not in local_quantities:
                initial_quantities[aggregate_key] = (
                    initial_quantities.get(aggregate_key, 0)
                    + transaction.previous_quantity
                )
                local_quantities[source_key] = transaction.previous_quantity
        aggregate_quantities: dict[tuple[str, str], float] = {}
        for transaction in original_transactions:
            old_location = str(transaction.location)
            target = resolve(old_location)
            old_key = (transaction.product_id, old_location)
            aggregate_key = (transaction.product_id, target)
            local_before = local_quantities[old_key]
            old_new_quantity = transaction.new_quantity
            total_before = aggregate_quantities.setdefault(
                aggregate_key, initial_quantities[aggregate_key]
            )
            delta = old_new_quantity - local_before
            total_after = total_before + delta
            transaction.previous_quantity = total_before
            transaction.new_quantity = total_after
            transaction.quantity_changed = delta
            transaction.location = target
            local_quantities[old_key] = old_new_quantity
            aggregate_quantities[aggregate_key] = total_after
        data.transactions = original_transactions

        transactions_by_id = {item.id: item for item in data.transactions}
        for operation in data.operations.values():
            transaction_id = operation.result.get("transaction_id")
            transaction = transactions_by_id.get(transaction_id)
            if transaction is None:
                continue
            operation.result.setdefault("location", str(transaction.location))
            operation.result["location_id"] = str(transaction.location)
            operation.result["quantity"] = transaction.new_quantity
            try:
                fingerprint = json.loads(operation.fingerprint)
            except json.JSONDecodeError as err:
                raise ModelValidationError(
                    "legacy operation fingerprint is invalid"
                ) from err
            if fingerprint.get("location") is not None:
                fingerprint["location"] = resolve(fingerprint["location"])
                operation.fingerprint = json.dumps(
                    fingerprint, sort_keys=True, separators=(",", ":")
                )

    @staticmethod
    def _infer_default_locations(data: KitchenManagerData) -> None:
        """Choose each product's largest existing stock location when available."""
        totals: dict[str, dict[str, float]] = {}
        for item in data.inventory.values():
            if item.quantity <= 0:
                continue
            locations = totals.setdefault(item.product_id, {})
            location = str(item.location)
            locations[location] = locations.get(location, 0) + item.quantity
        for product_id, product in data.products.items():
            if locations := totals.get(product_id):
                product.default_storage_location = validate_storage_location(
                    max(
                        locations,
                        key=lambda location: (locations[location], location),
                    ),
                    "product.default_storage_location",
                )
                continue
            existing_items = [
                item
                for item in data.inventory.values()
                if item.product_id == product_id
            ]
            if existing_items:
                product.default_storage_location = validate_storage_location(
                    max(existing_items, key=lambda item: item.updated_at).location,
                    "product.default_storage_location",
                )
                continue
            existing_transactions = [
                item
                for item in data.transactions
                if item.product_id == product_id
            ]
            if existing_transactions:
                product.default_storage_location = validate_storage_location(
                    max(
                        existing_transactions,
                        key=lambda item: item.timestamp,
                    ).location,
                    "product.default_storage_location",
                )
