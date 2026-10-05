"""Local background jobs for importing a VK conversation through its browser session."""
import ctypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid
from browser_launch import BROWSERS

TERMINAL = {"complete", "failed", "cancelled", "interrupted"}
_lock = threading.Lock()


def parse_dialog_link(value):
    value = str(value or "").strip()
    if re.fullmatch(r"-?\d+", value):
        peer = int(value)
    else:
        try:
            parsed = urlsplit(value)
            if (parsed.scheme not in ("https", "http") or parsed.hostname not in
                    ("vk.ru", "vk.com", "www.vk.ru", "www.vk.com") or parsed.username or parsed.password
                    or parsed.port not in (None, 80, 443)):
                raise ValueError()
            match = re.fullmatch(r"/im/convo/(-?\d+)/?", parsed.path)
            if match:
                peer = int(match.group(1))
            elif parsed.path in ("/im", "/im/"):
                selected = parse_qs(parsed.query).get("sel", [""])[0]
                if re.fullmatch(r"c\d+", selected):
                    peer = 2000000000 + int(selected[1:])
                elif re.fullmatch(r"-?\d+", selected):
                    peer = int(selected)
                else:
                    raise ValueError()
            else:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("Вставьте ссылку на диалог вида https://vk.ru/im/convo/12345678.") from None
    if not peer or not -2147483648 <= peer <= 2147483647:
        raise ValueError("Некорректный номер диалога.")
    return peer


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    for attempt in range(6):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.05)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def process_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


