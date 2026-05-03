# Live Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `md-doc preview <file>` command that serves a live-reloading HTML/PDF preview of a document, plus a thin VSCode extension that embeds it in a side panel.

**Architecture:** A Python HTTP server (`md_doc/preview.py`) renders the document using the existing pipeline, watches the file and its config cascade for changes, and pushes Server-Sent Events to connected browsers to trigger a reload. A thin VSCode extension (~80 lines TypeScript) spawns the server for the active file and loads the URL in a WebviewPanel — zero rendering logic in TypeScript.

**Tech Stack:** Python stdlib `http.server`, `watchdog>=4.0` (file watching), existing `md_doc` pipeline (`config`, `renderer`, `builders/pdf`), TypeScript + VS Code Extension API.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `pyproject.toml` | Add `watchdog` to core deps |
| Modify | `md_doc/builders/pdf.py` | Add public `build_preview_html()` function |
| Create | `md_doc/preview.py` | HTTP server, file watcher, SSE, render orchestration |
| Modify | `md_doc/cli.py` | Add `preview` Click command |
| Create | `tests/test_preview.py` | Unit + integration tests for preview module |
| Create | `vscode-extension/package.json` | Extension manifest |
| Create | `vscode-extension/tsconfig.json` | TypeScript config |
| Create | `vscode-extension/src/extension.ts` | Extension activate, commands, WebviewPanel |

---

## Task 1: Add watchdog dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add watchdog to core dependencies**

Edit `pyproject.toml`, add `"watchdog>=4.0"` to the `dependencies` list:

```toml
dependencies = [
    "pyyaml>=6.0",
    "jinja2>=3.1",
    "weasyprint>=60.0",
    "python-docx>=1.1",
    "markdown>=3.5",
    "click>=8.1",
    "markitdown[pdf,docx]>=0.1.0",
    "watchdog>=4.0",
]
```

- [ ] **Step 2: Install the new dependency**

```bash
uv sync --group dev
```

Expected: resolves and installs `watchdog` with no errors.

- [ ] **Step 3: Verify import works**

```bash
uv run python -c "import watchdog; print(watchdog.__version__)"
```

Expected: prints a version string like `4.0.2`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add watchdog dependency for live preview file watching"
```

---

## Task 2: Add `build_preview_html()` to pdf.py

**Files:**
- Modify: `md_doc/builders/pdf.py`
- Test: `tests/test_preview.py` (new file, first tests)

The existing `build()` function writes a PDF to disk. We need a variant that returns the intermediate HTML string so the preview server can serve it without running WeasyPrint.

- [ ] **Step 1: Write the failing test**

Create `tests/test_preview.py`:

```python
"""Tests for md_doc.preview and related helpers."""
import datetime
from pathlib import Path

import pytest

from md_doc.builders.pdf import build_preview_html
from md_doc.config import load_config


def test_build_preview_html_returns_html_string(tmp_path):
    """build_preview_html returns a complete HTML document string."""
    (tmp_path / ".git").mkdir()
    doc = tmp_path / "test.md"
    doc.write_text("# Hello\n\nWorld\n")

    config = load_config(doc, repo_root=tmp_path)
    html = build_preview_html(doc, config, repo_root=tmp_path)

    assert isinstance(html, str)
    assert "<!DOCTYPE html>" in html
    assert "Hello" in html
    assert "World" in html


def test_build_preview_html_includes_title_from_h1(tmp_path):
    """build_preview_html uses the first H1 as the document title."""
    (tmp_path / ".git").mkdir()
    doc = tmp_path / "report.md"
    doc.write_text("# My Report\n\nContent here.\n")

    config = load_config(doc, repo_root=tmp_path)
    html = build_preview_html(doc, config, repo_root=tmp_path)

    assert "My Report" in html


