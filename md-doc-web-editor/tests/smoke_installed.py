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
                    url + "/api/build",
                    data=json.dumps({"path": "doc.md", "format": "docx"}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(request, timeout=30) as response:
                    token = json.load(response)["token"]
                with urlopen(url + "/api/build/" + token) as response:
                    assert response.read().startswith(b"PK")
                print(
                    "Installed editor started, served static assets, and built Word with PATH empty."
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
