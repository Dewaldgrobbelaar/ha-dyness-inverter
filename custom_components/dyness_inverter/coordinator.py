"""Polling coordinator for the Dyness Inverter integration.

Dyness exposes two API generations and several regional servers, and not every
device model is enabled on every combination. For each serial number the
coordinator probes the known combinations once, remembers the first one that
returns data, and records every attempt for diagnostics.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import DynessApi, DynessApiError
from .const import (
    DOMAIN, EP_DEVICE_INFO, EP_V1_BIND, EP_V1_POWER, EP_V1_REALTIME, REGIONS,
    SCAN_INTERVAL, SOURCES,
)
from .parsing import flatten

_LOGGER = logging.getLogger(__name__)

REPROBE_AFTER = 3600  # seconds between probe rounds while nothing works


class DynessCoordinator(DataUpdateCoordinator[dict[str, dict[str, dict[str, Any]]]]):
    """data = {sn: {source: {flat_key: value}}}"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: DynessApi, sns: list[str]) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL, config_entry=entry
        )
        self.api = api
        self.sns = sns
        self._apis: dict[str, DynessApi] = {api.host: api}
        self.device_info: dict[str, dict[str, Any]] = {}
        self.raw: dict[str, dict[str, Any]] = {sn: {} for sn in sns}
        self.errors: dict[str, dict[str, str]] = {sn: {} for sn in sns}
        self.device_list: list[dict] | str | None = None
        # sn -> ("v2" | "v1", host)
        self.strategy: dict[str, tuple[str, str]] = {}
        self.probe_log: dict[str, list[str]] = {sn: [] for sn in sns}
        self._last_probe: dict[str, float] = {}

    def _api_for(self, host: str) -> DynessApi:
        if host not in self._apis:
            self._apis[host] = DynessApi(
                async_get_clientsession(self.hass), self.api._api_id, self.api._secret, host
            )
        return self._apis[host]

    async def async_load_device_info(self) -> None:
        try:
            self.device_list = await self.api.get_device_list()
        except DynessApiError as err:
            self.device_list = f"error: {err}"
        for sn in self.sns:
            try:
                info = await self.api.call(EP_DEVICE_INFO, {"deviceSn": sn})
                self.device_info[sn] = info if isinstance(info, dict) else {}
                self.raw[sn]["device_info"] = info
            except DynessApiError as err:
                self.errors[sn]["device_info"] = str(err)
                self.device_info[sn] = {}

    # ---- probing -------------------------------------------------------
    def _candidates(self) -> list[tuple[str, str]]:
        hosts = [self.api.host] + [h for h in (
            REGIONS["global"], REGIONS["europe"], REGIONS["africa"],
            REGIONS["europe_legacy"], REGIONS["asia_pacific"],
        ) if h != self.api.host]
        v2 = [("v2", h) for h in hosts[:4]]
        v1 = [("v1", h) for h in hosts]
        return v2 + v1

    async def _probe(self, sn: str) -> None:
        log = self.probe_log[sn]
        log.clear()
        for gen, host in self._candidates():
            api = self._api_for(host)
            label = f"{gen} @ {host}"
            try:
                if gen == "v2":
                    data = await api.call(SOURCES["realtime"], {"deviceSn": sn}, retries=1)
                else:
                    try:
                        await api.call(EP_V1_BIND, {"deviceSn": sn}, retries=1)
                        log.append(f"{label} bindSn: ok")
                    except DynessApiError as err:
                        log.append(f"{label} bindSn: {err}")
                    data = await api.call(
                        EP_V1_POWER, {"pageNo": 1, "pageSize": 1, "deviceSn": sn}, retries=1
                    )
                    if not data:
                        data = await api.call(EP_V1_REALTIME, {"deviceSn": sn}, retries=1)
            except DynessApiError as err:
                log.append(f"{label}: {err}")
                continue
            if data:
                log.append(f"{label}: OK")
                self.strategy[sn] = (gen, host)
                self.errors[sn] = {}  # earlier failures were from other combinations
                _LOGGER.info("Dyness: %s works for %s", label, sn)
                return
            log.append(f"{label}: success but empty data")
        _LOGGER.warning("Dyness: no API combination returned data for %s: %s", sn, log)

    # ---- fetching ------------------------------------------------------
    async def _fetch_v2(self, sn: str, host: str, out: dict) -> int:
        api, ok = self._api_for(host), 0
        for source, endpoint in SOURCES.items():
            try:
                data = await api.call(endpoint, {"deviceSn": sn})
            except DynessApiError as err:
                self.errors[sn][source] = str(err)
                continue
            self.errors[sn].pop(source, None)
            self.raw[sn][source] = data
            if isinstance(data, list) and data and isinstance(data[0], dict):
                data = data[0]
            out[source] = flatten(data) if isinstance(data, dict) else {}
            ok += 1
        return ok

    async def _fetch_v1(self, sn: str, host: str, out: dict) -> int:
        api, ok = self._api_for(host), 0
        try:
            data = await api.call(EP_V1_POWER, {"pageNo": 1, "pageSize": 1, "deviceSn": sn})
            self.raw[sn]["power"] = data
            if isinstance(data, dict):
                data = data.get("list") or data.get("records") or data
            if isinstance(data, list):
                data = data[-1] if data else {}
            out["power"] = flatten(data) if isinstance(data, dict) else {}
            self.errors[sn].pop("power", None)
            ok += 1
        except DynessApiError as err:
            self.errors[sn]["power"] = str(err)
        try:
            data = await api.call(EP_V1_REALTIME, {"deviceSn": sn})
            self.raw[sn]["points"] = data
            points = {}
            for item in data or []:
                if isinstance(item, dict) and "pointId" in item:
                    points[f"point_{item['pointId']}"] = item.get("pointValue")
            out["points"] = points
            self.errors[sn].pop("points", None)
            ok += 1
        except DynessApiError as err:
            self.errors[sn]["points"] = str(err)
        return ok

    async def _async_update_data(self) -> dict[str, dict[str, dict[str, Any]]]:
        result: dict[str, dict[str, dict[str, Any]]] = {}
        successes = 0
        for sn in self.sns:
            result[sn] = {}
            if sn not in self.strategy:
                # First try the default (v2 on the configured host) the cheap way.
                if sn not in self._last_probe:
                    n = await self._fetch_v2(sn, self.api.host, result[sn])
                    if n:
                        self.strategy[sn] = ("v2", self.api.host)
                        successes += n
                        continue
                if time.monotonic() - self._last_probe.get(sn, -REPROBE_AFTER) >= REPROBE_AFTER:
                    self._last_probe[sn] = time.monotonic()
                    await self._probe(sn)
                if sn not in self.strategy:
                    continue
            gen, host = self.strategy[sn]
            if gen == "v2":
                successes += await self._fetch_v2(sn, host, result[sn])
            else:
                successes += await self._fetch_v1(sn, host, result[sn])
        if successes == 0:
            _LOGGER.warning("Dyness: no data returned for %s", self.sns)
        return result
