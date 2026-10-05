"""Import through the user's paired browser; keep work alive after the UI closes."""
import json
import os
from pathlib import Path
import re
import time
import uuid

from config_loader import load_config
from main import main as run_pipeline
from Loggers.base_logger import BaseLogger
from Loggers.context_logger import warning_text
from vk_import import read_json, write_json

class Cancelled(Exception):
    pass


class Status(BaseLogger):
    def __init__(self, directory, peer):
        self.directory = directory
        self.data = {"state": "opening", "peer_id": peer, "warnings": 0, "warning_messages": [], "lines": [], "message": "Подключаюсь к ВК в вашем браузере…"}

    def publish(self, message=None, **fields):
        self.data.update(fields)
        if message:
            self.data["message"] = message
            self.data["lines"] = (self.data["lines"] + [message])[-40:]
        write_json(self.directory / "status.json", self.data)

    def check_cancel(self):
        if (self.directory / "cancel").exists():
            raise Cancelled()

    def LogWarning(self, error_type, exception=None):
        message = warning_text(error_type, exception)
        self.data["warning_messages"].append(message)
        self.publish(message, warnings=self.data["warnings"] + 1)


def collect_history(call, peer, status, pause=time.sleep):
    items, profiles, groups = {}, {}, {}
    offset = 0
    total = None
    while True:
        status.check_cancel()
        response = call(peer, offset)
        batch = response.get("items")
        if not isinstance(batch, list):
            raise ValueError("ВК вернул некорректную историю диалога.")
        if total is None:
            total = int(response.get("count", len(batch)))
        if not batch:
            if offset < total:
                raise ValueError("ВК вернул неполную историю. Экспорт не запущен; повторите загрузку.")
            break
        added = 0
        for item in batch:
            cid = item.get("conversation_message_id")
            if isinstance(cid, int) and cid not in items:
                items[cid] = item
                added += 1
        if not added:
            raise ValueError("ВК повторяет одну страницу истории. Повторите загрузку.")
        for name, destination in (("profiles", profiles), ("groups", groups)):
            for author in response.get(name, []):
                destination[author["id"]] = author
        offset += len(batch)
        status.publish(f"Получено сообщений: {len(items)} / {total}", state="history", received=len(items), total=total)
        if offset >= total:
            break
        pause(0.35)
    if len(items) < total:
        raise ValueError("ВК вернул неполную историю. Экспорт не запущен; повторите загрузку.")
    return {"peer_id": peer, "items": list(items.values()), "profiles": list(profiles.values()),
            "groups": list(groups.values()), "currentDate": int(time.time() * 1000)}


def run_import(config_path, job_dir):
    directory = Path(job_dir).resolve()
    expected = Path(config_path).resolve().parent / "Temp/VkImport"
    if directory.parent != expected.resolve() or not re.fullmatch(r"[a-f0-9]{32}", directory.name):
        raise ValueError("Некорректный каталог загрузки.")
    metadata = read_json(directory / "job.json")
    peer = metadata.get("peer_id")
    status = Status(directory, peer)
    status.publish()
    try:
        config = load_config(config_path)
        # Link import always preserves previous messages and their media.
        config.overwrite_existing_md = False
        config.overwrite_existing_original_message_json = False
        data = bridge_history(directory, peer, status)
        status.check_cancel()
        sources = Path(config.export_root) / "ExportMessages/Sources"
        sources.mkdir(parents=True, exist_ok=True)
        filename = f"messages_peerId_{peer}_{data['currentDate']}.json"
        write_json(sources / filename, data)
        status.publish("История получена. Сохраняю сообщения и скачиваю вложения…", state="media", source=filename)
        os.environ["VK_BACKUP_DOWNLOAD_PROGRESS"] = str(directory / "download.json")
        os.environ["VK_BACKUP_DOWNLOAD_CACHE"] = str(expected.parent / "DownloadCache")
        for message in run_pipeline(config, {peer}, status):
            status.check_cancel()
            if "Уже существует" not in message:
                status.publish(message.strip(), state="media")
        status.publish("Готово. Диалог сохранён." if not status.data["warnings"] else
                       f"Диалог сохранён. Предупреждений: {status.data['warnings']} — см. блок «Предупреждения».",
                       state="complete", chat_url=f"/chat/{peer}")
    except Cancelled:
        status.publish("Загрузка остановлена. Уже сохранённые сообщения и файлы остаются в архиве.", state="cancelled")
    except Exception as error:
        reason = warning_text(str(error).splitlines()[0] if str(error) else "")
        write_json(directory / "diagnostic.json", {"type": type(error).__name__, "reason": reason})
        if isinstance(error, ValueError):
            message = str(error)
        elif "VK_API_ERROR_" in str(error):
            match = re.search(r"VK_API_ERROR_(\w+)", str(error))
            message = "ВК не разрешил получить историю диалога (" + match.group(1) + "). Проверьте вход в аккаунт и доступ к этому диалогу."
        elif "closed" in str(error).lower():
            message = "Окно ВК закрыто. Повторите загрузку и оставьте его открытым до получения сообщений."
        elif "Timeout" in type(error).__name__:
            message = "Не дождались загрузки страницы ВК. Проверьте подключение и повторите запуск."
        else:
            message = "Не удалось получить диалог. Проверьте подключение, вход в ВК и повторите загрузку."
        status.publish(message, state="failed")


def bridge_history(directory, peer, status):
    login_deadline = time.monotonic() + 600

    def call(selected, offset):
        while True:
            status.check_cancel()
            command_id = uuid.uuid4().hex
            write_json(directory / "pending.json", {"job_id": directory.name, "command_id": command_id,
                       "peer_id": selected, "offset": offset, "expires": time.time() + 120})
            answer_path = directory / (command_id + ".response.json")
            deadline = time.monotonic() + 120
            while not answer_path.exists():
                status.check_cancel()
                if time.monotonic() > deadline:
                    raise ValueError("Браузер не ответил. Откройте браузер с подключённым помощником и повторите загрузку.")
                time.sleep(0.2)
            answer = read_json(answer_path)
            if answer.get("waiting_login"):
                if status.data["state"] != "login":
                    status.publish("Жду загрузку ВК в вашем браузере. При необходимости войдите в аккаунт.", state="login")
                if time.monotonic() > login_deadline:
                    raise ValueError("Не дождались входа в ВК в браузере. Повторите загрузку после входа.")
                time.sleep(2)
                continue
            if answer.get("error"):
                raise ValueError("Помощник браузера: " + str(answer["error"]))
            response = answer.get("response")
            if not isinstance(response, dict) or not isinstance(response.get("items"), list):
                raise ValueError("Браузер вернул некорректную историю диалога.")
            return response
    return collect_history(call, peer, status)
