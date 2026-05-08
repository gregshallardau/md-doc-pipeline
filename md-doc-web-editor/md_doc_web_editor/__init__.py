"""md-doc-web-editor — browser editor for md-doc workspaces.

Distributable as a separate ``pip install md-doc-web-editor`` package.
The main entry points are :func:`create_app` (returns a FastAPI app) and
the ``md-doc-edit`` CLI installed by the package.
"""

from .server import create_app

__all__ = ["create_app"]
__version__ = "0.1.0"
