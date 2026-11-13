"""Config flow for the Dyness Inverter integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DynessApi, DynessApiError, DynessAuthError
from .const import (
    CONF_API_ID, CONF_API_SECRET, CONF_EXTRA_SNS, CONF_HOST, CONF_REGION, CONF_SNS,
    DOMAIN, REGION_AUTO, REGIONS,
)

_LOGGER = logging.getLogger(__name__)


class DynessConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._devices: list[dict] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            api_id = user_input[CONF_API_ID].strip()
            secret = user_input[CONF_API_SECRET].strip()
            region = user_input[CONF_REGION]
            await self.async_set_unique_id(api_id)
            self._abort_if_unique_id_configured()

            hosts = list(REGIONS.values()) if region == REGION_AUTO else [REGIONS[region]]
            session = async_get_clientsession(self.hass)
            found_host: str | None = None
            auth_failures = 0
            for host in hosts:
                api = DynessApi(session, api_id, secret, host)
                try:
                    devices = await api.get_device_list()
                except DynessAuthError as err:
                    auth_failures += 1
                    _LOGGER.debug("Dyness %s: auth rejected: %s", host, err)
                    continue
                except DynessApiError as err:
                    _LOGGER.debug("Dyness %s: %s", host, err)
                    continue
                if found_host is None or (devices and not self._devices):
                    found_host, self._devices = host, devices
                if devices:
                    break

            if found_host is None:
                errors["base"] = "invalid_auth" if auth_failures else "cannot_connect"
            else:
                self._data = {CONF_API_ID: api_id, CONF_API_SECRET: secret, CONF_HOST: found_host}
                return await self.async_step_devices()

        schema = vol.Schema({
            vol.Required(CONF_API_ID): str,
            vol.Required(CONF_API_SECRET): str,
            vol.Required(CONF_REGION, default=REGION_AUTO): vol.In(
                {REGION_AUTO: "Auto-detect", **{k: k.replace("_", " ").title() for k in REGIONS}}
            ),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_devices(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        options = {}
        for d in self._devices:
            sn = str(d["deviceSn"])
            model = d.get("deviceModel") or d.get("deviceModelName") or d.get("deviceType") or ""
            options[sn] = f"{sn} {model}".strip()

        if user_input is not None:
            sns = list(user_input.get(CONF_SNS, []))
            extra = user_input.get(CONF_EXTRA_SNS, "") or ""
            sns += [s.strip() for s in extra.replace(";", ",").split(",") if s.strip()]
            sns = list(dict.fromkeys(sns))
            if not sns:
                errors["base"] = "no_devices"
            else:
                self._data[CONF_SNS] = sns
                return self.async_create_entry(title="Dyness inverter", data=self._data)

        fields: dict = {}
        if options:
            fields[vol.Optional(CONF_SNS, default=list(options))] = cv.multi_select(options)
        fields[vol.Optional(CONF_EXTRA_SNS, default="")] = str
        return self.async_show_form(
            step_id="devices",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={"count": str(len(options)), "host": self._data[CONF_HOST]},
        )
