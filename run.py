import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from app_info import APP_NAME, APP_VERSION

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "WebApp"))
sys.path.insert(0, str(root / "ExportMessageToMd"))
sys.path.insert(0, str(root / "Config"))


def _open_browser(port: int):
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.1)


def cli(args):
    from main import main as run_pipeline
    from config_loader import load_config
    from Loggers.print_logger import PrintLogger
    logger = PrintLogger()
    for msg in run_pipeline(load_config(args.config), peer_ids=None, logger=logger):
        print(msg)


def web(args):
    from web import app, load_configs
    load_configs(args.config)
    use_reloader = not getattr(sys, "frozen", False)
    if not args.no_browser:
        if not use_reloader or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
            threading.Thread(target=_open_browser, args=(args.port,), daemon=True).start()
    app.run(debug=not getattr(sys, "frozen", False), host="127.0.0.1", port=args.port, threaded=True,
            use_reloader=use_reloader)


def _default_config_path() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve().parent / "config.json")
    return str(Path(__file__).resolve().parent / "config.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument("--mode", choices=["cli", "web", "vk-import"], default="web",
                        help="cli — запуск генерации, web — запуск Flask сервера (default: web)")
    parser.add_argument("--config", "-c", default=_default_config_path(),
                        help="Path to config.json (default: config.json рядом с приложением)")
    parser.add_argument("--port", "-p", type=int, default=5000,
                        help="Port for web mode (default: 5000)")
    parser.add_argument("--no-browser", "-nb", action="store_true",
                        help="Не открывать браузер автоматически при старте web-режима")
    parser.add_argument("--job-dir", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error(f"--port must be in range 1..65535, got {args.port}")
    if args.mode == "vk-import":
        if not args.job_dir:
            parser.error("--job-dir is required for vk-import")
        from vk_import_worker import run_import
        run_import(args.config, args.job_dir)
    elif args.mode == "cli":
        cli(args)
    else:
        web(args)
