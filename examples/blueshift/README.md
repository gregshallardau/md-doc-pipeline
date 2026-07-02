# Blueshift Labs — Example Project

A multi-layer example project for `md-doc-pipeline` demonstrating cascading
`_meta.yml` config, nested `templates/`, and nested `_pdf-theme.css`.

## Structure

```
blueshift/
├── _meta.yml                            # Root: author, outputs, sync target
├── templates/
│   ├── company-header.md                # Company-wide letterhead (default)
│   └── legal-footer.md                  # Company-wide legal footer
│
├── decks/                              # PPTX slide decks (deck-first schema)
│   ├── _meta.yml                        # outputs: [pptx], slide_size: 16:9
│   └── quarterly-review.md              # every slide layout in one deck
│
├── products/
│   ├── _meta.yml                        # Products division: document_type, status
│   ├── templates/
│   │   └── product-disclaimer.md        # Shared product docs disclaimer
│   │
│   ├── nova/                            # Nova Analytics product line
│   │   ├── _meta.yml                    # product, version, support_email
│   │   ├── templates/
│   │   │   └── company-header.md        # ← overrides root company-header.md
│   │   ├── release-notes-v3.2.md
│   │   └── integration-guide.md
│   │
│   └── pulse/                           # Pulse Monitor product line
│       ├── _meta.yml                    # product, version, alert_email
│       ├── _pdf-theme.css                # ← amber theme, overrides default blue
│       └── on-call-handbook.md
│
└── clients/
    ├── _meta.yml                        # Clients division: document_type
    └── stormfront-inc/
        ├── _meta.yml                    # client, account_manager, status
        ├── templates/
        │   └── company-header.md        # ← client-branded header
        └── onboarding-proposal.md
```

## What this demonstrates

### Nested `_meta.yml` (3 levels deep)

Every document inherits from all ancestor `_meta.yml` files. A Nova Analytics
document resolves config in this order:

```
root/_meta.yml → products/_meta.yml → products/nova/_meta.yml → frontmatter
```

So `author` comes from root, `document_type` from products, and `product` +
`version` from nova — all merged automatically.

### Nested templates (deepest overrides shallowest)

`{% include "company-header.md" %}` resolves the *closest* match:

- Nova docs → `products/nova/templates/company-header.md` (product-branded)
- Stormfront docs → `clients/stormfront-inc/templates/company-header.md` (client-branded)
- Pulse docs → falls through to `templates/company-header.md` (root default)

`{% include "product-disclaimer.md" %}` resolves to `products/templates/` because
no deeper override exists.

### Nested `_pdf-theme.css`

Pulse documents automatically pick up `products/pulse/_pdf-theme.css` (amber/orange
palette) without any `pdf_theme` config key. All other documents fall through to
the repo-root default (blue palette), auto-generated on first build.

### Deck-first PPTX authoring (`decks/`)

`decks/quarterly-review.md` is a PowerPoint deck written with the slide schema
(full guide: [`docs/slides-guide.md`](../../docs/slides-guide.md)). `decks/_meta.yml`
sets `outputs: [pptx]`, so the folder builds to slides. The deck exercises every
layout in one file:

- a **title slide** from frontmatter (`title` / `product` / `date`);
- branded **section dividers** (`<!-- slide: section background=#1b4f72 -->`);
- a **stat** slide of big-number tiles;
- a two-column **columns** slide split by `<!-- col -->`;
- an **image** slide filled by a Mermaid pipeline diagram;
- a data **table** on a normal content slide;
- a **quote** slide with attribution;
- a centred **closer** (`<!-- slide: center -->`).

It also inherits the navy `_theme.css` palette (heading colours + fonts), so the
slides match the PDFs and Word docs. To generate a deck from raw content with an
LLM, see [`docs/llm-deck-prompt.md`](../../docs/llm-deck-prompt.md).

## Building

```bash
cd examples/blueshift
md-doc build . --output build/          # all formats (PDFs, Word, and the deck)
md-doc build decks/ --format pptx       # just the slide deck
```
