import base64, hashlib, hmac, json
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.dyness_inverter.api import build_headers
from custom_components.dyness_inverter.parsing import flatten, describe

SECRET = "test-secret-not-real"
AF = "https://af-openapi.dyness.com/openapi/ems-device"
GL = "https://global-openapi.dyness.com/openapi/ems-device"
SN = "103120023B070099"
BAT = "BX51100-ABC"

def shopf_sig(secret, md5, date, path):  # reference implementation from shopf/dyness_battery
    sts = "POST" + "\n" + md5 + "\n" + "application/json" + "\n" + date + "\n" + path
    return base64.b64encode(hmac.new(secret.encode(), sts.encode(), "sha1").digest()).decode()

def test_signature_matches_reference():
    body = '{"deviceSn":"X"}'
    date = "Fri, 13 Nov 2026 11:00:00 GMT"
    h = build_headers("ID", SECRET, body, "/v2/GetRealTimeDataBySN", date)
    md5 = base64.b64encode(hashlib.md5(body.encode()).digest()).decode()
    assert h["Content-MD5"] == md5
    assert h["Authorization"] == f"API ID:{shopf_sig(SECRET, md5, date, '/v2/GetRealTimeDataBySN')}"

def test_flatten_and_describe():
    f = flatten({"pvInfo": {"dailyPvGeneration": "12.5"}, "cellVoltageList": [3.3, 3.31]})
    assert f == {"pvInfo_dailyPvGeneration": "12.5", "cellVoltageList_1": 3.3, "cellVoltageList_2": 3.31}
    assert describe("pvInfo_dailyPvGeneration")[1:] == ("kWh", "energy", "total_increasing")
    assert describe("pvTotalPower")[0:2] == ("PV power", "W")
    assert describe("gridFrequency")[1] == "Hz"

def ok(data): return {"code": "200", "info": "success", "data": data}

async def test_full_flow(hass, aioclient_mock):
    aioclient_mock.post(f"{AF}/v2/GetDeviceList", json=ok([
        {"deviceSn": SN, "deviceModel": "DYNE8.0L-1P-A", "communicationStatus": 1},
        {"deviceSn": BAT, "deviceModel": "BX51100"}]))
    aioclient_mock.post(f"{AF}/v2/GetDeviceInfBySN", json=ok({"hostDeviceName": "DYNE8.0L-1P-A", "hostSoftwareVersion": "1.2"}))
    aioclient_mock.post(f"{AF}/v2/GetRealTimeDataBySN", json=ok({
        "deviceSn": SN, "soc": "87", "pvTotalPower": 3450, "gridPower": -120, "gridFrequency": "50.01Hz",
        "gridStatus": 1, "batteryPower": 1500, "batteryTemperature": 24.5, "cellVoltageList": [3.3, 3.31],
        "bmsSoftwareVersion": "V1.0"}))
    aioclient_mock.post(f"{AF}/v2/GetTotalEnergyDataBySN", json=ok({
        "pvInfo": {"dailyPvGeneration": 18.2, "totalPvGeneration": 1234.5},
        "gridInfo": {"dailyBuyEnergy": 2.1}}))
    aioclient_mock.post(f"{AF}/v2/GetStatusInfBySN", json={"code": "500", "info": "not supported"})

    result = await hass.config_entries.flow.async_init("dyness_inverter", context={"source": config_entries.SOURCE_USER})
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "api_id": "123456789", "api_secret": SECRET, "region": "auto"})
    assert result["step_id"] == "devices", result
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device_sns": [SN], "extra_sns": ""})
    assert result["type"] == FlowResultType.CREATE_ENTRY, result
    assert result["data"]["host"] == "https://af-openapi.dyness.com"
    await hass.async_block_till_done()

    # Check signed headers on a real request
    for call in aioclient_mock.mock_calls:
        method, url, data, headers = call[:4]
        assert headers["Authorization"].startswith("API 123456789:")

    states = {s.entity_id: s for s in hass.states.async_all("sensor")}
    print("\n".join(f"{k} = {v.state} {v.attributes.get('unit_of_measurement','')}" for k, v in sorted(states.items())))
    soc = [s for s in states.values() if s.attributes.get("api_field") == "soc"][0]
    assert soc.state == "87.0" and soc.attributes["device_class"] == "battery"
    grid = [s for s in states.values() if s.attributes.get("api_field") == "gridStatus"][0]
    assert grid.state == "On-grid"
    freq = [s for s in states.values() if s.attributes.get("api_field") == "gridFrequency"][0]
    assert freq.state == "50.01"
    pv = [s for s in states.values() if s.attributes.get("api_field") == "pvInfo_totalPvGeneration"][0]
    assert pv.attributes["state_class"] == "total_increasing" and pv.attributes["unit_of_measurement"] == "kWh"
    reg = er.async_get(hass)
    cell = [e for e in reg.entities.values() if e.unique_id.endswith("cellVoltageList_1")][0]
    assert cell.disabled_by is not None

