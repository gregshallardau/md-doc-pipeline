"""Create a persistent remote-workspace fixture for the browser editor."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import yaml

FOLDERS = [
    "01 - Overview",
    "02 - Client Reports",
    "03 - Proposals",
    "04 - Contracts",
    "05 - Operations",
    "06 - Finance",
    "07 - People",
    "08 - Projects",
    "09 - Product",
    "10 - Research",
    "11 - Training",
    "12 - Policies",
    "13 - Meetings",
    "14 - Archive",
    "_Drafts",
]


def create_demo(destination: Path) -> dict:
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"Choose an empty directory; existing files are preserved: {destination}")
    project = destination / "project"
    remote = destination / "mnt/c/Users/username/OneDrive - Example/Company/Client Library/affinity"
    linked = remote.with_name("affinity-linked")
    (project / "workspace").mkdir(parents=True)
    (project / "pyproject.toml").write_text("# Remote editor demonstration project\n")
    theme = Path(__file__).resolve().parents[1] / "examples/feature-showcase/_theme.css"
    for workspace in (remote, linked):
        workspace.mkdir(parents=True)
        (workspace / "_meta.yml").write_text(
            "product: Affinity Demo\nauthor: Remote Workspace Test\nversion: 1.0\n"
            "date: 9 October 2026\ncover_page: true\noutputs: [pdf, docx]\n"
        )
        (workspace / "_theme.css").write_text(theme.read_text())
        (workspace / "_pdf-theme.css").write_text('@import "_theme.css";\nh2 { color: #16846d; }\n')
        (workspace / "_shared.html").write_text(
            '<p class="demo-note">Included from the remote document root.</p>\n'
        )
        (workspace / "_merge_fields.yml").write_text("contact_name: Client contact\n")
    for name in FOLDERS:
        folder = remote / name
        folder.mkdir()
        (folder / "_meta.yml").write_text(yaml.safe_dump({"department": name}))
    for number in range(1, 51):
        folder = remote / FOLDERS[(number - 1) % 15]
        if number > 15:
            folder = folder / "2026" / "Q4"
            folder.mkdir(parents=True, exist_ok=True)
        source = folder / f"document-{number:02}.md"
        source.write_text(
            f"---\ntitle: Affinity document {number:02}\n---\n"
            f"# Affinity document {number:02}\n\n"
            "## Remote workspace verification\n\n"
            "Department: {{ department }}. Product: {{ product }}.\n\n"
            '{% include "_shared.html" %}\n\n'
            "| Check | Result |\n| --- | --- |\n| Markdown | Visible |\n"
            "| Metadata | Inherited |\n| CSS | Imported theme |\n"
        )
    # One real empty folder and fourteen linked folders reproduce the reported shape.
    (linked / FOLDERS[0]).mkdir()
    for name in FOLDERS[1:]:
        (linked / ".folder-data" / name).mkdir(parents=True)
        (linked / name).symlink_to(linked / ".folder-data" / name, target_is_directory=True)
    for number in range(1, 51):
        folder = linked / ".folder-data" / FOLDERS[1 + (number - 1) % 14]
        (folder / "_meta.yml").write_text("department: Linked department\n")
        source = next(remote.rglob(f"document-{number:02}.md"))
        (folder / source.name).write_text(source.read_text())
    config = {"affinity-demo": {"path": str(remote)}, "affinity-linked-demo": {"path": str(linked)}}
    (project / "workspace/remote-workspaces.yml").write_text(
        yaml.safe_dump(config, sort_keys=False)
    )
    manifest = {
        "project": str(project),
        "remote": str(remote),
        "linkedRemote": str(linked),
        "folders": 15,
        "documents": 50,
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(tempfile.gettempdir()) / "md-doc-remote-demo"
    )
    args = parser.parse_args()
    print(json.dumps(create_demo(args.root.resolve()), indent=2))


if __name__ == "__main__":
    main()
