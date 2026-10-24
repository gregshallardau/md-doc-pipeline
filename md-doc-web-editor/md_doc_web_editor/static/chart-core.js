/*
 * Chart catalogue core - data parsing, the registries every chart type plugs into,
 * spec building, and the YAML / JSON emitters. Pure: no DOM.
 *
 * Shared by both studios (see chart-wizard.js). CANONICAL COPIES live in
 * presentation-framework/editor/static/; md-doc-pipeline's studio carries
 * byte-identical copies (a SHA-256 manifest is checked in both repos).
 *
 * A chart type registers itself:
 *
 *   ChartCatalog.type({
 *     id, group, label, desc,
 *     sample,                  // key into the samples (CSV text or a function returning it)
 *     roles: [{ key, label, kind, required, multi }],   // which columns the chart reads
 *     options: ['agg', ...],   // option ids (see ChartCatalog.option) shown on the Customize step
 *     defaults: { color: 'Region' },   // role -> column to preselect for the sample
 *     opts: { stack: 'grouped' },      // option defaults for this type
 *     build(s) { return spec }         // Vega-Lite or Vega spec
 *   });
 *
 * `s` handed to build(): { records, table, types, map, opts, f(role), has(role),
 * list(role), kind(col), warn(msg) }.
 */
(function (root) {
	'use strict';

	const C = (root.ChartCatalog = { TYPES: [], GROUPS: [], SAMPLES: {}, OPTIONS: {}, PALETTE_NOTE: 'colours come from the theme' });

	const VEGA_SCHEMA = 'https://vega.github.io/schema/vega/v6.json';
	C.VEGA_SCHEMA = VEGA_SCHEMA;

	/* ── Registries ─────────────────────────────────────────────────────── */

	C.group = (g) => { C.GROUPS.push(g); return g; };
	C.option = (id, def) => { C.OPTIONS[id] = { id, ...def }; };
	C.sample = (key, text) => { C.SAMPLES[key] = text; };
	C.type = (t) => { C.TYPES.push({ options: [], roles: [], defaults: {}, opts: {}, ...t }); return t; };
	C.chartType = (id) => C.TYPES.find((c) => c.id === id) || C.TYPES[0];
	C.sampleText = (key) => (typeof C.SAMPLES[key] === 'function' ? C.SAMPLES[key]() : C.SAMPLES[key]);

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
			const base = String(name).trim() || `column${i + 1}`;
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

	Object.assign(C, { splitDelimited, parseTable, inferType, toRecords, isNumber });

	/* ── Roles and column mapping ───────────────────────────────────────── */

	/** role kinds: any | time (an axis in time or order) | num | cat | date */
	const fits = (types, col, kind) =>
		kind === 'any' || kind === 'time' || (kind === 'num' ? types[col] === 'quantitative' : kind === 'date' ? types[col] === 'temporal' || types[col] === 'nominal' : types[col] !== 'quantitative');

	const TIME_NAME = /date|time|year|month|day|week|quarter|period|season|age/i;
	/** The best unused column for a role: a time axis prefers dates, then date-like names, then labels. */
	function pickFor(kind, cols, used, types) {
		const free = cols.filter((c) => !used.has(c) && fits(types, c, kind));
		if (kind === 'time') {
			return free.find((c) => types[c] === 'temporal') || free.find((c) => TIME_NAME.test(c)) || free.find((c) => types[c] === 'nominal') || free[0] || null;
		}
		if (kind === 'any') return free.find((c) => types[c] !== 'quantitative') || free[0] || null;
		return free[0] || null;
	}

	/** Pick sensible columns for a chart's roles, keeping earlier choices that still fit. */
	function autoMap(chart, table, types, previous) {
		const map = {};
		const used = new Set();
		const cols = table.columns;
		for (const r of chart.roles) {
			const prev = previous && previous[r.key];
			if (r.multi) {
				const keep = Array.isArray(prev) ? prev.filter((c) => cols.includes(c) && fits(types, c, r.kind)) : [];
				if (keep.length) { map[r.key] = keep; keep.forEach((c) => used.add(c)); continue; }
				if (r.required || r.auto) {
					const picks = cols.filter((c) => !used.has(c) && fits(types, c, r.kind)).slice(0, r.max || 8);
					if (picks.length) { map[r.key] = picks; picks.forEach((c) => used.add(c)); }
				}
				continue;
			}
			let pick = prev && cols.includes(prev) && fits(types, prev, r.kind) ? prev : null;
			if (!pick && r.required) pick = pickFor(r.kind, cols, used, types);
			if (pick) { map[r.key] = pick; used.add(pick); }
		}
		for (const [k, v] of Object.entries(chart.defaults || {})) {
			if (!map[k] && cols.includes(v) && !Object.values(map).flat().includes(v)) map[k] = v;
		}
		return map;
	}
	C.autoMap = autoMap;

	/* ── Spec building ──────────────────────────────────────────────────── */

	const optionDefaults = (chart) => {
		const out = {};
		for (const [id, def] of Object.entries(C.OPTIONS)) if (def.default !== undefined) out[def.key || id] = def.default;
		return { ...out, ...chart.opts };
	};
	C.optionDefaults = optionDefaults;

	/** { type, table, types, map, opts } -> spec, or throws a readable error. `warnings` collects notes. */
	function buildSpec(state, warnings) {
		const chart = C.chartType(state.type);
		for (const r of chart.roles) {
			if (!r.required) continue;
			const v = state.map[r.key];
			if (r.multi ? !v || v.length < (r.min || 1) : !v) {
				throw new Error(r.multi ? `Choose at least ${r.min || 1} column${(r.min || 1) > 1 ? 's' : ''} for “${r.label}”.` : `Choose a column for “${r.label}”.`);
			}
		}
		if (!state.table.rows.length) throw new Error('Add at least one row of data.');
		const opts = { ...optionDefaults(chart), ...(state.opts || {}) };
		const s = {
			table: state.table,
			types: state.types,
			map: state.map,
			opts,
			records: toRecords(state.table, state.types),
			f: (role) => state.map[role],
			has: (role) => (Array.isArray(state.map[role]) ? state.map[role].length > 0 : !!state.map[role]),
			list: (role) => [].concat(state.map[role] || []),
			kind: (col) => state.types[col],
			warn: (m) => { if (warnings) warnings.push(m); },
		};
		const spec = chart.build(s);
		if (opts.title && spec.title === undefined) spec.title = opts.title;
		return spec;
	}
	C.buildSpec = buildSpec;

	/** Default state for a chart type with its sample data loaded. */
	function sampleState(chart) {
		const table = parseTable(C.sampleText(chart.sample));
		const types = {};
		for (const [i, c] of table.columns.entries()) types[c] = inferType(table.rows.map((r) => r[i]));
		// `sampleMap` pins the mapping where the sample's columns are ambiguous (years are numbers, etc.)
		return { type: chart.id, table, types, map: { ...autoMap(chart, table, types, {}), ...(chart.sampleMap || {}) }, opts: {} };
	}
	C.sampleState = sampleState;

	/** Spec for a chart type's own sample data (thumbnails, tests). */
	C.sampleSpec = (chart) => buildSpec(sampleState(chart));

	/* ── Built-in datasets (basemaps) ───────────────────────────────────── */

	/** Specs name a basemap as `url: vega-datasets:world-110m`; every renderer swaps it for the data. */
	C.DATASET_SCHEME = 'vega-datasets:';
	C.datasetNames = (spec) => {
		const found = new Set();
		(function walk(n) {
			if (Array.isArray(n)) return n.forEach(walk);
			if (!n || typeof n !== 'object') return;
			if (typeof n.url === 'string' && n.url.startsWith(C.DATASET_SCHEME)) found.add(n.url.slice(C.DATASET_SCHEME.length));
			Object.values(n).forEach(walk);
		})(spec);
		return [...found];
	};
	/** A copy of `spec` with every built-in dataset url replaced by inline values, loaded with `load(name)`. */
	C.resolveDatasets = async (spec, load) => {
		const names = C.datasetNames(spec);
		if (!names.length) return spec;
		const data = Object.fromEntries(await Promise.all(names.map(async (n) => [n, await load(n)])));
		const swap = (n) => {
			if (Array.isArray(n)) return n.map(swap);
			if (!n || typeof n !== 'object') return n;
			const out = {};
			for (const [k, v] of Object.entries(n)) out[k] = swap(v);
			if (typeof out.url === 'string' && out.url.startsWith(C.DATASET_SCHEME)) { out.values = data[out.url.slice(C.DATASET_SCHEME.length)]; delete out.url; }
			return out;
		};
		return swap(spec);
	};

	/* ── Small spec helpers shared by the type modules ──────────────────── */

	const h = (C.h = {});
	h.q = (field, extra) => ({ field, type: 'quantitative', ...extra });
	h.n = (field, extra) => ({ field, type: 'nominal', ...extra });
	/** A constant position on a quantitative axis (reference lines, labels at a value). */
	h.at = (value, extra) => ({ datum: value, type: 'quantitative', ...extra });
	h.o = (field, extra) => ({ field, type: 'ordinal', ...extra });
	h.t = (field, extra) => ({ field, type: 'temporal', ...extra });
	h.axis = (title) => (title ? { axis: { title } } : {});
	h.noLegend = (s) => (s.opts.legend === false ? { legend: null } : {});
	/** Vega-Lite `aggregate` for the "combine rows" option (count needs no field). */
	h.agg = (s) => (s.opts.agg && s.opts.agg !== 'none' && s.opts.agg !== 'count' ? { aggregate: s.opts.agg } : {});
	h.isCount = (s) => s.opts.agg === 'count';
	h.wrap = (s, mark, encoding, extra) => ({ data: { values: s.records }, mark, encoding, ...extra });
	/** Axis type for a column given the "X axis is" option and what a numeric column should default to. */
	h.axisKind = (s, col, numbersAreCategories) => {
		const choice = s.opts.xKind;
		if (choice === 'category') return 'ordinal';
		if (choice === 'number') return 'quantitative';
		if (choice === 'date') return 'temporal';
		const t = s.kind(col);
		if (t === 'temporal') return 'temporal';
		if (t === 'quantitative') return numbersAreCategories ? 'ordinal' : 'quantitative';
		return 'ordinal';
	};
	h.sortFor = (s, kind) => {
		if (kind !== 'ordinal') return {};
		const o = s.opts.sort;
		return { sort: o === 'asc' ? 'x' : o === 'desc' ? '-x' : o === 'value' ? '-y' : null };
	};
	/** Value channel for a role, honouring the "combine rows by" option (count needs no field). */
	h.value = (s, role, extra) => (h.isCount(s) ? { aggregate: 'count', type: 'quantitative', ...extra } : h.q(s.f(role), { ...h.agg(s), ...extra }));
	/** One chart made of layers sharing the data. */
	h.layers = (s, layer, extra) => ({ data: { values: s.records }, layer, ...extra });
	/** Colours that mean something (fixed, from the validated palette): up/down, good/bad. */
	h.good = '#1baf7a';
	h.bad = '#e34948';
	h.neutral = '#2a78d6';
	/** n colours along a ramp of hex stops (sRGB interpolation). */
	h.ramp = (stops, n) => {
		const rgb = (x) => [1, 3, 5].map((i) => parseInt(x.slice(i, i + 2), 16));
		const out = [];
		for (let i = 0; i < n; i++) {
			const pos = n === 1 ? 0 : (i / (n - 1)) * (stops.length - 1);
			const lo = Math.floor(pos), hi = Math.min(stops.length - 1, lo + 1), f = pos - lo;
			const a = rgb(stops[lo]), b = rgb(stops[hi]);
			out.push('#' + a.map((v, k) => Math.round(v + (b[k] - v) * f).toString(16).padStart(2, '0')).join(''));
		}
		return out;
	};
	/** Compact number text for labels: 1,234 / 1.2k stays out of it - labels show what the data says. */
	h.fmt = (v) => (Number.isInteger(v) ? String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ',') : String(r(v, 2)));
	/** Deterministic pseudo-random numbers, so sample data is the same everywhere. */
	h.rng = (seed) => { let x = seed >>> 0 || 1; return () => ((x = (Math.imul(x, 1664525) + 1013904223) >>> 0) / 4294967296); };
	/** ISO date string `n` days after 2025-01-01. */
	h.day = (n) => new Date(Date.UTC(2025, 0, 1 + n)).toISOString().slice(0, 10);
	/** Year-like numbers (1800-2200, all integers) should not get thousands separators. */
	h.looksLikeYears = (s, col) => {
		const v = s.records.map((rec) => rec[col]).filter((x) => x !== null && x !== undefined);
		return v.length > 0 && v.every((x) => Number.isInteger(x) && x >= 1800 && x <= 2200);
	};
	/** X axis settings: the title, plus plain-integer ticks for years. */
	h.xAxis = (s, kind, extra) => {
		const out = { ...(s.opts.xTitle ? { title: s.opts.xTitle } : {}), ...extra };
		if (kind === 'quantitative' && h.looksLikeYears(s, s.f('x'))) out.format = 'd';
		return Object.keys(out).length ? { axis: out } : {};
	};
	/**
	 * Rows of (name, parent, size) -> tree nodes ready for Vega's `stratify`: every node has one
	 * parent, exactly one root (orphans and extra roots hang off a synthetic "All"), and a `group`
	 * naming its top-level branch so branches can share a colour.
	 */
	h.tree = (s, idRole, parentRole, sizeRole) => {
		const idCol = s.f(idRole), parentCol = s.f(parentRole), sizeCol = sizeRole && s.has(sizeRole) ? s.f(sizeRole) : null;
		const nodes = [];
		const seen = new Set();
		for (const rec of s.records) {
			const name = String(rec[idCol] ?? '').trim();
			if (!name) continue;
			if (seen.has(name)) throw new Error(`“${name}” appears twice in “${idCol}”. Each name must be unique (or give each a different name).`);
			seen.add(name);
			const parent = rec[parentCol] === null || rec[parentCol] === undefined || String(rec[parentCol]).trim() === '' ? null : String(rec[parentCol]).trim();
			nodes.push({ name, parent, size: sizeCol ? Math.max(0, Number(rec[sizeCol]) || 0) : null });
		}
		const roots = nodes.filter((n) => n.parent === null || !seen.has(n.parent) || n.parent === n.name);
		let rootName;
		if (roots.length === 1 && roots[0].parent === null) rootName = roots[0].name;
		else {
			rootName = 'All';
			while (seen.has(rootName)) rootName += ' ';
			for (const n of roots) n.parent = rootName;
			nodes.unshift({ name: rootName, parent: null, size: null });
		}
		const byName = new Map(nodes.map((n) => [n.name, n]));
		const kids = new Map();
		for (const n of nodes) if (n.parent !== null) (kids.get(n.parent) || kids.set(n.parent, []).get(n.parent)).push(n);
		const group = (n) => { let cur = n; while (cur.parent !== null && cur.parent !== rootName) cur = byName.get(cur.parent); return cur.parent === null ? cur.name : cur.name; };
		const guard = new Set();
		for (const n of nodes) { if (guard.has(n.name)) continue; let cur = n; const path = new Set(); while (cur && cur.parent !== null) { if (path.has(cur.name)) throw new Error(`“${cur.name}” is its own ancestor; the parents form a loop.`); path.add(cur.name); cur = byName.get(cur.parent); } }
		return { rootName, nodes: nodes.map((n) => ({ name: n.name, parent: n.parent, size: kids.has(n.name) ? 0 : n.size === null ? 1 : n.size, group: group(n) })), groups: [...new Set(nodes.filter((n) => n.parent === rootName).map((n) => n.name))] };
	};
	/** The Vega `data` entry that turns those nodes into a hierarchy, plus extra layout transforms. */
	h.treeData = (tree, layout) => ({ name: 'tree', values: tree.nodes, transform: [{ type: 'stratify', key: 'name', parentKey: 'parent' }, ...layout] });
	h.groupScale = (tree) => ({ name: 'color', type: 'ordinal', domain: tree.groups, range: 'category' });
	/** Fill by branch; the root (depth 0) stays a neutral grey. */
	h.groupFill = { signal: "datum.depth == 0 ? '#9aa3ae' : scale('color', datum.group)" };
	/** Base of a full Vega spec: fixed size, sensible padding, our schema. */
	// `pad`: width x height is the drawing area and the padding sits outside it, so baked layouts are never clipped.
	h.vega = (s, width, height, body) => ({ $schema: C.VEGA_SCHEMA, width, height, padding: 6, autosize: { type: 'pad' }, ...body });
	/** Round for compact baked output. */
	h.r = (n, d = 2) => (Number.isFinite(n) ? Math.round(n * 10 ** d) / 10 ** d : n);
	/** Distinct values of a column in first-seen order. */
	h.distinct = (records, col) => [...new Set(records.map((r) => r[col]))];

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
	const isRows = (path) => /(^|\.)(values|nodes|links)$/.test(path);

	/** Compact, readable YAML (a JSON-superset parser reads it back identically). */
	function toYaml(value, indent = 0, path = '') {
		const pad = ' '.repeat(indent);
		const lines = [];
		if (Array.isArray(value)) {
			for (const item of value) {
				if (item && typeof item === 'object' && !Array.isArray(item) && (isRows(path) ? flow(item).length <= 160 : small(item))) lines.push(`${pad}- ${flow(item)}`);
				else if (item && typeof item === 'object' && !Array.isArray(item)) {
					const inner = toYaml(item, indent + 2, path).split('\n');
					inner[0] = `${pad}- ${inner[0].trimStart()}`;
					lines.push(inner.join('\n'));
				} else if (Array.isArray(item)) lines.push(`${pad}- ${flow(item)}`);
				else lines.push(`${pad}- ${scalar(item)}`);
			}
		} else {
			for (const [k, v] of Object.entries(value)) {
				const key = scalar(k);
				const here = path ? `${path}.${k}` : k;
				if (v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length && !small(v)) lines.push(`${pad}${key}:`, toYaml(v, indent + 2, here));
				else if (Array.isArray(v) && v.length && (isRows(here) || !small(v)) && v.some((x) => x && typeof x === 'object' && !Array.isArray(x))) lines.push(`${pad}${key}:`, toYaml(v, indent + 2, here));
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
	C.toYaml = toYaml;
	C.codeFor = codeFor;

	/* ── Groups, in the order the picker shows them ───────────────────── */

	C.group({ id: 'compare', label: 'Compare', desc: 'Categories side by side' });
	C.group({ id: 'trend', label: 'Change over time', desc: 'Trends, ranges and timelines' });
	C.group({ id: 'distribution', label: 'Distribution', desc: 'How values are spread' });
	C.group({ id: 'relationship', label: 'Relationships', desc: 'How measures relate' });
	C.group({ id: 'composition', label: 'Parts of a whole', desc: 'Shares and proportions' });
	C.group({ id: 'matrix', label: 'Heatmaps and matrices', desc: 'Intensity across two dimensions' });
	C.group({ id: 'kpi', label: 'Progress and KPIs', desc: 'Single numbers and targets' });
	C.group({ id: 'hierarchy', label: 'Hierarchies', desc: 'Nested and tree-shaped data' });
	C.group({ id: 'flow', label: 'Flows and networks', desc: 'Connections between things' });
	C.group({ id: 'text', label: 'Text', desc: 'Words sized by weight' });
	C.group({ id: 'geo', label: 'Maps', desc: 'Values by place' });

	/* ── Shared option definitions ──────────────────────────────────────── */

	C.option('agg', { label: 'Combine rows by', kind: 'select', default: 'none', hint: 'Sum / average rows that share a category',
		choices: [['none', 'Use each row as is'], ['sum', 'Sum'], ['mean', 'Average'], ['median', 'Median'], ['min', 'Minimum'], ['max', 'Maximum'], ['count', 'Count of rows']] });
	// For charts that stack: averages, minimums and maximums do not add up, so only sums and counts are offered.
	C.option('aggSum', { key: 'agg', label: 'Combine rows by', kind: 'select', default: 'none', hint: 'Rows that share a category are added up',
		choices: [['none', 'Use each row as is'], ['sum', 'Sum'], ['count', 'Count of rows']] });
	C.NON_SUMMATIVE = ['mean', 'median', 'min', 'max'];
	C.option('sort', { label: 'Sort categories', kind: 'select', default: 'data', choices: [['data', 'As in the data'], ['asc', 'A → Z'], ['desc', 'Z → A'], ['value', 'Largest first']] });
	C.option('xKind', { label: 'X axis is', kind: 'select', default: 'auto', choices: [['auto', 'Detect'], ['category', 'Categories'], ['number', 'Numbers'], ['date', 'Dates']] });
	C.option('points', { label: 'Show points', kind: 'check', default: true });
	C.option('smooth', { label: 'Smooth the line', kind: 'check', default: false });
	C.option('legend', { label: 'Show legend', kind: 'check', default: true });
	C.option('labels', { label: 'Show value labels', kind: 'check', default: false });

	root.ChartCatalog = C;
})(typeof window !== 'undefined' ? window : globalThis);
