"""Local launcher without the development debugger or auto-reloader."""
import argparse
import threading

from run import root, _open_browser
from web import app, load_configs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start local VK chat backup")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    load_configs(str(root / "config.json"))
    if not args.no_browser:
        threading.Thread(target=_open_browser, args=(5000,), daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False,
            threaded=True)
