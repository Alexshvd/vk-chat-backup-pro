"""Build a portable Windows release using public configuration only."""
import json
import importlib.metadata
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_info import APP_NAME, APP_VERSION, HELPER_VERSION
from check_publication import scan_revision


def prepare_portable(portable):
    """Add dependency notices; do not redistribute an unverified FFmpeg build."""
    portable = Path(portable).resolve()
    for binary in (portable / "_internal" / "imageio_ffmpeg" / "binaries").glob("*.exe"):
        if portable not in binary.resolve().parents:
            raise ValueError("Binary path escaped the release directory")
        binary.unlink()
    licenses = portable / "ThirdPartyLicenses"
    licenses.mkdir(exist_ok=True)
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name", "package")
        safe_name = "".join(char for char in name if char.isalnum() or char in "-_.")
        destination = licenses / safe_name
        for relative in distribution.files or ():
            path = Path(str(relative))
            if any(word in path.name.lower() for word in ("license", "copying", "copyright", "authors")):
                source = Path(distribution.locate_file(relative))
                if source.is_file():
                    destination.mkdir(exist_ok=True)
                    shutil.copyfile(source, destination / path.name)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copyfile(python_license, licenses / "Python-LICENSE.txt")
    shutil.copyfile(ROOT / "THIRD-PARTY.md", portable / "THIRD-PARTY.md")
    (portable / "Установить FFmpeg.cmd").write_text(
        '@echo off\r\necho FFmpeg is optional and used for HLS music.\r\n'
        'winget install --id Gyan.FFmpeg.Essentials --exact --source winget\r\n'
        'echo Restart VK Chat Backup Pro after installation.\r\npause\r\n', encoding="ascii")


def build():
    if sys.platform != "win32":
        raise SystemExit("Build the Windows release on Windows.")
    # The private working config is excluded; only committed, audited code is built.
    subprocess.run(["git", "diff", "--quiet", "HEAD", "--", ".", ":!config.json"],
                   cwd=ROOT, check=True)
    if scan_revision():
        raise SystemExit("Publication blocked by privacy checks.")
    release = ROOT / "Temp" / "Releases" / APP_VERSION
    release.mkdir(parents=True, exist_ok=False)
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--onedir", "--console", "--noconfirm",
        "--name", "VkChatBackupPro", "--distpath", str(release / "dist"),
        "--workpath", str(release / "build"), "--specpath", str(release),
        "--add-data", f"{ROOT / 'WebApp/templates'};WebApp/templates",
        "--add-data", f"{ROOT / 'WebApp/static'};WebApp/static",
        "--add-data", f"{ROOT / 'BrowserExtension'};BrowserExtension",
        "--paths", str(ROOT / "WebApp"), "--paths", str(ROOT / "ExportMessageToMd"),
        "--paths", str(ROOT / "Config"), str(ROOT / "run.py"),
    ], cwd=ROOT, check=True)
    portable = release / "dist" / "VkChatBackupPro"
    shutil.copyfile(ROOT / "config.example.json", portable / "config.json")
    for name in ("LICENSE.md", "PRIVACY.md", "SUPPORT.md"):
        shutil.copyfile(ROOT / name, portable / name)
    (portable / "НАЧНИТЕ ЗДЕСЬ.txt").write_text(
        f"{APP_NAME} {APP_VERSION}\n\n"
        "1. Распакуйте всю папку ZIP в обычную папку на компьютере.\n"
        "2. Дважды нажмите VkChatBackupPro.exe и оставьте окно открытым.\n"
        "3. На открывшейся странице нажмите «Скачать диалог» и следуйте подсказкам.\n"
        "4. Если страница не открылась: http://127.0.0.1:5000\n"
        "5. Для остановки нажмите Ctrl+C в окне программы.\n\n"
        "Это beta-версия. Архив создаётся в Temp рядом с программой.\n"
        "Помощник браузера скачивается на странице подключения.\n"
        "Для потоковой музыки HLS нужен отдельный FFmpeg: запустите «Установить FFmpeg.cmd»,\n"
        "завершите установку и перезапустите приложение. Для MP3/OGG и видео он не нужен.\n"
        "Поддержка: https://github.com/Alexshvd/vk-chat-backup-pro/issues/new/choose\n",
        encoding="utf-8-sig")
    (portable / "Запустить.cmd").write_text(
        '@echo off\r\ncd /d "%~dp0"\r\nVkChatBackupPro.exe\r\npause\r\n', encoding="ascii")
    prepare_portable(portable)
    shutil.make_archive(str(release / f"vk-chat-backup-pro-{APP_VERSION}-windows-x64"),
                        "zip", root_dir=portable.parent, base_dir=portable.name)
    extension = ROOT / "BrowserExtension"
    manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != HELPER_VERSION:
        raise ValueError("Helper version and manifest do not match")
    for family in ("chromium", "firefox"):
        data = dict(manifest)
        if family == "firefox":
            data.pop("minimum_chrome_version", None)
            data["background"] = {"scripts": ["background.js"]}
            data["browser_specific_settings"] = {"gecko": {
                "id": "vk-chat-backup@local.invalid", "strict_min_version": "128.0"}}
        package = release / f"vk-chat-backup-pro-helper-{HELPER_VERSION}-{family}.zip"
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(data, ensure_ascii=False, indent=2))
            for name in ("background.js", "connect.js"):
                archive.write(extension / name, name)
    if scan_revision(packages=list(release.glob("vk-chat-backup-pro-*.zip"))):
        raise SystemExit("Release packages failed privacy checks; do not publish them.")
    print(f"Release files: {release}")


if __name__ == "__main__":
    build()
