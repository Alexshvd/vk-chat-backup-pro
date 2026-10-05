import re
import json
from typing import Dict

import requests

from Loggers.base_logger import BaseLogger
from download_media import DOWNLOAD_HEADERS


def _parse_video_embed(text: str, logger: BaseLogger) -> Dict[str, str]:
    idx = text.find('"apiPrefetchCache"')
    if idx >= 0:
        files_pos = text.find('"files"', idx)
        if files_pos >= 0:
            brace = text.find("{", files_pos + 7)
            if brace >= 0:
                depth = 0
                in_str = False
                escaped = False
                for i in range(brace, len(text)):
                    ch = text[i]
                    if escaped:
                        escaped = False
                        continue
                    if ch == "\\" and in_str:
                        escaped = True
                        continue
                    if ch == '"':
                        in_str = not in_str
                        continue
                    if not in_str:
                        if ch == "{":
                            depth += 1
                        elif ch == "}":
                            depth -= 1
                            if depth == 0:
                                blob = text[brace : i + 1]
                                try:
                                    files = json.loads(blob)
                                    result = {k: v for k, v in files.items() if k.startswith("mp4_") or k == "src"}
                                    if result:
                                        if files.get("failover_host"):
                                            result["failover_host"] = files["failover_host"]
                                        return result
                                except json.JSONDecodeError as ex:
                                    logger.LogWarning("Ошибка парсинга apiPrefetchCache", ex)
                                break

    m = re.search(r'"files":\{(.+?)\}', text, re.DOTALL)
    if m:
        raw = "{" + m.group(1) + "}"
        raw = raw.replace('\\/', '/').replace('\\u0026', '&')
        try:
            files = json.loads(raw)
            result = {k: v for k, v in files.items() if k.startswith("mp4_") or k == "src"}
            if result and files.get("failover_host"):
                result["failover_host"] = files["failover_host"]
            return result
        except json.JSONDecodeError as ex:
            logger.LogWarning("Ошибка парсинга regex fallback", ex)

    return {}


def get_video_embed_urls(owner_id: int, video_id: int, logger: BaseLogger) -> Dict[str, str]:
    resp = requests.get(
        "https://vk.com/video_ext.php",
        params={"oid": owner_id, "id": video_id},
        timeout=30,
        headers=DOWNLOAD_HEADERS,
    )
    resp.raise_for_status()
    return _parse_video_embed(resp.text, logger)
