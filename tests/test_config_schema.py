"""Tests for md_doc.config_schema.validate_config."""

from __future__ import annotations

from md_doc.config_schema import validate_config, KNOWN_KEYS


def _levels(issues):
    return {sev for sev, _ in issues}


def test_clean_config_has_no_issues():
    assert (
        validate_config(
            {"outputs": ["pdf", "docx"], "cover_page": True, "section_bar_color": "#fff"}
        )
        == []
    )


def test_custom_variable_keys_are_allowed():
    # Config keys double as Jinja variables — arbitrary names must not warn.
    assert validate_config({"product_name": "acme", "insurer_name": "cgu"}) == []


def test_typo_of_reserved_key_warns_with_suggestion():
    issues = validate_config({"cover_bard": True})
    assert len(issues) == 1
    sev, msg = issues[0]
    assert sev == "warning"
    assert "cover_bard" in msg and "cover_bar" in msg


def test_bool_key_wrong_type_is_error():
    issues = validate_config({"cover_page": "yes"})
    assert issues == [("error", "'cover_page' must be true or false, got str")]


def test_enum_key_invalid_value_is_error():
    issues = validate_config({"body_text_align": "centre"})
    assert _levels(issues) == {"error"}
    assert "invalid value 'centre'" in issues[0][1]


def test_bad_output_format_is_error():
    issues = validate_config({"outputs": ["pdf", "xls"]})
    assert issues == [("error", "Unknown output format 'xls' in 'outputs'")]


def test_table_col_widths_must_be_numbers():
    assert _levels(validate_config({"table_col_widths": ["a", "b"]})) == {"error"}
    assert validate_config({"table_col_widths": [30, 70]}) == []


def test_non_dict_input_is_ignored():
    assert validate_config(["not", "a", "mapping"]) == []  # type: ignore[arg-type]


def test_known_keys_cover_documented_controls():
    for key in ("outputs", "cover_page", "section_bar", "sync_target", "table_col_widths"):
        assert key in KNOWN_KEYS