def test_build_preview_html_no_cover_when_disabled(tmp_path):
    """build_preview_html respects cover_page: false in config."""
    (tmp_path / ".git").mkdir()
    doc = tmp_path / "nodoc.md"
    doc.write_text("---\ncover_page: false\n---\n# Doc\n\nText.\n")

    config = load_config(doc, repo_root=tmp_path)
    html = build_preview_html(doc, config, repo_root=tmp_path)

    assert 'class="cover"' not in html
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_preview.py -v
```

Expected: `ImportError: cannot import name 'build_preview_html'`

- [ ] **Step 3: Implement `build_preview_html` in `md_doc/builders/pdf.py`**

Add this function after `_resolve_css` and before `build()`:

```python
def build_preview_html(
    doc_path: Path,
    config: dict[str, Any],
    *,
    repo_root: Path | None = None,
) -> str:
    """Return the rendered HTML for *doc_path* without running WeasyPrint.

    Uses the same pipeline as build() but stops before PDF generation,
    making it fast enough for live preview use (~100ms).
    """
    import datetime

    from ..renderer import render as _render

    doc_path = Path(doc_path).resolve()
    if repo_root is None:
        repo_root = _find_repo_root(doc_path.parent)

    rendered_md = _render(doc_path, config)

    title = (
        config.get("title")
        or _extract_title(rendered_md)
        or doc_path.stem
    )
    author = config.get("author", "Document Producer")
    date_str = config.get("date", datetime.date.today().isoformat())
    cover_page = config.get("cover_page", True)

    body_md = _strip_leading_h1(rendered_md) if cover_page else rendered_md
    body_md = _inject_appendix_breaks(body_md)

    import markdown as _markdown
    html_body = _markdown.markdown(body_md, extensions=_MD_EXTENSIONS)

    css_path = _resolve_css(config, repo_root, doc_path)

    return _build_html(
        title=title,
        date_str=date_str,
        author=author,
        html_body=html_body,
        css_path=css_path,
        cover_page=cover_page,
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_preview.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add md_doc/builders/pdf.py tests/test_preview.py
git commit -m "feat: add build_preview_html() to pdf builder"
```

---

## Task 3: `_collect_watch_paths()` and `_should_poll()`

**Files:**
- Create: `md_doc/preview.py`
- Test: `tests/test_preview.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_preview.py`:

```python
from md_doc.preview import _collect_watch_paths, _should_poll


def test_collect_watch_paths_includes_doc_and_meta(tmp_path):
    """_collect_watch_paths returns the doc file and any _meta.yml in the cascade."""
    (tmp_path / ".git").mkdir()
    sub = tmp_path / "workspace" / "acme"
    sub.mkdir(parents=True)
    doc = sub / "proposal.md"
    doc.write_text("# Proposal\n")
    meta = sub / "_meta.yml"
    meta.write_text("title: Test\n")

    paths = _collect_watch_paths(doc)

    assert doc in paths
    assert meta in paths


def test_collect_watch_paths_includes_ancestor_meta(tmp_path):
    """_collect_watch_paths includes _meta.yml files in parent directories."""
    (tmp_path / ".git").mkdir()
    parent_meta = tmp_path / "_meta.yml"
    parent_meta.write_text("author: Root\n")
    sub = tmp_path / "docs"
    sub.mkdir()
    doc = sub / "report.md"
    doc.write_text("# Report\n")

    paths = _collect_watch_paths(doc)

    assert parent_meta in paths


def test_collect_watch_paths_includes_templates_dir(tmp_path):
    """_collect_watch_paths includes any templates/ directory in the cascade."""
    (tmp_path / ".git").mkdir()
    templates = tmp_path / "templates"
    templates.mkdir()
    doc = tmp_path / "report.md"
    doc.write_text("# Report\n")

    paths = _collect_watch_paths(doc)

    assert templates in paths


def test_should_poll_true_for_mnt_paths():
    assert _should_poll([Path("/mnt/c/Users/greg/doc.md")]) is True


def test_should_poll_false_for_native_paths():
    assert _should_poll([Path("/home/greg/project/doc.md")]) is False


def test_should_poll_true_if_any_path_is_mnt():
    assert _should_poll([Path("/home/greg/doc.md"), Path("/mnt/d/workspace/meta.yml")]) is True
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_preview.py::test_collect_watch_paths_includes_doc_and_meta -v
```

Expected: `ModuleNotFoundError: No module named 'md_doc.preview'`

- [ ] **Step 3: Create `md_doc/preview.py` with the two functions**

```python
"""
Live preview server for md-doc documents.

Starts a local HTTP server that renders a Markdown document using the
existing pipeline and serves it at http://localhost:<port>. File changes
are detected and pushed to connected browsers via Server-Sent Events.

Public API
----------
    serve(doc_path, *, mode, trigger, port, idle_ms, poll_ms, open_browser)
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .config import load_config, _find_repo_root


def _collect_watch_paths(doc_path: Path) -> list[Path]:
    """Return all paths that should trigger a rebuild when changed.

    Includes: the document itself, all _meta.yml files in the cascade
    from doc dir up to repo root, and any templates/ directories found
    along the way.
    """
    doc_path = doc_path.resolve()
    repo_root = _find_repo_root(doc_path.parent)

    paths: list[Path] = [doc_path]

    # Walk from doc dir up to repo root, collecting _meta.yml + templates/
    current = doc_path.parent
    visited: set[Path] = set()
    while True:
        if current in visited:
            break
        visited.add(current)

        meta = current / "_meta.yml"
        if meta.exists():
            paths.append(meta)

        templates = current / "templates"
        if templates.is_dir():
            paths.append(templates)

        css = current / "_pdf-theme.css"
        if css.exists():
            paths.append(css)

        if current == repo_root or current == current.parent:
            break
        current = current.parent

    return paths


def _should_poll(paths: list[Path]) -> bool:
    """Return True if any watched path is under a WSL mount point (/mnt/).

    WSL-mounted paths don't reliably trigger inotify events for changes
    made from the Windows side. PollingObserver is used as fallback.
    """
    return any(str(p).startswith("/mnt/") for p in paths)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_preview.py -v
```

Expected: all existing tests pass (including new ones).

- [ ] **Step 5: Commit**

```bash
git add md_doc/preview.py tests/test_preview.py
git commit -m "feat: add preview module with watch path collection"
```

---

## Task 4: `_inject_sse_script()`

**Files:**
- Modify: `md_doc/preview.py`
- Test: `tests/test_preview.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_preview.py`:

```python
from md_doc.preview import _inject_sse_script


def test_inject_sse_script_inserts_before_body_close():
    html = "<html><body><p>Content</p></body></html>"
    result = _inject_sse_script(html)
    assert "<script>" in result
    assert "EventSource" in result
    assert result.index("<script>") < result.index("</body>")


def test_inject_sse_script_appends_if_no_body_close():
    """Falls back to appending if </body> is missing."""
    html = "<html><p>No body tag</p></html>"
    result = _inject_sse_script(html)
    assert "EventSource" in result


def test_inject_sse_script_idempotent_structure():
    """Injecting twice doesn't duplicate the script."""
    html = "<html><body><p>Hi</p></body></html>"
    once = _inject_sse_script(html)
    assert once.count("EventSource") == 1
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_preview.py::test_inject_sse_script_inserts_before_body_close -v
```

Expected: `ImportError: cannot import name '_inject_sse_script'`

- [ ] **Step 3: Implement `_inject_sse_script` in `md_doc/preview.py`**

Add after `_should_poll`:

```python
_SSE_SCRIPT = (
    '<script>'
    'new EventSource("/events").onmessage=function(){location.reload();};'
    '</script>'
)


def _inject_sse_script(html: str) -> str:
    """Inject the SSE live-reload script before </body>, or append if absent."""
    marker = "</body>"
    if marker in html:
        return html.replace(marker, _SSE_SCRIPT + marker, 1)
    return html + _SSE_SCRIPT
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_preview.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add md_doc/preview.py tests/test_preview.py
git commit -m "feat: add SSE script injection to preview module"
```

---

## Task 5: HTTP request handler

**Files:**
- Modify: `md_doc/preview.py`
- Test: `tests/test_preview.py`

The handler serves four routes: `/` (preview page), `/events` (SSE stream), `/preview.pdf` (PDF bytes, PDF mode only), `/rebuild` (manual trigger).

- [ ] **Step 1: Write the failing integration test**

Append to `tests/test_preview.py`:

```python
import socket
import threading
import time
import urllib.request
from http.server import HTTPServer

from md_doc.preview import _make_handler


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_handler_serves_html_on_root(tmp_path):
    """GET / returns the rendered HTML."""
    (tmp_path / ".git").mkdir()
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello Preview\n\nBody text.\n")

    html_store = {"html": "<html><body>Hello Preview</body></html>"}
    rebuild_event = threading.Event()
    sse_clients: list = []

    port = _free_port()
    handler = _make_handler(html_store, rebuild_event, sse_clients, pdf_store={"pdf": None})
    server = HTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=server.handle_request)
    t.start()

    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/")
    body = resp.read().decode()
    t.join(timeout=2)
    server.server_close()

    assert "Hello Preview" in body
    assert "EventSource" in body  # SSE script injected


