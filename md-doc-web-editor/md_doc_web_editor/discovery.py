"""Route each discovered workspace to its own isolated editor session."""

from urllib.parse import parse_qs, urlencode

from starlette.responses import JSONResponse, RedirectResponse

from .workspaces import discover
from .snapshots import safe_path, project_files


def install_discovery(app, project, factory, fixed=None):
    children = app.state.workspace_apps = {}

    class WorkspaceRouter:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await self.app(scope, receive, send)
            listed = [fixed] if fixed else discover(project)
            query = parse_qs(scope.get("query_string", b"").decode())
            name = query.get("workspace", [None])[0]
            if scope["path"] == "/api/workspaces":
                response = JSONResponse({"workspaces": [ws.public() for ws in listed]})
                return await response(scope, receive, send)
            if scope["path"] == "/" and name is None and fixed is None:
                query["workspace"] = [
                    next(
                        ws.name
                        for ws in sorted(listed, key=lambda ws: not ws.remote)
                        if ws.available
                    )
                ]
                response = RedirectResponse("/?" + urlencode(query, doseq=True))
                return await response(scope, receive, send)
            if (
                name is None
                and (query.get("folder") or scope["path"] == "/api/workspace-folders")
                and fixed
            ):
                name = fixed.name
            if name is None:
                return await self.app(scope, receive, send)
            workspace = next((ws for ws in listed if ws.name == name), None)
            if workspace is None or not workspace.available:
                response = JSONResponse({"detail": "Workspace is unavailable"}, status_code=404)
                return await response(scope, receive, send)
            try:
                root = safe_path(workspace.root, query.get("folder", [""])[0])
                if not root.is_dir():
                    raise ValueError("Document root is not a directory")
                if scope["path"] == "/api/workspace-folders":
                    current = safe_path(workspace.root, query.get("path", [""])[0])
                    folders = []
                    for path in sorted(current.iterdir(), key=lambda path: path.name.lower()):
                        if (
                            path.is_dir()
                            and not path.is_symlink()
                            and not path.name.startswith(".")
                            and path.name
                            not in {"node_modules", "__pycache__", "Exports", "dist", "build"}
                        ):
                            folders.append(
                                {
                                    "name": path.name,
                                    "path": path.relative_to(workspace.root).as_posix(),
                                    "documentCount": sum(
                                        file.suffix.lower() == ".md" for file in project_files(path)
                                    ),
                                }
                            )
                    response = JSONResponse(
                        {
                            "workspace": workspace.public(),
                            "root": str(workspace.root),
                            "path": current.relative_to(workspace.root).as_posix(),
                            "absolutePath": str(current),
                            "folders": folders,
                        }
                    )
                    return await response(scope, receive, send)
            except (ValueError, OSError) as exc:
                response = JSONResponse({"detail": str(exc)}, status_code=400)
                return await response(scope, receive, send)
            key = str(root)
            if key not in children:
                children[key] = factory(root)
                children[key].state.workspace_info = {
                    **workspace.public(),
                    "name": (
                        workspace.name
                        if root == workspace.root
                        else f"{workspace.name} / {root.name}"
                    ),
                }
            query.pop("workspace", None)
            query.pop("folder", None)
            scope = {**scope, "query_string": urlencode(query, doseq=True).encode()}
            return await children[key](scope, receive, send)

    app.add_middleware(WorkspaceRouter)
