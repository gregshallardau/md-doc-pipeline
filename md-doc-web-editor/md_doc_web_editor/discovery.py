"""Route each discovered workspace to its own isolated editor session."""

from urllib.parse import parse_qs, urlencode

from starlette.responses import JSONResponse, RedirectResponse

from .workspaces import discover


def install_discovery(app, project, factory):
    children = app.state.workspace_apps = {}

    class WorkspaceRouter:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await self.app(scope, receive, send)
            listed = discover(project)
            query = parse_qs(scope.get("query_string", b"").decode())
            name = query.get("workspace", [None])[0]
            if scope["path"] == "/api/workspaces":
                response = JSONResponse({"workspaces": [ws.public() for ws in listed]})
                return await response(scope, receive, send)
            if scope["path"] == "/" and name is None:
                query["workspace"] = [next(ws.name for ws in listed if ws.available)]
                response = RedirectResponse("/?" + urlencode(query, doseq=True))
                return await response(scope, receive, send)
            if name is None:
                return await self.app(scope, receive, send)
            workspace = next((ws for ws in listed if ws.name == name), None)
            if workspace is None or not workspace.available:
                response = JSONResponse({"detail": "Workspace is unavailable"}, status_code=404)
                return await response(scope, receive, send)
            key = str(workspace.root)
            if key not in children:
                children[key] = factory(workspace.root)
            return await children[key](scope, receive, send)

    app.add_middleware(WorkspaceRouter)
