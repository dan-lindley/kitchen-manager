"""Tests for integration setup and config flow."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kitchen_manager.const import DOMAIN
from custom_components.kitchen_manager.storage import KitchenManagerStorage


async def test_setup_and_unload(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Set up the integration and keep its runtime data on the config entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data, KitchenManagerStorage)
    assert entry.runtime_data.data.products == {}
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_config_flow_creates_single_entry(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Create one household entry through the UI and prevent duplicates."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "Kitchen Manager"
    assert result["result"].unique_id == DOMAIN

    duplicate = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert duplicate["type"] == "abort"
    assert duplicate["reason"] == "already_configured"
