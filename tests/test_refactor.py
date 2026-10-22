"""Tests for `md-doc refactor` (shared-section detection and extraction)."""

import pytest
from click.testing import CliRunner

from md_doc.cli import main
from md_doc.refactor import find_shared_sections
from md_doc.renderer import render

ABOUT = (
    "## About Blueshift\n\n"
    "Blueshift is a consultancy helping teams ship documents faster, with\n"
    "templates, themes and automated builds across every format.\n\n"
    "- Founded in 2015\n- Offices in Sydney and Melbourne\n"
)


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / ".git").mkdir()
    for i, body in enumerate(["Intro A.", "Intro B.", "Intro C."]):
        (tmp_path / f"doc{i}.md").write_text(
            f"---\ntitle: Doc {i}\n---\n\n# Doc {i}\n\n{body}\n\n{ABOUT}\nUnique end {i}.\n"
        )
    return tmp_path


def test_detects_shared_run_as_one_group(repo):
    groups = find_shared_sections(repo)
    assert len(groups) == 1
    g = groups[0]
    assert g.name == "about-blueshift"
    assert len(g.docs) == 3
    assert "Founded in 2015" in g.text
    assert g.target == repo / "templates" / "about-blueshift.md"


def test_thresholds(repo):
    assert find_shared_sections(repo, min_docs=4) == []
    assert find_shared_sections(repo, min_chars=10_000) == []


def test_dry_run_changes_nothing(repo):
    before = (repo / "doc0.md").read_text()
    result = CliRunner().invoke(main, ["refactor", str(repo)])
    assert result.exit_code == 0
    assert "about-blueshift" in result.output
    assert (repo / "doc0.md").read_text() == before
    assert not (repo / "templates").exists()


def test_apply_extracts_and_preserves_output(repo):
    before = {p: " ".join(render(p).split()) for p in sorted(repo.glob("doc*.md"))}
    result = CliRunner().invoke(main, ["refactor", str(repo), "--apply"])
    assert result.exit_code == 0, result.output
    assert (repo / "templates" / "about-blueshift.md").read_text().startswith("## About")
    for p, text in before.items():
        src = p.read_text()
        assert '{% include "about-blueshift.md" %}' in src
        assert "Founded in 2015" not in src
        assert " ".join(render(p).split()) == text


def test_nested_docs_put_template_at_common_ancestor(tmp_path):
    (tmp_path / ".git").mkdir()
    for client in ("a", "b"):
        d = tmp_path / "clients" / client
        d.mkdir(parents=True)
        (d / "p.md").write_text(f"# {client}\n\n{ABOUT}\n")
    [g] = find_shared_sections(tmp_path)
    assert g.target.parent == tmp_path / "clients" / "templates"
    CliRunner().invoke(main, ["refactor", str(tmp_path), "--apply"])
    assert "Founded in 2015" in render(tmp_path / "clients" / "a" / "p.md")


def test_ignores_existing_includes_and_short_text(tmp_path):
    (tmp_path / ".git").mkdir()
    for i in range(3):
        (tmp_path / f"d{i}.md").write_text('# T\n\n{% include "x.md" %}\n\nShort.\n')
    assert find_shared_sections(tmp_path) == []


def test_fenced_code_with_blank_lines_stays_one_block(tmp_path):
    (tmp_path / ".git").mkdir()
    code = "```bash\nmd-doc build a/\n\nmd-doc build b/\n```\n"
    for i in range(2):
        (tmp_path / f"d{i}.md").write_text(f"# T{i}\n\n{code}\n")
    [g] = find_shared_sections(tmp_path, min_chars=20)
    assert g.text == code


def test_matches_existing_template_even_in_one_document(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "about.md").write_text(ABOUT)
    (tmp_path / "only.md").write_text(f"# Only\n\n{ABOUT}\nTail.\n")
    (tmp_path / "other.md").write_text("# Other\n\nNothing shared here at all.\n")
    [g] = find_shared_sections(tmp_path)
    assert g.existing and g.include == "about.md" and g.target == tmp_path / "templates/about.md"
    before = " ".join(render(tmp_path / "only.md").split())
    result = CliRunner().invoke(main, ["refactor", str(tmp_path), "--apply"])
    assert result.exit_code == 0, result.output
    assert '{% include "about.md" %}' in (tmp_path / "only.md").read_text()
    assert (tmp_path / "templates/about.md").read_text() == ABOUT
    assert " ".join(render(tmp_path / "only.md").split()) == before


def test_existing_template_claims_text_before_new_duplicates(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "about.md").write_text(ABOUT)
    for i in range(3):
        (tmp_path / f"d{i}.md").write_text(f"# D{i}\n\n{ABOUT}\n")
    groups = find_shared_sections(tmp_path)
    assert [g.existing for g in groups] == [True]
    assert len(groups[0].occurrences) == 3


def test_template_not_reachable_from_unrelated_folder(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "a" / "templates").mkdir(parents=True)
    (tmp_path / "a" / "templates" / "about.md").write_text(ABOUT)
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "doc.md").write_text(f"# B\n\n{ABOUT}")
    assert find_shared_sections(tmp_path) == []
