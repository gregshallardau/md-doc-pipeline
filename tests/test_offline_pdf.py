"""The PDF renderer must never delegate network URLs to a fetcher."""

import pytest

from md_doc.builders import pdf


@pytest.mark.parametrize(
    "url",
    [
        "https://example.invalid/image.png",
        "http://127.0.0.1/image.png",
        "ftp://example.invalid/image.png",
        "//example.invalid/image.png",
        "file://example.invalid/share/image.png",
        "file:////example.invalid/share/image.png",
        "file:///%5C%5Cexample.invalid/share/image.png",
    ],
)
def test_network_urls_rejected_before_fetch(monkeypatch, url):
    def unexpected(*args, **kwargs):
        pytest.fail("Network URL reached the underlying fetcher")

    monkeypatch.setattr(pdf.weasyprint, "default_url_fetcher", unexpected)
    with pytest.raises(ValueError, match="External resource blocked"):
        pdf._local_url_fetcher(url)


def test_local_and_embedded_resources_still_work(tmp_path):
    resource = tmp_path / "local.css"
    resource.write_text("body { color: red }")
    result = pdf._local_url_fetcher(resource.as_uri())

    def read_and_close(response):
        if isinstance(response, dict):  # WeasyPrint < 68
            if "string" in response:
                return response["string"]
            with response["file_obj"] as stream:
                return stream.read()
        try:
            return response.read()
        finally:
            response.close()

    assert read_and_close(result) == b"body { color: red }"
    assert read_and_close(pdf._local_url_fetcher("data:text/plain;base64,b2s=")) == b"ok"


def test_pdf_build_uses_local_fetcher(tmp_path, monkeypatch):
    seen = []

    class HTML:
        def __init__(self, **kwargs):
            seen.append(kwargs["url_fetcher"])

        def write_pdf(self, *args, **kwargs):
            pass

    monkeypatch.setattr(pdf.weasyprint, "HTML", HTML)
    pdf.build("# Local document", {"title": "Local", "cover_page": False}, tmp_path / "doc.pdf")
    assert seen == [pdf._local_url_fetcher]
