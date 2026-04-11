from md_doc.theme import generate_base_theme, DEFAULTS


def test_generated_theme_includes_form_field_css():
    css = generate_base_theme(**DEFAULTS)
    assert "appearance: auto" in css
