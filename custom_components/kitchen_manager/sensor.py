"""Inventory summary sensor for Kitchen Manager."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, INVENTORY_UPDATED_SIGNAL
from .inventory import InventoryEngine

SUMMARY_DESCRIPTION = EntityDescription(key="inventory_summary", icon="mdi:food")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[InventoryEngine],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the single aggregate inventory sensor."""
    async_add_entities([KitchenManagerInventorySummary(entry.runtime_data)])


class KitchenManagerInventorySummary(SensorEntity):
    """Expose compact aggregate inventory information."""

    entity_description = SUMMARY_DESCRIPTION
    _attr_name = "Kitchen Manager Inventory Summary"

    def __init__(self, engine: InventoryEngine) -> None:
        """Initialize the summary sensor."""
        self._engine = engine
        self._attr_unique_id = f"{DOMAIN}_inventory_summary"
        self._update_state()

    def _update_state(self) -> None:
        """Refresh state and compact aggregate attributes."""
        summary = self._engine.summary()
        self._attr_native_value = summary["stocked_products"]
        self._attr_extra_state_attributes = {
            "total_products": summary["total_products"],
            "locations_in_use": summary["locations_in_use"],
            "last_inventory_update": summary["last_inventory_update"],
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to committed inventory updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, INVENTORY_UPDATED_SIGNAL, self._handle_inventory_update
            )
        )

    @callback
    def _handle_inventory_update(self) -> None:
        """Update sensor state after a successful persisted change."""
        self._update_state()
        self.async_write_ha_state()
