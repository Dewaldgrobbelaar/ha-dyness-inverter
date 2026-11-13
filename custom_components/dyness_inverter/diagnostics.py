"""Diagnostics: download the raw API responses (credentials redacted)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_ID, CONF_API_SECRET

TO_REDACT = {CONF_API_ID, CONF_API_SECRET}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "device_list": coordinator.device_list,
        "device_info": coordinator.device_info,
        "errors": coordinator.errors,
        "working_api": {sn: f"{g} @ {h}" for sn, (g, h) in coordinator.strategy.items()},
        "probe_log": coordinator.probe_log,
        "raw_responses": coordinator.raw,
        "parsed": coordinator.data,
    }
