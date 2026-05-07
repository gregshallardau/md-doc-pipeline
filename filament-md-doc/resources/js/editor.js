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

    // ── Diff viewer (Monaco diff editor) ──────────────────────────────────────

    let diffEditor = null;

    /**
     * Load file contents at the given commit, then render a side-by-side diff
     * against the working copy in the editor.
     */
    window.mdDocLoadDiff = function (sha) {
        if (!sha || !window.mdDocPath) return;

        const url = '/md-doc/git/file-at-commit?path=' + encodeURIComponent(window.mdDocPath) + '&commit=' + encodeURIComponent(sha);

        fetch(url, { credentials: 'same-origin' })
            .then(function (res) { return res.ok ? res.json() : Promise.reject(res); })
            .then(function (data) {
                const oldContent = data.content || '';
                const newContent = window.mdDocEditor ? window.mdDocEditor.getValue() : '';
                const language   = detectLanguage(window.mdDocFileType);
                renderDiff(oldContent, newContent, language);
            })
            .catch(function (err) {
                const container = document.getElementById('md-doc-diff');
                if (container) {
                    container.innerHTML = '<p style="color:#dc2626;padding:1rem;font-size:.85rem">'
                        + 'Failed to load diff: ' + (err.statusText || 'unknown error') + '</p>';
                }
            });
    };

    function renderDiff(oldText, newText, language) {
        const container = document.getElementById('md-doc-diff');
        if (!container || typeof monaco === 'undefined') return;

        if (diffEditor) {
            diffEditor.dispose();
            diffEditor = null;
        }
        container.innerHTML = '';

        diffEditor = monaco.editor.createDiffEditor(container, {
            theme:           'mddoc-light',
            readOnly:        true,
            renderSideBySide: true,
            fontSize:        12,
            automaticLayout: true,
            minimap:         { enabled: false },
        });

        diffEditor.setModel({
            original: monaco.editor.createModel(oldText, language),
            modified: monaco.editor.createModel(newText, language),
        });
    }

    // ── Lock heartbeat + page-unload release ─────────────────────────────────

    let lockHeartbeatTimer = null;

    function startLockHeartbeat() {
        if (lockHeartbeatTimer) clearInterval(lockHeartbeatTimer);

        const intervalMs = window.mdDocHeartbeatMs || 5 * 60 * 1000; // default 5 min
        if (!window.mdDocLockKey) return;

        lockHeartbeatTimer = setInterval(function () {
            // Use the lightweight HTTP endpoint (avoids a full Livewire round-trip)
            fetch('/md-doc/lock/refresh', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRF-TOKEN': document.querySelector('meta[name=csrf-token]')?.content || '' },
                body: JSON.stringify({ path: window.mdDocPath, lockKey: window.mdDocLockKey }),
            }).then(function (res) {
                return res.json();
            }).then(function (data) {
                if (!data.ok) {
                    // Lock expired — notify Livewire so it switches to read-only UI
                    clearInterval(lockHeartbeatTimer);
                    window.mdDocLockKey = null;
                    if (window.Livewire) {
                        window.Livewire.dispatch('lock-heartbeat'); // triggers onHeartbeat() which handles the expired case
                    }
                }
            }).catch(function () { /* network error — Livewire will clean up on next interaction */ });
        }, intervalMs);
    }

    // Release lock immediately when the user navigates away or closes the tab.
    // sendBeacon is fire-and-forget — no response awaited.
    window.addEventListener('beforeunload', function () {
        if (window.mdDocLockKey && window.mdDocPath) {
            navigator.sendBeacon('/md-doc/lock/release', JSON.stringify({
                path:    window.mdDocPath,
                lockKey: window.mdDocLockKey,
            }));
        }
    });

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
                readOnly:        !!window.mdDocIsReadOnly,
                minimap:         { enabled: false },
                fontSize:        13,
                lineNumbers:     'on',
                wordWrap:        'on',
                scrollBeyondLastLine: false,
                automaticLayout: true,
                tabSize:         2,
            });

            // Start lock heartbeat if we hold the lock
            startLockHeartbeat();

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
        Livewire.on('file-loaded', function ({ content, fileType, mergedConfig, resolvedCss, lockKey, isReadOnly }) {
            window.mdDocConfig   = mergedConfig  || {};
            window.mdDocCss      = resolvedCss   || '';
            window.mdDocFileType = fileType;
            window.mdDocLockKey  = lockKey  || null;
            window.mdDocIsReadOnly = !!isReadOnly;

            if (window.mdDocEditor && typeof window.mdDocEditor.setValue === 'function') {
                const language = detectLanguage(fileType);
                const model = window.mdDocEditor.getModel();
                if (model) {
                    monaco.editor.setModelLanguage(model, language);
                }
                window.mdDocEditor.updateOptions({ readOnly: !!isReadOnly });
                window.mdDocEditor.setValue(content || '');
            }

            // Restart heartbeat for the new file
            startLockHeartbeat();

            renderPreview(content || '', mergedConfig || {}, resolvedCss || '');
        });
    });

}());
