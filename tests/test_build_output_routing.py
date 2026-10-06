"""The build selection must not change an output's project-relative path."""

from click.testing import CliRunner
import pytest

from md_doc.cli import main


@pytest.mark.parametrize("marker", ["git", "meta"])
@pytest.mark.parametrize("destination", ["relative", "absolute", "cli"])
def test_single_file_and_workspace_share_destination(tmp_path, marker, destination):
    project = tmp_path / "project"
    nested = project / "clients" / "acme"
    nested.mkdir(parents=True)
    if marker == "git":
        (project / ".git").mkdir()
    out = project / "build" if destination == "relative" else tmp_path / "exports"
    config = "outputs: [docx]\n"
    args = []
    if destination == "cli":
        config += "output_dir: ignored\n"
        args = ["--output", str(out)]
    else:
        config += f"output_dir: {'build' if destination == 'relative' else out}\n"
    (project / "_meta.yml").write_text(config)
    source = nested / "proposal.md"
    source.write_text("# Proposal\nBody.\n")
    expected = out / "clients" / "acme" / "proposal.docx"
    for target in (project, source, nested):
        result = CliRunner().invoke(main, ["build", str(target), "--force", *args])
        assert result.exit_code == 0, result.output
        assert expected.exists(), result.output
        expected.unlink()
    assert not (nested / "build").exists()
    assert not (out / "proposal.docx").exists()
