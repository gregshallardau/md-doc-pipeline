"""Start an installed editor outside its checkout and exercise HTTP + Word build.

Run with the installed environment's Python; only the standard library is used.
"""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


def main():
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        (workspace / ".git").mkdir()
        (workspace / "doc.md").write_text("# Smoke test\nHello.\n")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        env = dict(os.environ, PATH="")
        with (workspace / "server.log").open("w+") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "md_doc_web_editor.cli",
                    "serve",
                    str(workspace),
                    "--port",
                    str(port),
                    "--no-browser",
                ],
                cwd=workspace,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("Editor exited before serving requests")
                    try:
                        with urlopen(url + "/", timeout=1) as response:
                            assert b"<html" in response.read().lower()
                        break
                    except URLError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Editor did not become ready")
                for asset in (
                    "editor.js",
                    "composition.js",
                    "viewer.js",
                    "preview-window.html",
                    "preview-window.js",
                    "vendor/pdfjs-6.4.299/legacy/build/pdf.min.mjs",
                    "vendor/pdfjs-6.4.299/legacy/build/pdf.worker.min.mjs",
                    "vendor/pdfjs-6.4.299/web/pdf_viewer.mjs",
                    "vendor/marked-17.0.5/marked.umd.js",
                    "vendor/monaco-editor-0.52.2/min/vs/loader.js",
                    "vendor/monaco-editor-0.52.2/min/vs/editor/editor.main.js",
                    "vendor/monaco-editor-0.52.2/min/vs/base/worker/workerMain.js",
                ):
                    with urlopen(url + "/static/" + asset) as response:
                        assert response.status == 200
                        assert response.read()
                with urlopen(url + "/api/tree") as response:
                    assert json.load(response)["workspace"] == str(workspace)
                request = Request(
                    url + "/api/outline",
                    data=json.dumps(
                        {
                            "path": "doc.md",
                            "buffers": {
                                "doc.md": '# Composed title\n\n{% include "fragment.md" %}\n',
                                "fragment.md": "## Included heading\n",
                            },
                        }
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(request, timeout=30) as response:
                    outline = json.load(response)
                    assert [item["title"] for item in outline["headings"]] == [
                        "Composed title",
                        "Included heading",
                    ]
                    assert outline["headings"][1]["path"] == "fragment.md"
                request = Request(
                    url + "/api/build",
                    data=json.dumps({"path": "doc.md", "format": "docx"}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(request, timeout=30) as response:
                    token = json.load(response)["token"]
                with urlopen(url + "/api/build/" + token) as response:
                    assert response.read().startswith(b"PK")
                request = Request(
                    url + "/api/preview/jobs",
                    data=json.dumps(
                        {"path": "doc.md", "buffers": {"doc.md": "# Unsaved packaged preview\n"}}
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(request, timeout=30) as response:
                    job = json.load(response)
                deadline = time.monotonic() + 30
                while job["state"] in {"queued", "running"}:
                    assert time.monotonic() < deadline
                    time.sleep(0.1)
                    with urlopen(url + "/api/jobs/" + job["id"]) as response:
                        job = json.load(response)
                assert job["state"] == "succeeded", job
                with urlopen(url + job["artifact"]["url"]) as response:
                    assert response.read().startswith(b"%PDF")
                assert (workspace / "doc.md").read_text() == "# Smoke test\nHello.\n"
                print(
                    "Installed editor served offline assets, built Word and rendered an unsaved PDF with PATH empty."
                )
            except Exception:
                log.seek(0)
                print(log.read(), file=sys.stderr)
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
