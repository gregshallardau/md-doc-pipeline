<?php

return [
    /*
     * Absolute path to the workspace directory that contains your md-doc projects.
     * All file reads and writes are sandboxed to this directory.
     */
    'workspace_path' => env('MD_DOC_WORKSPACE', base_path('workspace')),

    /*
     * Monaco editor base URL — the path to the monaco-editor `min/vs` directory.
     *
     * Default: jsDelivr CDN (works out of the box, but blocked by some proxies).
     *
     * For local / behind-proxy installs:
     *   1. In your host app:  npm install monaco-editor vite-plugin-monaco-editor
     *   2. In vite.config.js, add the monacoEditorPlugin (see plugin README)
     *   3. After `npm run build`, set MD_DOC_MONACO_URL to the compiled output path,
     *      e.g. MD_DOC_MONACO_URL=/build/monacoeditorwork
     */
    'monaco_base_url' => env('MD_DOC_MONACO_URL', 'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs'),

    /*
     * URL to the marked.js bundle.
     *
     * For local installs: after `npm install marked` and building, set this to
     * the path served by your app, e.g. MD_DOC_MARKED_URL=/build/js/marked.min.js
     */
    'marked_url' => env('MD_DOC_MARKED_URL', 'https://cdn.jsdelivr.net/npm/marked/marked.min.js'),

    /*
     * File lock TTL in minutes.
     * A lock acquired by opening a file expires after this many minutes of inactivity.
     * The editor sends a heartbeat every (lock_ttl_minutes / 2) minutes to keep the lock alive.
     */
    'lock_ttl_minutes' => env('MD_DOC_LOCK_TTL', 10),

    /*
     * User identifier for lock attribution.
     * 'auth'    — use the authenticated user's name/email (requires Laravel Auth)
     * 'session' — use the session ID (useful when auth is not configured)
     */
    'lock_user_source' => env('MD_DOC_LOCK_USER', 'auth'),

    /*
     * Path to the md-doc CLI binary (used by BuildRunner).
     * Default 'md-doc' assumes it is on PATH; override in production with the
     * absolute path, e.g. /opt/md-doc/.venv/bin/md-doc
     */
    'md_doc_bin' => env('MD_DOC_BIN', 'md-doc'),

    /*
     * Where built PDF/DOCX outputs are stored before being served via tokenised URL.
     */
    'build_tmp_dir' => env('MD_DOC_BUILD_DIR', sys_get_temp_dir() . '/md-doc-builds'),

    /*
     * Hard ceiling for a single md-doc build invocation.  WeasyPrint can be slow on
     * large documents so 120 s is a reasonable default.
     */
    'build_timeout_seconds' => env('MD_DOC_BUILD_TIMEOUT', 120),

    /*
     * How long a build token (returned to the browser) remains valid.
     */
    'build_token_ttl_minutes' => env('MD_DOC_BUILD_TTL', 30),
];
