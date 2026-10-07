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
- Resolve Word CSS font stacks with the PDF font matcher.
- Restart each numbered list and preserve explicit HTML start values.
- Preserve form grids, choice labels, field values and raw HTML controls in Word.
- Put white cover footers inside dark bottom bands.
- Match table/list leading to their actual font sizes without clipping embedded objects.
- Recognize both submit syntaxes as PDF buttons and omit them from Word rather than creating bogus text fields.
- Repeat Word table headings and keep them with the following row.

## Remaining parity gaps

- Word and PDF pagination differs for: on-call-handbook, form-controls, example-markdown-form, example-pdf-form.
- PDF fields are interactive AcroForms. DOCX now retains choice labels, checked states, values and row/box tables; raw HTML controls also have visible Word representations. DOTX keeps native fields inside these grids. Field heights, multiline textarea layout, form validation attributes and radio/dropdown appearance still differ.
- Word now resolves CSS font lists through the same Pango matcher as PDF, so the original Segoe UI themes render with the same installed fallback family. On Word-only hosts without Pango, the primary requested font is retained. Unsupported emoji glyphs and font availability on other viewing hosts remain limitations.
- Explicitly white cover footers now sit inside sufficiently tall bottom bands. Bands shorter than the footer height cannot accommodate the footer; long footer text can still wrap differently.
- Lists, code blocks, footnotes, table padding and emoji rendering need broader physical layout assertions.

## Feature coverage

Showcases exercise text and heading styles, lists, definitions, abbreviations, links, footnotes, code, source-relative images, table widths and cell images/math, explicit and appendix page breaks, inline/display LaTeX, all 11 supported diagram families, all supported Markdown form-control families, form attributes, row/box layouts, mail merge and Word form fields, portrait/landscape pages, branded covers, background colors, logos, top/bottom bands, section bars, repeated headers and custom footers.

This covers rendering feature families, not every configuration permutation. The quarterly-review source normally produces PPTX; its PDF/Word exports are flow documents and do not validate slide-specific PPTX layout. Editor, sync and Neovim behavior are application features outside document visual parity.

## Validation

491 Python tests passed, 2 skipped. All 8 controlled rendered parity cases passed, including font fallback and physical white-footer placement on the dark cover bar. Ruff, Black, mypy and whitespace checks passed.

## Reproduce

```sh
uv sync --group dev --group editor --group parity
uv run --group parity python tools/build_sample_gallery.py --output build/sample-gallery
uv run --group parity python tools/inspect_sample_gallery.py --output build/sample-gallery
MD_DOC_PARITY=1 uv run --group parity pytest tests/parity --no-cov
```

Install LibreOffice Writer and the fonts before rendering. The gallery audit records page dimensions/counts and Word structures; it deliberately does not label samples as passing parity. The eight controlled parity fixtures separately assert physical geometry with documented tolerances.
