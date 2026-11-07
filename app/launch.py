"""Start LineGuard or reuse its existing local server."""

import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn
from app.artifacts import build_version, verify

URL = "http://127.0.0.1:8000"


def lineguard_ready():
    try:
        with urllib.request.urlopen(URL + "/api/health", timeout=0.5) as response:
            status = json.load(response)
            return status.get("application") == "LineGuard" and status.get("status") == "ready"
    except (OSError, ValueError, AttributeError):
        return False


def port_in_use():
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=0.5):
            return True
    except OSError:
        return False


def open_when_ready():
    for _ in range(100):
        if lineguard_ready():
            webbrowser.open(URL)
            return
        time.sleep(0.2)


def main():
    open_browser = "--no-browser" not in sys.argv
    if port_in_use():
        if not lineguard_ready():
            raise SystemExit("Port 8000 is occupied by another service. Free the port and retry.")
        with urllib.request.urlopen(URL + "/api/health", timeout=1) as response:
            running = json.load(response)
        if running.get("build_version") != build_version():
            raise SystemExit(
                "An older LineGuard build is running. Stop it with Ctrl+C in its terminal, then launch again."
            )
        print(f"LineGuard is already running at {URL}")
        if open_browser:
            webbrowser.open(URL)
        return
    if not verify():
        raise SystemExit(
            "Local model artifacts do not match their manifest. Run launch.ps1 -Rebuild."
        )
    try:
        from app.main import app
    except (OSError, ValueError, ImportError, EOFError, KeyError) as error:
        raise SystemExit(
            f"LineGuard could not load its local files. Run launch.ps1 -Rebuild to restore model artifacts. Details: {error}"
        ) from error
    if open_browser:
        threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
