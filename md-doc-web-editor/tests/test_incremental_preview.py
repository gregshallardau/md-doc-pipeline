"""Checkpoint correctness, progressive delivery and editor lifecycle tests."""

from __future__ import annotations

import io
import time

import pdfplumber
import pytest
import weasyprint
from fastapi.testclient import TestClient

from md_doc_web_editor.incremental import IncrementalPreview
from md_doc_web_editor.server import create_app

pytestmark = pytest.mark.skipif(
    weasyprint.__version__ != IncrementalPreview.supported_version,
    reason="checkpoint adapter is tested for the pinned WeasyPrint release",
)

HEAD = """<html><head><style>
@page {size:A4;margin:20mm;@bottom-right {content:'Page ' counter(page) ' of ' counter(pages)}}
body {font:12pt serif} p {line-height:1.4} table {border-collapse:collapse}
td {border:1px solid black;padding:4px}
</style></head><body>"""


def assert_same_pdf(actual, expected):
    with pdfplumber.open(actual) as a, pdfplumber.open(expected) as b:
        assert len(a.pages) == len(b.pages)
        for left, right in zip(a.pages, b.pages):
            assert (left.width, left.height) == (right.width, right.height)
            assert left.extract_text() == right.extract_text()
            assert [(c["text"], round(c["x0"], 3), round(c["top"], 3)) for c in left.chars] == [
                (c["text"], round(c["x0"], 3), round(c["top"], 3)) for c in right.chars
            ]


@pytest.mark.parametrize("change", ["inline", "insert", "delete", "append", "table"])
def test_cached_prefix_matches_full_render(tmp_path, change, monkeypatch):
    from weasyprint.layout import page as page_layout

    parts = [
        f'<p style="break-before:page">Page {i + 1}. Original paragraph.</p>' for i in range(65)
    ]
    if change == "table":
        parts[49] += (
            "<table>"
            + "".join(f"<tr><td>Row {i}</td><td>Original</td></tr>" for i in range(100))
            + "</table>"
        )
    preview = IncrementalPreview()
    preview.write_pdf(
        HEAD + "".join(parts) + "</body></html>", str(tmp_path), tmp_path / "old.pdf", {}
    )
    if change == "inline":
        parts[49] = parts[49].replace("Original", "Edited")
    elif change == "insert":
        parts.insert(49, '<p style="break-before:page">Inserted page.</p>')
    elif change == "delete":
        del parts[49]
    elif change == "append":
        parts.append('<p style="break-before:page">Appended page.</p>')
    else:
        parts[49] = parts[49].replace("Original</td>", "Changed</td>")

    calls = []
    original = page_layout.remake_page

    def track(index, *args):
        calls.append(index)
        return original(index, *args)

    monkeypatch.setattr(page_layout, "remake_page", track)
    events = []

    def event(message):
        events.append(message)
        assert max(calls) < 64, "visible page must be published before the document tail"

    markup = HEAD + "".join(parts) + "</body></html>"
    output = tmp_path / "new.pdf"
    preview.write_pdf(markup, str(tmp_path), output, {}, visible_page=50, emit=event)
    assert preview.stats["mode"] == "incremental", preview.stats
    assert preview.stats["reused_pages"] >= 38
    assert min(calls) >= preview.stats["reused_pages"]
    if change != "append":
        assert events[0]["page"] == 50
        with pdfplumber.open(events[0]["path"]) as partial:
            assert len(partial.pages) == 1
    monkeypatch.setattr(page_layout, "remake_page", original)
    expected = tmp_path / "full.pdf"
    weasyprint.HTML(string=markup, base_url=str(tmp_path)).write_pdf(expected)
    assert_same_pdf(output, expected)


