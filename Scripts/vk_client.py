import time
from typing import Any

import requests

from config import API_BASE_URL, API_VERSION, VK_TOKEN


class VkClient:
    def __init__(self, token: str = VK_TOKEN):
        self.token = token
        self.session = requests.Session()

    def _call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if params is None:
            params = {}
        params["access_token"] = self.token
        params["v"] = API_VERSION

        url = f"{API_BASE_URL}/{method}"
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            err = data["error"]
            raise RuntimeError(
                f"VK API error [{err.get('error_code')}]: {err.get('error_msg')}"
            )

        return data.get("response", data)

    def get_conversations(
        self, count: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        return self._call("messages.getConversations", {
            "count": min(count, 200),
            "offset": offset,
        })

    def get_history(
        self, peer_id: int, count: int = 200, offset: int = 0
    ) -> dict[str, Any]:
        return self._call("messages.getHistory", {
            "peer_id": peer_id,
            "count": min(count, 200),
            "offset": offset,
        })

    def get_all_conversations(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        count = 200

        while True:
            data = self.get_conversations(count=count, offset=offset)
            batch = data.get("items", [])
            if not batch:
                break
            items.extend(batch)
            offset += count

        return items

    def get_all_history(self, peer_id: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        count = 200

        while True:
            data = self.get_history(peer_id, count=count, offset=offset)
            batch = data.get("items", [])
            if not batch:
                break
            items.extend(batch)
            offset += count

        items.reverse()
        return items
