"""Open a user-selected browser normally, without a separate automation profile."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import webbrowser

BROWSERS = {
    "default": {"name": "Системный браузер", "page": "", "paths": []},
    "chrome": {"name": "Google Chrome", "page": "chrome://extensions", "exe": "chrome.exe", "paths": ["Google/Chrome/Application/chrome.exe"]},
    "edge": {"name": "Microsoft Edge", "page": "edge://extensions", "exe": "msedge.exe", "paths": ["Microsoft/Edge/Application/msedge.exe"]},
    "firefox": {"name": "Mozilla Firefox", "page": "about:debugging#/runtime/this-firefox", "exe": "firefox.exe", "paths": ["Mozilla Firefox/firefox.exe"]},
    "opera": {"name": "Opera / Opera GX", "page": "opera://extensions", "exe": "opera.exe", "paths": ["Programs/Opera/launcher.exe", "Programs/Opera GX/launcher.exe", "Opera/launcher.exe", "Opera GX/launcher.exe"]},
    "brave": {"name": "Brave", "page": "brave://extensions", "exe": "brave.exe", "paths": ["BraveSoftware/Brave-Browser/Application/brave.exe"]},
    "vivaldi": {"name": "Vivaldi", "page": "vivaldi://extensions", "exe": "vivaldi.exe", "paths": ["Vivaldi/Application/vivaldi.exe"]},
    "yandex": {"name": "Яндекс Браузер", "page": "browser://extensions", "exe": "browser.exe", "paths": ["Yandex/YandexBrowser/Application/browser.exe"]},
    "manual": {"name": "Другой браузер / открыть ссылку вручную", "page": "", "paths": []},
}


def browser_executable(browser_id):
    info = BROWSERS[browser_id]
    if browser_id in ("default", "manual"):
        return None
    if sys.platform == "win32":
        import winreg
        key = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\" + info["exe"]
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                        path = str(winreg.QueryValueEx(handle, "")[0]).strip('"')
                        if Path(path).is_file():
                            return path
                except OSError:
                    pass
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = os.environ.get(env)
            if root:
                for relative in info["paths"]:
                    candidate = Path(root) / relative
                    if candidate.is_file():
                        return str(candidate)
    return shutil.which(info["exe"].removesuffix(".exe"))


def browser_options():
    return [{"id": key, "name": info["name"], "installed": key in ("default", "manual") or bool(browser_executable(key))}
            for key, info in BROWSERS.items()]


def open_browser(browser_id, url):
    if browser_id not in BROWSERS:
        raise ValueError("Выберите браузер из списка.")
    if browser_id == "manual":
        return False
    if browser_id == "default":
        return bool(webbrowser.open(url, new=2))
    executable = browser_executable(browser_id)
    if not executable:
        return False
    subprocess.Popen([executable, "-new-tab" if browser_id == "firefox" else "--new-tab", url],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True
