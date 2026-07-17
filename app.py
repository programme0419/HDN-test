#!/usr/bin/env python3
"""Desktop launcher for the After-Action Debrief tool.

Starts the local server on a free localhost port, then opens the UI in a native
desktop window (via ``pywebview`` if it is installed) or falls back to the
system default browser. Runs entirely offline; set ``OPENAI_API_KEY`` to enable
the optional LLM-assisted assessment.

Usage:
    python3 app.py [--host HOST] [--port PORT] [--no-window]
"""

from __future__ import annotations

import argparse
import socket
import threading
import time

from debrief.server import create_server


def _free_port(host: str, preferred: int) -> int:
    """Return the preferred port if free, otherwise an OS-assigned one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def _open_window(url: str) -> bool:
    """Try to open a native window with pywebview. Returns True on success."""
    try:
        import webview  # type: ignore
    except ImportError:
        return False
    webview.create_window("After-Action Debrief", url, width=1180, height=860)
    webview.start()
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Post-mission debrief desktop tool")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="Serve only; do not open a window or browser.",
    )
    args = parser.parse_args()

    port = _free_port(args.host, args.port)
    httpd, _ = create_server(args.host, port)
    url = f"http://{args.host}:{port}/"

    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    print(f"After-Action Debrief serving on {url}")

    if args.no_window:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            httpd.shutdown()
            httpd.server_close()
        return

    # Prefer a native desktop window; fall back to the default browser.
    if not _open_window(url):
        import webbrowser

        print("pywebview not installed; opening in the default browser.")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    httpd.shutdown()
    httpd.server_close()


if __name__ == "__main__":
    main()
