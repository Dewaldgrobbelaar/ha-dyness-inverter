"""Minimal async client for the Dyness Open API (HMAC-SHA1 signed requests)."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from email.utils import formatdate
from typing import Any

import aiohttp

from .const import API_PREFIX, EP_DEVICE_LIST, MIN_CALL_SPACING

_LOGGER = logging.getLogger(__name__)


class DynessApiError(Exception):
    """Generic API error."""


class DynessAuthError(DynessApiError):
    """Credentials rejected (or wrong region)."""


def content_md5(body: str) -> str:
    return base64.b64encode(hashlib.md5(body.encode("utf-8")).digest()).decode()


def sign(secret: str, md5: str, date: str, path: str, method: str = "POST") -> str:
    string_to_sign = f"{method}\n{md5}\napplication/json\n{date}\n{path}"
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def build_headers(api_id: str, secret: str, body: str, path: str, date: str | None = None) -> dict:
    date = date or formatdate(timeval=None, localtime=False, usegmt=True)
    md5 = content_md5(body)
    return {
        "Content-Type": "application/json;charset=UTF-8",
        "Content-MD5": md5,
        "Date": date,
        "Authorization": f"API {api_id}:{sign(secret, md5, date, path)}",
    }


def is_success(payload: dict) -> bool:
    return str(payload.get("code")) in ("0", "200")


class DynessApi:
    """Signed POST client. Serialises calls and spaces them out."""

    def __init__(self, session: aiohttp.ClientSession, api_id: str, api_secret: str, host: str) -> None:
        self._session = session
        self._api_id = api_id.strip()
        self._secret = api_secret.strip()
        self.host = host.rstrip("/")
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def call(self, path: str, body: dict | None = None, retries: int = 3) -> Any:
        """POST to an endpoint and return the `data` field of a successful reply."""
        payload_str = json.dumps(body or {}, separators=(",", ":"))
        url = f"{self.host}{API_PREFIX}{path}"
        async with self._lock:
            for attempt in range(retries + 1):
                wait = MIN_CALL_SPACING - (time.monotonic() - self._last_call)
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_call = time.monotonic()
                headers = build_headers(self._api_id, self._secret, payload_str, path)
                try:
                    async with self._session.post(
                        url, data=payload_str, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=20),
                    ) as resp:
                        status = resp.status
                        text = await resp.text()
                except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                    raise DynessApiError(f"{path}: connection error: {err}") from err

                _LOGGER.debug("Dyness %s %s -> HTTP %s: %s", url, payload_str, status, text[:2000])

                try:
                    payload = json.loads(text) if text else {}
                except json.JSONDecodeError as err:
                    raise DynessApiError(f"{path}: HTTP {status}, not JSON: {text[:200]}") from err

                code = str(payload.get("code", status))
                if status == 429 or code == "429":
                    if attempt < retries:
                        await asyncio.sleep(5 * (attempt + 1))
                        continue
                    raise DynessApiError(f"{path}: rate limited")
                if is_success(payload):
                    return payload.get("data")
                info = payload.get("info") or payload.get("msg") or payload.get("message") or text[:200]
                if status in (401, 403) or code in ("401", "403"):
                    raise DynessAuthError(f"{path}: {code} {info}")
                raise DynessApiError(f"{path}: code={code} {info}")
        raise DynessApiError(f"{path}: no response")

    async def get_device_list(self) -> list[dict]:
        data = await self.call(EP_DEVICE_LIST, {})
        if isinstance(data, dict):
            data = data.get("list") or data.get("records") or []
        return [d for d in (data or []) if isinstance(d, dict) and d.get("deviceSn")]
