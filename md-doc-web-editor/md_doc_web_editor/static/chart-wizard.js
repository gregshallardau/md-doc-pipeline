/*
 * Chart wizard - a step-by-step Vega-Lite / Vega chart builder, shared by both studios.
 *
 * CANONICAL COPIES: presentation-framework/editor/static/chart-*.js. md-doc-pipeline's studio
 * (md-doc-web-editor/md_doc_web_editor/static/) carries byte-identical copies; a SHA-256 manifest
 * is checked in both repos, so change them together. The wizard knows nothing about either studio;
 * each passes a small host object to ChartWizard.open():
 *
 *   ChartWizard.open({
 *     format: 'yaml-fence' | 'deck-element',   // what to insert (see ChartCatalog.codeFor)
 *     scriptBase: '/static',                    // where chart-*.js are served (loaded on first use)
 *     vendorBase: '/static/vendor/vega-6.2.0',  // vega.min.js, vega-lite.min.js, vega-embed.min.js
 *     datasetBase: '/static/vendor/vega-6.2.0/datasets',  // world-110m.json, us-10m.json
 *     getConfig: async () => vegaConfig,        // theme config for the preview (optional)
 *     onInsert: (code) => {},                   // put the text at the cursor
 *   });
 *
 * The chart types live in chart-core.js and chart-types-*.js (ChartCatalog); this file is the dialog.
 * Output is the spec md-doc-pipeline renders in documents (a ```chart block) and the presentation
 * framework renders on slides (<deck-chart-vega>), so a chart built here is the same chart in both.
 */
