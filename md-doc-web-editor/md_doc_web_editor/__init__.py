"""md-doc-web-editor — browser editor for md-doc workspaces.

Installed from a source checkout (``uv sync --group editor``); it is not published to PyPI.
The main entry points are :func:`create_app` (returns a FastAPI app) and
the ``md-doc-edit`` CLI installed by the package.
"""

from .server import create_app

__all__ = ["create_app"]
__version__ = "0.1.0"
