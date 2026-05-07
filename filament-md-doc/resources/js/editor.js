/**
 * md-doc Filament plugin — Monaco editor + marked.js live preview
 */

(function () {
    'use strict';

    const DEBOUNCE_MS = 400;

    // ── Helpers ───────────────────────────────────────────────────────────────

    function detectLanguage(fileType) {
        if (fileType === 'css')  return 'css';
        if (fileType === 'meta') return 'mddoc-yaml';
        return 'mddoc-markdown';
    }

    function stripFrontmatter(content) {
        const trimmed = content.trimStart();
        if (!trimmed.startsWith('---')) return content;
        const end = trimmed.indexOf('\n---', 3);
        if (end === -1) return content;
        return trimmed.slice(end + 4).trimStart();
    }

    function substituteVars(html, config) {
        if (!config || typeof config !== 'object') return html;
        return html.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (match, key) => {
            const value = config[key];
            return value !== undefined ? String(value) : match;
        });
    }

    function renderPreview(content, config, css) {
        const preview = document.getElementById('md-doc-preview');
        if (!preview) return;

        if (typeof marked === 'undefined') {
            preview.innerHTML = '<p style="color:#9ca3af;font-size:.8rem">Loading preview…</p>';
            return;
        }

        const body = stripFrontmatter(content);
        let html = marked.parse(body);
        html = substituteVars(html, config);

        const styleTag = css ? `<style>${css}</style>` : '';
        preview.innerHTML = styleTag + html;
    }

    // ── Debounce ──────────────────────────────────────────────────────────────

    function debounce(fn, ms) {
        let timer;
        return function (...args) {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), ms);
        };
    }

    // ── Monaco bootstrap ──────────────────────────────────────────────────────

    function initMonaco() {
        const container = document.getElementById('md-doc-monaco');
        if (!container) return;

        const initialContent = window.mdDocInitialContent || '';
        const fileType       = window.mdDocFileType || 'md';
        const language       = detectLanguage(fileType);

        require(['vs/editor/editor.main'], function () {
            // Register md-doc custom languages + theme (defined in tokenizers.js)
            if (typeof registerMdDocLanguages === 'function') {
                registerMdDocLanguages(monaco);
            }

            const editor = monaco.editor.create(container, {
                value:           initialContent,
                language:        language,
                theme:           'mddoc-light',
                minimap:         { enabled: false },
                fontSize:        13,
                lineNumbers:     'on',
                wordWrap:        'on',
                scrollBeyondLastLine: false,
                automaticLayout: true,
                tabSize:         2,
            });

            // Initial preview render
            renderPreview(initialContent, window.mdDocConfig, window.mdDocCss);

            // Live preview: debounced on content change
            const debouncedUpdate = debounce(function (value) {
                renderPreview(value, window.mdDocConfig, window.mdDocCss);

                // Notify Livewire so it can refresh config/CSS/includes panels
                window.Livewire.dispatch('editor-content-changed', { content: value });
            }, DEBOUNCE_MS);

            editor.onDidChangeModelContent(function () {
                debouncedUpdate(editor.getValue());
            });

            // Store reference for Livewire-triggered updates
            window.mdDocEditor = editor;
        });
    }

    // ── Alpine component ──────────────────────────────────────────────────────

    window.mdDocEditor = null;

    window.mdDocEditorComponent = function ({ fileType, mergedConfig, resolvedCss }) {
        return {
            fileType,
            mergedConfig,
            resolvedCss,

            init() {
                // Wait for Monaco loader to be available
                this.waitForMonaco();
            },

            waitForMonaco() {
                if (typeof require !== 'undefined') {
                    initMonaco();
                } else {
                    setTimeout(() => this.waitForMonaco(), 100);
                }
            },

            onContentUpdated(detail) {
                // Livewire has refreshed config/CSS — update preview globals and re-render
                if (detail.mergedConfig !== undefined) {
                    window.mdDocConfig = detail.mergedConfig;
                }
                if (detail.resolvedCss !== undefined) {
                    window.mdDocCss = detail.resolvedCss;
                }
                if (window.mdDocEditor) {
                    renderPreview(window.mdDocEditor.getValue(), window.mdDocConfig, window.mdDocCss);
                }
            },
        };
    };

    // Expose as Alpine magic (called from x-data in the Blade template)
    document.addEventListener('alpine:init', function () {
        Alpine.data('mdDocEditor', window.mdDocEditorComponent);
    });

    // ── Livewire lifecycle hook — re-init Monaco after Livewire navigation ────
    document.addEventListener('livewire:navigated', function () {
        // Destroy existing Monaco instance if any
        if (window.mdDocEditor && typeof window.mdDocEditor.dispose === 'function') {
            window.mdDocEditor.dispose();
            window.mdDocEditor = null;
        }

        // Re-initialise if the container is present
        if (document.getElementById('md-doc-monaco')) {
            // Update globals from fresh page data
            initMonaco();
        }
    });

    // ── Livewire event: file loaded / saved — update Monaco model ─────────────
    document.addEventListener('livewire:init', function () {
        Livewire.on('file-loaded', function ({ content, fileType, mergedConfig, resolvedCss }) {
            window.mdDocConfig  = mergedConfig  || {};
            window.mdDocCss     = resolvedCss   || '';
            window.mdDocFileType = fileType;

            if (window.mdDocEditor && typeof window.mdDocEditor.setValue === 'function') {
                const language = detectLanguage(fileType);
                const model = window.mdDocEditor.getModel();
                if (model) {
                    monaco.editor.setModelLanguage(model, language);
                }
                window.mdDocEditor.setValue(content || '');
            }

            renderPreview(content || '', mergedConfig || {}, resolvedCss || '');
        });
    });

}());
