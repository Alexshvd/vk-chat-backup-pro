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
    from Loggers.print_logger import PrintLogger
    logger = PrintLogger()
    for msg in run_pipeline(load_config(args.config), peer_ids=None, logger=logger):
        print(msg)


def web(args):
    from web import app, load_configs
    load_configs(args.config)
    app.run(debug=True, host="127.0.0.1", port=args.port, threaded=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VkChatBackupCommunity")
    parser.add_argument("--mode", choices=["cli", "web"], required=True,
                        help="cli — запуск генерации, web — запуск Flask сервера")
    parser.add_argument("--config", "-c", required=True, help="Path to config.json")
    parser.add_argument("--port", "-p", type=int, default=5000,
                        help="Port for web mode (default: 5000)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error(f"--port must be in range 1..65535, got {args.port}")
    if args.mode == "cli":
        cli(args)
    else:
        web(args)
