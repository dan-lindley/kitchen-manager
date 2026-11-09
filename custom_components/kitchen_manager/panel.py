"""Lifecycle helpers for the Kitchen Manager sidebar panel."""

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

PANEL_PATH = "kitchen-manager"
STATIC_URL_PATH = "/kitchen_manager"
FRONTEND_PATH = Path(__file__).parent / "frontend"
_DATA_ASSETS_REGISTERED = "frontend_assets_registered"


async def async_register_panel(hass: HomeAssistant) -> None:
    """Serve the local panel module and register its sidebar entry."""
    integration_data = hass.data.setdefault(DOMAIN, {})
    if not integration_data.get(_DATA_ASSETS_REGISTERED):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    STATIC_URL_PATH,
                    str(FRONTEND_PATH),
                    cache_headers=False,
                )
            ]
        )
        integration_data[_DATA_ASSETS_REGISTERED] = True

    if frontend.async_panel_exists(hass, PANEL_PATH):
        raise HomeAssistantError(
            "The Kitchen Manager panel URL is already registered"
        )

    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_PATH,
        webcomponent_name="kitchen-manager-panel",
        sidebar_title="Kitchen Manager",
        sidebar_icon="mdi:fridge-outline",
        module_url=f"{STATIC_URL_PATH}/panel.js",
    )


def async_remove_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel when its config entry unloads."""
    frontend.async_remove_panel(hass, PANEL_PATH, warn_if_unknown=False)
