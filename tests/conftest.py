import pytest
pytest_plugins = "pytest_homeassistant_custom_component"

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield

@pytest.fixture(autouse=True)
def fast(monkeypatch):
    import custom_components.dyness_inverter.api as api
    monkeypatch.setattr(api, "MIN_CALL_SPACING", 0)
