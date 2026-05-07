# Self-hosting Monaco and marked.js

By default, the plugin loads Monaco editor and `marked.js` from jsDelivr's CDN. This works out of the box but breaks behind corporate proxies that block external CDNs. This guide covers serving them locally.

---

## Quick option: just marked.js

`marked.min.js` is small (~50 KB). Easiest path is to vendor it once and forget about it:

```bash
# In your Laravel app:
mkdir -p public/vendor/md-doc/js
curl -o public/vendor/md-doc/js/marked.min.js https://cdn.jsdelivr.net/npm/marked/marked.min.js
```

Then in `.env`:

```env
MD_DOC_MARKED_URL=/vendor/md-doc/js/marked.min.js
```

You're done for marked. Monaco is more involved.

---

## Full option: npm + Vite

This is the recommended production setup for behind-proxy environments.

### 1. Install via npm

In your Laravel app's root (the same directory as `package.json`):

```bash
npm install monaco-editor marked vite-plugin-monaco-editor --save-dev
```

If your Laravel app's `package.json` doesn't yet exist, init it first: `npm init -y`.

### 2. Configure Vite

Edit `vite.config.js`:

```js
import { defineConfig } from 'vite';
import laravel from 'laravel-vite-plugin';
import monacoEditorPlugin from 'vite-plugin-monaco-editor';

export default defineConfig({
    plugins: [
        laravel({
            input: ['resources/css/app.css', 'resources/js/app.js'],
            refresh: true,
        }),
        monacoEditorPlugin.default({
            languageWorkers: ['css', 'editorWorkerService'],
        }),
    ],
});
```

The Monaco plugin emits the editor's worker bundles into `public/build/monacoeditorwork/` during `npm run build`.

### 3. Build assets

```bash
npm run build
```

You should now see:

```
public/build/
├── monacoeditorwork/
│   ├── css.worker.js
│   ├── editor.worker.js
│   └── ts.worker.js
└── ...other compiled assets
```

### 4. Vendor marked

Either bundle it in your `app.js`:

```js
// resources/js/app.js
import { marked } from 'marked';
window.marked = marked;
```

… or copy the standalone bundle:

```bash
cp node_modules/marked/marked.min.js public/build/marked.min.js
```

### 5. Point the plugin at the local files

In `.env`:

```env
# The path you serve the loader.js from.
# Note: this should NOT include /loader.js — the Blade template appends it.
MD_DOC_MONACO_URL=/build/monacoeditorwork

# If you bundled marked into app.js, set this to a small wrapper that just
# defines `window.marked` (so the plugin's existence check passes).
# If you copied marked.min.js, point at it directly:
MD_DOC_MARKED_URL=/build/marked.min.js
```

Restart the server / run `php artisan config:clear`.

---

## Just Monaco's `min/vs` directory (no Vite)

If your app doesn't use Vite, you can serve Monaco's pre-built distribution directly:

```bash
# Copy the entire min/ tree into public/
cp -r node_modules/monaco-editor/min public/vendor/md-doc/monaco
```

```env
MD_DOC_MONACO_URL=/vendor/md-doc/monaco/vs
```

The plugin's Blade template loads `<MD_DOC_MONACO_URL>/loader.js`, which then dynamically loads the rest from the same base URL.

This setup is simpler but ships ~5 MB of static assets. Vite's `monacoEditorPlugin` is smarter — it only emits the bits you actually need.

---

## Verifying

After setting `MD_DOC_MONACO_URL` and reloading:

1. Open the browser DevTools Network tab
2. Open the editor
3. Confirm `loader.js`, `editor.main.js`, etc. are loading from your domain (not jsdelivr)
4. The Monaco editor should render with full syntax highlighting

If you see a CORS error or 404, the path is wrong. Double-check that `<MD_DOC_MONACO_URL>/loader.js` is reachable in your browser directly.

---

## Behind a corporate proxy — extra notes

If you're in a locked-down env where even npm itself can't reach the public registry:

1. Check if your org has an internal mirror (Verdaccio, Nexus, Artifactory)
2. Configure npm to use it: `npm config set registry https://your-internal-registry/`
3. Then `npm install` works as normal
4. Or download the tarballs manually and `npm install ./monaco-editor-0.52.2.tgz`

The plugin itself only cares that `<MD_DOC_MONACO_URL>/loader.js` is reachable from the browser — *how* you got the files there is up to you.
