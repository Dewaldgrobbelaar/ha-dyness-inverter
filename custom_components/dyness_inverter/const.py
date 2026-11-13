"""Constants for the Dyness Inverter integration."""
from datetime import timedelta

DOMAIN = "dyness_inverter"

CONF_API_ID = "api_id"
CONF_API_SECRET = "api_secret"
CONF_REGION = "region"
CONF_HOST = "host"
CONF_SNS = "device_sns"
CONF_EXTRA_SNS = "extra_sns"

REGION_AUTO = "auto"

# Dyness Open API hosts (v2). Order matters for "auto" detection.
REGIONS: dict[str, str] = {
    "africa": "https://af-openapi.dyness.com",
    "global": "https://global-openapi.dyness.com",
    "europe": "https://eu-openapi.dyness.com",
    "europe_legacy": "https://open-api.dyness.com",
    "asia_pacific": "https://apacopen-api.dyness.com",
    "middle_east": "https://me-openapi.dyness.com",
    "north_america": "https://na-openapi.dyness.com",
    "latin_america": "https://latam-openapi.dyness.com",
    "south_america": "https://sa-openapi.dyness.com",
}

API_PREFIX = "/openapi/ems-device"

EP_DEVICE_LIST = "/v2/GetDeviceList"
EP_DEVICE_INFO = "/v2/GetDeviceInfBySN"
EP_REALTIME = "/v2/GetRealTimeDataBySN"
EP_ENERGY = "/v2/GetTotalEnergyDataBySN"
EP_STATUS = "/v2/GetStatusInfBySN"

# Data sources polled for every device: key -> endpoint
SOURCES: dict[str, str] = {
    "realtime": EP_REALTIME,
    "energy": EP_ENERGY,
    "status": EP_STATUS,
}

# Dyness refreshes cloud data every 5 minutes; polling faster gains nothing.
SCAN_INTERVAL = timedelta(minutes=5)
# Minimum spacing between two API calls (rate-limit protection).
MIN_CALL_SPACING = 2.0
