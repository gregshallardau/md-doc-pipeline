---
title: Text tables images and LaTeX
page_header_bar: true
page_header_bar_offset: 2cm
page_header_bar_height: 10mm
page_header_bar_padding: 6mm
header_text: Full width header 20 mm from page top
footer_left: Feature demonstration
footer_center: Fixed fixture date
footer_right: Page {page} of {pages}
---
# Text tables images and LaTeX

## Typography and navigation

This paragraph has **bold**, *italic*, <del>strike-through</del>, `inline code`, a [link](https://example.com), and a footnote.[^one]

> A quotation with **emphasis** demonstrates inset text and wrapping.

1. First numbered item
2. Second numbered item

<!-- Separate list types -->

- First bullet
    - Nested bullet
- Second bullet

Term
: Definition list description.

Abbreviation HTML is defined below.

*[HTML]: Hypertext Markup Language

[^one]: A real footnote reference and note text.

## Tables and images

<!-- col-widths: 30, 70 -->
| Item | Description |
|:---|:---|
| Short label | A deliberately long description that wraps across the available width. |
| Image in cell | ![Logo](logo.png) |
| Equation | $\sqrt{x^2 + y^2}$ |

| | |
|---|---|
| Headerless table | Adjacent table handling |

![A small source-relative image](logo.png)

<!-- pagebreak -->

## Equations

Inline mathematics $E = mc^2$ stays between words. Currency stays literal: $5 and $10.

$$
\frac{-b \pm \sqrt{b^2-4ac}}{2a}
$$

$$
\sum_{i=1}^{n} i = \frac{n(n+1)}{2}
$$

```python
# Code preserves literal math delimiters.
price = "$5"
equation = "$x^2$"
```

# APPENDIX

## Supporting material

The appendix starts on a new page in both formats.
