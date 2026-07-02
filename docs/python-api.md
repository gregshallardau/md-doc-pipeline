# Using md-doc as a Python library

The CLI is a thin wrapper around a small set of functions you can call directly
when embedding the pipeline in another tool or service.

## Build a single document

```python
from pathlib import Path

from md_doc.config import load_config
from md_doc.renderer import render
from md_doc.builders.pdf import build as build_pdf
from md_doc.builders.docx import build as build_docx  # docx / dotx

doc = Path("workspace/acme/proposal.md")

config = load_config(doc)              # merged _meta.yml cascade + frontmatter
rendered_md = render(doc)             # Jinja2 (sandboxed) → Markdown string

build_pdf(rendered_md, config, Path("out/proposal.pdf"), doc_path=doc)
build_docx(rendered_md, config, Path("out/proposal.docx"), doc_path=doc)
# For a Word template, pass output_format="dotx":
build_docx(rendered_md, config, Path("out/proposal.dotx"), doc_path=doc,
           output_format="dotx")
```

`doc_path` lets the builders resolve the theme / asset / template cascade
relative to the document; pass `repo_root=` to pin the cascade root explicitly.

## Validate config

```python
from md_doc.config_schema import validate_config

for severity, message in validate_config({"cover_page": "yes"}):
    print(severity, message)          # error 'cover_page' must be true or false, got str
```

## Sync built outputs

```python
from pathlib import Path
from md_doc.sync import run as sync_run, SyncError

try:
    summary = sync_run(Path("workspace/acme/"), backend="local")
    print(summary["uploaded"], summary["failed"])
except SyncError as exc:
    ...  # at least one file failed after retries
```

## Render a Mermaid diagram to SVG

```python
from md_doc.mermaid import render_to_svg

svg = render_to_svg("flowchart LR\n  A --> B")
```

## Logging

The package logs under the `md_doc` namespace. Configure it as you would any
logger; the CLI's `--debug` / `--quiet` flags simply set this logger's level.

```python
import logging
logging.getLogger("md_doc").setLevel(logging.DEBUG)
```
