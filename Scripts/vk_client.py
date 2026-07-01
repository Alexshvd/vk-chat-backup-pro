import re
import json
import time
from typing import Any, Optional

import requests

from config import API_BASE_URL, API_VERSION, VK_TOKEN


class VkClient:
    def __init__(self, token: str = VK_TOKEN):
        self.token = token
        self.session = requests.Session()

    def _call(
        self, method: str, params: Optional[dict[str, Any]] = None, retries: int = 3
    ) -> dict[str, Any]:
        if params is None:
            params = {}
        params["access_token"] = self.token
        params["v"] = API_VERSION

        for attempt in range(retries):
            url = f"{API_BASE_URL}/{method}"
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            if "error" in data:
                err = data["error"]
                code = err.get("error_code")
                if code == 6 and attempt < retries - 1:
                    delay = 2 ** attempt
                    time.sleep(delay)
                    continue
                raise RuntimeError(
                    f"VK API error [{code}]: {err.get('error_msg')}"
                )

            return data.get("response", data)

        raise RuntimeError("VK API error [6]: превышено число попыток")

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
            time.sleep(0.35)

        return items

    def get_video_urls(self, owner_id: int, video_id: int) -> dict[str, str]:
        resp = self.session.get(
            "https://vk.com/video_ext.php",
            params={"oid": owner_id, "id": video_id},
            timeout=30
        )
        resp.raise_for_status()

        m = re.search(r'"files":\{(.+?)\}', resp.text, re.DOTALL)
        if not m:
            return {}

        raw = "{" + m.group(1) + "}"
        raw = raw.replace('\\/', '/').replace('\\u0026', '&')
        files = json.loads(raw)

        return {
            k: v for k, v in files.items()
            if k.startswith("mp4_")
        }

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
            time.sleep(0.35)

        items.reverse()
        return items
