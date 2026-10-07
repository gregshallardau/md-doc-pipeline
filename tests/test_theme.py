from md_doc.theme import generate_base_theme, DEFAULTS


def test_generated_theme_includes_form_field_css():
    css = generate_base_theme(**DEFAULTS)
    assert "appearance: auto" in css


def test_word_theme_resolves_css_font_stack_like_pdf(tmp_path, monkeypatch):
    from md_doc import docx_theme

    css = tmp_path / "_theme.css"
    css.write_text("body { font-family: 'Missing Font', 'DejaVu Sans', sans-serif; }")
    doc = tmp_path / "document.md"
    doc.write_text("Body")
    parsed = docx_theme.parse_css_for_word(css)
    assert parsed["font_body"] == "Missing Font"
    monkeypatch.setattr(docx_theme, "_resolve_font_stack", lambda stack: "DejaVu Sans")
    assert docx_theme.resolve_docx_theme(doc, tmp_path)["font_body"] == "DejaVu Sans"


def test_word_keeps_primary_font_without_pdf_font_matcher(tmp_path, monkeypatch):
    from md_doc import docx_theme

    (tmp_path / "_theme.css").write_text("body { font-family: 'Preferred', sans-serif; }")
    doc = tmp_path / "document.md"
    doc.write_text("Body")
    monkeypatch.setattr(docx_theme, "_resolve_font_stack", lambda stack: None)
    assert docx_theme.resolve_docx_theme(doc, tmp_path)["font_body"] == "Preferred"
