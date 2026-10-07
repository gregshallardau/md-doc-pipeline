# Rendered Word/PDF parity

These tests generate a PDF and an editable DOCX from the same Markdown and
configuration, render the DOCX through LibreOffice, rasterize both PDFs at
144 DPI, and measure physical geometry. They do not accept regenerated golden
images automatically.

Install LibreOffice Writer and DejaVu Sans, then run from the repository root:

```sh
uv venv
source .venv/bin/activate
uv sync --group dev --group parity
MD_DOC_PARITY=1 MD_DOC_PARITY_ARTIFACTS=parity-artifacts \
  uv run --group parity pytest tests/parity --no-cov
```

When enabled, missing dependencies or an office renderer fail the tests. Normal
unit-test runs skip this optional suite before importing its extra dependencies.
CI uses Ubuntu 24.04, the locked Python dependencies and DejaVu fixtures, and
uploads diagnostic artifacts even on failure.

The contract covers A4 portrait/landscape, exactly two pages after an explicit
page break, a full-width 10mm header at 0mm or 20mm from the page top, repeated
header text, body starts, table headers, and an embedded image. Cover checks
include short and wrapped titles, physical top/bottom bands, accent stripe,
metadata placement, custom themes without cover CSS, landscape dimensions,
first-page header suppression, and the body starting on page two.

Page dimensions tolerate 0.1mm; header geometry 0.25mm; body/header text 0.8mm;
tables/images 1mm; cover text 1.5mm. Header colored-area overlap must exceed 97%.
These explicit tolerances allow font rasterization differences without hiding
layout shifts. The measurements JSON, original exports, office version/log,
page PNGs, overlays and differences identify a failing element.

LibreOffice is the deterministic Word renderer for this suite. This verifies
these fixtures, not pixel identity across arbitrary themes, documents, fonts,
or every version of Microsoft Word. Extend fixtures and physical assertions when
adding layout behavior; review differences instead of relaxing tolerances to
make a regression pass.
