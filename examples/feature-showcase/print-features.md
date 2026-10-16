---
title: Print-grade PDF features
description: A tour of the bookmarks, numbering, footnotes, columns, running titles and PDF standards available through config keys.
keywords: [pdf, print, accessibility]
lang: en-GB
outputs: [pdf]
cover_page: true
cover_label: Feature tour
header_text: "{title} — {chapter}"
footer_left: "{section}"
footer_right: "Page {page} of {pages}"
pdf_variant: pdf/a-3b
pdf_attach_source: true
pdf_layout_check: true
numbered_headings: true
page_footnotes: true
xref_pages: true
hyphenate: true
tabular_numbers: true
duplex: true
binding_margin: 8mm
chapter_break: recto
---
# Print-grade PDF features

[TOC]

# Navigation

The PDF carries a bookmark for every heading, so a reader can jump around from the viewer's
outline pane. Links can name a heading without repeating its text: see [](#columns-and-cards).
Notes appear at the foot of the page that cites them.[^foot]

## Numbered headings

Headings are numbered automatically, and the contents list above shows the same numbers.

| Quarter | Revenue | Margin |
|---------|--------:|-------:|
| Q1 | 1,204,500 | 18.2% |
| Q2 | 987,300 | 17.9% |
| Q3 | 1,310,050 | 19.4% |

Tabular figures keep the digits above lined up in every column.

# Columns and cards

<!-- columns: 2, gap=8mm, rule=0.5pt solid #ccc -->
Text can flow across columns for newsletters, cheat sheets and datasheets. Automatic
hyphenation keeps the right edge of the narrow columns tidy, which matters when the measure is
short. Internationalisation and interoperability are long words that need it.

A second paragraph continues in the same flow and moves to the next column as the first fills.
<!-- /columns -->

<!-- grid: 3, gap=6mm -->
**Starter** — everything for a single author.

**Team** — shared themes and templates.

**Enterprise** — PDF/A archives and sync.
<!-- /grid -->

# Standards

This file is a PDF/A-3b archive with its Markdown source attached, a language tag for screen
readers and hyphenation, facing-page margins with a binding gutter, and a layout check that
warns when a heading is stranded at the foot of a page.

[^foot]: Footnotes use the ordinary Markdown syntax; `page_footnotes: true` moves them to the page bottom.
