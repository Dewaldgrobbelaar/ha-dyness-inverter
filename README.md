# Dyness Inverter (Cloud) for Home Assistant

Reads a Dyness hybrid inverter (DYNE …L-1P-A / HT-A / LS series) and its batteries from the Dyness Open API (v2), using the App ID and App Secret from the Dyness portal (Developer Center → API Management).

- Cloud polling every 5 minutes (Dyness only refreshes cloud data every 5 minutes).
- Sensors are created automatically from whatever fields the API returns for your device: PV power, grid power/voltage/frequency, load, battery SOC/power/temperature, and daily/total energy counters.
- Energy counters are in kWh with `total_increasing`, so they work in the Energy dashboard.
- Per-cell values are created but disabled by default.
- Settings → Devices & services → Dyness Inverter → ⋮ → Download diagnostics gives the raw API replies (credentials removed).

## Install

Copy `custom_components/dyness_inverter` into `/config/custom_components/` and restart Home Assistant. Then go to Settings → Devices & services → Add integration → "Dyness Inverter (Cloud)".
