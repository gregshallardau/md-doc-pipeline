# Word and PDF parity

The PDF and Word builders lay text out with different engines (WeasyPrint and Word), so the two
formats are built to *agree on the things that decide how a document reads* rather than to be
identical line for line. This page says what is kept in step, how that is checked, and what is
known to differ.

## What is kept in step

- **Page geometry and breaks.** Paper size and margins come from the theme's `@page` rule;
  explicit `<!-- pagebreak -->`, APPENDIX sections and the theme's H1 page break are applied
  identically; headings stay with the content that follows.
- **Covers, header bars, section bars and footers**, including logos, cover bands, running date
  and live `Page N of M` fields. Form documents hide the running date in both formats.
- **Typography.** Fonts resolve through the same matcher; heading, table, list, code, quote and
  `hr` spacing follow the theme (CSS margin collapsing is emulated in Word).
- **Tables.** Column widths come from the PDF's own layout (or `col-widths`), zebra rows follow
  CSS counting, header rows repeat, adjacent tables stay separate.
- **Forms.** `?[box]` and `?[row]` grids take their row heights from the PDF layout of the same
  markup; input boxes, choice lines, signatures and captions scale with the theme's font sizes
  and use the same theme-tinted colours.
- **Math and diagrams.** Equations are native Office Math in Word; diagrams are embedded images.

See the [theming guide](theming-guide.md) for what Word reads from a theme and the
[Markdown reference](markdown-reference.md) for per-feature differences.

## How it is checked

- `tests/test_docx_parity.py` and the form tests assert structure (breaks, fields, spacing).
- `tests/parity/` renders controlled fixtures with LibreOffice and asserts physical geometry
  (page size, bands, footers, fonts) against the PDF within stated tolerances. It runs in CI as
  *Rendered Word/PDF parity*.
- `tools/build_sample_gallery.py` and `tools/inspect_sample_gallery.py` build every sample in
  `examples/` as PDF and DOCX and record page counts and vertical drift for review.

```sh
uv sync --group dev --group parity
MD_DOC_PARITY=1 uv run --group parity pytest tests/parity --no-cov
uv run --group parity python tools/build_sample_gallery.py --output build/sample-gallery
uv run --group parity python tools/inspect_sample_gallery.py --output build/sample-gallery
```

Install LibreOffice Writer (and its Math component for equations) and the fonts first. A gallery
run does not label samples pass or fail; it is a review aid.

## Known differences

- **Submit buttons** have no Word equivalent and are omitted, so content after one sits one
  button-height higher in Word.
- **Checkboxes and radios** are drawn as `☐` / `○` glyphs in plain `.docx`; Yes/No text in grid
  cells sits at the bottom of its cell rather than centred. Use `.dotx` for fillable Word fields.
- **Page-boundary cases.** Where WeasyPrint moves a label and its box to the next page together,
  Word can fit them by a few points.
- **Header text** is offset about 5pt when a header bar has logos, and a right-aligned cover
  logo differs by about 9pt horizontally.
- **Tables** that overflow the right margin in the PDF (for example with oversized
  `col-widths`) are clamped to the text width in Word.
- **`.section-note` and other class-based styles** in a theme are not translated to Word.
- **Renderer artifacts.** LibreOffice keeps heading space-before at automatic page breaks (Word
  and the PDF drop it); this shows up only when checking with LibreOffice.
- **Fonts and emoji.** Unsupported emoji glyphs, and fonts that are not installed on the viewing
  machine, fall back differently per application.
