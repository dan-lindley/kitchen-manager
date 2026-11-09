"""Kitchen Manager integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import async_register_websocket_commands
from .const import DOMAIN
from .inventory import InventoryEngine
from .models import ModelValidationError
from .panel import async_register_panel, async_remove_panel
from .services import async_setup_services
from .storage import KitchenManagerStorage

_LOGGER = logging.getLogger(__name__)

PLATFORMS = (Platform.SENSOR,)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
KitchenManagerConfigEntry = ConfigEntry[InventoryEngine]


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Register Kitchen Manager actions even when no entry is loaded."""
    async_setup_services(hass)
    async_register_websocket_commands(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: KitchenManagerConfigEntry
) -> None:
    """Set up Kitchen Manager from a config entry."""
    storage = KitchenManagerStorage(hass)
    try:
        await storage.async_load()
    except ModelValidationError as err:
        _LOGGER.exception("Stored Kitchen Manager data failed validation")
        raise HomeAssistantError(
            "Stored Kitchen Manager data is invalid; see the log for details"
        ) from err
    entry.runtime_data = InventoryEngine(storage)
    await async_register_panel(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)


async def async_unload_entry(
    hass: HomeAssistant, entry: KitchenManagerConfigEntry
) -> bool:
    """Unload Kitchen Manager platforms."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    async_remove_panel(hass)
    return True
