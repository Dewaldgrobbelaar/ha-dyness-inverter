"""Sensors for the Dyness Inverter integration.

Sensors are created dynamically from whatever fields the Dyness API returns for
each device, so new/unknown fields still show up.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SOURCES
from .coordinator import DynessCoordinator
from .parsing import ENUMS, SKIP_KEYS, describe, is_list_item, leaf, to_number

_SOURCE_LABEL = {"realtime": "", "energy": "", "status": "Status "}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: DynessCoordinator = entry.runtime_data
    seen: set[tuple[str, str]] = set()

    def _new_entities() -> list[SensorEntity]:
        new: list[SensorEntity] = []
        for sn, sources in (coordinator.data or {}).items():
            for source, fields in sources.items():
                for key, value in fields.items():
                    if leaf(key) in SKIP_KEYS or value is None or value == "":
                        continue
                    if (sn, key) in seen:  # same field from two endpoints: keep the first
                        continue
                    seen.add((sn, key))
                    new.append(DynessSensor(coordinator, sn, source, key, value))
        return new

    async_add_entities([DynessApiStatusSensor(coordinator, sn) for sn in coordinator.sns] + _new_entities())

    @callback
    def _on_update() -> None:
        new = _new_entities()
        if new:
            async_add_entities(new)

    entry.async_on_unload(coordinator.async_add_listener(_on_update))


def _device_info(coordinator: DynessCoordinator, sn: str) -> DeviceInfo:
    info = coordinator.device_info.get(sn, {})
    return DeviceInfo(
        identifiers={(DOMAIN, sn)},
        name=f"Dyness {info.get('hostDeviceName') or sn}",
        manufacturer="Dyness",
        model=info.get("hostDeviceName"),
        sw_version=info.get("hostSoftwareVersion"),
        serial_number=sn,
    )


class DynessApiStatusSensor(CoordinatorEntity[DynessCoordinator], SensorEntity):
    """Shows whether Dyness returns data for this device, and the error if not."""

    _attr_has_entity_name = True
    _attr_name = "API status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud-check-outline"

    def __init__(self, coordinator: DynessCoordinator, sn: str) -> None:
        super().__init__(coordinator)
        self._sn = sn
        self._attr_unique_id = f"{DOMAIN}_{sn}_api_status"
        self._attr_device_info = _device_info(coordinator, sn)

    @property
    def native_value(self) -> str:
        errors = self.coordinator.errors.get(self._sn, {})
        ok = [s for s in SOURCES if s not in errors and (self.coordinator.data or {}).get(self._sn, {}).get(s) is not None]
        if not errors:
            return "OK"
        return "Partial" if ok else "No data"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {f"{k}_error": v[:250] for k, v in self.coordinator.errors.get(self._sn, {}).items()}


class DynessSensor(CoordinatorEntity[DynessCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: DynessCoordinator, sn: str, source: str, key: str, sample: Any) -> None:
        super().__init__(coordinator)
        self._sn, self._source, self._key = sn, source, key
        self._attr_unique_id = f"{DOMAIN}_{sn}_{source}_{key}"
        self._enum = ENUMS.get(leaf(key))
        name, unit, dclass, sclass = describe(key)
        self._attr_name = f"{_SOURCE_LABEL.get(source, '')}{name}"
        self._numeric = self._enum is None and to_number(sample) is not None

        if self._numeric:
            self._attr_native_unit_of_measurement = unit
            if dclass:
                try:
                    self._attr_device_class = SensorDeviceClass(dclass)
                except ValueError:
                    pass
            if sclass:
                self._attr_state_class = SensorStateClass(sclass)
        else:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        if is_list_item(key):  # per-cell values etc.: available but off by default
            self._attr_entity_registry_enabled_default = False
        if source == "status":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        self._attr_device_info = _device_info(coordinator, sn)

    def _raw(self) -> Any:
        return (self.coordinator.data or {}).get(self._sn, {}).get(self._source, {}).get(self._key)

    @property
    def available(self) -> bool:
        return super().available and self._raw() not in (None, "")

    @property
    def native_value(self):
        raw = self._raw()
        if raw is None:
            return None
        if self._enum is not None:
            num = to_number(raw)
            key = str(int(num)) if num is not None else str(raw)
            return self._enum.get(key, str(raw))
        if self._numeric:
            return to_number(raw)
        return str(raw)[:255]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"api_field": self._key, "source": self._source}
