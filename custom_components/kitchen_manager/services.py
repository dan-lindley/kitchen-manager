"""Home Assistant actions for Kitchen Manager."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DEFAULT_HISTORY_LIMIT, DOMAIN
from .inventory import InventoryEngine, InventoryError
from .models import ModelValidationError, TransactionType

_LOCATION_SCHEMA = vol.Any("fridge", "freezer", "cupboard", "other")
_PRODUCT_SELECTOR = {
    vol.Optional("product_id"): cv.string,
    vol.Optional("barcode"): cv.string,
}
_STOCK_CHANGE_FIELDS = {
    **_PRODUCT_SELECTOR,
    vol.Required("quantity"): vol.Any(int, float),
    vol.Optional("location"): _LOCATION_SCHEMA,
    vol.Optional("operation_id"): cv.string,
}

CREATE_PRODUCT_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Optional("brand"): cv.string,
        vol.Optional("barcode"): cv.string,
        vol.Optional("package_size"): vol.Any(int, float),
        vol.Optional("package_unit"): cv.string,
        vol.Optional("ingredient_name"): cv.string,
    }
)
UPDATE_PRODUCT_SCHEMA = vol.Schema(
    {
        vol.Required("product_id"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("brand"): cv.string,
        vol.Optional("barcode"): cv.string,
        vol.Optional("package_size"): vol.Any(int, float),
        vol.Optional("package_unit"): cv.string,
        vol.Optional("ingredient_name"): cv.string,
    }
)
FIND_PRODUCT_SCHEMA = vol.Schema(
    {
        vol.Required("search_term"): cv.string,
    }
)
STOCK_CHANGE_SCHEMA = vol.Schema(_STOCK_CHANGE_FIELDS)
STOCK_CHANGE_REQUIRED_LOCATION_SCHEMA = vol.Schema(
    {
        **_PRODUCT_SELECTOR,
        vol.Required("quantity"): vol.Any(int, float),
        vol.Required("location"): _LOCATION_SCHEMA,
        vol.Optional("operation_id"): cv.string,
    }
)
GET_STOCK_SCHEMA = vol.Schema(
    {
        vol.Optional("product_id"): cv.string,
        vol.Optional("barcode"): cv.string,
        vol.Optional("search_term"): cv.string,
        vol.Optional("location"): _LOCATION_SCHEMA,
    }
)
LIST_INVENTORY_SCHEMA = vol.Schema(
    {
        vol.Optional("location"): _LOCATION_SCHEMA,
        vol.Optional("product_name"): cv.string,
    }
)
HISTORY_SCHEMA = vol.Schema(
    {
        **_PRODUCT_SELECTOR,
        vol.Optional("limit", default=DEFAULT_HISTORY_LIMIT): vol.All(
            cv.positive_int, vol.Range(max=200)
        ),
    }
)


def _engine(hass: HomeAssistant) -> InventoryEngine:
    """Return the sole loaded Kitchen Manager engine."""
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if len(entries) != 1:
        raise ServiceValidationError(
            "Kitchen Manager must have exactly one loaded configuration entry"
        )
    engine = entries[0].runtime_data
    if not isinstance(engine, InventoryEngine):
        raise ServiceValidationError("Kitchen Manager is not ready")
    return engine


def _product_selector(data: dict[str, Any]) -> tuple[str | None, str | None]:
    """Extract and validate the product ID or barcode selector."""
    product_id = data.get("product_id")
    barcode = data.get("barcode")
    if bool(product_id) == bool(barcode):
        raise ServiceValidationError("Provide exactly one of product_id or barcode")
    return product_id, barcode


def _validation_error(
    err: InventoryError | ModelValidationError,
) -> ServiceValidationError:
    """Convert bad user input into a Home Assistant action error."""
    return ServiceValidationError(str(err), translation_domain=DOMAIN)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register actions once, independently of config-entry load state."""

    async def create_product(call: ServiceCall) -> ServiceResponse:
        try:
            product = await _engine(hass).async_create_product(**call.data)
        except (InventoryError, ModelValidationError) as err:
            raise _validation_error(err) from err
        return {"product": product}

    async def update_product(call: ServiceCall) -> ServiceResponse:
        try:
            product = await _engine(hass).async_update_product(**call.data)
        except (InventoryError, ModelValidationError) as err:
            raise _validation_error(err) from err
        return {"product": product}

    async def find_product(call: ServiceCall) -> ServiceResponse:
        try:
            products = _engine(hass).find_products(call.data["search_term"])
        except (InventoryError, ModelValidationError) as err:
            raise _validation_error(err) from err
        return {"products": products, "count": len(products)}

    def stock_action(
        operation: TransactionType,
    ) -> Callable[[ServiceCall], ServiceResponse]:
        async def handler(call: ServiceCall) -> ServiceResponse:
            try:
                product_id, barcode = _product_selector(call.data)
                result = await _engine(hass).async_change_stock(
                    operation,
                    product_id=product_id,
                    barcode=barcode,
                    quantity=call.data["quantity"],
                    location=call.data.get("location"),
                    operation_id=call.data.get("operation_id"),
                )
            except (InventoryError, ModelValidationError) as err:
                raise _validation_error(err) from err
            return result

        return handler

    async def get_stock(call: ServiceCall) -> ServiceResponse:
        try:
            results = _engine(hass).get_stock(**call.data)
        except (InventoryError, ModelValidationError) as err:
            raise _validation_error(err) from err
        return {"products": results, "count": len(results)}

    async def list_inventory(call: ServiceCall) -> ServiceResponse:
        try:
            inventory = _engine(hass).list_inventory(**call.data)
        except (InventoryError, ModelValidationError) as err:
            raise _validation_error(err) from err
        return {"inventory": inventory, "count": len(inventory)}

    async def get_stock_history(call: ServiceCall) -> ServiceResponse:
        try:
            product_id, barcode = _product_selector(
                {key: value for key, value in call.data.items() if key != "limit"}
            ) if "product_id" in call.data or "barcode" in call.data else (None, None)
            transactions = _engine(hass).get_stock_history(
                product_id=product_id,
                barcode=barcode,
                limit=call.data["limit"],
            )
        except (InventoryError, ModelValidationError) as err:
            raise _validation_error(err) from err
        return {"transactions": transactions, "count": len(transactions)}

    registrations = (
        ("create_product", create_product, CREATE_PRODUCT_SCHEMA),
        ("update_product", update_product, UPDATE_PRODUCT_SCHEMA),
        ("find_product", find_product, FIND_PRODUCT_SCHEMA),
        (
            "add_stock",
            stock_action(TransactionType.ADD),
            STOCK_CHANGE_REQUIRED_LOCATION_SCHEMA,
        ),
        ("consume_stock", stock_action(TransactionType.CONSUME), STOCK_CHANGE_SCHEMA),
        (
            "set_stock",
            stock_action(TransactionType.SET),
            STOCK_CHANGE_REQUIRED_LOCATION_SCHEMA,
        ),
        ("get_stock", get_stock, GET_STOCK_SCHEMA),
        ("list_inventory", list_inventory, LIST_INVENTORY_SCHEMA),
        ("get_stock_history", get_stock_history, HISTORY_SCHEMA),
    )
    for service_name, handler, schema in registrations:
        hass.services.async_register(
            DOMAIN,
            service_name,
            handler,
            schema=schema,
            supports_response=SupportsResponse.ONLY,
        )
