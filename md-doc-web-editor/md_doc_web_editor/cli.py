"""``md-doc-edit serve [WORKSPACE]`` — launch the browser editor.

Examples
--------
    md-doc-edit serve workspace/
    md-doc-edit serve workspace/acme/ --port 9000
    md-doc-edit serve workspace/ --host 0.0.0.0   # expose on the network
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

import uvicorn

from .server import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="md-doc-edit", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="Start the editor web server.")
    p_serve.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="Workspace directory (default: current directory).",
    )
    p_serve.add_argument("--host", default="127.0.0.1", help="Listen address.")
    p_serve.add_argument("--port", type=int, default=8765, help="Listen port.")
    p_serve.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't auto-open a browser tab on launch.",
    )

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        return _run_serve(args)
    parser.print_help()
    return 1


def _run_serve(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        print(f"error: workspace path is not a directory: {workspace}", file=sys.stderr)
        return 2

    app = create_app(workspace)

    url = f"http://{args.host}:{args.port}/"
    print(f"md-doc editor → {url}")
    print(f"  workspace:    {workspace}")
    print("  Ctrl-C to stop")

    if not args.no_browser:
        # Best-effort browser launch — fine if it fails (headless environments).
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