def test_handler_rebuild_endpoint_sets_event(tmp_path):
    """GET /rebuild sets the rebuild_event flag."""
    html_store = {"html": "<html><body>x</body></html>"}
    rebuild_event = threading.Event()
    sse_clients: list = []

    port = _free_port()
    handler = _make_handler(html_store, rebuild_event, sse_clients, pdf_store={"pdf": None})
    server = HTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=server.handle_request)
    t.start()

    urllib.request.urlopen(f"http://127.0.0.1:{port}/rebuild")
    t.join(timeout=2)
    server.server_close()

    assert rebuild_event.is_set()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_preview.py::test_handler_serves_html_on_root -v
```

Expected: `ImportError: cannot import name '_make_handler'`

- [ ] **Step 3: Implement `_make_handler` in `md_doc/preview.py`**

Add after `_inject_sse_script`:

```python
import http.server
import io


def _make_handler(
    html_store: dict[str, str | None],
    rebuild_event: threading.Event,
    sse_clients: list[Any],
    pdf_store: dict[str, bytes | None],
) -> type:
    """Return a request handler class closed over shared state."""

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            pass  # suppress access logs

        def do_GET(self) -> None:
            if self.path == "/":
                self._serve_preview()
            elif self.path == "/events":
                self._serve_sse()
            elif self.path == "/preview.pdf":
                self._serve_pdf()
            elif self.path == "/rebuild":
                self._trigger_rebuild()
            else:
                self.send_error(404)

        def _serve_preview(self) -> None:
            html = html_store.get("html") or "<html><body>Rendering...</body></html>"
            body = _inject_sse_script(html).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_pdf(self) -> None:
            pdf = pdf_store.get("pdf")
            if pdf is None:
                self.send_error(503, "PDF not yet rendered")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(pdf)))
            self.end_headers()
            self.wfile.write(pdf)

        def _serve_sse(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            # Register this client
            sse_clients.append(self.wfile)
            # Keep connection open until client disconnects
            try:
                while True:
                    threading.Event().wait(30)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                if self.wfile in sse_clients:
                    sse_clients.remove(self.wfile)

        def _trigger_rebuild(self) -> None:
            rebuild_event.set()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"rebuilding")

    return _Handler
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_preview.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add md_doc/preview.py tests/test_preview.py
git commit -m "feat: add HTTP request handler to preview module"
```

---

## Task 6: File watcher + SSE broadcast

**Files:**
- Modify: `md_doc/preview.py`
- Test: `tests/test_preview.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_preview.py`:

```python
import io
from md_doc.preview import _broadcast_reload, _build_watcher


