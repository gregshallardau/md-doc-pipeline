/**
 * Monaco Monarch tokenizer definitions for md-doc-pipeline.
 *
 * Registers two custom languages and a colour theme:
 *   mddoc-markdown  — .md files: YAML frontmatter, Jinja2, [[fields]], ?[forms], Markdown
 *   mddoc-yaml      — _meta.yml: YAML with Jinja2 and md-doc config-key highlighting
 *   mddoc-light     — custom Monaco theme
 *
 * Usage (inside the Monaco require() callback):
 *   registerMdDocLanguages(monaco);
 */

(function (global) {
    'use strict';

    // ── Known md-doc configuration keys ───────────────────────────────────────
    // Used to colour config keys distinctly in frontmatter and _meta.yml files.

    const MD_DOC_CONFIG_KEYS = [
        // Core metadata
        'title', 'product', 'version', 'codename', 'author', 'date',
        'status', 'document_type',
        // Output control
        'outputs', 'output_filename', 'output_dir',
        'pdf_forms', 'dotx_field_type', 'body_text_align', 'include_md_in_share',
        // Cover page
        'cover_page', 'cover_label', 'cover_text_align', 'cover_background',
        'cover_logo', 'cover_bar_logo', 'cover_divider',
        'cover_bar', 'cover_bar_position', 'cover_bar_height',
        'cover_bar_top_height', 'cover_bar_bottom_height', 'cover_text_on_bar',
        'cover_stripe', 'cover_stripe_height', 'cover_stripe_width',
        'cover_footer', 'cover_footer_text', 'cover_footer_line',
        'cover_footer_color', 'cover_meta_label', 'cover_meta_author',
        // Page header bar
        'page_header_bar', 'page_header_bar_color', 'page_header_bar_text_color',
        'page_header_bar_height', 'page_header_bar_padding',
        'page_header_bar_logo', 'page_header_bar_logo_position', 'page_header_bar_logos',
        // Page headers / footers
        'header_logo', 'header_logo_position', 'header_text', 'header_text_position',
        'footer_left', 'footer_center', 'footer_right',
        // Section bars
        'section_bar', 'section_bar_color', 'section_bar_text_on_bar',
        'section_bar_text_color', 'section_bar_headings',
        // Theming
        'pdf_theme',
        // Sync
        'sync_target', 'sync_config',
        // Export / vault
        'export', 'export_format', 'export_path', 'export_filename', 'draft', 'tags',
        // Client / engagement fields (common user-defined cascade keys)
        'client', 'client_abn', 'client_contact', 'account_manager',
        'support_email', 'alert_email',
    ];

    // ── Shared Jinja2 state rules (embedded in both language definitions) ──────
    // These states handle {{ expr }}, {% tag %}, {# comment #}

    const JINJA_EXPR = [
        [/\}\}/, { token: 'delimiter.jinja', next: '@pop' }],
        // Filters (pipe operator)
        [/\|/, 'operator.jinja'],
        // Strings inside expressions
        [/"[^"]*"/, 'string.jinja'],
        [/'[^']*'/, 'string.jinja'],
        // Literals
        [/\b(true|false|none|True|False|None)\b/, 'constant.jinja'],
        [/[\d.]+/, 'number.jinja'],
        // Variable / attribute access (includes dotted paths like var.attr)
        [/[\w_][\w_.]*/, 'variable.jinja'],
        [/[().,\[\]]/, 'punctuation.jinja'],
        [/\s+/, ''],
    ];

    const JINJA_TAG = [
        [/-?%\}/, { token: 'delimiter.jinja', next: '@pop' }],
        // Block keywords
        [/\b(if|elif|else|endif|for|endfor|block|endblock|extends|include|macro|endmacro|call|endcall|filter|endfilter|set|do|with|endwith|not|and|or|in|is)\b/, 'keyword.jinja'],
        // Literals
        [/\b(true|false|none|True|False|None)\b/, 'constant.jinja'],
        [/"[^"]*"/, 'string.jinja'],
        [/'[^']*'/, 'string.jinja'],
        [/[\w_][\w_.]*/, 'variable.jinja'],
        [/[().,\[\]]/, 'punctuation.jinja'],
        [/\s+/, ''],
    ];

    const JINJA_COMMENT = [
        [/#\}/, { token: 'comment.jinja', next: '@pop' }],
        [/.+/, 'comment.jinja'],
    ];

    // ── mddoc-markdown Monarch definition ─────────────────────────────────────

    const MDDOC_MARKDOWN_DEF = {
        defaultToken: '',

        // Arrays referenced in `cases` clauses below via @mdDocConfigKeys
        mdDocConfigKeys: MD_DOC_CONFIG_KEYS,

        tokenizer: {

            // ── root: main markdown body ───────────────────────────────────────
            root: [

                // YAML frontmatter — must be the very first line (^---$)
                // We rely on Monarch starting in root state on line 1.
                [/^---\s*$/, { token: 'meta.separator', next: '@frontmatter' }],

                // ── Jinja2 ─────────────────────────────────────────────────────
                [/\{\{/, { token: 'delimiter.jinja', next: '@jinja_expr' }],
                [/\{%-?/, { token: 'delimiter.jinja', next: '@jinja_tag' }],
                [/\{#/, { token: 'comment.jinja', next: '@jinja_comment' }],

                // ── md-doc custom syntax ───────────────────────────────────────
                // Word / merge fields  [[field_name]]
                [/\[\[[\w_]+\]\]/, 'type.mddoc.field'],
                // PDF form fields  ?[type: name, ...]
                [/\?\[/, { token: 'delimiter.form', next: '@form_field' }],

                // ── Headings  # through ###### ─────────────────────────────────
                [/^(#{1,6})(\s+)(.+)$/, ['markup.heading.marker', '', 'markup.heading']],

                // ── Fenced code blocks ─────────────────────────────────────────
                // Mermaid (more specific — must precede the generic rule)
                [/^```mermaid\s*$/, { token: 'markup.fenced_code.lang', next: '@mermaid_block' }],
                // Generic code fence
                [/^```[\w-]*\s*$/, { token: 'markup.fenced_code.lang', next: '@code_block' }],

                // ── Block-level elements ───────────────────────────────────────
                // Horizontal rule (after frontmatter, --- is a HR here)
                [/^(---|\*\*\*|___)\s*$/, 'markup.hr'],
                // Blockquote
                [/^(>+)(\s)/, ['markup.quote.marker', '']],
                // Task list items    - [ ] or - [x]
                [/^(\s*)([-*+])(\s+)(\[[ xX]\])(\s)/, ['', 'markup.list.bullet', '', 'markup.list.checkbox', '']],
                // Unordered list
                [/^(\s*)([-*+])(\s)/, ['', 'markup.list.bullet', '']],
                // Ordered list
                [/^(\s*)(\d+\.)(\s)/, ['', 'markup.list.bullet', '']],
                // Table separator row  |---|:---:|---:|
                [/^\|[\s\-:|]+\|$/, 'markup.table.separator'],

                // ── Inline spans ───────────────────────────────────────────────
                // Images (before links — both start with [)
                [/!\[[^\]]*\]\([^)]*\)/, 'markup.underline.link'],
                [/!\[[^\]]*\](\[[^\]]*\])?/, 'markup.underline.link'],
                // Inline links and reference links
                [/\[[^\]]+\]\([^)]*\)/, 'markup.underline.link'],
                [/\[[^\]]+\]\[[^\]]*\]/, 'markup.underline.link'],
                // Auto-links  <url>
                [/<https?:\/\/[^\s>]+>/, 'markup.underline.link'],

                // Bold + italic  ***...***  ___...___
                [/\*\*\*[^*]+\*\*\*/, 'markup.bold.italic'],
                [/___[^_]+___/, 'markup.bold.italic'],
                // Bold  **...**  __...__
                [/\*\*[^*\n]+\*\*/, 'markup.bold'],
                [/__[^_\n]+__/, 'markup.bold'],
                // Italic  *...*  _..._  (must come after bold)
                [/\*[^*\s][^*\n]*\*/, 'markup.italic'],
                [/_[^_\s][^_\n]*_/, 'markup.italic'],
                // Strikethrough  ~~...~~
                [/~~[^~\n]+~~/, 'markup.strikethrough'],
                // Double-backtick inline code
                [/``[^`]+``/, 'markup.inline.code'],
                // Single-backtick inline code
                [/`[^`\n]+`/, 'markup.inline.code'],

                // ── HTML tags (common in md-doc forms) ─────────────────────────
                [/<\/?(input|select|textarea|option|form|label|button|div|span|table|thead|tbody|tr|td|th|p|br|strong|em|a|img|ul|ol|li|h[1-6])\b[^>]*>/i, 'tag.html'],
                // Self-closing tags
                [/<[a-z][\w.-]*\s*\/>/i, 'tag.html'],

                // ── Table pipe (remaining pipes in table rows) ─────────────────
                [/\|/, 'markup.table.pipe'],
            ],

            // ── frontmatter: YAML between opening and closing --- ──────────────
            frontmatter: [
                // Closing delimiter
                [/^---\s*$/, { token: 'meta.separator', next: '@root' }],

                // Jinja2 (allowed in YAML values)
                [/\{\{/, { token: 'delimiter.jinja', next: '@jinja_expr' }],
                [/\{%-?/, { token: 'delimiter.jinja', next: '@jinja_tag' }],

                // YAML comment
                [/#.*$/, 'comment.yaml'],

                // Indented nested key  (e.g. sync_config sub-keys)
                [/^([ \t]+)([\w_-]+)(\s*:)/, ['', 'attribute.name.yaml', 'punctuation.yaml']],

                // Top-level key — highlight known md-doc keys in violet
                [/^([\w_-]+)(\s*:)/, [
                    {
                        cases: {
                            '@mdDocConfigKeys': 'keyword.mddoc',
                            '@default': 'attribute.name.yaml',
                        }
                    },
                    'punctuation.yaml',
                ]],

                // Block-sequence item marker  -
                [/^(\s*)(-)(\s)/, ['', 'punctuation.yaml', '']],

                // Flow-sequence  [ ... ]
                [/\[/, 'punctuation.yaml'],
                [/\]/, 'punctuation.yaml'],
                [/,/, 'punctuation.yaml'],

                // YAML booleans
                [/\b(true|false|yes|no|on|off|True|False)\b/, 'constant.yaml'],

                // Numbers — with optional CSS dimension units
                [/\d+(\.\d+)?(mm|cm|px|pt|em|rem|%)?(?=[\s,\]#\n])/, 'number.yaml'],

                // Hex colour strings  "#2563eb"  '#2563eb'
                [/"#[0-9a-fA-F]{3,8}"/, 'string.color.yaml'],
                [/'#[0-9a-fA-F]{3,8}'/, 'string.color.yaml'],

                // Quoted strings
                [/"[^"]*"/, 'string.yaml'],
                [/'[^']*'/, 'string.yaml'],

                // Known enum-like values
                [/\b(pdf|docx|dotx|azure|s3|local|form|merge|justify|left|right|center|top|bottom|both|draft|final|current)\b/, 'type.yaml'],
            ],

            // ── Jinja2 states (shared) ─────────────────────────────────────────
            jinja_expr:     JINJA_EXPR,
            jinja_tag:      JINJA_TAG,
            jinja_comment:  JINJA_COMMENT,

            // ── Fenced code block (generic) ────────────────────────────────────
            code_block: [
                [/^```\s*$/, { token: 'markup.fenced_code.lang', next: '@root' }],
                [/.+/, 'markup.fenced_code'],
                [/$/, ''],
            ],

            // ── Mermaid diagram block ──────────────────────────────────────────
            mermaid_block: [
                [/^```\s*$/, { token: 'markup.fenced_code.lang', next: '@root' }],

                // Diagram type declaration (first line of the block)
                [/\b(flowchart|graph|sequenceDiagram|pie|donut|gantt|classDiagram|stateDiagram|stateDiagram-v2|erDiagram|timeline|mindmap|xychart-beta|bar|gauge)\b/, 'keyword.mermaid.type'],

                // Common Mermaid keywords
                [/\b(TD|LR|TB|BT|RL|participant|actor|note|loop|alt|opt|par|critical|break|rect|end|title|section|state|direction|as|over|right|left|of)\b/, 'keyword.mermaid'],

                // Relationship / edge arrows
                [/-->|-->>|-.->|-\.->>|==>|===|---|\|>|o--|x--|<-->|--\|/, 'operator.mermaid'],

                // Node / entity labels in various bracket types
                [/\[[^\]]*\]/, 'string.mermaid.label'],
                [/\([^)]*\)/, 'string.mermaid.label'],
                [/\{[^}]*\}/, 'string.mermaid.label'],
                [/>"[^"]*"/, 'string.mermaid.label'],
                [/"[^"]*"/, 'string.mermaid.label'],

                // Percentages and numbers
                [/\d+(\.\d+)?%/, 'number.mermaid'],
                [/\d+(\.\d+)?/, 'number.mermaid'],

                [/.+/, 'markup.fenced_code.mermaid'],
                [/$/, ''],
            ],

            // ── PDF form field  ?[ type: name, params | option | ... ] ─────────
            form_field: [
                [/\]/, { token: 'delimiter.form', next: '@pop' }],
                // Field type  text | select | radio-inline | etc.
                [/\b(text|date|email|number|tel|url|select|radio|radio-inline|checkbox|checkbox-inline|signature|submit|row|\/row)\b/, 'keyword.form.type'],
                // Modifier keywords
                [/\b(required|readonly|maxlength|rows|placeholder|checked)\b/, 'keyword.form.param'],
                // = value  (e.g. maxlength=100)
                [/=\w+/, 'number.form'],
                // Pipe separating options in select/radio/checkbox
                [/\|/, 'operator.form'],
                [/,/, 'punctuation.form'],
                [/[\w_ -]+/, 'variable.form'],
                [/"[^"]*"/, 'string.form'],
                [/'[^']*'/, 'string.form'],
            ],
        },
    };

    // ── mddoc-yaml Monarch definition (_meta.yml) ─────────────────────────────

    const MDDOC_YAML_DEF = {
        defaultToken: '',

        // Arrays referenced in `cases` clauses via @mdDocConfigKeys
        mdDocConfigKeys: MD_DOC_CONFIG_KEYS,

        tokenizer: {

            root: [
                // YAML comments
                [/#.*$/, 'comment.yaml'],

                // Jinja2 inside values
                [/\{\{/, { token: 'delimiter.jinja', next: '@jinja_expr' }],
                [/\{%-?/, { token: 'delimiter.jinja', next: '@jinja_tag' }],

                // Indented nested key (sync_config sub-keys, page_header_bar_logos items, etc.)
                [/^([ \t]+)([\w_-]+)(\s*:)/, ['', 'attribute.name.yaml', 'punctuation.yaml']],

                // Top-level key — known md-doc config keys highlighted in violet
                [/^([\w_-]+)(\s*:)/, [
                    {
                        cases: {
                            '@mdDocConfigKeys': 'keyword.mddoc',
                            '@default': 'attribute.name.yaml',
                        }
                    },
                    'punctuation.yaml',
                ]],

                // Block-sequence item marker
                [/^(\s*)(-)(\s)/, ['', 'punctuation.yaml', '']],

                // Flow-sequence  [ ... ]
                [/\[/, 'punctuation.yaml'],
                [/\]/, 'punctuation.yaml'],
                [/,/, 'punctuation.yaml'],

                // YAML booleans
                [/\b(true|false|yes|no|on|off|True|False)\b/, 'constant.yaml'],

                // Numbers with optional CSS dimension units
                [/\d+(\.\d+)?(mm|cm|px|pt|em|rem|%)?(?=[\s,\]#\n])/, 'number.yaml'],

                // Hex colour strings  "#2563eb"
                [/"#[0-9a-fA-F]{3,8}"/, 'string.color.yaml'],
                [/'#[0-9a-fA-F]{3,8}'/, 'string.color.yaml'],

                // Quoted strings
                [/"[^"]*"/, 'string.yaml'],
                [/'[^']*'/, 'string.yaml'],

                // Known enum values (output formats, sync targets, alignment keywords)
                [/\b(pdf|docx|dotx|azure|s3|local|form|merge|justify|left|right|center|top|bottom|both|draft|final|current)\b/, 'type.yaml'],

                // Bare colon (standalone — after the key matching above)
                [/:/, 'punctuation.yaml'],
            ],

            jinja_expr:    JINJA_EXPR,
            jinja_tag:     JINJA_TAG,
        },
    };

    // ── Theme: mddoc-light ────────────────────────────────────────────────────
    // Extends Monaco's built-in 'vs' (light) theme with custom token colours.

    const MDDOC_LIGHT_THEME = {
        base: 'vs',
        inherit: true,
        rules: [
            // ── Frontmatter / YAML ──────────────────────────────────────────────
            { token: 'meta.separator',       foreground: '94a3b8' },            // slate-400 ---
            { token: 'attribute.name.yaml',  foreground: '0f766e' },            // teal-700   generic key
            { token: 'keyword.mddoc',        foreground: '7c3aed', fontStyle: 'bold' }, // violet-600 known key
            { token: 'punctuation.yaml',     foreground: '94a3b8' },            // slate-400  :
            { token: 'comment.yaml',         foreground: '94a3b8', fontStyle: 'italic' },
            { token: 'constant.yaml',        foreground: '16a34a', fontStyle: 'bold' }, // green-600 true/false
            { token: 'number.yaml',          foreground: '0284c7' },            // sky-600
            { token: 'string.yaml',          foreground: 'd97706' },            // amber-600
            { token: 'string.color.yaml',    foreground: 'e11d48', fontStyle: 'bold' }, // rose-600  #hex
            { token: 'type.yaml',            foreground: '2563eb' },            // blue-600   enum values

            // ── Jinja2 ──────────────────────────────────────────────────────────
            { token: 'delimiter.jinja',      foreground: 'd97706', fontStyle: 'bold' }, // amber-600 {{ }}
            { token: 'keyword.jinja',        foreground: 'dc2626', fontStyle: 'bold' }, // red-600   if/for/include
            { token: 'variable.jinja',       foreground: '7c3aed' },            // violet-600
            { token: 'string.jinja',         foreground: '16a34a' },            // green-600
            { token: 'constant.jinja',       foreground: '0284c7' },            // sky-600    true/none
            { token: 'number.jinja',         foreground: '0284c7' },
            { token: 'operator.jinja',       foreground: 'd97706' },            // amber | filter pipe
            { token: 'comment.jinja',        foreground: '94a3b8', fontStyle: 'italic' },

            // ── [[Word fields]] ──────────────────────────────────────────────────
            { token: 'type.mddoc.field',     foreground: '7c3aed', fontStyle: 'bold' }, // violet-600

            // ── ?[PDF form fields] ───────────────────────────────────────────────
            { token: 'delimiter.form',       foreground: '0d9488', fontStyle: 'bold' }, // teal-600
            { token: 'keyword.form.type',    foreground: '0f766e', fontStyle: 'bold' }, // teal-700
            { token: 'keyword.form.param',   foreground: '0d9488' },
            { token: 'variable.form',        foreground: '374151' },
            { token: 'operator.form',        foreground: '94a3b8' },
            { token: 'number.form',          foreground: '0284c7' },
            { token: 'string.form',          foreground: 'd97706' },

            // ── Headings ─────────────────────────────────────────────────────────
            { token: 'markup.heading',       foreground: '1e3a8a', fontStyle: 'bold' }, // blue-900
            { token: 'markup.heading.marker',foreground: '93c5fd' },            // blue-300  # symbols

            // ── Inline spans ──────────────────────────────────────────────────────
            { token: 'markup.bold',          foreground: '111827', fontStyle: 'bold' },
            { token: 'markup.italic',        foreground: '374151', fontStyle: 'italic' },
            { token: 'markup.bold.italic',   foreground: '111827', fontStyle: 'bold italic' },
            { token: 'markup.strikethrough', foreground: '9ca3af' },
            { token: 'markup.inline.code',   foreground: '0f766e' },            // teal-700
            { token: 'markup.underline.link',foreground: '2563eb', fontStyle: 'underline' }, // blue-600
            { token: 'markup.hr',            foreground: 'd1d5db' },            // gray-300

            // ── Lists ─────────────────────────────────────────────────────────────
            { token: 'markup.list.bullet',   foreground: '2563eb', fontStyle: 'bold' }, // blue-600
            { token: 'markup.list.checkbox', foreground: '7c3aed' },            // violet-600

            // ── Blockquotes ───────────────────────────────────────────────────────
            { token: 'markup.quote.marker',  foreground: '64748b', fontStyle: 'italic' }, // slate-500

            // ── Tables ───────────────────────────────────────────────────────────
            { token: 'markup.table.separator', foreground: '94a3b8' },
            { token: 'markup.table.pipe',    foreground: 'cbd5e1' },            // slate-300

            // ── Fenced code ───────────────────────────────────────────────────────
            { token: 'markup.fenced_code.lang', foreground: '6b7280', fontStyle: 'italic' }, // gray-500
            { token: 'markup.fenced_code',    foreground: '374151' },           // gray-700
            { token: 'markup.fenced_code.mermaid', foreground: '374151' },

            // ── Mermaid ───────────────────────────────────────────────────────────
            { token: 'keyword.mermaid.type', foreground: 'dc2626', fontStyle: 'bold' }, // red-600  diagram type
            { token: 'keyword.mermaid',      foreground: '7c3aed' },            // violet-600 keywords
            { token: 'operator.mermaid',     foreground: 'd97706', fontStyle: 'bold' }, // amber-600 -->
            { token: 'string.mermaid.label', foreground: '16a34a' },            // green-600  [labels]
            { token: 'number.mermaid',       foreground: '0284c7' },

            // ── HTML tags ─────────────────────────────────────────────────────────
            { token: 'tag.html',             foreground: '0f766e' },            // teal-700
        ],
        colors: {},
    };

    // ── Registration ──────────────────────────────────────────────────────────

    /**
     * Register both custom languages and the mddoc-light theme with Monaco.
     * Call this once inside the Monaco require() callback, before creating editors.
     *
     * @param {object} monaco - The global monaco object
     */
    function registerMdDocLanguages(monaco) {

        // mddoc-markdown
        monaco.languages.register({ id: 'mddoc-markdown' });
        monaco.languages.setMonarchTokensProvider('mddoc-markdown', MDDOC_MARKDOWN_DEF);
        monaco.languages.setLanguageConfiguration('mddoc-markdown', {
            comments: { lineComment: '//' },
            brackets: [
                ['[', ']'],
                ['(', ')'],
                ['{', '}'],
                ['[[', ']]'],
            ],
            autoClosingPairs: [
                { open: '[[', close: ']]' },
                { open: '{{', close: '}}' },
                { open: '{%', close: '%}' },
                { open: '{#', close: '#}' },
                { open: '?[', close: ']' },
                { open: '[', close: ']' },
                { open: '(', close: ')' },
                { open: '"', close: '"' },
                { open: "'", close: "'" },
                { open: '`', close: '`' },
                { open: '**', close: '**' },
            ],
            surroundingPairs: [
                { open: '**', close: '**' },
                { open: '*', close: '*' },
                { open: '_', close: '_' },
                { open: '`', close: '`' },
                { open: '[', close: ']' },
                { open: '(', close: ')' },
                { open: '"', close: '"' },
                { open: "'", close: "'" },
            ],
        });

        // mddoc-yaml
        monaco.languages.register({ id: 'mddoc-yaml' });
        monaco.languages.setMonarchTokensProvider('mddoc-yaml', MDDOC_YAML_DEF);
        monaco.languages.setLanguageConfiguration('mddoc-yaml', {
            comments: { lineComment: '#' },
            brackets: [
                ['[', ']'],
                ['{', '}'],
            ],
            autoClosingPairs: [
                { open: '{{', close: '}}' },
                { open: '{%', close: '%}' },
                { open: '[', close: ']' },
                { open: '{', close: '}' },
                { open: '"', close: '"' },
                { open: "'", close: "'" },
            ],
        });

        // Custom light theme
        monaco.editor.defineTheme('mddoc-light', MDDOC_LIGHT_THEME);
    }

    // Export
    global.registerMdDocLanguages = registerMdDocLanguages;

}(window));
