"""Tiny static file server for the built React SPA.

The standard SimpleHTTPRequestHandler is enough for assets, but client-side
routes like /alerts/1 need to fall back to index.html.
"""

from __future__ import annotations

import http.server
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


class ThreadingSpaServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class SpaHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        root = Path(self.directory).resolve()
        parsed = urlparse(path)
        requested = root / unquote(parsed.path.lstrip("/"))

        try:
            requested.resolve().relative_to(root)
        except ValueError:
            return str(root / "index.html")

        if requested.is_file():
            return str(requested)
        return str(root / "index.html")

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stdout.write("[frontend] " + fmt % args + "\n")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: spa_server.py <dist-dir> <port>")

    directory = Path(sys.argv[1]).resolve()
    port = int(sys.argv[2])
    if not (directory / "index.html").is_file():
        raise SystemExit(f"missing index.html under {directory}")

    os.chdir(directory)
    handler = lambda *args, **kwargs: SpaHandler(*args, directory=str(directory), **kwargs)
    with ThreadingSpaServer(("0.0.0.0", port), handler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
