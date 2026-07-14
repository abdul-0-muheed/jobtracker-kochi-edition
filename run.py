"""
run.py — Entry point. Run with: python run.py
Opens http://localhost:5000 in the default browser.
"""
import sys
import webbrowser
import threading
import time

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = 5000

    def _open_browser():
        time.sleep(1.2)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=_open_browser, daemon=True).start()

    print(f"\n>>> Job Tracker running at http://localhost:{port}\n   Press Ctrl+C to stop.\n")
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
