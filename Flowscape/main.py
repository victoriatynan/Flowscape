"""
Flowscape entry point (WEB_MIGRATION_PLAN.md Phase 6: the browser is the app).

    python main.py               serve the web app + API and open the browser
    python main.py --no-browser  serve only (e.g. on a headless box)

The former pygame editor has been retired (its code lives in the local
archive/ folder); the simulation engine, geometry, and all tests are
pygame-free.
"""

import sys

HOST = "127.0.0.1"
PORT = 8000


def run_web(open_browser=True):
    import threading
    import webbrowser

    import uvicorn

    from api_server import app

    if open_browser:
        # Fire shortly after startup; uvicorn.run blocks this thread.
        threading.Timer(
            1.0, webbrowser.open, args=(f"http://{HOST}:{PORT}/",)).start()
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    run_web(open_browser="--no-browser" not in sys.argv)