def test_broadcast_reload_pushes_to_all_clients():
    """_broadcast_reload writes SSE data to all connected clients."""
    buf1 = io.BytesIO()
    buf2 = io.BytesIO()
    clients = [buf1, buf2]

    _broadcast_reload(clients)

    buf1.seek(0)
    buf2.seek(0)
    assert b"data: reload" in buf1.read()
    assert b"data: reload" in buf2.read()


def test_broadcast_reload_removes_dead_clients():
    """_broadcast_reload silently removes clients that raise on write."""

    class _DeadStream:
        def write(self, data: bytes) -> None:
            raise BrokenPipeError

        def flush(self) -> None:
            pass

    clients = [_DeadStream()]
    _broadcast_reload(clients)  # should not raise
    assert clients == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_preview.py::test_broadcast_reload_pushes_to_all_clients -v
```

Expected: `ImportError: cannot import name '_broadcast_reload'`

- [ ] **Step 3: Implement `_broadcast_reload` and `_build_watcher` in `md_doc/preview.py`**

Add after `_make_handler`:

```python
def _broadcast_reload(sse_clients: list[Any]) -> None:
    """Push a reload event to all connected SSE clients, removing dead ones."""
    message = b"data: reload\n\n"
    dead = []
    for client in sse_clients:
        try:
            client.write(message)
            client.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            dead.append(client)
    for client in dead:
        sse_clients.remove(client)


