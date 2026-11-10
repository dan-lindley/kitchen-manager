"""Authenticated WebSocket commands for the Kitchen Manager panel."""

from __future__ import annotations

from typing import Any, NoReturn

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import DEFAULT_HISTORY_LIMIT, DOMAIN
from .inventory import InventoryEngine, InventoryError
from .meals import MealError, MealPlanner
from .models import ModelValidationError, TransactionType

_CLEARABLE_FIELDS = (
    "brand",
    "barcode",
    "description",
    "package",
    "reorder_threshold",
    "ingredient",
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


def _raise_user_error(
    err: InventoryError | MealError | ModelValidationError,
) -> NoReturn:
    """Convert domain validation errors to Home Assistant WebSocket errors."""
    raise ServiceValidationError(str(err), translation_domain=DOMAIN) from err


def _meal_planner(hass: HomeAssistant) -> MealPlanner:
    """Return a meal planner over the inventory engine's shared store."""
    return MealPlanner(_engine(hass).storage)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/catalog",
        vol.Optional("search_term"): cv.string,
    }
)
@websocket_api.async_response
async def websocket_catalog(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return catalogue products and their current per-location stock."""
    try:
        products = _engine(hass).list_products(msg.get("search_term"))
    except (InventoryError, ModelValidationError) as err:
        _raise_user_error(err)
    locations = _engine(hass).list_locations()
    connection.send_result(
        msg["id"],
        {"products": products, "count": len(products), "locations": locations},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/product/create",
        vol.Required("name"): cv.string,
        vol.Optional("brand"): cv.string,
        vol.Optional("barcode"): cv.string,
        vol.Optional("description"): cv.string,
        vol.Optional("package_size"): vol.Any(int, float),
        vol.Optional("package_unit"): cv.string,
        vol.Optional("ingredient_name"): cv.string,
        vol.Optional("reorder_threshold"): vol.Any(int, float),
        vol.Optional("default_storage_location"): cv.string,
    }
)
@websocket_api.async_response
async def websocket_create_product(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a catalogue product from the panel."""
    fields = {
        key: value
        for key, value in msg.items()
        if key not in {"id", "type"}
    }
    try:
        product = await _engine(hass).async_create_product(**fields)
    except (InventoryError, ModelValidationError) as err:
        _raise_user_error(err)
    connection.send_result(msg["id"], {"product": product})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/product/update",
        vol.Required("product_id"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("brand"): cv.string,
        vol.Optional("barcode"): cv.string,
        vol.Optional("description"): cv.string,
        vol.Optional("package_size"): vol.Any(int, float),
        vol.Optional("package_unit"): cv.string,
        vol.Optional("ingredient_name"): cv.string,
        vol.Optional("reorder_threshold"): vol.Any(int, float),
        vol.Optional("default_storage_location"): cv.string,
        vol.Optional("clear_fields"): vol.All(
            cv.ensure_list, [vol.In(_CLEARABLE_FIELDS)]
        ),
    }
)
@websocket_api.async_response
async def websocket_update_product(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update a catalogue product from the panel."""
    fields = {
        key: value
        for key, value in msg.items()
        if key not in {"id", "type"}
    }
    try:
        product = await _engine(hass).async_update_product(**fields)
    except (InventoryError, ModelValidationError) as err:
        _raise_user_error(err)
    connection.send_result(msg["id"], {"product": product})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/stock/change",
        vol.Required("operation"): vol.In(
            [operation.value for operation in TransactionType]
        ),
        vol.Required("product_id"): cv.string,
        vol.Required("quantity"): vol.Any(int, float),
        vol.Optional("location"): cv.string,
        vol.Optional("operation_id"): cv.string,
    }
)
@websocket_api.async_response
async def websocket_change_stock(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Add, consume, or correct stock using the shared inventory engine."""
    try:
        result = await _engine(hass).async_change_stock(
            TransactionType(msg["operation"]),
            product_id=msg["product_id"],
            quantity=msg["quantity"],
            location=msg.get("location"),
            operation_id=msg.get("operation_id"),
        )
    except (InventoryError, ModelValidationError) as err:
        _raise_user_error(err)
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/history",
        vol.Optional("limit", default=DEFAULT_HISTORY_LIMIT): vol.All(
            cv.positive_int, vol.Range(max=200)
        ),
    }
)
@websocket_api.async_response
async def websocket_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return recent stock transactions."""
    try:
        transactions = _engine(hass).get_stock_history(limit=msg["limit"])
    except (InventoryError, ModelValidationError) as err:
        _raise_user_error(err)
    connection.send_result(
        msg["id"], {"transactions": transactions, "count": len(transactions)}
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/meals"}
)
@websocket_api.async_response
async def websocket_meals(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return saved meals and their catalogue ingredient references."""
    meals = _meal_planner(hass).list_meals()
    connection.send_result(msg["id"], {"meals": meals, "count": len(meals)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/meal/save",
        vol.Required("name"): cv.string,
        vol.Required("effort"): vol.In(["low", "medium", "high"]),
        vol.Required("time_minutes"): vol.Any(int, float),
        vol.Optional("meal_id"): cv.string,
        vol.Optional("eligible_weekdays"): cv.ensure_list,
        vol.Optional("ingredients"): cv.ensure_list,
        vol.Optional("instructions"): vol.Any(None, cv.string),
        vol.Optional("recurrence"): vol.Any(
            None,
            {
                vol.Required("weekday"): vol.Any(int, float),
                vol.Required("interval_weeks"): vol.Any(int, float),
            },
        ),
    }
)
@websocket_api.async_response
async def websocket_save_meal(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create or update a meal and its optional recurrence."""
    fields = {key: value for key, value in msg.items() if key not in {"id", "type"}}
    try:
        meal = await _meal_planner(hass).async_save_meal(
            **fields,
            today=dt_util.now().date(),
        )
    except (MealError, ModelValidationError) as err:
        _raise_user_error(err)
    connection.send_result(msg["id"], {"meal": meal})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/meal/delete",
        vol.Required("meal_id"): cv.string,
    }
)
@websocket_api.async_response
async def websocket_delete_meal(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a meal and its recurrence while preserving past planner history."""
    try:
        await _meal_planner(hass).async_delete_meal(
            msg["meal_id"], today=dt_util.now().date()
        )
    except (MealError, ModelValidationError) as err:
        _raise_user_error(err)
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/planner"}
)
@websocket_api.async_response
async def websocket_planner(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the persisted four-week planner."""
    connection.send_result(
        msg["id"], _meal_planner(hass).get_planner(today=dt_util.now().date())
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/planner/generate"}
)
@websocket_api.async_response
async def websocket_generate_planner(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Persist random eligible meal suggestions for unplanned dates."""
    try:
        planner = await _meal_planner(hass).async_generate(today=dt_util.now().date())
    except (MealError, ModelValidationError) as err:
        _raise_user_error(err)
    connection.send_result(msg["id"], planner)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/planner/set",
        vol.Required("date"): cv.string,
        vol.Optional("meal_id"): vol.Any(None, cv.string),
        vol.Optional("use_recurrence", default=False): cv.boolean,
        vol.Optional("allow_ineligible", default=False): cv.boolean,
    }
)
@websocket_api.async_response
async def websocket_set_planner_day(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Assign a meal to one planner date or explicitly mark it unplanned."""
    try:
        result = await _meal_planner(hass).async_assign(
            day=msg["date"],
            meal_id=msg.get("meal_id"),
            use_recurrence=msg["use_recurrence"],
            allow_ineligible=msg["allow_ineligible"],
        )
    except (MealError, ModelValidationError) as err:
        _raise_user_error(err)
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/planner/shuffle",
        vol.Required("date"): cv.string,
    }
)
@websocket_api.async_response
async def websocket_shuffle_planner_day(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Persist a different eligible meal for one date only."""
    try:
        result = await _meal_planner(hass).async_shuffle(
            day=msg["date"], today=dt_util.now().date()
        )
    except (MealError, ModelValidationError) as err:
        _raise_user_error(err)
    connection.send_result(msg["id"], result)


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register authenticated panel commands once per Home Assistant instance."""
    for handler in (
        websocket_catalog,
        websocket_create_product,
        websocket_update_product,
        websocket_change_stock,
        websocket_history,
        websocket_meals,
        websocket_save_meal,
        websocket_delete_meal,
        websocket_planner,
        websocket_generate_planner,
        websocket_set_planner_day,
        websocket_shuffle_planner_day,
    ):
        websocket_api.async_register_command(hass, handler)