async def test_auth_fail(hass, aioclient_mock):
    for host in ["af-openapi","global-openapi","eu-openapi","open-api","apacopen-api","me-openapi","na-openapi","latam-openapi","sa-openapi"]:
        aioclient_mock.post(f"https://{host}.dyness.com/openapi/ems-device/v2/GetDeviceList", status=401, json={"code": "401", "info": "ACCESS_DENIED"})
    result = await hass.config_entries.flow.async_init("dyness_inverter", context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_id": "x", "api_secret": "y", "region": "auto"})
    assert result["errors"] == {"base": "invalid_auth"}

async def test_manual_sn_when_list_empty(hass, aioclient_mock):
    aioclient_mock.post(f"{AF}/v2/GetDeviceList", status=401, json={"code": "401"})
    aioclient_mock.post(f"{GL}/v2/GetDeviceList", json=ok([]))
    for h in ["eu-openapi","open-api","apacopen-api","me-openapi","na-openapi","latam-openapi","sa-openapi"]:
        aioclient_mock.post(f"https://{h}.dyness.com/openapi/ems-device/v2/GetDeviceList", status=401, json={"code":"401"})
    for ep in ["GetDeviceInfBySN","GetRealTimeDataBySN","GetTotalEnergyDataBySN","GetStatusInfBySN"]:
        aioclient_mock.post(f"{GL}/v2/{ep}", json=ok({"soc": 50}))
    result = await hass.config_entries.flow.async_init("dyness_inverter", context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_id": "x", "api_secret": "y", "region": "auto"})
    assert result["step_id"] == "devices"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"extra_sns": SN})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["host"].startswith("https://global") and result["data"]["device_sns"] == [SN]

async def test_unsupported_model_stays_loaded(hass, aioclient_mock):
    aioclient_mock.post(f"{AF}/v2/GetDeviceList", json=ok([{"deviceSn": SN}]))
    for ep in ["GetDeviceInfBySN","GetRealTimeDataBySN","GetTotalEnergyDataBySN","GetStatusInfBySN"]:
        aioclient_mock.post(f"{AF}/v2/{ep}", json={"code": "500", "info": "The current device model does not support API access"})
    result = await hass.config_entries.flow.async_init("dyness_inverter", context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_id": "x", "api_secret": "y", "region": "africa"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device_sns": [SN], "extra_sns": ""})
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries("dyness_inverter")[0]
    assert entry.state.value == "loaded"
    st = [s for s in hass.states.async_all("sensor") if s.entity_id.endswith("api_status")][0]
    assert st.state == "No data" and "not support" in st.attributes["status_error"]
    from custom_components.dyness_inverter.diagnostics import async_get_config_entry_diagnostics
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["device_list"] == [{"deviceSn": SN}] and diag["errors"][SN]
