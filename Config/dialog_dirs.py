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
        if not entry.is_dir():
            continue
        if entry.name in config.peer_id_by_dialog_custom_name:
            result[config.peer_id_by_dialog_custom_name[entry.name]] = entry
        elif entry.name.startswith("dialog_"):
            pid = int(entry.name[len("dialog_"):])
            result[pid] = entry
    return result
