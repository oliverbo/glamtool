from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class GlamglareApiError(ValueError):
    """Raised when the glamglare API returns an unusable response."""


@dataclass(frozen=True)
class GlamglareArtist:
    name: str
    instagram_handle: str | None


class GlamglareClient:
    """Client for the artist search endpoint defined by gg-api's OpenAPI spec."""

    def __init__(
        self,
        base_url: str,
        secret: str,
        *,
        client_id: str = "glamtool",
        timeout_s: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.secret = secret.strip()
        self.client_id = client_id
        self.timeout_s = timeout_s
        self.transport = transport

    def _endpoint(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"ApiKey {self.client_id}.{self.secret}"}

    def find_artist(self, name: str) -> GlamglareArtist | None:
        search_name = name.strip()
        with httpx.Client(timeout=self.timeout_s, transport=self.transport) as client:
            response = client.get(
                self._endpoint("api/artists"),
                headers=self._headers(),
                params={"name": search_name.casefold(), "limit": 100},
            )
            response.raise_for_status()
            try:
                payload: Any = response.json()
            except ValueError as exc:
                raise GlamglareApiError(
                    "glamglare returned an invalid artist search response"
                ) from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("result"), list):
            raise GlamglareApiError("glamglare returned an invalid artist search response")

        matches: list[dict[str, Any]] = []
        for item in payload["result"]:
            if not isinstance(item, dict):
                continue
            item_name = item.get("name")
            if (
                isinstance(item_name, str)
                and item_name.strip().casefold() == search_name.casefold()
            ):
                matches.append(item)

        if not matches:
            return None
        if len(matches) > 1:
            raise GlamglareApiError(
                f"glamglare returned multiple exact matches for artist {name!r}"
            )

        match = matches[0]
        handle = match.get("instagramHandle")
        return GlamglareArtist(
            name=match["name"].strip(),
            instagram_handle=(
                handle.strip() if isinstance(handle, str) and handle.strip() else None
            ),
        )
