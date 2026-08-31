from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import requests

# Contacts expose their modification time under a different property name than
# every other CRM object. Filtering contacts on hs_lastmodifieddate does not
# error, it silently returns zero results, so an incremental run would quietly
# stop seeing contact changes after the first load. Verified against a live
# portal: contacts respond to lastmodifieddate only, companies and deals reject
# it and respond to hs_lastmodifieddate only.
MODIFIED_PROPERTY = {
    "contacts": "lastmodifieddate",
    "companies": "hs_lastmodifieddate",
    "deals": "hs_lastmodifieddate",
}

# The search endpoint refuses to page beyond 10,000 results for one query.
SEARCH_RESULT_CAP = 10_000

# The v4 association batch endpoint accepts 100 ids per call.
ASSOCIATION_BATCH_SIZE = 100

PAGE_SIZE = 100


def modified_property(object_type: str) -> str:
    try:
        return MODIFIED_PROPERTY[object_type]
    except KeyError:
        raise ValueError(f"unsupported object type: {object_type}") from None


def _to_millis(value: str | int) -> int:
    if isinstance(value, int):
        return value
    if value.isdigit():
        return int(value)
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


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
        """Every record of object_type, or every record modified since a watermark.

        The incremental path sorts ascending by modification time. That is what
        makes the 10,000 result cap survivable: at the cap the query is
        re-anchored on the last record seen rather than abandoned.
        """
        modified_field = modified_property(object_type)
        if modified_after is None:
            yield from self._iter_all(object_type, properties)
            return

        cursor_value = str(int(modified_after.timestamp() * 1000))
        after: str | None = None
        seen_in_query = 0

        while True:
            body: dict[str, Any] = {
                "filterGroups": [{"filters": [{
                    "propertyName": modified_field,
                    "operator": "GTE",
                    "value": cursor_value,
                }]}],
                "sorts": [{"propertyName": modified_field, "direction": "ASCENDING"}],
                "properties": properties,
                "limit": PAGE_SIZE,
            }
            if after:
                body["after"] = after
            page = self._request("POST", f"/crm/v3/objects/{object_type}/search", json=body)
            results = page.get("results", [])
            if not results:
                return
            yield from results

            seen_in_query += len(results)
            after = page.get("paging", {}).get("next", {}).get("after")
            if not after:
                return
            if seen_in_query + PAGE_SIZE > SEARCH_RESULT_CAP:
                last_seen = results[-1].get("properties", {}).get(modified_field)
                if not last_seen:
                    raise RuntimeError(
                        f"cannot re-anchor {object_type} search: {modified_field} missing from results"
                    )
                # The boundary record is read twice. Upserts make that free.
                cursor_value = str(_to_millis(last_seen))
                after, seen_in_query = None, 0

    def _iter_all(self, object_type: str, properties: list[str]) -> Iterator[dict[str, Any]]:
        after: str | None = None
        while True:
            params: dict[str, Any] = {
                "limit": PAGE_SIZE,
                "properties": ",".join(properties),
                "archived": "false",
            }
            if after:
                params["after"] = after
            page = self._request("GET", f"/crm/v3/objects/{object_type}", params=params)
            yield from page.get("results", [])
            after = page.get("paging", {}).get("next", {}).get("after")
            if not after:
                return

    def read_associations(
        self, from_type: str, to_type: str, object_ids: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Associations for many objects in one call per 100 ids.

        Asking per object costs one request per record per association type,
        which is the difference between three requests and six hundred on a
        few hundred deals. Ids with no associations come back absent from the
        response and are returned here as an empty list, so the caller can tell
        "no links" apart from "not looked at".
        """
        associations: dict[str, list[dict[str, Any]]] = {str(i): [] for i in object_ids}
        for start in range(0, len(object_ids), ASSOCIATION_BATCH_SIZE):
            chunk = object_ids[start : start + ASSOCIATION_BATCH_SIZE]
            page = self._request(
                "POST",
                f"/crm/v4/associations/{from_type}/{to_type}/batch/read",
                json={"inputs": [{"id": str(object_id)} for object_id in chunk]},
            )
            for result in page.get("results", []):
                from_id = str(result.get("from", {}).get("id"))
                if from_id in associations:
                    associations[from_id] = result.get("to", [])
        return associations
