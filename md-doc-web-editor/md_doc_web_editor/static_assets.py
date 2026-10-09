"""Serve browser modules with explicit types, independent of OS MIME registries."""

from pathlib import Path

from fastapi.staticfiles import StaticFiles


class EditorStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        media = {
            ".js": "text/javascript",
            ".mjs": "text/javascript",
            ".css": "text/css",
            ".wasm": "application/wasm",
        }.get(Path(path).suffix.lower())
        if media and response.status_code in {200, 206, 304}:
            response.headers["Content-Type"] = media
            if media == "text/javascript":
                response.headers["Cache-Control"] = "no-cache"
        return response