def _build_watcher(
    watch_paths: list[Path],
    on_change: Any,
    poll_ms: int,
    use_poll: bool,
) -> Any:
    """Build and return a started watchdog observer.

    Uses PollingObserver for WSL-mounted paths, InotifyObserver otherwise.
    """
    from watchdog.observers import Observer
    from watchdog.observers.polling import PollingObserver
    from watchdog.events import FileSystemEventHandler

    class _Handler(FileSystemEventHandler):
        def on_modified(self, event: Any) -> None:
            if not event.is_directory:
                on_change()

        def on_created(self, event: Any) -> None:
            if not event.is_directory:
                on_change()

    ObserverClass = PollingObserver if use_poll else Observer
    observer = ObserverClass(timeout=poll_ms / 1000)

    # Watch each path: files are watched via their parent dir (watchdog requirement)
    watched_dirs: set[Path] = set()
    handler = _Handler()
    for path in watch_paths:
        watch_dir = path if path.is_dir() else path.parent
        if watch_dir not in watched_dirs:
            observer.schedule(handler, str(watch_dir), recursive=path.is_dir())
            watched_dirs.add(watch_dir)

    observer.start()
    return observer
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_preview.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add md_doc/preview.py tests/test_preview.py
git commit -m "feat: add SSE broadcast and file watcher to preview module"
```

---

## Task 7: `serve()` — the public entry point

**Files:**
- Modify: `md_doc/preview.py`

This function wires together the server, watcher, and render loop. It is not unit-tested directly (tested via the CLI command in Task 8). It blocks until Ctrl-C.

- [ ] **Step 1: Implement `serve()` in `md_doc/preview.py`**

Add after `_build_watcher`:

```python
import datetime
import logging
import webbrowser

logger = logging.getLogger(__name__)


def serve(
    doc_path: Path,
    *,
    mode: str = "html",
    trigger: str = "save",
    port: int = 8765,
    idle_ms: int = 500,
    poll_ms: int = 1000,
    open_browser: bool = False,
) -> None:
    """Start the preview server and block until Ctrl-C.

    Parameters
    ----------
    doc_path : Path
        The Markdown document to preview.
    mode : str
        ``"html"`` (fast, default) or ``"pdf"`` (exact, slow).
    trigger : str
        ``"save"`` — rebuild on file change.
        ``"idle"`` — rebuild after *idle_ms* ms of no further changes.
        ``"manual"`` — only rebuild via GET /rebuild.
    port : int
        HTTP server port (default 8765).
    idle_ms : int
        Debounce delay for idle trigger (default 500).
    poll_ms : int
        File poll interval for WSL-mounted paths (default 1000).
    open_browser : bool
        Open the default browser on startup.
    """
    from http.server import HTTPServer

    from .builders.pdf import build_preview_html, build as build_pdf
    from .config import load_config
    from .renderer import render as _render_doc

    doc_path = Path(doc_path).resolve()
    repo_root = _find_repo_root(doc_path.parent)

    # Shared mutable state (protected by _lock)
    _lock = threading.Lock()
    html_store: dict[str, str | None] = {"html": None}
    pdf_store: dict[str, bytes | None] = {"pdf": None}
    sse_clients: list[Any] = []
    rebuild_event = threading.Event()

    def _render() -> None:
        """Run the pipeline and update shared stores."""
        try:
            config = load_config(doc_path, repo_root=repo_root)
            html = build_preview_html(doc_path, config, repo_root=repo_root)
            with _lock:
                html_store["html"] = html
            if mode == "pdf":
                import tempfile
                tmp = Path(tempfile.mktemp(suffix=".pdf"))
                rendered_md = _render_doc(doc_path, config)
                build_pdf(
                    rendered_md,
                    config,
                    tmp,
                    repo_root=repo_root,
                    doc_path=doc_path,
                )
                with _lock:
                    pdf_store["pdf"] = tmp.read_bytes()
                tmp.unlink(missing_ok=True)
            _broadcast_reload(sse_clients)
            logger.info("Rebuilt %s", doc_path.name)
        except Exception as exc:
            logger.error("Rebuild failed: %s", exc)

    # Initial render
    _render()

    # File watcher (only for save/idle triggers)
    observer = None
    if trigger in ("save", "idle"):
        watch_paths = _collect_watch_paths(doc_path)
        use_poll = _should_poll(watch_paths)

        _pending_timer: list[Any] = [None]

        def _on_change() -> None:
            if trigger == "save":
                _render()
            else:  # idle — debounce
                if _pending_timer[0]:
                    _pending_timer[0].cancel()
                t = threading.Timer(idle_ms / 1000, _render)
                _pending_timer[0] = t
                t.start()

        observer = _build_watcher(watch_paths, _on_change, poll_ms=poll_ms, use_poll=use_poll)

    # Manual rebuild: poll the rebuild_event in a background thread
    def _manual_rebuild_loop() -> None:
        while True:
            rebuild_event.wait()
            rebuild_event.clear()
            _render()

    if trigger == "manual":
        threading.Thread(target=_manual_rebuild_loop, daemon=True).start()

    # Start HTTP server
    handler = _make_handler(html_store, rebuild_event, sse_clients, pdf_store)
    server = HTTPServer(("127.0.0.1", port), handler)

    url = f"http://localhost:{port}"
    print(f"md-doc preview: {url}  (Ctrl-C to stop)")

    if open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if observer:
            observer.stop()
            observer.join()
