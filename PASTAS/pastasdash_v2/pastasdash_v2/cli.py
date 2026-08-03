"""CLI entrypoint: `pastasdash-v2`."""

from __future__ import annotations

import argparse

from pastasdash_v2 import __version__
from pastasdash_v2.config import DEFAULT_PORT
from pastasdash_v2.main import run


def main() -> None:
    p = argparse.ArgumentParser(prog="pastasdash-v2", description="NiceGUI grondwaterdashboard.")
    p.add_argument("--host", default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Poort (default: {DEFAULT_PORT})")
    p.add_argument("--reload", action="store_true", help="Auto-reload bij file-change (dev)")
    p.add_argument("--version", action="version", version=f"pastasdash-v2 {__version__}")
    args = p.parse_args()
    run(host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
