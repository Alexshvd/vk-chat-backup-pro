import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv


def path_rel(target: str, start: str = os.curdir) -> str:
    return os.path.relpath(target, start).replace("\\", "/")


dotenv_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path)


VK_TOKEN = os.getenv("VK_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")

if not VK_TOKEN:
    raise ValueError("VK_TOKEN не задан. Создайте .env на основе .env.example")
if not GROUP_ID:
    raise ValueError("GROUP_ID не задан. Создайте .env на основе .env.example")

try:
    GROUP_ID = int(GROUP_ID)
except ValueError:
    raise ValueError("GROUP_ID должен быть числом")

PEER_ID = os.getenv("PEER_ID")
if not PEER_ID:
    raise ValueError("PEER_ID не задан. Создайте .env на основе .env.example")
try:
    PEER_ID = int(PEER_ID)
except ValueError:
    raise ValueError("PEER_ID должен быть числом")

API_VERSION = "5.199"
API_BASE_URL = "https://api.vk.com/method"

EXPORT_ROOT = os.getenv("EXPORT_ROOT", str(Path(__file__).resolve().parent / "Temp" / "ExportMessages"))

DOWNLOAD_SHORT_VIDEO = True
DOWNLOAD_LONG_VIDEO = False
LONG_VIDEO_THRESHOLD = 180

_MIN_DATE_RAW: dict[int, str] = {
    # 2000000001: "2026-06-30-00-00-00",
}

MIN_DATE_BY_PEER_ID: dict[int, int] = {}
for _pid, _s in _MIN_DATE_RAW.items():
    MIN_DATE_BY_PEER_ID[_pid] = int(datetime.strptime(_s, "%Y-%m-%d-%H-%M-%S").timestamp())

MIN_CID_BY_PEER_ID: dict[int, int] = {
    # 2000000001: 1660,
}
