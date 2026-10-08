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


def test_bool_key_accepts_boollike_strings():
    # Real bools and yes/no-style strings are all fine (YAML + rendered Jinja
    # values routinely produce the string "false" / "true").
    for value in (True, False, "true", "false", "yes", "no", "on", "off", "1", "0"):
        assert validate_config({"cover_page": value}) == [], f"{value!r} should be accepted"


def test_bool_key_skips_unresolved_template():
    # A value still containing a Jinja expression can't be type-checked pre-render.
    assert validate_config({"cover_page": "{{ want_cover }}"}) == []


def test_bool_key_non_boollike_string_is_error():
    issues = validate_config({"cover_page": "maybe"})
    assert len(issues) == 1 and issues[0][0] == "error"
    assert "must be true or false" in issues[0][1]


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


def test_cover_text_align_accepts_center():
    """Both builders implement ``center`` and the config reference documents it."""
    from md_doc.config_schema import validate_config

    for value in ("left", "center", "right"):
        assert validate_config({"cover_text_align": value}) == []
    assert validate_config({"cover_text_align": "justify"})