class VkImportJobs:
    def __init__(self, config_path):
        self.config_path = Path(config_path).resolve()
        self.root = self.config_path.parent / "Temp/VkImport"

    def directory(self, job_id):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ValueError("Загрузка не найдена.")
        return self.root / job_id

    def status(self, job_id):
        directory = self.directory(job_id)
        result = read_json(directory / "status.json")
        if not result:
            return None
        metadata = read_json(directory / "job.json")
        if result.get("state") not in TERMINAL and not process_alive(metadata.get("pid")):
            result.update(state="interrupted", message="Загрузка прервана. Можно запустить её повторно.")
        result["id"] = job_id
        download = read_json(directory / "download.json")
        if result.get("state") == "media" and download:
            result["download"] = download
        if result.get('warnings') and result.get('state') in TERMINAL and (
                not result.get('warning_messages') or any('[ссылка]' in message for message in result['warning_messages'])):
            from archive_warnings import warning_attachments
            try:
                result['warning_attachments'] = warning_attachments(self.config_path, result.get('peer_id'))
                result['warning_details_legacy'] = True
            except (OSError, ValueError):
                result['warning_attachments'] = []
        return result

    def latest(self):
        directories = sorted(self.root.glob("*/job.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return self.status(directories[0].parent.name) if directories else None

    def start(self, link, login_only=False, browser_id=None):
        if login_only:
            raise ValueError("Подключите помощник кнопкой «Подключить браузер».")
        peer = parse_dialog_link(link)
        with _lock:
            for path in self.root.glob("*/job.json"):
                current = self.status(path.parent.name)
                if current and current.get("state") not in TERMINAL:
                    raise RuntimeError("Уже идёт загрузка. Дождитесь завершения или нажмите «Остановить».")
            connection = BrowserBridge(self.config_path).status()
            if not connection["connected"]:
                raise ValueError("Подключите помощник в браузере, где открыт ВК, затем повторите загрузку.")
            if browser_id is not None and browser_id not in BROWSERS:
                raise ValueError("Выберите браузер из списка.")
            if browser_id not in (None, "default", "manual") and browser_id != connection.get("browser_id"):
                raise ValueError("Сейчас подключён " + connection.get("browser", "другой браузер") +
                                 ". Нажмите «Подключить браузер» для выбранного браузера.")
            job_id = uuid.uuid4().hex
            directory = self.directory(job_id)
            directory.mkdir(parents=True)
            write_json(directory / "job.json", {"peer_id": peer, "login_only": False, "browser_mode": "bridge"})
            write_json(directory / "status.json", {"state": "queued", "peer_id": peer, "message": "Подключаюсь к ВК в вашем браузере…", "warnings": 0, "lines": []})
            if getattr(sys, "frozen", False):
                command = [sys.executable]
            else:
                command = [sys.executable, str(Path(__file__).resolve().parents[1] / "run.py")]
            command += ["--mode", "vk-import", "--config", str(self.config_path), "--job-dir", str(directory)]
            try:
                with (directory / "worker.log").open("wb") as log:
                    process = subprocess.Popen(command, stdout=log, stderr=log, cwd=str(self.config_path.parent),
                                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                metadata = read_json(directory / "job.json")
                metadata["pid"] = process.pid
                write_json(directory / "job.json", metadata)
            except Exception:
                write_json(directory / "status.json", {"state": "failed", "message": "Не удалось запустить загрузку."})
                raise
            return job_id

    def cancel(self, job_id):
        directory = self.directory(job_id)
        if not (directory / "job.json").is_file():
            raise ValueError("Загрузка не найдена.")
        (directory / "cancel").touch()


class BrowserBridge:
    """Authenticated, read-only RPC between the local worker and a paired browser."""
    def __init__(self, config_path):
        self.root = Path(config_path).resolve().parent / "Temp/VkImport"
        self.key_path = self.root / "BridgeKey.json"

    def status(self):
        data = read_json(self.key_path)
        browser_id = data.get("browser_id", "chrome" if data.get("token_hash") else "default")
        return {"connected": bool(data.get("token_hash")) and time.time() - data.get("last_seen", 0) < 95,
                "browser_id": browser_id, "browser": data.get("browser", BROWSERS.get(browser_id, BROWSERS["default"])["name"])}

    def create_pairing(self, browser_id="default"):
        if browser_id not in BROWSERS:
            raise ValueError("Выберите браузер из списка.")
        nonce = secrets.token_urlsafe(32)
        self.root.mkdir(parents=True, exist_ok=True)
        with _lock:
            data = read_json(self.key_path)
            data.update(pair_hash=hashlib.sha256(nonce.encode()).hexdigest(), pair_until=time.time() + 900,
                        pair_browser_id=browser_id)
            write_json(self.key_path, data)
        return nonce

    def pair(self, nonce, detected_browser=None):
        with _lock:
            data = read_json(self.key_path)
            supplied = hashlib.sha256(str(nonce).encode()).hexdigest()
            if time.time() > data.get("pair_until", 0) or not hmac.compare_digest(supplied, data.get("pair_hash", "")):
                raise PermissionError("Код подключения недействителен.")
            token = secrets.token_urlsafe(32)
            browser_id = data.get("pair_browser_id", "default")
            if (isinstance(detected_browser, str) and detected_browser in BROWSERS and detected_browser not in ("default", "manual")
                    and (detected_browser != "chrome" or browser_id in ("default", "manual", "firefox"))):
                browser_id = detected_browser
            write_json(self.key_path, {"token_hash": hashlib.sha256(token.encode()).hexdigest(), "last_seen": time.time(),
                                      "browser_id": browser_id, "browser": BROWSERS[browser_id]["name"]})
            return token

    def authorize(self, token):
        with _lock:
            data = read_json(self.key_path)
            supplied = hashlib.sha256(str(token).encode()).hexdigest()
            if not hmac.compare_digest(supplied, data.get("token_hash", "")):
                raise PermissionError("Браузер не подключён.")
            data["last_seen"] = time.time()
            write_json(self.key_path, data)

    def pending(self):
        for path in self.root.glob("*/pending.json"):
            command = read_json(path)
            state = read_json(path.parent / "status.json").get("state")
            if (command.get("expires", 0) > time.time() and state not in TERMINAL
                    and not (path.parent / "cancel").exists()
                    and not (path.parent / (command.get("command_id", "") + ".response.json")).exists()):
                return command
        return None

    def respond(self, payload):
        job_id, command_id = payload.get("job_id", ""), payload.get("command_id", "")
        if (not isinstance(job_id, str) or not isinstance(command_id, str)
                or not re.fullmatch(r"[a-f0-9]{32}", job_id) or not re.fullmatch(r"[a-f0-9]{32}", command_id)):
            raise ValueError("Некорректный ответ браузера.")
        directory = self.root / job_id
        pending = read_json(directory / "pending.json")
        if pending.get("command_id") != command_id or pending.get("expires", 0) < time.time():
            raise ValueError("Запрос уже завершён.")
        destination = directory / (command_id + ".response.json")
        if not destination.exists():
            write_json(destination, {"response": payload.get("response"), "waiting_login": payload.get("waiting_login", False),
                                     "error": payload.get("error")})