```

- [ ] **Step 2: Verify existing tests still pass**

```bash
uv run pytest tests/test_preview.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add md_doc/preview.py
git commit -m "feat: add serve() entry point to preview module"
```

---

## Task 8: `md-doc preview` CLI command

**Files:**
- Modify: `md_doc/cli.py`
- Test: `tests/test_preview.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_preview.py`:

```python
from click.testing import CliRunner
from md_doc.cli import main


def test_preview_command_exists():
    """md-doc preview --help exits cleanly."""
    runner = CliRunner()
    result = runner.invoke(main, ["preview", "--help"])
    assert result.exit_code == 0
    assert "--mode" in result.output
    assert "--trigger" in result.output
    assert "--port" in result.output
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
uv run pytest tests/test_preview.py::test_preview_command_exists -v
```

Expected: `AssertionError` — `preview` subcommand not found.

- [ ] **Step 3: Add the `preview` command to `md_doc/cli.py`**

Open `md_doc/cli.py`. At the top, add the preview import alongside existing imports:

```python
from .preview import serve as _preview_serve
```

Then add the command (place it before the `if __name__ == "__main__":` block, or after the last existing command):

```python
@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--mode", type=click.Choice(["html", "pdf"]), default="html", show_default=True)
@click.option(
    "--trigger",
    type=click.Choice(["save", "idle", "manual"]),
    default="save",
    show_default=True,
)
@click.option("--port", type=int, default=8765, show_default=True)
@click.option("--idle-ms", type=int, default=500, show_default=True)
@click.option("--poll-ms", type=int, default=1000, show_default=True)
@click.option("--open", "open_browser", is_flag=True, default=False)
def preview(
    path: Path,
    mode: str,
    trigger: str,
    port: int,
    idle_ms: int,
    poll_ms: int,
    open_browser: bool,
) -> None:
    """Start a live-reloading preview server for PATH."""
    _preview_serve(
        path,
        mode=mode,
        trigger=trigger,
        port=port,
        idle_ms=idle_ms,
        poll_ms=poll_ms,
        open_browser=open_browser,
    )
```

- [ ] **Step 4: Run all tests**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass including the new one.

- [ ] **Step 5: Smoke test manually**

```bash
uv run md-doc preview --help
```

Expected output includes `--mode`, `--trigger`, `--port`, `--idle-ms`, `--poll-ms`, `--open`.

- [ ] **Step 6: Commit**

```bash
git add md_doc/cli.py tests/test_preview.py
git commit -m "feat: add md-doc preview CLI command"
```

---

## Task 9: Integration smoke test

**Files:**
- Test: `tests/test_preview.py`

Verify the full server renders a real document and serves it correctly.

- [ ] **Step 1: Write the integration test**

Append to `tests/test_preview.py`:

```python
def test_serve_renders_and_serves_html(tmp_path):
    """Full integration: serve() renders a doc and GET / returns its content."""
    (tmp_path / ".git").mkdir()
    doc = tmp_path / "smoke.md"
    doc.write_text("# Smoke Test\n\nFull integration.\n")

    # Run serve() in a background thread, stop after one request
    from md_doc.preview import serve
    import urllib.request

    port = _free_port()
    done = threading.Event()

    def _run():
        # Serve just long enough to handle one request then stop
        from http.server import HTTPServer
        from md_doc.preview import (
            _collect_watch_paths, _should_poll,
            _make_handler, _build_watcher,
        )
        from md_doc.builders.pdf import build_preview_html
        from md_doc.config import load_config, _find_repo_root

        repo_root = _find_repo_root(doc.parent)
        config = load_config(doc, repo_root=repo_root)
        html = build_preview_html(doc, config, repo_root=repo_root)

        html_store = {"html": html}
        pdf_store = {"pdf": None}
        sse_clients: list = []
        rebuild_event = threading.Event()

        handler = _make_handler(html_store, rebuild_event, sse_clients, pdf_store)
        server = HTTPServer(("127.0.0.1", port), handler)
        done.set()
        server.handle_request()
        server.server_close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    done.wait(timeout=5)

    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/")
    body = resp.read().decode()
    t.join(timeout=2)

    assert "Smoke Test" in body
    assert "EventSource" in body
