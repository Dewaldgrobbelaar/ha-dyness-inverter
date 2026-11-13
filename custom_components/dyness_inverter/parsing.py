"""Pure helpers: flatten API responses and describe fields. No Home Assistant imports."""
from __future__ import annotations

import re
from typing import Any

_NUM_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[A-Za-z%°]*\s*$")
MAX_LIST_ITEMS = 40

# Keys that are identifiers/metadata, not measurements.
SKIP_KEYS = {"deviceSn", "sn", "collectorSn", "stationId", "stationName", "imgAddress", "position"}

# Enum fields with known meanings (from Dyness protocol docs).
ENUMS: dict[str, dict[str, str]] = {
    "gridStatus": {"0": "Standby", "1": "On-grid", "2": "Off-grid"},
    "batteryStatus": {"0": "Standby", "1": "Standby", "2": "Discharging", "3": "Charging"},
    "bmsCommunicationStatus": {"0": "Fault", "1": "OK"},
    "communicationStatus": {"0": "Offline", "1": "Online"},
}

# Explicit overrides: key -> (friendly name, unit, device_class, state_class)
KNOWN: dict[str, tuple[str, str | None, str | None, str | None]] = {
    "soc": ("Battery SOC", "%", "battery", "measurement"),
    "soh": ("Battery SOH", "%", None, "measurement"),
    "pvTotalPower": ("PV power", "W", "power", "measurement"),
    "gridPower": ("Grid power", "W", "power", "measurement"),
    "activePower": ("Active power", "W", "power", "measurement"),
    "inverterTotalPower": ("Inverter power", "W", "power", "measurement"),
    "TotalLoadPower": ("Total load power", "W", "power", "measurement"),
    "homeLoad": ("Home load", "W", "power", "measurement"),
    "backupLoadPower": ("Backup load power", "W", "power", "measurement"),
    "batteryPower": ("Battery power", "W", "power", "measurement"),
    "batteryCapacity": ("Battery capacity", "Ah", None, None),
    "dailyPvGeneration": ("PV generation today", "kWh", "energy", "total_increasing"),
    "totalPvGeneration": ("PV generation total", "kWh", "energy", "total_increasing"),
    "dailyBuyEnergy": ("Grid import today", "kWh", "energy", "total_increasing"),
    "totalBuyEnergy": ("Grid import total", "kWh", "energy", "total_increasing"),
    "dailySellEnergy": ("Grid export today", "kWh", "energy", "total_increasing"),
    "totalSellEnergy": ("Grid export total", "kWh", "energy", "total_increasing"),
    "dailyElectricity": ("Load consumption today", "kWh", "energy", "total_increasing"),
    "totalElectricity": ("Load consumption total", "kWh", "energy", "total_increasing"),
    "dailyChargeEnergy": ("Battery charge today", "kWh", "energy", "total_increasing"),
    "totalChargeEnergy": ("Battery charge total", "kWh", "energy", "total_increasing"),
    "dailyDischargeEnergy": ("Battery discharge today", "kWh", "energy", "total_increasing"),
    "totalDischargeEnergy": ("Battery discharge total", "kWh", "energy", "total_increasing"),
    "onGridDischargeDepth": ("On-grid depth of discharge", "%", None, "measurement"),
    "offGridDischargeDepth": ("Off-grid depth of discharge", "%", None, "measurement"),
    "batteryRemainingEnergy": ("Battery remaining energy", "Wh", "energy_storage", "measurement"),
    "batteryRatedEnergy": ("Battery rated energy", "Wh", "energy_storage", None),
    "cycleCount": ("Battery cycle count", None, None, "total_increasing"),
}


def to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = _NUM_RE.match(value)
        if m:
            return float(m.group(1))
    return None


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested dicts/lists into {"pvInfo_pv1Power": 123, "cellVoltageList_1": 3.3}."""
    out: dict[str, Any] = {}
    if not isinstance(obj, dict):
        return out
    for key, val in obj.items():
        full = f"{prefix}_{key}" if prefix else str(key)
        if isinstance(val, dict):
            out.update(flatten(val, full))
        elif isinstance(val, list):
            for i, item in enumerate(val[:MAX_LIST_ITEMS], start=1):
                if isinstance(item, dict):
                    out.update(flatten(item, f"{full}_{i}"))
                elif not isinstance(item, list):
                    out[f"{full}_{i}"] = item
        else:
            out[full] = val
    return out


def leaf(key: str) -> str:
    """Last segment of a flattened key, ignoring list indexes."""
    parts = [p for p in key.split("_") if not p.isdigit()]
    return parts[-1] if parts else key


def is_list_item(key: str) -> bool:
    return any(p.isdigit() for p in key.split("_"))


def humanize(key: str) -> str:
    words = []
    for part in key.split("_"):
        part = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", part)
        part = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", part)
        words.append(part)
    text = " ".join(words).replace("pv ", "PV ").replace("Pv ", "PV ")
    text = re.sub(r"\bpv\b", "PV", text, flags=re.I)
    text = re.sub(r"\b(soc|soh|bms|mppt|dsp|arm)\b", lambda m: m.group(1).upper(), text, flags=re.I)
    return text[:1].upper() + text[1:]


def describe(key: str) -> tuple[str, str | None, str | None, str | None]:
    """Return (name, unit, device_class, state_class) for a flattened key."""
    base = leaf(key)
    if base in KNOWN:
        name, unit, dclass, sclass = KNOWN[base]
        if key != base:  # nested / indexed: keep path context in the name
            name = humanize(key)
        return name, unit, dclass, sclass

    k = base.lower()
    name = humanize(key)
    if k.endswith("unit") or k.endswith("version") or k.endswith("time") or k.endswith("code"):
        return name, None, None, None
    if k in ("soc",) or k.endswith("soc"):
        return name, "%", "battery", "measurement"
    if k.endswith("soh") or "depth" in k or "percent" in k:
        return name, "%", None, "measurement"
    if "temp" in k:
        return name, "°C", "temperature", "measurement"
    if "frequency" in k or k.endswith("freq"):
        return name, "Hz", "frequency", "measurement"
    if "voltage" in k:
        return name, "V", "voltage", "measurement"
    if "current" in k:
        return name, "A", "current", "measurement"
    if any(w in k for w in ("energy", "generation", "electricity")):
        return name, "kWh", "energy", "total_increasing"
    if "power" in k or k.endswith("load"):
        return name, "W", "power", "measurement"
    return name, None, None, "measurement"
