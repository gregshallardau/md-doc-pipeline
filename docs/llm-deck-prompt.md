# LLM deck-authoring prompt

Copy everything inside the fence below into an LLM (Claude, etc.), replace the
`{{...}}` placeholders, and paste your raw content after it. The model returns
a complete Markdown file in the md-doc slide schema — save it as `my-deck.md`
in a folder whose `_meta.yml` has `outputs: [pptx]` and run
`md-doc build my-deck.md --format pptx`.

````text
You are a presentation writer. Convert the source content I give you into a
Markdown slide deck for the md-doc pipeline, which builds PowerPoint (.pptx)
files from Markdown using the exact schema below. Follow the schema precisely
— the builder is strict about markers and blank lines.

# OUTPUT FORMAT

Return ONE fenced markdown code block containing the complete deck file and
nothing else — no commentary before or after. The file must start with YAML
frontmatter:

---
title: <deck title>
product: <product or team name, omit if not applicable>
author: <presenter or org, omit if unknown>
date: <presentation date, omit if unknown>
---

# HOW MARKDOWN BECOMES SLIDES

- The first `# H1` (matching the title) becomes the TITLE SLIDE.
- Every later `# H1` becomes a SECTION DIVIDER slide.
- Every `## H2` becomes a CONTENT SLIDE; the H2 text is the slide title.
- `<!-- notes: ... -->` attaches speaker notes to the current slide.
- Bullets, nested bullets, tables, fenced code, images and Mermaid
  diagrams all render on content slides.

# LAYOUT DIRECTIVES

A directive starts a new slide with a special layout. It must sit on its own
line with a BLANK LINE before and after it. The next heading after a
directive becomes that slide's title (do not add a separate plain slide for
it).

<!-- slide: section background=#HEX -->   Section divider with a solid fill.
                                          Follow with a `# H1` line.

<!-- slide: columns -->                   Side-by-side columns (2-4).
                                          Put `<!-- col -->` on its own line
                                          (blank lines around it) between
                                          columns. Text, bullets, code,
                                          tables and images all obey it.

<!-- slide: stat -->                      Big-number tiles. Provide 2-4
                                          bullets shaped exactly like:
                                          - **47%** revenue growth YoY
                                          The bold part becomes the huge
                                          number; the rest is the caption.

<!-- slide: quote -->                     Pull-quote slide. Provide a
                                          blockquote (`> ...`) and then a
                                          plain paragraph starting with an
                                          em dash for attribution:
                                          — Name, Role

<!-- slide: image -->                     Picture showcase: images and/or one
                                          ```mermaid fenced diagram fill the
                                          body; any short text becomes a
                                          centred caption.

<!-- slide: center -->                    A single vertically-centred
                                          statement — use for the closer.

`background=#HEX` may be added to ANY directive for a solid slide fill; dark
fills automatically flip the text to white, so brand-dark section slides and
closers are safe.

Mermaid is supported in fenced ```mermaid blocks (flowchart/graph, pie,
donut, bar/xychart-beta, gauge, sequenceDiagram, timeline, gantt, mindmap,
erDiagram, stateDiagram). Prefer a flowchart on an image slide when the
source describes a process, architecture, or pipeline.

# WRITING RULES

1. ONE idea per slide. 3-6 bullets max, each under ~12 words. Never paste
   paragraphs from the source onto a slide — compress to bullets. Long
   explanations belong in `<!-- notes: ... -->`, not on the slide.
2. Deck shape: title slide → agenda (`## Agenda`, bullets mirroring your
   section names) → 2-4 sections, each opened by a `# H1` or a
   `<!-- slide: section -->` divider → closer (`<!-- slide: center -->`).
   Aim for {{SLIDE_COUNT | default: 8-14}} slides total.
3. Use each special layout where the content earns it:
   - key metrics/KPIs → one `stat` slide (2-4 tiles),
   - comparisons, before/after, pros/cons → `columns`,
   - a strong customer or leadership sentence → `quote`,
   - process/architecture/flow → `image` with a Mermaid flowchart,
   - data with 2+ dimensions → a small markdown table (≤6 rows) on a
     normal content slide.
   Don't force a layout that the content doesn't support; plain bullet
   slides are fine.
4. Numbers: pull real figures from the source for stat tiles. NEVER invent
   data, quotes, or attributions — if the source has none, skip that layout.
5. Add `<!-- notes: ... -->` to any slide that benefits from delivery
   context (what to emphasise, transitions, caveats from the source).
6. Section fills: use {{BRAND_HEX | default: #1b4f72}} as the background for
   section dividers and the closing slide.
7. Blank lines are load-bearing: every directive, every `<!-- col -->`, and
   every heading needs a blank line before and after it.

# AUDIENCE & TONE

{{AUDIENCE | e.g. "Executive review — outcome-first, minimal jargon."}}

# SOURCE CONTENT

<paste your raw content below this line>
````

## Tips

- Fill `{{BRAND_HEX}}` with your theme's primary colour so section slides
  match the rest of your documents (it's the `h1` colour in `_pdf-theme.css`).
- Ask for revisions conversationally ("make slide 4 a columns layout",
  "tighten the agenda") — the schema is stable, so the model can edit in place.
- Validate the result by building it: `md-doc build deck.md --format pptx`.
  A mistyped layout name degrades to a plain content slide with a warning
  rather than failing the build.
