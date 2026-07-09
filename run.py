import argparse
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "WebApp"))
sys.path.insert(0, str(root / "ExportMessageToMd"))
sys.path.insert(0, str(root / "Config"))


def cli(args):
    from main import main as run_pipeline
    from config_loader import load_config
    for msg in run_pipeline(load_config(args.config)):
        print(msg)


def web(args):
    from web import app, init_app
    init_app(args.config)
    app.run(debug=True, host="127.0.0.1", port=5000, threaded=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VkChatBackupCommunity")
    parser.add_argument("--mode", choices=["cli", "web"], required=True,
                        help="cli — запуск генерации, web — запуск Flask сервера")
    parser.add_argument("--config", "-c", required=True, help="Path to config.json")
    args = parser.parse_args()
    if args.mode == "cli":
        cli(args)
    else:
        web(args)
