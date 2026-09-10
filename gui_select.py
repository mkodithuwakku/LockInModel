"""Compatibility launcher for the shared multi-team dashboard."""

import threading
import webbrowser
from app import app

if __name__ == "__main__":
    threading.Timer(1, lambda: webbrowser.open("http://127.0.0.1:8765")).start()
    app.run(host="127.0.0.1", port=8765, debug=False, threaded=True)