def test_flowing_paragraphs_and_unchanged_revision(tmp_path):
    parts = [f"<p>{i}. " + "Flowing paragraph content. " * 20 + "</p>" for i in range(130)]
    preview = IncrementalPreview()
    preview.write_pdf(
        HEAD + "".join(parts) + "</body></html>", str(tmp_path), tmp_path / "old.pdf", {}
    )
    parts[105] = parts[105].replace("content", "content with extra words", 1)
    markup = HEAD + "".join(parts) + "</body></html>"
    preview.write_pdf(markup, str(tmp_path), tmp_path / "new.pdf", {})
    assert preview.stats["reused_pages"] > 0
    weasyprint.HTML(string=markup, base_url=str(tmp_path)).write_pdf(tmp_path / "full.pdf")
    assert_same_pdf(tmp_path / "new.pdf", tmp_path / "full.pdf")
    preview.write_pdf(markup, str(tmp_path), tmp_path / "unchanged.pdf", {})
    assert preview.stats["laid_out_pages"] == 0
    assert_same_pdf(tmp_path / "unchanged.pdf", tmp_path / "full.pdf")


@pytest.mark.parametrize("kind", ["image", "inline_svg"])
def test_image_source_edit_refreshes_image_pixels(tmp_path, kind):
    from PIL import Image

    Image.new("RGB", (80, 80), "red").save(tmp_path / "red.png")
    Image.new("RGB", (80, 80), "blue").save(tmp_path / "blue.png")
    parts = [f'<p style="break-before:page">Page {i + 1}</p>' for i in range(65)]
    parts[49] += (
        '<img src="red.png" width="80" height="80">'
        if kind == "image"
        else '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><rect width="80" height="80" fill="red"/></svg>'
    )
    preview = IncrementalPreview()
    preview.write_pdf(
        HEAD + "".join(parts) + "</body></html>", str(tmp_path) + "/", tmp_path / "old.pdf", {}
    )
    parts[49] = parts[49].replace("red.png", "blue.png").replace('fill="red"', 'fill="blue"')
    markup = HEAD + "".join(parts) + "</body></html>"
    preview.write_pdf(markup, str(tmp_path) + "/", tmp_path / "new.pdf", {})
    assert preview.stats["reused_pages"] >= 38
    weasyprint.HTML(string=markup, base_url=str(tmp_path) + "/").write_pdf(tmp_path / "full.pdf")
    with (
        pdfplumber.open(tmp_path / "new.pdf") as actual,
        pdfplumber.open(tmp_path / "full.pdf") as expected,
    ):
        assert (
            actual.pages[49].to_image(resolution=50).original.tobytes()
            == expected.pages[49].to_image(resolution=50).original.tobytes()
        )


def test_cover_running_header_orientation_and_bookmarks(tmp_path):
    markup_head = HEAD.replace(
        "body {",
        """
@page landscape {size:A4 landscape}
@page {@top-left {content:element(header)} @top-right {content:string(section)}}
.header {position:running(header)} h2 {string-set:section content()}
.cover {position:relative;height:250mm;break-after:page}
.cover span {position:absolute;top:40mm;left:30mm}
body {""",
    )
    parts = [
        '<div class="header">Running header</div><div class="cover"><span>Cover artwork</span></div>'
    ]
    parts += [
        f'<h2 id="section-{i}" style="break-before:page">Section {i}</h2><p>Original {i}</p>'
        for i in range(60)
    ]
    parts += ['<div style="page:landscape;break-before:page">Landscape content</div>']
    preview = IncrementalPreview()
    preview.write_pdf(
        markup_head + "".join(parts) + "</body></html>", str(tmp_path), tmp_path / "old.pdf", {}
    )
    parts[49] = parts[49].replace("Original", "Updated")
    markup = markup_head + "".join(parts) + "</body></html>"
    preview.write_pdf(markup, str(tmp_path), tmp_path / "new.pdf", {})
    assert preview.stats["reused_pages"] > 0, preview.stats
    weasyprint.HTML(string=markup, base_url=str(tmp_path)).write_pdf(tmp_path / "full.pdf")
    assert_same_pdf(tmp_path / "new.pdf", tmp_path / "full.pdf")
    with (
        pdfplumber.open(tmp_path / "new.pdf") as actual,
        pdfplumber.open(tmp_path / "full.pdf") as expected,
    ):
        for index in (0, 20, 49, len(actual.pages) - 1):
            assert (
                actual.pages[index].to_image(resolution=50).original.tobytes()
                == expected.pages[index].to_image(resolution=50).original.tobytes()
            )


