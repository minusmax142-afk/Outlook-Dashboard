"""
Outlook Dashboard launcher: runs the dashboard in the background with no console window.

  pythonw launcher.pyw               start the server if it isn't running, then open the browser
  pythonw launcher.pyw --background  start the server only (used at Windows sign-in)

Only one copy runs: if the dashboard is already running, this just opens the browser.
Problems are written to %LOCALAPPDATA%\\OutlookDashboard\\dashboard.log (error types only, never email content).
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import time
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

URL = "http://127.0.0.1:5000"
DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "OutlookDashboard")
LOG_PATH = os.path.join(DATA_DIR, "dashboard.log")


def _running() -> bool:
    try:
        with urllib.request.urlopen(URL + "/api/auth/status", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _port_busy() -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", 5000)) == 0


def _setup_logging() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # pythonw has no console: send any stray output to the log instead of crashing.
    stream = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream


def _shortcut(path: str, args: str, description: str) -> None:
    import win32com.client  # pywin32

    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    link = win32com.client.Dispatch("WScript.Shell").CreateShortcut(path)
    link.TargetPath = pythonw
    link.Arguments = f'"{os.path.join(HERE, "launcher.pyw")}" {args}'.strip()
    link.WorkingDirectory = HERE
    link.Description = description
    link.IconLocation = os.path.join(HERE, "static", "dashboard.ico") if os.path.exists(os.path.join(HERE, "static", "dashboard.ico")) else "shell32.dll,156"
    link.WindowStyle = 7  # minimized (pythonw shows no window anyway)
    link.Save()


def install() -> None:
    """Desktop + Start menu icons, and start automatically (hidden) when you sign in to Windows."""
    appdata = os.environ["APPDATA"]
    startup = os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\Startup")
    programs = os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs")
    import win32com.client

    desktop = win32com.client.Dispatch("WScript.Shell").SpecialFolders("Desktop")
    _shortcut(os.path.join(startup, "Outlook Dashboard (background).lnk"), "--background",
              "Starts the Outlook Dashboard in the background when you sign in")
    _shortcut(os.path.join(desktop, "Outlook Dashboard.lnk"), "", "Open the Outlook Dashboard")
    _shortcut(os.path.join(programs, "Outlook Dashboard.lnk"), "", "Open the Outlook Dashboard")


def uninstall() -> None:
    import win32com.client

    appdata = os.environ["APPDATA"]
    desktop = win32com.client.Dispatch("WScript.Shell").SpecialFolders("Desktop")
    for path in (os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\Startup\Outlook Dashboard (background).lnk"),
                 os.path.join(desktop, "Outlook Dashboard.lnk"),
                 os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\Outlook Dashboard.lnk")):
        if os.path.exists(path):
            os.remove(path)


def main() -> None:
    if "--install" in sys.argv:
        return install()
    if "--uninstall" in sys.argv:
        return uninstall()
    background = "--background" in sys.argv
    if _running():
        if not background:
            webbrowser.open(URL)
        return
    if _port_busy():
        # Something else holds port 5000; wait briefly in case the dashboard is still starting.
        for _ in range(10):
            time.sleep(1)
            if _running():
                if not background:
                    webbrowser.open(URL)
                return
        return

    _setup_logging()
    logging.getLogger("launcher").info("Starting Outlook Dashboard")
    import app as dashboard  # noqa: E402  (imported after logging is set up)

    if not background:
        import threading
        threading.Timer(1.5, lambda: webbrowser.open(URL)).start()
    try:
        dashboard.app.run(host=dashboard.HOST, port=dashboard.PORT, debug=False, threaded=True, use_reloader=False)
    except Exception as err:  # pragma: no cover
        logging.getLogger("launcher").error("Dashboard stopped: %s", type(err).__name__)
        raise


if __name__ == "__main__":
    main()
