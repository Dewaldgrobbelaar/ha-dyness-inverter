"""Dyness Inverter (cloud Open API) integration for Home Assistant."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DynessApi
from .const import CONF_API_ID, CONF_API_SECRET, CONF_HOST, CONF_SNS
from .coordinator import DynessCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = DynessApi(
        async_get_clientsession(hass),
        entry.data[CONF_API_ID],
        entry.data[CONF_API_SECRET],
        entry.data[CONF_HOST],
    )
    coordinator = DynessCoordinator(hass, entry, api, list(entry.data[CONF_SNS]))
    await coordinator.async_load_device_info()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
