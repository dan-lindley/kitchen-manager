"""Tests for Home Assistant actions and the inventory summary sensor."""

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kitchen_manager.const import DOMAIN
from custom_components.kitchen_manager.inventory import InventoryEngine


async def test_actions_return_responses_and_update_summary(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Create products, change stock, query it, and update the summary sensor."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert isinstance(entry.runtime_data, InventoryEngine)
    await hass.async_block_till_done()

    created = await hass.services.async_call(
        DOMAIN,
        "create_product",
        {
            "name": "Milk",
            "brand": "Brand A",
            "ingredient_name": "Milk",
        },
        blocking=True,
        return_response=True,
    )
    product_id = created["product"]["id"]
    added = await hass.services.async_call(
        DOMAIN,
        "add_stock",
        {
            "product_id": product_id,
            "quantity": 2,
            "location": "fridge",
            "operation_id": "delivery-1",
        },
        blocking=True,
        return_response=True,
    )
    stock = await hass.services.async_call(
        DOMAIN,
        "get_stock",
        {"product_id": product_id},
        blocking=True,
        return_response=True,
    )
    retry = await hass.services.async_call(
        DOMAIN,
        "add_stock",
        {
            "product_id": product_id,
            "quantity": 2,
            "location": "fridge",
            "operation_id": "delivery-1",
        },
        blocking=True,
        return_response=True,
    )
    found = await hass.services.async_call(
        DOMAIN,
        "find_product",
        {"search_term": "MILK"},
        blocking=True,
        return_response=True,
    )
    updated = await hass.services.async_call(
        DOMAIN,
        "update_product",
        {"product_id": product_id, "name": "Whole milk"},
        blocking=True,
        return_response=True,
    )
    corrected = await hass.services.async_call(
        DOMAIN,
        "set_stock",
        {
            "product_id": product_id,
            "quantity": 3,
            "location": "freezer",
        },
        blocking=True,
        return_response=True,
    )
    inventory = await hass.services.async_call(
        DOMAIN,
        "list_inventory",
        {},
        blocking=True,
        return_response=True,
    )
    with pytest.raises(ServiceValidationError, match="multiple locations"):
        await hass.services.async_call(
            DOMAIN,
            "consume_stock",
            {"product_id": product_id, "quantity": 1},
            blocking=True,
            return_response=True,
        )
    consumed = await hass.services.async_call(
        DOMAIN,
        "consume_stock",
        {
            "product_id": product_id,
            "quantity": 1,
            "location": "freezer",
        },
        blocking=True,
        return_response=True,
    )
    history = await hass.services.async_call(
        DOMAIN,
        "get_stock_history",
        {"product_id": product_id, "limit": 10},
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done()

    assert added["quantity"] == 2
    assert retry == added
    assert stock["products"][0]["stock"][0]["quantity"] == 2
    assert found["count"] == 1
    assert updated["product"]["name"] == "Whole milk"
    assert corrected["quantity"] == 3
    assert {row["location"] for row in inventory["inventory"]} == {
        "fridge",
        "freezer",
    }
    assert consumed["quantity"] == 2
    assert history["count"] == 3
    for service_name in (
        "create_product",
        "update_product",
        "find_product",
        "add_stock",
        "consume_stock",
        "set_stock",
        "get_stock",
        "list_inventory",
        "get_stock_history",
    ):
        assert hass.services.has_service(DOMAIN, service_name)
    assert hass.states.get("sensor.kitchen_manager_inventory_summary").state == "1"
    assert hass.states.get(
        "sensor.kitchen_manager_inventory_summary"
    ).attributes["locations_in_use"] == 2

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert hass.services.has_service(DOMAIN, "add_stock")
    with pytest.raises(ServiceValidationError, match="loaded configuration entry"):
        await hass.services.async_call(
            DOMAIN,
            "get_stock",
            {"product_id": product_id},
            blocking=True,
            return_response=True,
        )
