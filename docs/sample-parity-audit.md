# PDF / Word sample audit

Generated every discovered sample in `examples/` and `docs/examples/`: 12 existing documents plus 5 feature showcases, each exported as native PDF and editable DOCX. Word exports were rendered with LibreOffice for comparison. All 34 primary exports and 17 Word renders succeeded. Companion DOTX form/merge templates are included where relevant.

**Full visual parity is not resolved.** Matching page dimensions or counts is only a prerequisite, not a passing parity test. 4 samples have different pagination. Other samples still differ in fonts, diagrams, spacing and form appearance. Open `index.html` after extracting this archive to compare every page; click an image for the full resolution raster.

## Measurements

| Source | PDF pages | Word pages | Pagination |
| --- | ---: | ---: | --- |
| `examples/blueshift/clients/stormfront-inc/liability-application.md` | 2 | 2 | Same count only |
| `examples/blueshift/clients/stormfront-inc/onboarding-intake-form.md` | 2 | 2 | Same count only |
| `examples/blueshift/clients/stormfront-inc/onboarding-proposal.md` | 3 | 3 | Same count only |
| `examples/blueshift/decks/quarterly-review.md` | 3 | 3 | Same count only |
| `examples/blueshift/products/nova/integration-guide.md` | 3 | 3 | Same count only |
| `examples/blueshift/products/nova/release-notes-v3.2.md` | 3 | 3 | Same count only |
| `examples/blueshift/products/pulse/on-call-handbook.md` | 3 | 4 | Mismatch |
| `examples/feature-showcase/branded-cover.md` | 3 | 3 | Same count only |
| `examples/feature-showcase/diagram-gallery.md` | 11 | 11 | Same count only |
| `examples/feature-showcase/form-controls.md` | 3 | 2 | Mismatch |
| `examples/feature-showcase/landscape.md` | 2 | 2 | Same count only |
| `examples/feature-showcase/text-tables-math.md` | 4 | 4 | Same count only |
| `examples/project-reports/docs/projects/2026/alpha-project-report.md` | 3 | 3 | Same count only |
| `docs/examples/example-dotx-template.md` | 2 | 2 | Same count only |
| `docs/examples/example-markdown-form.md` | 3 | 2 | Mismatch |
| `docs/examples/example-pdf-form.md` | 3 | 2 | Mismatch |
| `docs/examples/example-pdf-report.md` | 3 | 3 | Same count only |

## Fixes validated by this run

- Restore readable white text and divider on dark cover bars.
- Render configured Word cover backgrounds and align PDF cover logos correctly.
- Keep inline PDF math inline even when the theme makes ordinary images block elements.
- Rasterize wrapped gauge SVGs for Word; parse sequence arrows without corrupting participant names.
- Collapse soft HTML/source whitespace in Word; preserve explicit line breaks and preformatted code.
- Preserve full-width diagram sizing instead of interpreting SVG viewBox coordinates as raster pixel widths.
- Avoid redundant PDF blank pages after explicit page breaks and a stranded initial letterhead before the first heading.
- Restore report footer dates in PDF.
- Repeat Word table headings and keep them with the following row.

## Remaining parity gaps

- Word and PDF pagination differs for: on-call-handbook, form-controls, example-markdown-form, example-pdf-form.
- PDF fields are interactive AcroForms; ordinary DOCX represents Markdown controls as fill-in lines and does not preserve structured row/box appearance. Raw HTML inputs are not represented as equivalent Word fields. DOTX variants contain native fields but are not evidence of visual parity.
- Existing themes request Segoe UI, which is unavailable in this renderer. Different font fallback changes wrapping and spacing. The new showcases use DejaVu Sans explicitly; original samples retain their styles.
- White footers can land outside narrow dark bottom bands; font fallback still changes cover title wrapping.
- Lists, code blocks, footnotes, table padding and emoji rendering need broader physical layout assertions.

## Feature coverage

Showcases exercise text and heading styles, lists, definitions, abbreviations, links, footnotes, code, source-relative images, table widths and cell images/math, explicit and appendix page breaks, inline/display LaTeX, all 11 supported diagram families, all supported Markdown form-control families, form attributes, row/box layouts, mail merge and Word form fields, portrait/landscape pages, branded covers, background colors, logos, top/bottom bands, section bars, repeated headers and custom footers.

This covers rendering feature families, not every configuration permutation. The quarterly-review source normally produces PPTX; its PDF/Word exports are flow documents and do not validate slide-specific PPTX layout. Editor, sync and Neovim behavior are application features outside document visual parity.

## Validation

478 Python tests passed, 2 skipped. All 7 controlled rendered parity cases passed, including the new dark cover-bar case. Ruff, Black, mypy and whitespace checks passed.

## Reproduce

```sh
uv sync --group dev --group editor --group parity
uv run --group parity python tools/build_sample_gallery.py --output build/sample-gallery
uv run --group parity python tools/inspect_sample_gallery.py --output build/sample-gallery
MD_DOC_PARITY=1 uv run --group parity pytest tests/parity --no-cov
```

Install LibreOffice Writer and the fonts before rendering. The gallery audit records page dimensions/counts and Word structures; it deliberately does not label samples as passing parity. The seven controlled parity fixtures separately assert physical geometry with documented tolerances.
