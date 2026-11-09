"""Kitchen Manager integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .models import ModelValidationError
from .storage import KitchenManagerStorage

_LOGGER = logging.getLogger(__name__)

KitchenManagerConfigEntry = ConfigEntry[KitchenManagerStorage]


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
    entry.runtime_data = storage


async def async_unload_entry(
    _hass: HomeAssistant, _entry: KitchenManagerConfigEntry
) -> bool:
    """Unload Kitchen Manager."""
    return True