@pytest.mark.parametrize(
    "change", ["theme", "inline_page_css", "asset", "selector", "footnote", "version", "forms"]
)
def test_global_or_unsupported_changes_use_full_render(tmp_path, change, monkeypatch):
    markup = (
        HEAD
        + "".join(f'<p style="break-before:page">{i}</p>' for i in range(25))
        + "</body></html>"
    )
    preview = IncrementalPreview()
    preview.write_pdf(markup, str(tmp_path), tmp_path / "old.pdf", {}, inputs="original")
    inputs = "original"
    options = {}
    if change == "theme":
        markup = markup.replace("12pt", "14pt")
    elif change == "inline_page_css":
        markup = markup.replace("</body>", "<style>@page {margin:10mm}</style></body>")
    elif change == "asset":
        inputs = "new asset fingerprint"
    elif change == "selector":
        markup = markup.replace("body {", "p:last-child {color:red} body {")
    elif change == "footnote":
        markup = markup.replace("</body>", '<span style="float:footnote">Footnote</span></body>')
    elif change == "version":
        monkeypatch.setattr(weasyprint, "__version__", "unverified")
    else:
        options = {"pdf_forms": True}
    preview.write_pdf(markup, str(tmp_path), tmp_path / "new.pdf", options, inputs=inputs)
    assert preview.stats["mode"] == "full"
    assert preview.stats.get("reused_pages", 0) == 0
    weasyprint.HTML(string=markup, base_url=str(tmp_path)).write_pdf(
        tmp_path / "full.pdf", **options
    )
    assert_same_pdf(tmp_path / "new.pdf", tmp_path / "full.pdf")


def wait_job(client, job):
    deadline = time.monotonic() + 30
    while job["state"] in {"running", "queued"}:
        assert time.monotonic() < deadline
        time.sleep(0.02)
        job = client.get("/api/jobs/" + job["id"]).json()
    assert job["state"] == "succeeded", job
    return job


def test_editor_reuses_worker_for_unsaved_included_markdown(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "_theme.css").write_text("@page {size:A4;margin:20mm} body {font:12pt serif}")
    pages = "\n\n<!-- pagebreak -->\n\n".join(
        f"## Page {i + 1}\n\nOriginal {i + 1}." for i in range(65)
    )
    (tmp_path / "chapter.md").write_text(pages)
    (tmp_path / "doc.md").write_text('{% include "chapter.md" %}')
    with TestClient(create_app(tmp_path)) as client:
        first = wait_job(
            client,
            client.post("/api/preview/jobs", json={"path": "doc.md", "client": "same"}).json(),
        )
        session = client.app.state.studio.sessions["same"]
        pid = session.process.pid
        response = client.post(
            "/api/preview/jobs",
            json={
                "path": "doc.md",
                "client": "same",
                "revision": 2,
                "visible_page": 50,
                "buffers": {"chapter.md": pages.replace("Original 50.", "Updated 50.")},
            },
        )
        job = wait_job(client, response.json())
        assert session.process.pid == pid
        assert job["render_stats"]["reused_pages"] >= 38
        assert job["preview_pages"][0]["revision"] == 2
        partial = client.get(job["preview_pages"][0]["url"])
        with pdfplumber.open(io.BytesIO(partial.content)) as pdf:
            assert "Updated 50." in pdf.pages[0].extract_text()
        assert (tmp_path / "chapter.md").read_text() == pages
        assert not list(tmp_path.glob("*.pdf"))
        assert first["artifact"]["url"] != job["artifact"]["url"]
        process = session.process
    assert process.returncode is not None
    assert session.process is None
    assert not session.directory.exists()
