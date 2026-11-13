"""Polling coordinator for the Dyness Inverter integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DynessApi, DynessApiError, DynessAuthError
from .const import DOMAIN, EP_DEVICE_INFO, SCAN_INTERVAL, SOURCES
from .parsing import flatten

_LOGGER = logging.getLogger(__name__)


class DynessCoordinator(DataUpdateCoordinator[dict[str, dict[str, dict[str, Any]]]]):
    """Fetches every data source for every selected serial number.

    data = {sn: {"realtime": {flat_key: value}, "energy": {...}, "status": {...}}}
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: DynessApi, sns: list[str]) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL, config_entry=entry
        )
        self.api = api
        self.sns = sns
        self.device_info: dict[str, dict[str, Any]] = {}
        self.raw: dict[str, dict[str, Any]] = {sn: {} for sn in sns}

    async def async_load_device_info(self) -> None:
        for sn in self.sns:
            try:
                info = await self.api.call(EP_DEVICE_INFO, {"deviceSn": sn})
                self.device_info[sn] = info if isinstance(info, dict) else {}
                self.raw[sn]["device_info"] = info
            except DynessApiError as err:
                _LOGGER.debug("Dyness: device info for %s unavailable: %s", sn, err)
                self.device_info[sn] = {}

    async def _async_update_data(self) -> dict[str, dict[str, dict[str, Any]]]:
        result: dict[str, dict[str, dict[str, Any]]] = {}
        successes = 0
        last_error: Exception | None = None
        for sn in self.sns:
            result[sn] = {}
            for source, endpoint in SOURCES.items():
                try:
                    data = await self.api.call(endpoint, {"deviceSn": sn})
                except DynessAuthError as err:
                    last_error = err
                    _LOGGER.debug("Dyness %s %s: %s", sn, source, err)
                    continue
                except DynessApiError as err:
                    last_error = err
                    _LOGGER.debug("Dyness %s %s: %s", sn, source, err)
                    continue
                self.raw[sn][source] = data
                successes += 1
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    data = data[0]
                result[sn][source] = flatten(data) if isinstance(data, dict) else {}
        if successes == 0:
            raise UpdateFailed(f"No data from Dyness API: {last_error}")
        return result
