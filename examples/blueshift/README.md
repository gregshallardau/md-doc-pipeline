# Blueshift Labs — Example Project

A multi-layer example project for `md-doc-pipeline` demonstrating cascading
`_meta.yml` config, nested `templates/`, and nested `pdf-theme.css`.

## Structure

```
blueshift/
├── _meta.yml                            # Root: author, outputs, sync target
├── templates/
│   ├── company-header.md                # Company-wide letterhead (default)
│   └── legal-footer.md                  # Company-wide legal footer
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
│       ├── pdf-theme.css                # ← amber theme, overrides default blue
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

### Nested `pdf-theme.css`

Pulse documents automatically pick up `products/pulse/pdf-theme.css` (amber/orange
palette) without any `pdf_theme` config key. All other documents fall through to
the repo default at `themes/default/pdf-theme.css` (blue palette).

## Building

```bash
cd examples/blueshift
md-doc build . --output build/
```
