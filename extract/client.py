from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import requests


class HubSpotClient:
    def __init__(self, token: str, base_url: str = "https://api.hubapi.com", session=None):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        for attempt in range(6):
            response = self.session.request(method, f"{self.base_url}{path}", timeout=30, **kwargs)
            if response.status_code < 400:
                return response.json()
            if response.status_code != 429 and response.status_code < 500:
                response.raise_for_status()
            if attempt == 5:
                response.raise_for_status()
            delay = float(response.headers.get("Retry-After", 2**attempt))
            time.sleep(min(delay, 30))
        raise RuntimeError("retry loop exhausted")

    def iter_objects(
        self, object_type: str, properties: list[str], modified_after: datetime | None
    ) -> Iterator[dict[str, Any]]:
        after: str | None = None
        while True:
            params: dict[str, Any] = {
                "limit": 100,
                "properties": ",".join(properties),
                "archived": "false",
            }
            if after:
                params["after"] = after
            if modified_after:
                # Search is required because the basic objects endpoint has no modified-date filter.
                body = {
                    "filterGroups": [{"filters": [{
                        "propertyName": "hs_lastmodifieddate",
                        "operator": "GTE",
                        "value": str(int(modified_after.timestamp() * 1000)),
                    }]}],
                    "properties": properties,
                    "limit": 100,
                }
                if after:
                    body["after"] = after
                page = self._request("POST", f"/crm/v3/objects/{object_type}/search", json=body)
            else:
                page = self._request("GET", f"/crm/v3/objects/{object_type}", params=params)
            yield from page.get("results", [])
            after = page.get("paging", {}).get("next", {}).get("after")
            if not after:
                break

    def iter_associations(
        self, from_type: str, object_id: str, to_type: str
    ) -> Iterator[dict[str, Any]]:
        after: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 500}
            if after:
                params["after"] = after
            page = self._request(
                "GET",
                f"/crm/v4/objects/{from_type}/{object_id}/associations/{to_type}",
                params=params,
            )
            yield from page.get("results", [])
            after = page.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
