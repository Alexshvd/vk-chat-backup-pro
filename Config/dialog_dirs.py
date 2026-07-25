from pathlib import Path

from config import Config


def collect_dialog_dirs(dialogs_dir: Path, config: Config) -> dict:
    """Сканирует dialogs_dir и возвращает {peer_id: Path} для всех папок диалогов.

    Находит и стандартные dialog_{peer_id}, и кастомно названные папки из config.
    """
    result = {}
    if not dialogs_dir.is_dir():
        return result
    for entry in dialogs_dir.iterdir():
        if entry.is_dir() and entry.name.startswith("dialog_"):
            pid = int(entry.name[len("dialog_"):])
            result[pid] = entry
    for pid, custom_name in config.dialog_name_by_peer_id.items():
        if pid not in result:
            custom_dir = dialogs_dir / custom_name
            if custom_dir.is_dir():
                result[pid] = custom_dir
    return result
