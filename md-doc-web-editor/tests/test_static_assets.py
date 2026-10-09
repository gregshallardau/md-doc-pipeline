"""Browser module responses must not depend on Windows/system MIME mappings."""

import mimetypes

from fastapi.testclient import TestClient

from md_doc_web_editor.server import create_app


def test_javascript_module_types_override_system_registry(tmp_path, monkeypatch):
    original = mimetypes.guess_type

    def incorrect_type(path, strict=True):
        if str(path).endswith((".js", ".mjs")):
            return "text/plain", None
        return original(path, strict=strict)

    monkeypatch.setattr(mimetypes, "guess_type", incorrect_type)
    with TestClient(create_app(tmp_path)) as client:
        for path in (
            "viewer.js",
            "vendor/pdfjs-6.4.299/legacy/build/pdf.min.mjs",
            "vendor/pdfjs-6.4.299/web/pdf_viewer.mjs",
            "vendor/pdfjs-6.4.299/legacy/build/pdf.worker.min.mjs",
        ):
            response = client.get("/static/" + path)
            assert response.status_code == 200
            assert response.headers["content-type"].split(";")[0] == "text/javascript"
            head = client.head("/static/" + path)
            assert head.headers["content-type"].split(";")[0] == "text/javascript"
            assert head.headers["cache-control"] in {"no-cache", "no-store"}