```

- [ ] **Step 2: Run all tests**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_preview.py
git commit -m "test: add integration smoke test for preview server"
```

---

## Task 10: VSCode extension scaffold

**Files:**
- Create: `vscode-extension/package.json`
- Create: `vscode-extension/tsconfig.json`
- Create: `vscode-extension/.vscodeignore`

- [ ] **Step 1: Create `vscode-extension/package.json`**

```json
{
  "name": "md-doc-preview",
  "displayName": "md-doc Preview",
  "description": "Live preview for md-doc-pipeline documents",
  "version": "0.1.0",
  "engines": { "vscode": "^1.85.0" },
  "categories": ["Other"],
  "activationEvents": ["onLanguage:markdown"],
  "main": "./out/extension.js",
  "contributes": {
    "commands": [
      {
        "command": "md-doc.openPreview",
        "title": "md-doc: Open Preview"
      },
      {
        "command": "md-doc.stopPreview",
        "title": "md-doc: Stop Preview"
      },
      {
        "command": "md-doc.rebuildNow",
        "title": "md-doc: Rebuild Now"
      }
    ],
    "configuration": {
      "title": "md-doc Preview",
      "properties": {
        "md-doc.preview.mode": {
          "type": "string",
          "enum": ["html", "pdf"],
          "default": "html",
          "description": "Render mode: html (fast) or pdf (exact)"
        },
        "md-doc.preview.trigger": {
          "type": "string",
          "enum": ["save", "idle", "manual"],
          "default": "save",
          "description": "Rebuild trigger: save, idle (debounced), or manual"
        },
        "md-doc.preview.port": {
          "type": "number",
          "default": 8765,
          "description": "Preview server port"
        },
        "md-doc.preview.pollMs": {
          "type": "number",
          "default": 1000,
          "description": "Poll interval (ms) for WSL-mounted paths"
        },
        "md-doc.preview.autoOpen": {
          "type": "boolean",
          "default": false,
          "description": "Automatically open preview when a .md file is opened"
        }
      }
    }
  },
  "scripts": {
    "compile": "tsc -p ./",
    "watch": "tsc -watch -p ./"
  },
  "devDependencies": {
    "@types/vscode": "^1.85.0",
    "@types/node": "^20.0.0",
    "typescript": "^5.3.0"
  }
}
```

- [ ] **Step 2: Create `vscode-extension/tsconfig.json`**

```json
{
  "compilerOptions": {
    "module": "commonjs",
    "target": "ES2020",
    "outDir": "out",
    "lib": ["ES2020"],
    "sourceMap": true,
    "rootDir": "src",
    "strict": true
  },
  "exclude": ["node_modules", ".vscode-test"]
}
```

- [ ] **Step 3: Create `vscode-extension/.vscodeignore`**

```
.vscode/**
src/**
.gitignore
tsconfig.json
```

- [ ] **Step 4: Install TypeScript deps**

```bash
cd vscode-extension && npm install
```

Expected: `node_modules/` created, no errors.

- [ ] **Step 5: Commit**

```bash
cd ..
git add vscode-extension/
git commit -m "feat: add VSCode extension scaffold"
```

---

## Task 11: VSCode extension `extension.ts`

**Files:**
- Create: `vscode-extension/src/extension.ts`

- [ ] **Step 1: Create `vscode-extension/src/`**

```bash
mkdir -p vscode-extension/src
```

- [ ] **Step 2: Create `vscode-extension/src/extension.ts`**