(function (root) {
	'use strict';

	/** Catalogue files, in load order (core first; the rest only register themselves). */
	const FILES = [
		'chart-core.js', 'chart-templates.js', 'chart-geo-data.js',
	];
	// Upstream-backed types replace the hand-built ones with the same id, so they load last.
	const LATE = ['chart-types-upstream.js', 'chart-types-custom.js'];
	const STEPS = ['Type', 'Data', 'Customize', 'Insert'];
	const THUMB = { w: 132, h: 84 };

	const loading = {};
	let styleNode = null;
	const thumbCache = new Map();
	const datasetCache = new Map();

	/* ── Loading ────────────────────────────────────────────────────────── */

	function loadScript(src) {
		if (!loading[src]) {
			loading[src] = new Promise((resolve, reject) => {
				const s = document.createElement('script');
				s.src = src;
				s.onload = resolve;
				s.onerror = () => reject(new Error(`Could not load ${src}`));
				document.head.append(s);
			});
		}
		return loading[src];
	}

	async function ensureCatalog(base) {
		if (root.ChartCatalog && root.ChartCatalog.TYPES.length) return root.ChartCatalog;
		const b = base.replace(/\/$/, '');
		await loadScript(`${b}/${FILES[0]}`);
		await loadScript(`${b}/${FILES[1]}`);
		await Promise.all(FILES.slice(2).map((f) => loadScript(`${b}/${f}`)));
		for (const f of LATE) await loadScript(`${b}/${f}`);
		return root.ChartCatalog;
	}

	async function loadVega(base) {
		const b = base.replace(/\/$/, '');
		if (!root.vegaEmbed) {
			// Monaco's AMD loader defines `define`, which makes these UMD bundles register as
			// AMD modules instead of setting globals - hide it while they load.
			const amd = root.define;
			root.define = undefined;
			try {
				await loadScript(`${b}/vega.min.js`);
				await loadScript(`${b}/vega-lite.min.js`);
				await loadScript(`${b}/vega-embed.min.js`);
			} finally {
				root.define = amd;
			}
		}
		return root.vegaEmbed;
	}

	/* ── DOM helpers ────────────────────────────────────────────────────── */

	function h(tag, props, ...kids) {
		const node = document.createElement(tag);
		for (const [k, v] of Object.entries(props || {})) {
			if (v === undefined || v === null || v === false) continue;
			if (k === 'class') node.className = v;
			else if (k === 'html') node.innerHTML = v;
			else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
			else if (k === 'value') node.value = v;
			else if (k === 'checked' || k === 'disabled' || k === 'selected') node[k] = !!v;
			else node.setAttribute(k, v === true ? '' : v);
		}
		for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
		return node;
	}

	function isDark() {
		for (const el of [document.body, document.documentElement]) {
			const m = (getComputedStyle(el).backgroundColor || '').match(/[\d.]+/g);
			if (m && (m.length < 4 || +m[3] > 0)) return (0.2126 * +m[0] + 0.7152 * +m[1] + 0.0722 * +m[2]) / 255 < 0.45;
		}
		return false;
	}

	const CSS = `
.cw { width: min(1120px, 96vw); max-height: 94vh; padding: 0; border: 1px solid color-mix(in srgb, CanvasText 25%, transparent); border-radius: 12px; background: Canvas; color: CanvasText; font: 14px/1.45 system-ui, sans-serif; }
.cw::backdrop { background: rgba(0,0,0,.45); }
.cw * { box-sizing: border-box; }
.cw[open] { display: flex; flex-direction: column; }
.cw-head { display: flex; align-items: center; gap: 16px; padding: 12px 18px; border-bottom: 1px solid color-mix(in srgb, CanvasText 15%, transparent); }
.cw-head h2 { margin: 0; font-size: 16px; }
.cw-steps { display: flex; gap: 6px; margin: 0 auto 0 8px; padding: 0; list-style: none; }
.cw-steps li { padding: 3px 10px; border-radius: 99px; color: GrayText; font-size: 12.5px; }
.cw-steps li[aria-current="step"] { background: var(--cw-accent, #2563eb); color: #fff; }
.cw-steps li.done { color: CanvasText; }
.cw-body { display: flex; gap: 18px; padding: 16px 18px; overflow: auto; min-height: 400px; flex: 1; }
.cw-main { flex: 1 1 52%; min-width: 0; }
.cw-preview { flex: 1 1 44%; min-width: 0; display: flex; flex-direction: column; gap: 8px; position: sticky; top: 0; align-self: flex-start; }
.cw-chart { border: 1px solid color-mix(in srgb, CanvasText 15%, transparent); border-radius: 8px; padding: 10px; min-height: 280px; display: grid; place-items: center; background: #fff; color: #1f2328; overflow: auto; }
.cw-note { margin: 0; color: GrayText; font-size: 12.5px; min-height: 1.4em; }
.cw-note.error { color: #d03b3b; }
.cw-note.warn { color: #a45c00; }
.cw-search { margin-bottom: 12px; }
.cw-group { margin: 0 0 18px; }
.cw-group h4 { margin: 0 0 8px; font-size: 13px; font-weight: 600; }
.cw-group h4 span { color: GrayText; font-weight: 400; margin-left: 8px; }
.cw-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.cw-card { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; padding: 8px; border: 1px solid color-mix(in srgb, CanvasText 20%, transparent); border-radius: 10px; background: transparent; color: inherit; text-align: left; cursor: pointer; font: inherit; }
.cw-card:hover, .cw-card:focus-visible { border-color: var(--cw-accent, #2563eb); }
.cw-card[aria-pressed="true"] { border-color: var(--cw-accent, #2563eb); box-shadow: 0 0 0 2px color-mix(in srgb, var(--cw-accent, #2563eb) 35%, transparent); }
.cw-thumb { width: ${THUMB.w}px; height: ${THUMB.h}px; overflow: hidden; border-radius: 6px; background: #fff; position: relative; pointer-events: none; align-self: center; }
.cw-thumb > div { transform-origin: top left; position: absolute; left: 0; top: 0; }
.cw-thumb .role-legend, .cw-thumb .role-title { display: none; }
.cw-card b { font-weight: 600; font-size: 13px; }
.cw-card span.d { color: GrayText; font-size: 12px; line-height: 1.3; }
.cw label { display: block; margin: 0 0 10px; font-weight: 500; }
.cw label small { display: block; font-weight: 400; color: GrayText; }
.cw select, .cw input[type="text"], .cw input[type="number"], .cw input[type="search"], .cw textarea { width: 100%; padding: 6px 8px; border: 1px solid color-mix(in srgb, CanvasText 30%, transparent); border-radius: 6px; background: Field; color: FieldText; font: inherit; }
.cw textarea { min-height: 76px; font: 12.5px ui-monospace, monospace; }
.cw .row { display: flex; gap: 10px; flex-wrap: wrap; }
.cw .row > * { flex: 1 1 180px; }
.cw .check { display: flex; gap: 8px; align-items: center; font-weight: 400; }
.cw .check input { width: auto; }
.cw fieldset { margin: 0 0 12px; padding: 8px 10px; border: 1px solid color-mix(in srgb, CanvasText 25%, transparent); border-radius: 6px; }
.cw legend { font-weight: 500; padding: 0 4px; }
.cw fieldset .picks { display: flex; flex-wrap: wrap; gap: 4px 14px; }
.cw-grid-wrap { overflow: auto; max-height: 250px; border: 1px solid color-mix(in srgb, CanvasText 20%, transparent); border-radius: 6px; margin: 8px 0; }
.cw-grid { border-collapse: collapse; width: 100%; font-size: 13px; }
.cw-grid th, .cw-grid td { border: 1px solid color-mix(in srgb, CanvasText 12%, transparent); padding: 0; }
.cw-grid input { width: 100%; min-width: 64px; border: 0; padding: 4px 6px; background: transparent; color: inherit; font: inherit; }
.cw-grid th input { font-weight: 600; }
.cw-grid th select { width: 100%; border: 0; border-top: 1px solid color-mix(in srgb, CanvasText 12%, transparent); border-radius: 0; font-size: 11.5px; color: GrayText; }
.cw-grid .gutter { width: 28px; text-align: center; color: GrayText; background: color-mix(in srgb, CanvasText 5%, transparent); cursor: pointer; }
.cw-tools { display: flex; gap: 8px; flex-wrap: wrap; }
.cw button.btn { padding: 6px 12px; border: 1px solid color-mix(in srgb, CanvasText 30%, transparent); border-radius: 6px; background: transparent; color: inherit; font: inherit; cursor: pointer; }
.cw button.btn.primary { background: var(--cw-accent, #2563eb); border-color: var(--cw-accent, #2563eb); color: #fff; }
.cw button.btn:disabled { opacity: .45; cursor: default; }
.cw-foot { display: flex; gap: 8px; align-items: center; padding: 12px 18px; border-top: 1px solid color-mix(in srgb, CanvasText 15%, transparent); }
.cw-foot .grow { flex: 1; }
.cw-code { margin: 0; padding: 10px; max-height: 320px; overflow: auto; border-radius: 6px; background: color-mix(in srgb, CanvasText 7%, transparent); font: 12px/1.45 ui-monospace, monospace; white-space: pre; }
.cw h3 { margin: 0 0 8px; font-size: 14px; }
.cw p.hint { margin: 0 0 10px; color: GrayText; font-size: 13px; }
`;

	/* ── Datasets and previews ──────────────────────────────────────────── */

	async function loadDataset(host, name) {
		if (!datasetCache.has(name)) {
			datasetCache.set(name, fetch(`${host.datasetBase.replace(/\/$/, '')}/${encodeURIComponent(name)}.json`).then((r) => {
				if (!r.ok) throw new Error(`Could not load the ${name} map data`);
				return r.json();
			}));
		}
		return datasetCache.get(name);
	}

	const isCompound = (spec) => ['repeat', 'facet', 'concat', 'hconcat', 'vconcat'].some((k) => k in spec);
	const hasFixedSize = (spec) => typeof spec.width === 'number' && typeof spec.height === 'number';

	/** What the preview draws: the spec with built-in maps inlined and a size when it has none. */
	async function previewSpec(C, host, spec, size) {
		const out = await C.resolveDatasets(spec, (name) => loadDataset(host, name));
		if (isCompound(out) || hasFixedSize(out)) return out;
		return { ...out, width: size.w, height: size.h, autosize: { type: 'fit', contains: 'padding' } };
	}

	/** A chart wider than its box is scaled down to fit (keeping its proportions). */
	function fitToBox(box) {
		const svg = box.querySelector('svg');
		const w = parseFloat(svg?.getAttribute('width')), ht = parseFloat(svg?.getAttribute('height'));
		const room = box.clientWidth - 22;
		if (!svg || !w || !ht || w <= room) return;
		svg.setAttribute('viewBox', `0 0 ${w} ${ht}`);
		svg.style.width = `${room}px`;
		svg.style.height = `${(ht * room) / w}px`;
	}

	/* ── The dialog ─────────────────────────────────────────────────────── */

	async function open(host) {
		const C = await ensureCatalog(host.scriptBase || '.');
		if (!styleNode) {
			styleNode = h('style', { id: 'chart-wizard-style' });
			styleNode.textContent = CSS;
			document.head.append(styleNode);
		}
		const state = {
			step: 0,
			type: 'bar',
			table: { columns: [], rows: [] },
			types: {},
			userTyped: {},
			map: {},
			opts: {},
			config: null,
			touched: false,
			query: '',
		};
		const dialog = h('dialog', { class: 'cw', 'aria-label': 'Insert a chart' });
		dialog.style.colorScheme = isDark() ? 'dark' : 'light';
		const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
		if (accent) dialog.style.setProperty('--cw-accent', accent);
		document.body.append(dialog);
		let timer = null, previewToken = 0, observer = null;

		const chart = () => C.chartType(state.type);
		const optValue = (id) => (state.opts[id] !== undefined ? state.opts[id] : C.optionDefaults(chart())[id]);
		const currentOpts = () => ({ ...C.optionDefaults(chart()), ...state.opts });
		const snapshot = () => ({ type: state.type, table: state.table, types: state.types, map: state.map, opts: state.opts, userTyped: state.userTyped });
		const codeNow = () => C.codeFor(host.format, current(), currentOpts().title, snapshot());
		const current = (warnings) => C.buildSpec({ type: state.type, table: state.table, types: state.types, map: state.map, opts: currentOpts() }, warnings);

		function setTable(table) {
			state.table = table;
			state.types = {};
			for (const [i, c] of table.columns.entries()) state.types[c] = C.inferType(table.rows.map((r) => r[i]));
			state.userTyped = {};
			state.map = C.autoMap(chart(), table, state.types, state.map);
		}
		function loadSample() {
			const st = C.sampleState(chart());
			state.table = st.table;
			state.types = st.types;
			state.userTyped = {};
			state.map = st.map;
			state.opts = {};
		}
		const editing = host.editing || null;
		if (editing) Object.assign(state, editing.state, { step: 1, touched: true });
		else loadSample();

		/* preview */
		async function preview(box, note) {
			const token = ++previewToken;
			const warnings = [];
			let spec;
			try {
				spec = current(warnings);
			} catch (e) {
				box.replaceChildren(h('span', { class: 'cw-note' }, 'The preview appears once the data and columns are set.'));
				note.textContent = e.message;
				note.className = 'cw-note error';
				return;
			}
			note.className = warnings.length ? 'cw-note warn' : 'cw-note';
			note.textContent = warnings.length ? warnings.join(' ') : 'Close to the final look; the built chart uses your theme’s colours and fonts.';
			try {
				const embed = await loadVega(host.vendorBase);
				if (state.config === null) state.config = host.getConfig ? (await host.getConfig()) || {} : {};
				const drawn = await previewSpec(C, host, spec, { w: 420, h: 250 });
				if (token !== previewToken) return;
				box.replaceChildren();
				await embed(box, drawn, { actions: false, renderer: 'svg', config: state.config });
				fitToBox(box);
			} catch (e) {
				note.textContent = `Preview failed: ${e.message}`;
				note.className = 'cw-note error';
			}
		}

		/* thumbnails */
		async function drawThumb(box, type) {
			try {
				let svg = thumbCache.get(type.id);
				if (!svg) {
					const embed = await loadVega(host.vendorBase);
					if (state.config === null) state.config = host.getConfig ? (await host.getConfig()) || {} : {};
					const spec = C.sampleSpec(type);
					delete spec.title;
					const drawn = await previewSpec(C, host, spec, { w: 320, h: 200 });
					const holder = h('div');
					await embed(holder, drawn, { actions: false, renderer: 'svg', config: state.config });
					const el = holder.querySelector('svg');
					const w = parseFloat(el.getAttribute('width')) || 320, ht = parseFloat(el.getAttribute('height')) || 200;
					svg = { html: holder.innerHTML, scale: Math.min(THUMB.w / w, THUMB.h / ht), w, h: ht };
					thumbCache.set(type.id, svg);
				}
				const inner = h('div', { html: svg.html });
				inner.style.transform = `scale(${svg.scale})`;
				inner.style.left = `${(THUMB.w - svg.w * svg.scale) / 2}px`;
				inner.style.top = `${(THUMB.h - svg.h * svg.scale) / 2}px`;
				box.replaceChildren(inner);
			} catch (e) {
				box.replaceChildren(h('span', { class: 'cw-note', title: e.message }, ''));
			}
		}

		/* step 1: type */
		function typeStep() {
			observer?.disconnect();
			observer = new IntersectionObserver((entries) => {
				for (const entry of entries) if (entry.isIntersecting) { observer.unobserve(entry.target); drawThumb(entry.target, entry.target._type); }
			}, { root: dialog.querySelector('.cw-body'), rootMargin: '120px' });
			const list = h('div');
			const search = h('input', { type: 'search', class: 'cw-search', placeholder: `Search ${C.TYPES.length} chart types…`, 'aria-label': 'Search chart types', value: state.query,
				oninput: (e) => { state.query = e.target.value; fill(); } });
			const fill = () => {
				observer.disconnect();
				list.replaceChildren();
				const q = state.query.trim().toLowerCase();
				for (const g of C.GROUPS) {
					const types = C.TYPES.filter((t) => t.group === g.id && (!q || `${t.label} ${t.desc} ${g.label} ${t.id}`.toLowerCase().includes(q)));
					if (!types.length) continue;
					const cards = h('div', { class: 'cw-cards', role: 'group', 'aria-label': g.label });
					for (const t of types) {
						const thumb = h('div', { class: 'cw-thumb', 'aria-hidden': 'true' });
						thumb._type = t;
						const card = h('button', { type: 'button', class: 'cw-card', 'aria-pressed': String(t.id === state.type), title: t.desc,
							onclick: () => pick(t.id) }, thumb, h('b', null, t.label), h('span', { class: 'd' }, t.desc));
						cards.append(card);
						observer.observe(thumb);
					}
					list.append(h('section', { class: 'cw-group' }, h('h4', null, g.label, h('span', null, g.desc)), cards));
				}
				if (!list.childNodes.length) list.append(h('p', { class: 'hint' }, 'No chart type matches that search.'));
			};
			fill();
			return [h('h3', null, 'What kind of chart?'), search, list];
		}

		function pick(id) {
			const same = id === state.type;
			state.type = id;
			if (!same) {
				if (state.touched) { state.map = C.autoMap(chart(), state.table, state.types, {}); state.opts = {}; }
				else loadSample();
			}
			go(1);
		}

		/* step 2: data */
		function dataStep(refresh) {
			const paste = h('textarea', { placeholder: 'Paste from a spreadsheet or CSV (first row = column names)…', 'aria-label': 'Paste data', spellcheck: 'false' });
			const wrap = h('div', { class: 'cw-grid-wrap' });
			const retype = () => {
				for (const [i, c] of state.table.columns.entries()) if (!state.userTyped[c]) state.types[c] = C.inferType(state.table.rows.map((r) => r[i]));
				state.map = C.autoMap(chart(), state.table, state.types, state.map);
			};
			const draw = () => {
				const { columns, rows } = state.table;
				const head = h('tr', null, h('th', { class: 'gutter' }), columns.map((c, i) => h('th', null,
					h('input', { value: c, 'aria-label': `Column ${i + 1} name`, onchange: (e) => renameColumn(i, e.target.value.trim() || c) }),
					h('select', { 'aria-label': `${c} type`, onchange: (e) => { state.types[c] = e.target.value; state.userTyped[c] = true; refresh(); draw(); } },
						[['nominal', 'Text'], ['quantitative', 'Number'], ['temporal', 'Date']].map(([v, l]) => h('option', { value: v, selected: state.types[c] === v }, l))))));
				const body = rows.map((r, ri) => h('tr', null,
					h('td', { class: 'gutter', title: 'Remove row', onclick: () => { rows.splice(ri, 1); retype(); draw(); refresh(); } }, '×'),
					columns.map((c, ci) => h('td', null, h('input', { value: r[ci], 'aria-label': `${c}, row ${ri + 1}`, onchange: (e) => { r[ci] = e.target.value.trim(); retype(); refresh(); } })))));
				wrap.replaceChildren(h('table', { class: 'cw-grid' }, head, body));
			};
			const renameColumn = (i, name) => {
				const old = state.table.columns[i];
				if (state.table.columns.includes(name) && name !== old) return draw();
				state.table.columns[i] = name;
				state.types[name] = state.types[old];
				delete state.types[old];
				if (state.userTyped[old]) { state.userTyped[name] = true; delete state.userTyped[old]; }
				for (const k of Object.keys(state.map)) {
					if (Array.isArray(state.map[k])) state.map[k] = state.map[k].map((c) => (c === old ? name : c));
					else if (state.map[k] === old) state.map[k] = name;
				}
				draw(); refresh();
			};
			paste.addEventListener('input', () => {
				const t = C.parseTable(paste.value);
				if (t.columns.length) { state.touched = true; setTable(t); draw(); refresh(); }
			});
			draw();
			return [
				h('h3', null, `Your data — ${chart().label}`),
				h('p', { class: 'hint' }, dataHint(chart())),
				paste,
				wrap,
				h('div', { class: 'cw-tools' },
					h('button', { type: 'button', class: 'btn', onclick: () => { state.table.rows.push(state.table.columns.map(() => '')); draw(); } }, 'Add row'),
					h('button', { type: 'button', class: 'btn', onclick: () => { let n = state.table.columns.length + 1; while (state.table.columns.includes(`column${n}`)) n++; const name = `column${n}`; state.table.columns.push(name); state.table.rows.forEach((r) => r.push('')); state.types[name] = 'nominal'; draw(); refresh(); } }, 'Add column'),
					h('button', { type: 'button', class: 'btn', onclick: () => { state.touched = false; loadSample(); draw(); refresh(); } }, 'Reset to sample')),
			];
		}

		function dataHint(t) {
			const kinds = {
				hierarchy: 'One row per node: its name, its parent’s name (blank for the top), and a size for the leaves.',
				flow: t.id === 'edge-bundling' ? 'One row per item: its name, its parent, and the names it links to (separated by ;).' : 'One row per link: where it starts, where it ends, and an amount.',
				geo: t.id.startsWith('bubble') ? 'One row per place, with its latitude and longitude as numbers.' : 'One row per place: a name or code (countries by name or ISO code, US states by name, postal code or FIPS) and a value.',
				text: t.id === 'word-cloud' ? 'One row per word, with a weight (or leave the weight out to count repeats).' : 'One row per metric per item, in long form.',
			};
			return kinds[t.group] || 'Edit the sample, or paste your own table. One row per data point; the first row names the columns.';
		}

		/* step 3: customize */
		const NO_AXIS_TITLES = new Set(['pie', 'donut', 'rose', 'radial-bar', 'waffle', 'gauge', 'parallel', 'scatter-matrix', 'correlation', 'calendar', 'radar', 'sparkline', 'treemap', 'sunburst', 'icicle', 'circle-pack', 'tree', 'dendrogram', 'radial-tree', 'sankey', 'chord', 'arc-diagram', 'force', 'edge-bundling', 'word-cloud', 'map-world', 'map-us', 'bubble-map-world', 'bubble-map-us']);

		function designStep(refresh) {
			const t = chart();
			const cols = state.table.columns;
			const out = [h('h3', null, `${t.label} — columns and options`)];
			for (const r of t.roles) {
				if (r.multi) {
					const chosen = new Set([].concat(state.map[r.key] || []));
					const picks = h('div', { class: 'picks' }, cols.filter((c) => state.types[c] === 'quantitative' || r.kind !== 'num').map((c) => h('label', { class: 'check' },
						h('input', { type: 'checkbox', checked: chosen.has(c), onchange: (e) => {
							const set = new Set([].concat(state.map[r.key] || []));
							if (e.target.checked) set.add(c); else set.delete(c);
							const list = cols.filter((x) => set.has(x));
							if (list.length) state.map[r.key] = list; else delete state.map[r.key];
							refresh();
						} }), c)));
					out.push(h('fieldset', null, h('legend', null, r.label), picks));
					continue;
				}
				const options = (r.required ? [] : [h('option', { value: '' }, '— none —')]).concat(cols.map((c) => h('option', { value: c, selected: state.map[r.key] === c }, c)));
				out.push(h('label', null, r.label, h('select', { 'aria-label': r.label, onchange: (e) => { if (e.target.value) state.map[r.key] = e.target.value; else delete state.map[r.key]; refresh(); } }, options)));
			}
			const text = (label, key) => h('label', null, label, h('input', { type: 'text', value: state.opts[key] ?? '', 'aria-label': label, oninput: (e) => { state.opts[key] = e.target.value; refresh(true); } }));
			out.push(text('Chart title', 'title'));
			const row = h('div', { class: 'row' });
			const checks = [];
			for (const id of t.options) {
				const o = C.OPTIONS[id];
				if (!o) continue;
				const key = o.key || id; // some options share a setting (the stacking-safe "combine rows by")
				const value = optValue(key);
				if (o.kind === 'select') row.append(h('label', null, o.label, o.hint ? h('small', null, o.hint) : null, h('select', { 'aria-label': o.label, onchange: (e) => { state.opts[key] = e.target.value; refresh(); } }, o.choices.map(([v, l]) => h('option', { value: v, selected: String(value) === String(v) }, l)))));
				else if (o.kind === 'number') row.append(h('label', null, o.label, h('input', { type: 'number', value: value ?? '', min: o.min, max: o.max, 'aria-label': o.label, oninput: (e) => { state.opts[key] = e.target.value === '' ? undefined : Number(e.target.value); refresh(true); } })));
				else if (o.kind === 'text') row.append(h('label', null, o.label, h('input', { type: 'text', value: value ?? '', 'aria-label': o.label, oninput: (e) => { state.opts[key] = e.target.value; refresh(true); } })));
				else checks.push(h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: !!value, onchange: (e) => { state.opts[key] = e.target.checked; refresh(); } }), o.label));
			}
			out.push(row);
			if (!NO_AXIS_TITLES.has(t.id)) out.push(h('div', { class: 'row' }, text('X axis title', 'xTitle'), text('Y axis title', 'yTitle')));
			out.push(...checks);
			return out;
		}

		/* step 4: insert */
		function insertStep() {
			const warnings = [];
			let code = '', problem = '';
			try { code = C.codeFor(host.format, current(warnings), currentOpts().title, snapshot()); } catch (e) { problem = e.message; }
			const copy = h('button', { type: 'button', class: 'btn', onclick: async () => { try { await navigator.clipboard.writeText(code); copy.textContent = 'Copied'; } catch { copy.textContent = 'Copy failed'; } } }, 'Copy');
			const rows = state.table.rows.length;
			return [
				h('h3', null, editing ? 'Ready to update' : 'Ready to insert'),
				handEdited(),
				h('p', { class: 'hint' }, editing ? 'This replaces the chart you opened, in place.' : host.format === 'deck-element'
					? 'This <deck-chart-vega> goes in at the cursor. It is interactive on the slide.'
					: 'This chart block goes in at the cursor. The same block works in md-doc documents and in Markdown slides.'),
				problem ? h('p', { class: 'cw-note error' }, problem) : h('pre', { class: 'cw-code', tabindex: '0' }, code),
				warnings.length ? h('p', { class: 'cw-note warn' }, warnings.join(' ')) : null,
				rows > 150 ? h('p', { class: 'cw-note' }, `${rows} rows of data are inlined. For large data, keep a CSV beside the document instead.`) : null,
				h('div', { class: 'cw-tools' }, copy),
			];
		}

		/* shell */
		const handEdited = () => (editing && editing.edited
			? h('p', { class: 'cw-note warn' }, 'This block was changed by hand after the wizard wrote it. Updating it rebuilds the chart from the settings below and replaces those changes.')
			: null);
		const lowest = editing ? 1 : 0; // the chart type is fixed while editing a chart
		function go(to) { state.step = Math.max(lowest, Math.min(STEPS.length - 1, to)); render(); }

		function render() {
			const main = h('div', { class: 'cw-main' });
			const box = h('div', { class: 'cw-chart', role: 'img', 'aria-label': 'Chart preview' });
			const note = h('p', { class: 'cw-note', 'aria-live': 'polite' });
			const refresh = (quiet) => { clearTimeout(timer); timer = setTimeout(() => preview(box, note), quiet ? 250 : 80); };
			const showPreview = state.step > 0;
			const body = h('div', { class: 'cw-body' }, main, showPreview ? h('aside', { class: 'cw-preview', 'aria-label': 'Preview' }, box, note) : null);
			const steps = h('ol', { class: 'cw-steps' }, STEPS.map((s, i) => h('li', { class: i < state.step ? 'done' : '', 'aria-current': i === state.step ? 'step' : null }, editing && i === 0 ? `${i + 1}. ${chart().label}` : `${i + 1}. ${s}`)));
			const head = h('div', { class: 'cw-head' }, h('h2', null, editing ? `Edit ${chart().label.toLowerCase()}` : 'Insert a chart'), steps, h('button', { type: 'button', class: 'btn', onclick: () => dialog.close(), 'aria-label': 'Close' }, '✕'));
			const last = state.step === STEPS.length - 1;
			const foot = h('div', { class: 'cw-foot' },
				h('button', { type: 'button', class: 'btn', disabled: state.step <= lowest, onclick: () => go(state.step - 1) }, 'Back'),
				h('span', { class: 'grow' }),
				h('button', { type: 'button', class: 'btn', onclick: () => dialog.close() }, 'Cancel'),
				last
					? h('button', { type: 'button', class: 'btn primary', onclick: () => { try { host.onInsert(codeNow()); dialog.close(); } catch (e) { note.textContent = e.message; } } }, editing ? 'Update chart' : 'Insert at cursor')
					: state.step === 0 ? null : h('button', { type: 'button', class: 'btn primary', onclick: () => go(state.step + 1) }, 'Next'));
			dialog.replaceChildren(head, body, foot);
			main.append(...[state.step === 1 ? handEdited() : null, ...[typeStep, dataStep, designStep, insertStep][state.step](refresh)].filter(Boolean));
			if (showPreview) refresh();
		}

		dialog.addEventListener('close', () => { clearTimeout(timer); observer?.disconnect(); dialog.remove(); host.onClose?.(); });
		render();
		dialog.showModal();
		return dialog;
	}

	/**
	 * Edit the chart block under the cursor. The host also supplies
	 *   getSource():              { text, offset }  the whole document and the cursor position in it
	 *   replaceRange(start, end, code)              swap that part of the document for the new block
	 *   notify(message)                             say why there is nothing to edit
	 * Only a block the wizard wrote can be reopened, and only as its own chart type.
	 */
	async function edit(host) {
		const C = await ensureCatalog(host.scriptBase || '.');
		const { text, offset } = host.getSource();
		const block = C.findBlock(text, offset, host.format);
		if (!block) return host.notify('Put the cursor inside a chart block to edit it.');
		const read = C.readBlock(block.text, host.format);
		if (read.error) return host.notify(read.error);
		return open({ ...host, editing: read, onInsert: (code) => host.replaceRange(block.start, block.end, code) });
	}

	root.ChartWizard = { open, edit, FILES: [...FILES, ...LATE], ensureCatalog };
})(typeof window !== 'undefined' ? window : globalThis);
