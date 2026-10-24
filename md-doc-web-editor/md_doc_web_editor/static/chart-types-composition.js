/*
 * Chart types: parts of a whole, and gauges. See chart-core.js for the registration API.
 * Several of these lay out their marks here (angles, rings, cells) because the arithmetic is
 * simple and it keeps the chart identical in every renderer.
 * Shared byte-for-byte with md-doc-pipeline's studio.
 */
(function (root) {
	'use strict';
	const C = root.ChartCatalog;
	const { q, noLegend, wrap, layers, r, distinct, value, isCount, fmt } = C.h;

	const role = (key, label, kind = 'any', required = true, extra) => ({ key, label, kind, required, ...extra });
	const TAU = Math.PI * 2;

	C.option('gaugeMin', { label: 'Gauge minimum', kind: 'number', default: 0 });
	C.option('gaugeMax', { label: 'Gauge maximum', kind: 'number', default: 100 });
	C.option('unit', { label: 'Unit after the value', kind: 'text', default: '%' });

	C.sample('shares', 'Region,Revenue\nNorth,42\nSouth,31\nEast,17\nWest,10');
	C.sample('seasons', 'Month,Rainfall\nJan,78\nFeb,64\nMar,52\nApr,41\nMay,33\nJun,27\nJul,19\nAug,24\nSep,38\nOct,56\nNov,71\nDec,83');
	C.sample('quota', 'Team,Attainment\nPlatform,92\nGrowth,74\nSupport,61\nPartners,48');
	C.sample('gauge', 'Metric,Value\nCustomer satisfaction,72');

	/** Totals per category in first-seen order (the chart's slices). */
	function totals(s, catRole, valRole) {
		const sums = new Map();
		for (const rec of s.records) {
			const key = String(rec[s.f(catRole)]);
			const v = isCount(s) ? 1 : rec[s.f(valRole)] || 0;
			const prev = sums.get(key) || { sum: 0, n: 0, min: Infinity, max: -Infinity };
			prev.sum += v; prev.n += 1; prev.min = Math.min(prev.min, v); prev.max = Math.max(prev.max, v);
			sums.set(key, prev);
		}
		const op = s.opts.agg || 'none';
		return [...sums].map(([name, a]) => ({ name, value: op === 'mean' ? a.sum / a.n : op === 'min' ? a.min : op === 'max' ? a.max : op === 'count' ? a.n : a.sum }));
	}

	/* ── Pie and donut ──────────────────────────────────────────────────── */

	function arcSpec(s, donut) {
		const rows = totals(s, 'x', 'y');
		const sum = rows.reduce((a, b) => a + b.value, 0) || 1;
		const order = s.opts.sort === 'value' ? [...rows].sort((a, b) => b.value - a.value) : rows;
		const data = order.map((d) => ({ slice: d.name, amount: r(d.value, 3), share: r(d.value / sum, 4), label: `${d.name} ${r((d.value / sum) * 100, 1)}%` }));
		const theta = { field: 'amount', type: 'quantitative', stack: true };
		const color = { field: 'slice', type: 'nominal', sort: null, scale: { domain: data.map((d) => d.slice) }, ...noLegend(s) };
		const parts = [{ mark: { type: 'arc', innerRadius: donut ? 62 : 0, stroke: 'white', strokeWidth: 1.5 }, encoding: { theta, color, order: { field: 'amount', sort: s.opts.sort === 'value' ? 'descending' : undefined } } }];
		if (s.opts.labels) parts.push({ mark: { type: 'text', radius: { expr: 'min(width, height) * 0.5 * 0.78' }, fontSize: 11, fontWeight: 600, color: 'white' }, encoding: { theta, text: { field: 'label' }, order: { field: 'amount', sort: s.opts.sort === 'value' ? 'descending' : undefined } } });
		const spec = { data: { values: data }, layer: parts, view: { stroke: null } };
		if (!parts[0].encoding.order.sort) delete parts[0].encoding.order, parts[1] && delete parts[1].encoding.order;
		return spec;
	}
	const arcOptions = ['agg', 'sort', 'labels', 'legend'];
	const pieRoles = [role('x', 'Slice label', 'any'), role('y', 'Slice size', 'num')];
	C.type({ id: 'pie', group: 'composition', label: 'Pie', desc: 'Share of a whole (few slices)', sample: 'shares', roles: pieRoles, options: arcOptions, build: (s) => arcSpec(s, false) });
	C.type({ id: 'donut', group: 'composition', label: 'Donut', desc: 'Share of a whole, with a centre', sample: 'shares', roles: pieRoles, options: arcOptions, build: (s) => arcSpec(s, true) });

	/* ── Nightingale rose ───────────────────────────────────────────────── */

	C.type({
		id: 'rose', group: 'composition', label: 'Nightingale rose', desc: 'Equal slices whose reach shows the value', sample: 'seasons',
		roles: [role('x', 'Category (around the circle)', 'any'), role('y', 'Value (reach)', 'num')], options: ['agg', 'labels', 'legend'], opts: { labels: true, legend: false },
		build(s) {
			const rows = totals(s, 'x', 'y');
			const n = rows.length;
			const data = rows.map((d, i) => ({ category: d.name, amount: r(d.value, 3), a0: r((i * TAU) / n, 4), a1: r(((i + 1) * TAU) / n, 4) }));
			const enc = {
				theta: { field: 'a0', type: 'quantitative', stack: null, scale: { domain: [0, TAU], range: [0, TAU] } },
				theta2: { field: 'a1' },
				radius: { field: 'amount', type: 'quantitative', scale: { type: 'sqrt', zero: true, rangeMin: 22 } },
				color: { field: 'category', type: 'nominal', sort: null, scale: { domain: data.map((d) => d.category) }, ...noLegend(s) },
			};
			const parts = [{ mark: { type: 'arc', innerRadius: 22, stroke: 'white', strokeWidth: 1.5 }, encoding: enc }];
			if (s.opts.labels) parts.push({ mark: { type: 'text', radiusOffset: 12, fontSize: 10 }, encoding: { theta: { ...enc.theta, bandPosition: 0.5 }, theta2: undefined, radius: enc.radius, text: { field: 'category' } } });
			return { data: { values: data }, width: 360, height: 360, autosize: { type: 'pad' }, layer: parts, view: { stroke: null } };
		},
	});

	/* ── Radial bar ─────────────────────────────────────────────────────── */

	C.type({
		id: 'radial-bar', group: 'composition', label: 'Radial bar', desc: 'Concentric rings, each filled to its value', sample: 'quota',
		roles: [role('x', 'Ring label', 'any'), role('y', 'Value', 'num')], options: ['agg', 'legend'], opts: { legend: false },
		build(s) {
			const rows = totals(s, 'x', 'y');
			const top = Math.max(...rows.map((d) => d.value), 1e-9);
			const n = rows.length;
			const outer = 160, inner = 34;
			const band = (outer - inner) / n;
			const data = rows.map((d, i) => ({ ring: d.name, amount: r(d.value, 3), t1: r((d.value / top) * TAU * 0.75, 4), r0: r(outer - (i + 1) * band + band * 0.14, 2), r1: r(outer - i * band - band * 0.14, 2), mid: r(outer - (i + 0.5) * band, 2) }));
			const theta = { field: 't0', type: 'quantitative', scale: null };
			return {
				data: { values: data.map((d) => ({ ...d, t0: 0 })) },
				width: 340, height: 340, autosize: { type: 'pad' },
				layer: [
					{ mark: { type: 'arc', theta: 0, theta2: TAU * 0.75, fill: '#eceae4' }, encoding: { radius: { field: 'r1', type: 'quantitative', scale: null }, radius2: { field: 'r0' } } },
					{ mark: { type: 'arc', cornerRadius: 3 }, encoding: { theta, theta2: { field: 't1' }, radius: { field: 'r1', type: 'quantitative', scale: null }, radius2: { field: 'r0' }, color: { field: 'ring', type: 'nominal', sort: null, ...noLegend(s) } } },
					{ mark: { type: 'text', align: 'right', dx: -6, fontSize: 11 }, encoding: { theta: { value: 0 }, radius: { field: 'mid', type: 'quantitative', scale: null }, text: { field: 'ring' } } },
				],
				view: { stroke: null },
			};
		},
	});

	/* ── Waffle ─────────────────────────────────────────────────────────── */

	C.type({
		id: 'waffle', group: 'composition', label: 'Waffle', desc: '100 squares, shared out by proportion', sample: 'shares',
		roles: [role('x', 'Category', 'any'), role('y', 'Amount', 'num')], options: ['agg', 'legend'],
		build(s) {
			const rows = totals(s, 'x', 'y');
			const sum = rows.reduce((a, b) => a + b.value, 0) || 1;
			// Largest-remainder rounding so the squares add up to exactly 100.
			const exact = rows.map((d) => (d.value / sum) * 100);
			const cells = exact.map((v) => Math.floor(v));
			let left = 100 - cells.reduce((a, b) => a + b, 0);
			[...exact.keys()].sort((a, b) => (exact[b] - Math.floor(exact[b])) - (exact[a] - Math.floor(exact[a]))).slice(0, left).forEach((i) => { cells[i] += 1; });
			const data = [];
			let k = 0;
			rows.forEach((d, i) => {
				const label = `${d.name} (${r((d.value / sum) * 100, 0)}%)`;
				for (let c = 0; c < cells[i]; c++, k++) data.push({ col: k % 10, row: Math.floor(k / 10), group: label });
			});
			return {
				data: { values: data },
				width: 260, height: 260, autosize: { type: 'pad' },
				mark: { type: 'rect', cornerRadius: 3 },
				encoding: {
					x: { field: 'col', type: 'ordinal', axis: null, scale: { paddingInner: 0.12 } },
					y: { field: 'row', type: 'ordinal', axis: null, scale: { paddingInner: 0.12 }, sort: 'descending' },
					color: { field: 'group', type: 'nominal', sort: null, scale: { domain: [...new Set(data.map((d) => d.group))] }, legend: s.opts.legend === false ? null : { title: null } },
				},
				view: { stroke: null },
			};
		},
	});

	/* ── Gauge ──────────────────────────────────────────────────────────── */

	C.type({
		id: 'gauge', group: 'kpi', label: 'Gauge', desc: 'One number against a range', sample: 'gauge',
		roles: [role('label', 'Label (optional)', 'any', false), role('y', 'Value', 'num')], options: ['gaugeMin', 'gaugeMax', 'unit'], opts: { gaugeMin: 0, gaugeMax: 100, unit: '%' }, sampleMap: { label: 'Metric', y: 'Value' },
		build(s) {
			const lo = Number(s.opts.gaugeMin) || 0, hi = Number(s.opts.gaugeMax);
			const top = Number.isFinite(hi) && hi > lo ? hi : lo + 100;
			const v = Number(s.records[0][s.f('y')]) || 0;
			const frac = Math.max(0, Math.min(1, (v - lo) / (top - lo)));
			const half = Math.PI / 2;
			const unit = s.opts.unit || '';
			const label = s.has('label') ? String(s.records[0][s.f('label')]) : s.f('y');
			const cx = 170, cy = 188; // the arc's centre, in view pixels
			const centre = { x: { value: cx }, y: { value: cy } };
			const arc = { type: 'arc', innerRadius: 96, outerRadius: 150, cornerRadius: 6 };
			return {
				data: { values: [{ k: 'track', a0: -half, a1: half }, { k: 'value', a0: -half, a1: r(-half + frac * Math.PI, 4) }] },
				width: 340, height: 210, autosize: { type: 'pad' },
				layer: [
					{ mark: arc, transform: [{ filter: "datum.k === 'track'" }], encoding: { ...centre, theta: { field: 'a0', type: 'quantitative', scale: null }, theta2: { field: 'a1' }, color: { value: '#eceae4' } } },
					{ mark: arc, transform: [{ filter: "datum.k === 'value'" }], encoding: { ...centre, theta: { field: 'a0', type: 'quantitative', scale: null }, theta2: { field: 'a1' } } },
					{ data: { values: [{ t: `${fmt(v)}${unit}` }] }, mark: { type: 'text', fontSize: 34, fontWeight: 600 }, encoding: { ...centre, text: { field: 't' } } },
					{ data: { values: [{ t: label }] }, mark: { type: 'text', fontSize: 13, color: '#57606a', dy: 26 }, encoding: { ...centre, text: { field: 't' } } },
				],
				view: { stroke: null },
			};
		},
	});
})(typeof window !== 'undefined' ? window : globalThis);