```typescript
import * as vscode from 'vscode';
import * as cp from 'child_process';

let serverProcess: cp.ChildProcess | undefined;
let panel: vscode.WebviewPanel | undefined;
let statusBar: vscode.StatusBarItem;

export function activate(context: vscode.ExtensionContext) {
    statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left);
    statusBar.command = 'md-doc.openPreview';
    statusBar.text = '$(circle-outline) md-doc';
    statusBar.show();
    context.subscriptions.push(statusBar);

    context.subscriptions.push(
        vscode.commands.registerCommand('md-doc.openPreview', openPreview),
        vscode.commands.registerCommand('md-doc.stopPreview', stopPreview),
        vscode.commands.registerCommand('md-doc.rebuildNow', rebuildNow),
    );

    // Auto-open if configured
    const cfg = vscode.workspace.getConfiguration('md-doc.preview');
    if (cfg.get<boolean>('autoOpen')) {
        vscode.window.onDidChangeActiveTextEditor(e => {
            if (e?.document.languageId === 'markdown') {
                openPreview();
            }
        }, null, context.subscriptions);
    } else {
        // Prompt to switch when active file changes while preview is running
        vscode.window.onDidChangeActiveTextEditor(e => {
            if (serverProcess && e?.document.languageId === 'markdown') {
                const name = e.document.fileName.split('/').pop() ?? '';
                vscode.window.showInformationMessage(
                    `Switch md-doc preview to ${name}?`,
                    'Yes'
                ).then(choice => { if (choice === 'Yes') openPreview(); });
            }
        }, null, context.subscriptions);
    }
}

function openPreview() {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== 'markdown') {
        vscode.window.showWarningMessage('md-doc preview: open a Markdown file first.');
        return;
    }

    const filePath = editor.document.fileName;
    const cfg = vscode.workspace.getConfiguration('md-doc.preview');
    const mode = cfg.get<string>('mode', 'html');
    const trigger = cfg.get<string>('trigger', 'save');
    const port = cfg.get<number>('port', 8765);
    const pollMs = cfg.get<number>('pollMs', 1000);
    const url = `http://localhost:${port}`;

    // Kill any existing server
    stopPreview();

    serverProcess = cp.spawn('md-doc', [
        'preview', filePath,
        '--mode', mode,
        '--trigger', trigger,
        '--port', String(port),
        '--poll-ms', String(pollMs),
    ], { shell: true });

    serverProcess.on('error', err => {
        vscode.window.showErrorMessage(`md-doc preview: ${err.message}`);
    });

    statusBar.text = `$(circle-filled) md-doc: watching · ${mode} · ${trigger}`;

    // Give the server a moment to start, then open the panel
    setTimeout(() => {
        if (!panel) {
            panel = vscode.window.createWebviewPanel(
                'mdDocPreview',
                'md-doc Preview',
                vscode.ViewColumn.Beside,
                { enableScripts: true, retainContextWhenHidden: true }
            );
            panel.onDidDispose(() => {
                panel = undefined;
                stopPreview();
            });
        }
        panel.webview.html = `<!DOCTYPE html><html><head>
            <style>body,html{margin:0;padding:0;height:100%;overflow:hidden}</style>
        </head><body>
            <iframe src="${url}" style="width:100%;height:100vh;border:none"></iframe>
        </body></html>`;
    }, 800);
}

function stopPreview() {
    if (serverProcess) {
        serverProcess.kill();
        serverProcess = undefined;
    }
    statusBar.text = '$(circle-outline) md-doc';
}

async function rebuildNow() {
    const cfg = vscode.workspace.getConfiguration('md-doc.preview');
    const port = cfg.get<number>('port', 8765);
    try {
        await fetch(`http://localhost:${port}/rebuild`);
    } catch {
        vscode.window.showWarningMessage('md-doc preview: server not running.');
    }
}

export function deactivate() {
    stopPreview();
}
```

- [ ] **Step 3: Compile the extension**

```bash
cd vscode-extension && npm run compile
```

Expected: `out/extension.js` created with no TypeScript errors.

- [ ] **Step 4: Manual smoke test**

1. In VSCode, open the `vscode-extension/` folder
2. Press F5 to launch the Extension Development Host
3. In the new VSCode window, open any `.md` file from `workspace/`
4. Open command palette → `md-doc: Open Preview`
5. Verify a side panel opens showing the rendered document
6. Edit and save the `.md` file — panel should reload

- [ ] **Step 5: Commit**

```bash
cd ..
git add vscode-extension/src/extension.ts vscode-extension/out/
git commit -m "feat: add VSCode extension for live preview"
```

---

## Done

Run the full test suite to confirm everything is green:

```bash
uv run pytest tests/ -v
uv run ruff check .
uv run mypy md_doc/
```
