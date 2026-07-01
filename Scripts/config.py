import os
from pathlib import Path
from dotenv import load_dotenv


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

DOWNLOAD_SHORT_VIDEO = True
DOWNLOAD_LONG_VIDEO = False
LONG_VIDEO_THRESHOLD = 180
