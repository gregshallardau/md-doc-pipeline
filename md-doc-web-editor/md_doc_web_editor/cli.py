"""``md-doc-edit [serve] [WORKSPACE]`` — launch the browser editor.

Run from inside an md-doc project with no arguments and the editor finds the project's
workspaces itself: every folder under ``workspace/`` plus the remote workspaces named in
``workspace/remote-workspaces.yml``. Give a directory to edit just that one instead.

Examples
--------
    md-doc-edit                                   # discover this project's workspaces
    md-doc-edit --port 9000
    md-doc-edit serve workspace/acme/             # just this directory
    md-doc-edit --host 0.0.0.0                    # expose on the network
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

import uvicorn

from .server import create_app
from .workspaces import discover, find_project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="md-doc-edit", description=__doc__)
    sub = parser.add_subparsers(dest="cmd")

    p_serve = sub.add_parser("serve", help="Start the editor web server.")
    p_serve.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Edit just this directory. Default: discover the project's workspaces.",
    )
    p_serve.add_argument("--host", default="127.0.0.1", help="Listen address.")
    p_serve.add_argument("--port", type=int, default=8765, help="Listen port.")
    p_serve.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't auto-open a browser tab on launch.",
    )

    argv = list(sys.argv[1:] if argv is None else argv)
    # ``md-doc-edit`` and ``md-doc-edit --port 9000`` mean ``serve``.
    if not argv or (argv[0] not in ("serve", "-h", "--help")):
        argv = ["serve", *argv]
    args = parser.parse_args(argv)

    if args.cmd == "serve":
        return _run_serve(args)
    parser.print_help()
    return 1


def _run_serve(args: argparse.Namespace) -> int:
    if args.workspace is None:
        project = find_project()
        app = create_app(project=project)
        print(f"md-doc editor: project {project}")
        for ws in discover(project):
            note = "" if ws.available else "  (not available: not mounted?)"
            kind = "remote" if ws.remote else "local "
            print(f"  {kind}  {ws.name:<20} {ws.root}{note}")
    else:
        workspace = Path(args.workspace).resolve()
        if not workspace.is_dir():
            print(f"error: workspace path is not a directory: {workspace}", file=sys.stderr)
            return 2
        app = create_app(workspace)
        print(f"md-doc editor: workspace {workspace}")

    url = f"http://{args.host}:{args.port}/"
    print(f"  open {url}   (Ctrl-C to stop)")

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
