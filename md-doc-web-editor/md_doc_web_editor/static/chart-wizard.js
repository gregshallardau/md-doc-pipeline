/*
 * Chart wizard - a step-by-step Vega-Lite chart builder, shared by both studios.
 *
 * CANONICAL COPY: presentation-framework/editor/static/chart-wizard.js.
 * md-doc-pipeline's md-doc-web-editor/md_doc_web_editor/static/chart-wizard.js is a
 * byte-identical copy (a test in each repo checks the same SHA-256), so change both
 * together. The wizard knows nothing about either studio; each passes a small host
 * object to ChartWizard.open():
 *
 *   ChartWizard.open({
 *     format: 'yaml-fence' | 'deck-element',  // what to insert (see codeFor)
 *     vendorBase: '/path/to/dir',             // holds vega.min.js, vega-lite.min.js, vega-embed.min.js
 *     getConfig: async () => vegaConfig,      // theme config for the preview (optional)
 *     onInsert: (code) => {},                 // put the text at the cursor
 *   });
 *
 * Output is the spec md-doc-pipeline renders in documents (a ```chart block) and the
 * presentation framework renders on slides (<deck-chart-vega>), so a chart built
 * here is the same chart in both. Pure helpers are exposed for tests.
 */
(function (root) {
	'use strict';

	/* ── Data: parsing and type inference ───────────────────────────────── */

	/** Split pasted CSV / TSV / semicolon text into rows of fields (quotes supported). */
	function splitDelimited(text) {
		text = String(text).replace(/\r\n?/g, '\n').replace(/^﻿/, '').replace(/\n+$/, '');
		if (!text.trim()) return [];
		const first = text.split('\n', 1)[0];
		const count = (ch) => first.split(ch).length - 1;
		const delimiter = [['\t', count('\t')], [';', count(';')], [',', count(',')]].sort((a, b) => b[1] - a[1])[0];
		const sep = delimiter[1] ? delimiter[0] : ',';
		const rows = [];
		let row = [], field = '', quoted = false;
		for (let i = 0; i < text.length; i++) {
			const ch = text[i];
			if (quoted) {
				if (ch === '"' && text[i + 1] === '"') { field += '"'; i++; }
				else if (ch === '"') quoted = false;
				else field += ch;
			} else if (ch === '"' && field === '') quoted = true;
			else if (ch === sep) { row.push(field); field = ''; }
			else if (ch === '\n') { row.push(field); rows.push(row); row = []; field = ''; }
			else field += ch;
		}
		row.push(field);
		rows.push(row);
		return rows;
	}

	/** Pasted text -> { columns, rows }; the first line is the header. Names are made unique. */
	function parseTable(text) {
		const grid = splitDelimited(text);
		if (!grid.length) return { columns: [], rows: [] };
		const seen = new Map();
		const columns = grid[0].map((name, i) => {
			let base = String(name).trim() || `column${i + 1}`;
			const n = seen.get(base) || 0;
			seen.set(base, n + 1);
			return n ? `${base}_${n + 1}` : base;
		});
		const rows = grid.slice(1).filter((r) => r.some((c) => String(c).trim() !== ''))
			.map((r) => columns.map((_, i) => String(r[i] ?? '').trim()));
		return { columns, rows };
	}

	const DATE_RE = /^\d{4}-\d{2}(-\d{2})?([T ]\d{2}:\d{2}.*)?$/;
	const isNumber = (v) => v !== '' && /^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(String(v).trim());

	/** 'quantitative' | 'temporal' | 'nominal' from a column's cell values. */
	function inferType(values) {
		const filled = values.map((v) => String(v ?? '').trim()).filter((v) => v !== '');
		if (!filled.length) return 'nominal';
		if (filled.every(isNumber)) return 'quantitative';
		if (filled.every((v) => DATE_RE.test(v))) return 'temporal';
		return 'nominal';
	}

	/** Table + per-column types -> array of objects with numbers as numbers. */
	function toRecords(table, types) {
		return table.rows.map((r) => {
			const rec = {};
			table.columns.forEach((name, i) => {
				const v = r[i];
				rec[name] = types[name] === 'quantitative' ? (v === '' ? null : Number(v)) : v === '' ? null : v;
			});
			return rec;
		});
	}

	/* ── Chart types: what each needs and how it becomes a Vega-Lite spec ── */

	const AGGREGATES = ['none', 'sum', 'mean', 'median', 'min', 'max', 'count'];

	const q = (field, extra) => ({ field, type: 'quantitative', ...extra });

	/** X axis type for a column, honouring the "X axis is" override. */
	function axisKind(s, col, fallbackNumberIsCategory) {
		const choice = s.opts.xKind;
		if (choice === 'category') return 'ordinal';
		if (choice === 'number') return 'quantitative';
		if (choice === 'date') return 'temporal';
		const t = s.types[col];
		if (t === 'temporal') return 'temporal';
		if (t === 'quantitative') return fallbackNumberIsCategory ? 'ordinal' : 'quantitative';
		return 'ordinal';
	}

	function sortFor(s, kind) {
		if (kind !== 'ordinal') return {};
		const o = s.opts.sort;
		return { sort: o === 'asc' ? 'x' : o === 'desc' ? '-x' : o === 'value' ? '-y' : null };
	}

	function colorEnc(s, continuous) {
		const f = s.map.color;
		if (!f) return {};
		const t = continuous && s.types[f] === 'quantitative' ? 'quantitative' : 'nominal';
		return { color: { field: f, type: t, ...(s.opts.legend === false ? { legend: null } : {}) } };
	}

	const agg = (s) => (s.opts.agg && s.opts.agg !== 'none' ? { aggregate: s.opts.agg } : {});
	const yValue = (s, extra) => (s.opts.agg === 'count' ? { aggregate: 'count', type: 'quantitative', ...extra } : q(s.map.y, { ...agg(s), ...extra }));
	const axisTitle = (title) => (title ? { axis: { title } } : {});

	function wrap(s, mark, encoding, extra) {
		const spec = { data: { values: s.records }, mark, encoding, ...extra };
		if (s.opts.title) spec.title = s.opts.title;
		return spec;
	}

	function barSpec(s, horizontal) {
		const kind = axisKind(s, s.map.x, true);
		const cat = { field: s.map.x, type: kind, ...sortFor(s, kind), ...axisTitle(s.opts.xTitle) };
		const val = yValue(s, axisTitle(s.opts.yTitle));
		const enc = horizontal ? { y: { ...cat, ...(cat.sort !== undefined ? { sort: cat.sort === 'x' ? 'y' : cat.sort === '-x' ? '-y' : cat.sort === '-y' ? '-x' : null } : {}) }, x: val } : { x: cat, y: val };
		Object.assign(enc, colorEnc(s, false));
		if (s.map.color && s.opts.stack === 'grouped') enc[horizontal ? 'yOffset' : 'xOffset'] = { field: s.map.color };
		return wrap(s, { type: 'bar', cornerRadiusEnd: 2 }, enc);
	}

	function lineSpec(s, area) {
		const kind = axisKind(s, s.map.x, false);
		const mark = area
			? { type: 'area', opacity: 0.85, line: true, interpolate: s.opts.smooth ? 'monotone' : 'linear' }
			: { type: 'line', point: !!s.opts.points, interpolate: s.opts.smooth ? 'monotone' : 'linear' };
		const y = yValue(s, { ...axisTitle(s.opts.yTitle), ...(area && s.map.color && s.opts.stack === 'percent' ? { stack: 'normalize' } : {}) });
		return wrap(s, mark, {
			x: { field: s.map.x, type: kind, ...(kind === 'ordinal' ? { sort: null } : {}), ...axisTitle(s.opts.xTitle) }, // keep the data's own order
			y,
			...colorEnc(s, false),
		});
	}

	function scatterSpec(s) {
		const enc = {
			x: q(s.map.x, { scale: { zero: false }, ...axisTitle(s.opts.xTitle) }),
			y: q(s.map.y, { scale: { zero: false }, ...axisTitle(s.opts.yTitle) }),
			...colorEnc(s, true),
		};
		if (s.map.size) enc.size = q(s.map.size);
		return wrap(s, { type: 'point', filled: true, opacity: 0.8 }, enc);
	}

	function arcSpec(s, donut) {
		const enc = {
			theta: yValue(s, { stack: true }),
			color: { field: s.map.x, type: 'nominal', ...(s.opts.legend === false ? { legend: null } : {}) },
		};
		return wrap(s, { type: 'arc', innerRadius: donut ? 60 : 0 }, enc, { view: { stroke: null } });
	}

	function heatmapSpec(s) {
		return wrap(s, 'rect', {
			x: { field: s.map.x, type: 'ordinal', sort: null, ...axisTitle(s.opts.xTitle) },
			y: { field: s.map.y, type: 'ordinal', sort: null, ...axisTitle(s.opts.yTitle) },
			color: q(s.map.value, { ...agg(s), ...(s.opts.legend === false ? { legend: null } : {}) }),
		});
	}

	function histogramSpec(s) {
		return wrap(s, { type: 'bar', cornerRadiusEnd: 2 }, {
			x: q(s.map.x, { bin: true, ...axisTitle(s.opts.xTitle) }),
			y: { aggregate: 'count', type: 'quantitative', ...axisTitle(s.opts.yTitle || 'Count') },
		});
	}

	const role = (key, label, kind, required = true) => ({ key, label, kind, required });
	const X_CAT = role('x', 'Category (X axis)', 'any');
	const Y_VAL = role('y', 'Value (Y axis)', 'number');
	const GROUP = role('color', 'Group by (optional)', 'any', false);

	/** `options` names the controls shown on the Customize step. */
	const CHART_TYPES = [
		{ id: 'bar', label: 'Bar', desc: 'Compare values across categories', roles: [X_CAT, Y_VAL, GROUP], options: ['agg', 'sort', 'stack', 'legend'], build: (s) => barSpec(s, false), sample: 'categories' },
		{ id: 'hbar', label: 'Horizontal bar', desc: 'Long labels or rankings', roles: [X_CAT, Y_VAL, GROUP], options: ['agg', 'sort', 'stack', 'legend'], build: (s) => barSpec(s, true), sample: 'categories' },
		{ id: 'line', label: 'Line', desc: 'Change over time or order', roles: [role('x', 'X axis (time or order)', 'any'), Y_VAL, role('color', 'Series (optional)', 'any', false)], options: ['agg', 'xKind', 'points', 'smooth', 'legend'], build: (s) => lineSpec(s, false), sample: 'series', sampleColor: 'Region' },
		{ id: 'area', label: 'Area', desc: 'Volume over time, stacked or percent', roles: [role('x', 'X axis (time or order)', 'any'), Y_VAL, role('color', 'Series (optional)', 'any', false)], options: ['agg', 'xKind', 'smooth', 'stackArea', 'legend'], build: (s) => lineSpec(s, true), sample: 'series', sampleColor: 'Region' },
		{ id: 'scatter', label: 'Scatter', desc: 'Relationship between two numbers', roles: [role('x', 'X (number)', 'number'), role('y', 'Y (number)', 'number'), role('color', 'Colour by (optional)', 'any', false), role('size', 'Size by (optional)', 'number', false)], options: ['legend'], build: scatterSpec, sample: 'points', sampleColor: 'Group' },
		{ id: 'pie', label: 'Pie', desc: 'Share of a whole (few slices)', roles: [role('x', 'Slice label', 'any'), role('y', 'Slice size', 'number')], options: ['agg', 'legend'], build: (s) => arcSpec(s, false), sample: 'categories' },
		{ id: 'donut', label: 'Donut', desc: 'Share of a whole, with a centre', roles: [role('x', 'Slice label', 'any'), role('y', 'Slice size', 'number')], options: ['agg', 'legend'], build: (s) => arcSpec(s, true), sample: 'categories' },
		{ id: 'heatmap', label: 'Heatmap', desc: 'Intensity across two categories', roles: [role('x', 'Columns', 'any'), role('y', 'Rows', 'any'), role('value', 'Value (colour)', 'number')], options: ['agg', 'legend'], build: heatmapSpec, sample: 'grid' },
		{ id: 'histogram', label: 'Histogram', desc: 'How a number is distributed', roles: [role('x', 'Values to count', 'number')], options: [], build: histogramSpec, sample: 'distribution' },
	];

	const SAMPLES = {
		categories: 'Region,Revenue\nNorth,42\nSouth,31\nEast,17\nWest,10',
		series: 'Month,Revenue,Region\nJan,12,North\nFeb,19,North\nMar,14,North\nApr,23,North\nJan,8,South\nFeb,15,South\nMar,21,South\nApr,18,South',
		points: 'Height,Weight,Group\n150,52,A\n160,58,A\n165,63,B\n172,70,B\n180,82,A\n185,88,B\n158,55,A\n170,68,B',
		grid: 'Day,Hour,Visits\nMon,9am,12\nMon,12pm,30\nMon,3pm,22\nTue,9am,15\nTue,12pm,35\nTue,3pm,18\nWed,9am,9\nWed,12pm,28\nWed,3pm,25',
		distribution: 'Score\n52\n58\n61\n64\n66\n67\n68\n70\n71\n71\n72\n74\n75\n77\n78\n80\n83\n85\n91',
	};

	const chartType = (id) => CHART_TYPES.find((c) => c.id === id) || CHART_TYPES[0];

	/** Pick sensible columns for a chart's roles, keeping earlier choices that still fit. */
	function autoMap(chart, table, types, previous) {
		const map = {};
		const used = new Set();
		const cols = table.columns;
		const fits = (col, kind) => kind === 'any' || (kind === 'number' ? types[col] === 'quantitative' : true);
		for (const r of chart.roles) {
			let pick = previous && previous[r.key] && cols.includes(previous[r.key]) && fits(previous[r.key], r.kind) ? previous[r.key] : null;
			if (!pick && r.required) {
				const candidates = cols.filter((c) => !used.has(c) && fits(c, r.kind));
				pick = (r.kind === 'any' ? candidates.find((c) => types[c] !== 'quantitative') : null) || candidates[0] || null;
			}
			if (pick) { map[r.key] = pick; used.add(pick); }
		}
		return map;
	}

	/** { type, table, types, map, opts } -> Vega-Lite spec, or throws a readable error. */
	function buildSpec(state) {
		const chart = chartType(state.type);
		for (const r of chart.roles) {
			if (r.required && !state.map[r.key]) throw new Error(`Choose a column for “${r.label}”.`);
		}
		if (!state.table.rows.length) throw new Error('Add at least one row of data.');
		const s = { ...state, records: toRecords(state.table, state.types), opts: state.opts || {} };
		return chart.build(s);
	}

	/* ── Output: YAML for fences, JSON for slide elements ───────────────── */

	const PLAIN = /^[A-Za-z_][\w .\-\/]*$/;
	const RESERVED = /^(true|false|yes|no|on|off|null|y|n|~)$/i;

	function scalar(v) {
		if (v === null || v === undefined) return 'null';
		if (typeof v === 'number') return Number.isFinite(v) ? String(v) : 'null';
		if (typeof v === 'boolean') return String(v);
		const s = String(v);
		return PLAIN.test(s) && s.trim() === s && !RESERVED.test(s) && !isNumber(s) ? s : JSON.stringify(s);
	}

	function flow(v) {
		if (Array.isArray(v)) return `[${v.map(flow).join(', ')}]`;
		if (v && typeof v === 'object') return `{${Object.entries(v).map(([k, x]) => `${scalar(k)}: ${flow(x)}`).join(', ')}}`;
		return scalar(v);
	}

	const small = (v) => flow(v).length <= 70;

	/** Compact, readable YAML (a JSON superset parser reads it back identically). */
	function toYaml(value, indent = 0, path = '') {
		const pad = ' '.repeat(indent);
		const lines = [];
		if (Array.isArray(value)) {
			for (const item of value) {
				if (item && typeof item === 'object' && (path === 'data.values' || small(item))) lines.push(`${pad}- ${flow(item)}`);
				else if (item && typeof item === 'object') lines.push(`${pad}-`, toYaml(item, indent + 2, path));
				else lines.push(`${pad}- ${scalar(item)}`);
			}
		} else {
			for (const [k, v] of Object.entries(value)) {
				const key = scalar(k);
				const here = path ? `${path}.${k}` : k;
				if (v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length && !small(v)) lines.push(`${pad}${key}:`, toYaml(v, indent + 2, here));
				else if (Array.isArray(v) && v.length && here === 'data.values') lines.push(`${pad}${key}:`, toYaml(v, indent + 2, here));
				else if (Array.isArray(v) && v.length && !small(v)) lines.push(`${pad}${key}:`, toYaml(v, indent + 2, here));
				else lines.push(`${pad}${key}: ${flow(v)}`);
			}
		}
		return lines.join('\n');
	}

	/**
	 * The text to insert.
	 *   yaml-fence    a ```chart block (md-doc documents and deck .md slides)
	 *   deck-element  <deck-chart-vega> with a JSON script (deck .html slides)
	 */
	function codeFor(format, spec, label) {
		if (format === 'deck-element') {
			const json = JSON.stringify(spec, null, '\t').replace(/<\//g, '<\\/').replace(/\n/g, '\n\t\t');
			const attr = label ? ` label="${String(label).replace(/&/g, '&amp;').replace(/"/g, '&quot;')}"` : '';
			return `<deck-chart-vega${attr}>\n\t<script type="application/json">\n\t\t${json}\n\t</script>\n</deck-chart-vega>\n`;
		}
		return '```chart\n' + toYaml(spec) + '\n```\n';
	}

	/* ── Icons (one tiny glyph per chart type) ──────────────────────────── */

	const ICONS = {
		bar: '<rect x="4" y="14" width="5" height="10"/><rect x="12" y="8" width="5" height="16"/><rect x="20" y="4" width="5" height="20"/>',
		hbar: '<rect x="4" y="4" width="10" height="5"/><rect x="4" y="12" width="16" height="5"/><rect x="4" y="20" width="22" height="5"/>',
		line: '<polyline fill="none" stroke-width="2.5" points="3,22 10,13 17,17 26,5"/>',
		area: '<polygon points="3,24 3,16 10,10 17,14 26,4 26,24" opacity=".75"/>',
		scatter: '<circle cx="7" cy="20" r="2.6"/><circle cx="13" cy="12" r="2.6"/><circle cx="19" cy="17" r="2.6"/><circle cx="24" cy="6" r="2.6"/>',
		pie: '<path d="M14 14V3a11 11 0 1 1-9.5 16.5z"/><path d="M14 14 4.5 19.5A11 11 0 0 1 14 3z" opacity=".5"/>',
		donut: '<path fill-rule="evenodd" d="M14 3a11 11 0 1 1 0 22 11 11 0 0 1 0-22zm0 6a5 5 0 1 0 0 10 5 5 0 0 0 0-10z"/>',
		heatmap: '<rect x="3" y="3" width="7" height="7" opacity=".3"/><rect x="11" y="3" width="7" height="7"/><rect x="19" y="3" width="7" height="7" opacity=".6"/><rect x="3" y="11" width="7" height="7" opacity=".8"/><rect x="11" y="11" width="7" height="7" opacity=".4"/><rect x="19" y="11" width="7" height="7"/>',
		histogram: '<rect x="3" y="16" width="5" height="8"/><rect x="9" y="8" width="5" height="16"/><rect x="15" y="4" width="5" height="20"/><rect x="21" y="14" width="5" height="10"/>',
	};

	/* ── UI ─────────────────────────────────────────────────────────────── */

	const STEPS = ['Type', 'Data', 'Customize', 'Insert'];
	let styleNode = null;
	const loading = {};

	const CSS = `
.cw { width: min(1040px, 96vw); max-height: 92vh; padding: 0; border: 1px solid color-mix(in srgb, CanvasText 25%, transparent); border-radius: 12px; background: Canvas; color: CanvasText; font: 14px/1.45 system-ui, sans-serif; }
.cw::backdrop { background: rgba(0,0,0,.45); }
.cw * { box-sizing: border-box; }
.cw[open] { display: flex; flex-direction: column; }
.cw-head { display: flex; align-items: center; gap: 16px; padding: 12px 18px; border-bottom: 1px solid color-mix(in srgb, CanvasText 15%, transparent); }
.cw-head h2 { margin: 0; font-size: 16px; }
.cw-steps { display: flex; gap: 6px; margin: 0 auto 0 8px; padding: 0; list-style: none; }
.cw-steps li { padding: 3px 10px; border-radius: 99px; color: GrayText; font-size: 12.5px; }
.cw-steps li[aria-current="step"] { background: var(--cw-accent, #2563eb); color: #fff; }
.cw-steps li.done { color: CanvasText; }
.cw-body { display: flex; gap: 18px; padding: 16px 18px; overflow: auto; min-height: 380px; flex: 1; }
.cw-main { flex: 1 1 52%; min-width: 0; }
.cw-preview { flex: 1 1 44%; min-width: 0; display: flex; flex-direction: column; gap: 8px; }
.cw-chart { border: 1px solid color-mix(in srgb, CanvasText 15%, transparent); border-radius: 8px; padding: 10px; min-height: 280px; display: grid; place-items: center; background: #fff; color: #1f2328; overflow: auto; }
.cw-note { margin: 0; color: GrayText; font-size: 12.5px; min-height: 1.4em; }
.cw-note.error { color: #d03b3b; }
.cw-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.cw-card { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; padding: 12px; border: 1px solid color-mix(in srgb, CanvasText 20%, transparent); border-radius: 10px; background: transparent; color: inherit; text-align: left; cursor: pointer; font: inherit; }
.cw-card:hover { border-color: var(--cw-accent, #2563eb); }
.cw-card[aria-pressed="true"] { border-color: var(--cw-accent, #2563eb); box-shadow: 0 0 0 2px color-mix(in srgb, var(--cw-accent, #2563eb) 35%, transparent); }
.cw-card svg { width: 34px; height: 34px; fill: var(--cw-accent, #2563eb); stroke: var(--cw-accent, #2563eb); }
.cw-card b { font-weight: 600; }
.cw-card span { color: GrayText; font-size: 12.5px; }
.cw label { display: block; margin: 0 0 10px; font-weight: 500; }
.cw label small { display: block; font-weight: 400; color: GrayText; }
.cw select, .cw input[type="text"], .cw textarea { width: 100%; padding: 6px 8px; border: 1px solid color-mix(in srgb, CanvasText 30%, transparent); border-radius: 6px; background: Field; color: FieldText; font: inherit; }
.cw textarea { min-height: 76px; font: 12.5px ui-monospace, monospace; }
.cw .row { display: flex; gap: 10px; flex-wrap: wrap; }
.cw .row > * { flex: 1 1 180px; }
.cw .check { display: flex; gap: 8px; align-items: center; font-weight: 400; }
.cw .check input { width: auto; }
.cw-grid-wrap { overflow: auto; max-height: 250px; border: 1px solid color-mix(in srgb, CanvasText 20%, transparent); border-radius: 6px; margin: 8px 0; }
.cw-grid { border-collapse: collapse; width: 100%; font-size: 13px; }
.cw-grid th, .cw-grid td { border: 1px solid color-mix(in srgb, CanvasText 12%, transparent); padding: 0; }
.cw-grid input { width: 100%; min-width: 64px; border: 0; padding: 4px 6px; background: transparent; color: inherit; font: inherit; }
.cw-grid th input { font-weight: 600; }
.cw-grid th select { width: 100%; border: 0; border-top: 1px solid color-mix(in srgb, CanvasText 12%, transparent); border-radius: 0; font-size: 11.5px; color: GrayText; }
.cw-grid .gutter { width: 28px; text-align: center; color: GrayText; background: color-mix(in srgb, CanvasText 5%, transparent); }
.cw-tools { display: flex; gap: 8px; flex-wrap: wrap; }
.cw button.btn { padding: 6px 12px; border: 1px solid color-mix(in srgb, CanvasText 30%, transparent); border-radius: 6px; background: transparent; color: inherit; font: inherit; cursor: pointer; }
.cw button.btn.primary { background: var(--cw-accent, #2563eb); border-color: var(--cw-accent, #2563eb); color: #fff; }
.cw button.btn:disabled { opacity: .45; cursor: default; }
.cw-foot { display: flex; gap: 8px; align-items: center; padding: 12px 18px; border-top: 1px solid color-mix(in srgb, CanvasText 15%, transparent); }
.cw-foot .grow { flex: 1; }
.cw-code { margin: 0; padding: 10px; max-height: 300px; overflow: auto; border-radius: 6px; background: color-mix(in srgb, CanvasText 7%, transparent); font: 12px/1.45 ui-monospace, monospace; white-space: pre; }
.cw h3 { margin: 0 0 8px; font-size: 14px; }
.cw p.hint { margin: 0 0 10px; color: GrayText; font-size: 13px; }
`;

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
		for (const kid of kids.flat()) if (kid !== null && kid !== undefined) node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
		return node;
	}

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

	function isDark() {
		for (const el of [document.body, document.documentElement]) {
			const m = (getComputedStyle(el).backgroundColor || '').match(/[\d.]+/g);
			if (m && (m.length < 4 || +m[3] > 0)) return (0.2126 * +m[0] + 0.7152 * +m[1] + 0.0722 * +m[2]) / 255 < 0.45;
		}
		return false;
	}

	function open(host) {
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
			map: {},
			opts: { agg: 'none', sort: 'data', stack: 'stacked', legend: true, points: true, smooth: false, xKind: 'auto' },
			config: null,
		};
		const dialog = h('dialog', { class: 'cw', 'aria-label': 'Insert a chart' });
		dialog.style.colorScheme = isDark() ? 'dark' : 'light';
		const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
		if (accent) dialog.style.setProperty('--cw-accent', accent);
		document.body.append(dialog);
		let timer = null;

		const setTable = (table) => {
			state.table = table;
			state.types = {};
			for (const [i, c] of table.columns.entries()) state.types[c] = inferType(table.rows.map((r) => r[i]));
			state.map = autoMap(chartType(state.type), table, state.types, state.map);
		};
		const loadSample = () => {
			const chart = chartType(state.type);
			setTable(parseTable(SAMPLES[chart.sample]));
			if (chart.sampleColor && state.table.columns.includes(chart.sampleColor)) state.map.color = chart.sampleColor;
		};
		loadSample();

		function currentSpec() {
			return buildSpec({ ...state, opts: state.opts });
		}

		let previewToken = 0;
		async function preview(box, note) {
			const token = ++previewToken;
			let spec;
			try {
				spec = currentSpec();
			} catch (e) {
				box.replaceChildren(h('span', { class: 'cw-note' }, 'Preview appears once the data and columns are set.'));
				note.textContent = e.message;
				note.className = 'cw-note error';
				return;
			}
			note.className = 'cw-note';
			note.textContent = 'Close to the final look; the built chart uses your theme\u2019s colours and fonts.';
			try {
				const embed = await loadVega(host.vendorBase);
				if (state.config === null) state.config = host.getConfig ? (await host.getConfig()) || {} : {};
				if (token !== previewToken) return;
				box.replaceChildren();
				await embed(box, { ...spec, width: 420, height: 250, autosize: { type: 'fit', contains: 'padding' } }, { actions: false, renderer: 'svg', config: state.config });
			} catch (e) {
				note.textContent = `Preview failed: ${e.message}`;
				note.className = 'cw-note error';
			}
		}

		/* step 1 */
		function typeStep() {
			const grid = h('div', { class: 'cw-cards', role: 'group', 'aria-label': 'Chart type' });
			for (const c of CHART_TYPES) {
				const card = h('button', { type: 'button', class: 'cw-card', 'aria-pressed': String(c.id === state.type),
					onclick: () => { const same = c.id === state.type; state.type = c.id; if (!same) { state.map = {}; if (!state.touched) loadSample(); else state.map = autoMap(c, state.table, state.types, {}); } go(1); },
				},
				h('span', { html: `<svg viewBox="0 0 28 28" aria-hidden="true">${ICONS[c.id]}</svg>` }), h('b', null, c.label), h('span', null, c.desc));
				grid.append(card);
			}
			return [h('h3', null, 'What kind of chart?'), h('p', { class: 'hint' }, 'Pick one — you can come back and change it.'), grid];
		}

		/* step 2 */
		function dataStep(refresh) {
			const paste = h('textarea', { placeholder: 'Paste from a spreadsheet or CSV (first row = column names)…', 'aria-label': 'Paste data', 'spellcheck': 'false' });
			const wrap = h('div', { class: 'cw-grid-wrap' });
			const draw = () => {
				const { columns, rows } = state.table;
				const head = h('tr', null, h('th', { class: 'gutter' }), columns.map((c, i) => h('th', null,
					h('input', { value: c, 'aria-label': `Column ${i + 1} name`, onchange: (e) => renameColumn(i, e.target.value.trim() || c) }),
					h('select', { 'aria-label': `${c} type`, onchange: (e) => { state.types[c] = e.target.value; (state.userTyped ??= {})[c] = true; refresh(); draw(); } },
						[['nominal', 'Text'], ['quantitative', 'Number'], ['temporal', 'Date']].map(([v, l]) => h('option', { value: v, selected: state.types[c] === v }, l))))));
				const body = rows.map((r, ri) => h('tr', null,
					h('td', { class: 'gutter', title: 'Remove row', onclick: () => { rows.splice(ri, 1); retype(); draw(); refresh(); } }, '×'),
					columns.map((c, ci) => h('td', null, h('input', { value: r[ci], 'aria-label': `${c}, row ${ri + 1}`, onchange: (e) => { r[ci] = e.target.value.trim(); retype(); refresh(); } })))));
				wrap.replaceChildren(h('table', { class: 'cw-grid' }, head, body));
			};
			const retype = () => {
				for (const [i, c] of state.table.columns.entries()) if (!state.userTyped?.[c]) state.types[c] = inferType(state.table.rows.map((r) => r[i]));
				state.map = autoMap(chartType(state.type), state.table, state.types, state.map);
			};
			const renameColumn = (i, name) => {
				const old = state.table.columns[i];
				if (state.table.columns.includes(name) && name !== old) return draw();
				state.table.columns[i] = name;
				state.types[name] = state.types[old];
				delete state.types[old];
				if (state.userTyped?.[old]) { state.userTyped[name] = true; delete state.userTyped[old]; }
				for (const k of Object.keys(state.map)) if (state.map[k] === old) state.map[k] = name;
				draw(); refresh();
			};
			paste.addEventListener('input', () => {
				const t = parseTable(paste.value);
				if (t.columns.length) { state.touched = true; setTable(t); draw(); refresh(); }
			});
			draw();
			return [
				h('h3', null, 'Your data'),
				h('p', { class: 'hint' }, 'Edit the sample, or paste your own table. One row per data point; the first row names the columns.'),
				paste,
				wrap,
				h('div', { class: 'cw-tools' },
					h('button', { type: 'button', class: 'btn', onclick: () => { state.table.rows.push(state.table.columns.map(() => '')); draw(); } }, 'Add row'),
					h('button', { type: 'button', class: 'btn', onclick: () => { let n = state.table.columns.length + 1; while (state.table.columns.includes(`column${n}`)) n++; const name = `column${n}`; state.table.columns.push(name); state.table.rows.forEach((r) => r.push('')); state.types[name] = 'nominal'; draw(); refresh(); } }, 'Add column'),
					h('button', { type: 'button', class: 'btn', onclick: () => { state.touched = false; loadSample(); draw(); refresh(); } }, 'Reset to sample')),
			];
		}

		/* step 3 */
		function designStep(refresh) {
			const chart = chartType(state.type);
			const cols = state.table.columns;
			const out = [h('h3', null, `${chart.label} — columns and options`)];
			for (const r of chart.roles) {
				const options = (r.required ? [] : [h('option', { value: '' }, '— none —')]).concat(cols.map((c) => h('option', { value: c, selected: state.map[r.key] === c }, c)));
				out.push(h('label', null, r.label, h('select', { 'aria-label': r.label, onchange: (e) => { if (e.target.value) state.map[r.key] = e.target.value; else delete state.map[r.key]; refresh(); } }, options)));
			}
			const has = (k) => chart.options.includes(k);
			const select = (label, key, pairs, hint) => h('label', null, label, hint ? h('small', null, hint) : null, h('select', { 'aria-label': label, onchange: (e) => { state.opts[key] = e.target.value; refresh(); } }, pairs.map(([v, l]) => h('option', { value: v, selected: state.opts[key] === v }, l))));
			const check = (label, key) => h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: state.opts[key], onchange: (e) => { state.opts[key] = e.target.checked; refresh(); } }), label);
			const text = (label, key) => h('label', null, label, h('input', { type: 'text', value: state.opts[key] || '', 'aria-label': label, oninput: (e) => { state.opts[key] = e.target.value; refresh(true); } }));
			out.push(text('Chart title', 'title'));
			const row = h('div', { class: 'row' });
			if (has('agg')) row.append(select('Combine rows by', 'agg', AGGREGATES.map((a) => [a, a === 'none' ? 'Use each row as is' : a === 'count' ? 'Count of rows' : a[0].toUpperCase() + a.slice(1)]), 'Sum / average rows that share a category'));
			if (has('sort')) row.append(select('Sort categories', 'sort', [['data', 'As in the data'], ['asc', 'A → Z'], ['desc', 'Z → A'], ['value', 'Largest first']]));
			if (has('stack') && state.map.color) row.append(select('Groups appear', 'stack', [['stacked', 'Stacked'], ['grouped', 'Side by side']]));
			if (has('stackArea') && state.map.color) row.append(select('Series appear', 'stack', [['stacked', 'Stacked'], ['percent', 'As a percentage']]));
			if (has('xKind')) row.append(select('X axis is', 'xKind', [['auto', 'Detect'], ['category', 'Categories'], ['number', 'Numbers'], ['date', 'Dates']]));
			out.push(row);
			if (!['pie', 'donut', 'heatmap', 'histogram'].includes(chart.id)) out.push(h('div', { class: 'row' }, text('X axis title', 'xTitle'), text('Y axis title', 'yTitle')));
			if (has('points')) out.push(check('Show points', 'points'));
			if (has('smooth')) out.push(check('Smooth the line', 'smooth'));
			if (has('legend') && (state.map.color || ['pie', 'donut', 'heatmap'].includes(chart.id))) out.push(check('Show legend', 'legend'));
			return out;
		}

		/* step 4 */
		function insertStep() {
			let code = '', problem = '';
			try { code = codeFor(host.format, currentSpec(), state.opts.title); } catch (e) { problem = e.message; }
			const copy = h('button', { type: 'button', class: 'btn', onclick: async () => { try { await navigator.clipboard.writeText(code); copy.textContent = 'Copied'; } catch { copy.textContent = 'Copy failed'; } } }, 'Copy');
			const rows = state.table.rows.length;
			return [
				h('h3', null, 'Ready to insert'),
				h('p', { class: 'hint' }, host.format === 'deck-element'
					? 'This <deck-chart-vega> goes in at the cursor. It is interactive on the slide.'
					: 'This chart block goes in at the cursor. The same block works in md-doc documents and in Markdown slides.'),
				problem ? h('p', { class: 'cw-note error' }, problem) : h('pre', { class: 'cw-code', tabindex: '0' }, code),
				rows > 150 ? h('p', { class: 'cw-note' }, `${rows} rows of data are inlined. For large data, keep a CSV beside the document instead.`) : null,
				h('div', { class: 'cw-tools' }, copy),
			];
		}

		/* shell */
		function go(to) { state.step = Math.max(0, Math.min(STEPS.length - 1, to)); render(); }

		function render() {
			const main = h('div', { class: 'cw-main' });
			const box = h('div', { class: 'cw-chart', role: 'img', 'aria-label': 'Chart preview' });
			const note = h('p', { class: 'cw-note', 'aria-live': 'polite' });
			const refresh = (quiet) => { clearTimeout(timer); timer = setTimeout(() => preview(box, note), quiet ? 250 : 80); };
			const content = [typeStep, dataStep, designStep, insertStep][state.step](refresh);
			main.append(...content.filter(Boolean));
			const showPreview = state.step > 0;
			const body = h('div', { class: 'cw-body' }, main, showPreview ? h('aside', { class: 'cw-preview', 'aria-label': 'Preview' }, box, note) : null);
			const steps = h('ol', { class: 'cw-steps' }, STEPS.map((s, i) => h('li', { class: i < state.step ? 'done' : '', 'aria-current': i === state.step ? 'step' : null }, `${i + 1}. ${s}`)));
			const head = h('div', { class: 'cw-head' }, h('h2', null, 'Insert a chart'), steps, h('button', { type: 'button', class: 'btn', onclick: () => dialog.close(), 'aria-label': 'Close' }, '✕'));
			const last = state.step === STEPS.length - 1;
			const foot = h('div', { class: 'cw-foot' },
				h('button', { type: 'button', class: 'btn', disabled: state.step === 0, onclick: () => go(state.step - 1) }, 'Back'),
				h('span', { class: 'grow' }),
				h('button', { type: 'button', class: 'btn', onclick: () => dialog.close() }, 'Cancel'),
				last
					? h('button', { type: 'button', class: 'btn primary', onclick: () => { try { host.onInsert(codeFor(host.format, currentSpec(), state.opts.title)); dialog.close(); } catch (e) { note.textContent = e.message; } } }, 'Insert at cursor')
					: state.step === 0 ? null : h('button', { type: 'button', class: 'btn primary', onclick: () => go(state.step + 1) }, 'Next'));
			dialog.replaceChildren(head, body, foot);
			if (showPreview) refresh();
		}

		dialog.addEventListener('close', () => { clearTimeout(timer); dialog.remove(); host.onClose?.(); });
		render();
		dialog.showModal();
		return dialog;
	}

	const api = { open, parseTable, splitDelimited, inferType, toRecords, buildSpec, toYaml, codeFor, autoMap, CHART_TYPES, SAMPLES };
	root.ChartWizard = api;
})(typeof window !== 'undefined' ? window : globalThis);
