/*
 * Chart types: heatmaps and matrices. See chart-core.js for the registration API.
 * Shared byte-for-byte with md-doc-pipeline's studio.
 */
(function (root) {
	'use strict';
	const C = root.ChartCatalog;
	const { q, noLegend, wrap, layers, r, distinct, rng, agg, isCount, value } = C.h;

	const role = (key, label, kind = 'any', required = true, extra) => ({ key, label, kind, required, ...extra });

	/* ── Samples ────────────────────────────────────────────────────────── */

	C.sample('grid', 'Day,Hour,Visits\nMon,9am,12\nMon,12pm,30\nMon,3pm,22\nMon,6pm,9\nTue,9am,15\nTue,12pm,35\nTue,3pm,18\nTue,6pm,11\nWed,9am,9\nWed,12pm,28\nWed,3pm,25\nWed,6pm,14\nThu,9am,20\nThu,12pm,40\nThu,3pm,31\nThu,6pm,16\nFri,9am,18\nFri,12pm,33\nFri,3pm,12\nFri,6pm,6');
	C.sample('calendar', () => {
		const rand = rng(23);
		const rows = ['Date,Commits'];
		for (let i = 0; i < 154; i++) {
			const d = new Date(Date.UTC(2025, 0, 1 + i));
			const weekday = d.getUTCDay();
			const n = weekday === 0 || weekday === 6 ? Math.floor(rand() * 3) : Math.floor(rand() * 9);
			rows.push(`${d.toISOString().slice(0, 10)},${n}`);
		}
		return rows.join('\n');
	});
	C.sample('measures', () => {
		const rand = rng(51);
		const rows = ['Revenue,Marketing,Headcount,Churn,Support'];
		for (let i = 0; i < 30; i++) {
			const base = rand() * 10;
			rows.push([base * 8 + rand() * 9, base * 3 + rand() * 6, base * 1.5 + rand() * 5, 18 - base * 1.1 + rand() * 4, base * 0.4 + rand() * 4].map((v) => Math.round(v * 10) / 10).join(','));
		}
		return rows.join('\n');
	});
	C.sample('scatterBins', () => {
		const rand = rng(61);
		const normal = () => Math.sqrt(-2 * Math.log(rand() || 1e-9)) * Math.cos(2 * Math.PI * rand());
		const rows = ['Height,Weight'];
		for (let i = 0; i < 300; i++) { const h = 170 + normal() * 9; rows.push(`${Math.round(h * 10) / 10},${Math.round((0.9 * (h - 100) + normal() * 6) * 10) / 10}`); }
		return rows.join('\n');
	});

	/* ── Heatmaps ───────────────────────────────────────────────────────── */

	const cellAxes = (s) => ({
		x: { field: s.f('x'), type: 'ordinal', sort: null, axis: { title: s.opts.xTitle || null, labelAngle: 0 } },
		y: { field: s.f('y'), type: 'ordinal', sort: null, axis: { title: s.opts.yTitle || null } },
	});
	const heatRoles = [role('x', 'Columns', 'any'), role('y', 'Rows', 'any'), role('value', 'Value (colour)', 'num')];

	C.type({
		id: 'heatmap', group: 'matrix', label: 'Heatmap', desc: 'Intensity across two categories', sample: 'grid',
		roles: heatRoles, options: ['agg', 'legend'],
		build(s) {
			const color = isCount(s) ? { aggregate: 'count', type: 'quantitative' } : q(s.f('value'), { ...agg(s) });
			return wrap(s, { type: 'rect', stroke: 'white', strokeWidth: 1 }, { ...cellAxes(s), color: { ...color, scale: { scheme: 'blues' }, ...(s.opts.legend === false ? { legend: null } : {}) } });
		},
	});

	C.type({
		id: 'heatmap-annotated', group: 'matrix', label: 'Annotated heatmap', desc: 'A heatmap with the value written in each cell', sample: 'grid',
		roles: heatRoles, options: ['agg', 'legend'],
		build(s) {
			const vals = s.records.map((rec) => rec[s.f('value')]).filter((v) => typeof v === 'number');
			const mid = r((Math.min(...vals) + Math.max(...vals)) / 2, 3);
			const axes = cellAxes(s);
			const val = isCount(s) ? { aggregate: 'count', type: 'quantitative' } : q(s.f('value'), { ...agg(s) });
			return layers(s, [
				{ mark: { type: 'rect', stroke: 'white', strokeWidth: 1 }, encoding: { ...axes, color: { ...val, scale: { scheme: 'blues' }, ...(s.opts.legend === false ? { legend: null } : {}) } } },
				{ mark: { type: 'text', fontSize: 12 }, encoding: { ...axes, text: val, color: { condition: { test: `datum['${s.f('value')}'] > ${mid}`, value: 'white' }, value: '#1f2328' } } },
			]);
		},
	});

	C.type({
		id: 'hist2d', group: 'matrix', label: '2D histogram', desc: 'Where many points pile up, in bins', sample: 'scatterBins',
		roles: [role('x', 'X (number)', 'num'), role('y', 'Y (number)', 'num')], options: ['bins', 'legend'],
		build(s) {
			const bins = { maxbins: Math.max(3, Math.min(60, Math.round(Number(s.opts.bins) || 20))) };
			return wrap(s, 'rect', {
				x: q(s.f('x'), { bin: bins, axis: { title: s.opts.xTitle || s.f('x') } }),
				y: q(s.f('y'), { bin: bins, axis: { title: s.opts.yTitle || s.f('y') } }),
				color: { aggregate: 'count', type: 'quantitative', scale: { scheme: 'blues' }, ...(s.opts.legend === false ? { legend: null } : { legend: { title: 'Count' } }) },
			});
		},
		opts: { bins: 20 },
	});

	/* ── Calendar ───────────────────────────────────────────────────────── */

	C.type({
		id: 'calendar', group: 'matrix', label: 'Calendar heatmap', desc: 'A value per day, laid out by week', sample: 'calendar',
		roles: [role('x', 'Date', 'date'), role('value', 'Value (colour)', 'num')], options: ['agg', 'legend'],
		build(s) {
			const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
			const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
			const byDay = new Map();
			for (const rec of s.records) {
				const d = String(rec[s.f('x')]).slice(0, 10);
				if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) continue;
				const list = byDay.get(d) || [];
				list.push(rec[s.f('value')] || 0);
				byDay.set(d, list);
			}
			if (!byDay.size) throw new Error('The date column needs values like 2025-03-14.');
			const days = [...byDay.keys()].sort();
			const toUtc = (d) => Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10));
			const dow = (ms) => (new Date(ms).getUTCDay() + 6) % 7; // Monday = 0
			const start = toUtc(days[0]) - dow(toUtc(days[0])) * 86400000;
			const op = s.opts.agg === 'none' || !s.opts.agg ? 'sum' : s.opts.agg;
			const reduce = (list) => (op === 'count' ? list.length : op === 'mean' ? list.reduce((a, b) => a + b, 0) / list.length : op === 'min' ? Math.min(...list) : op === 'max' ? Math.max(...list) : op === 'median' ? [...list].sort((a, b) => a - b)[Math.floor(list.length / 2)] : list.reduce((a, b) => a + b, 0));
			const cells = days.map((d) => ({ date: d, week: Math.floor((toUtc(d) - start) / (7 * 86400000)), day: dow(toUtc(d)), value: r(reduce(byDay.get(d)), 3) }));
			const firstOfMonth = [];
			let lastMonth = -1;
			for (const c of cells) { const m = +c.date.slice(5, 7) - 1; if (m !== lastMonth && c.day <= 3 || (m !== lastMonth && !firstOfMonth.length)) { firstOfMonth.push([c.week, MONTHS[m]]); lastMonth = m; } }
			const weeks = firstOfMonth.map((p) => p[0]);
			const labelExpr = `${JSON.stringify(firstOfMonth.map((p) => p[1]))}[indexof(${JSON.stringify(weeks)}, datum.value)]`;
			return {
				data: { values: cells },
				mark: { type: 'rect', stroke: 'white', strokeWidth: 2, cornerRadius: 2 },
				encoding: {
					x: { field: 'week', type: 'ordinal', axis: { title: null, values: weeks, labelExpr, ticks: false, domain: false, labelAngle: 0, labelAlign: 'left' } },
					y: { field: 'day', type: 'ordinal', sort: 'ascending', axis: { title: null, ticks: false, domain: false, labelExpr: `${JSON.stringify(DAYS)}[datum.value]` } },
					color: { field: 'value', type: 'quantitative', scale: { scheme: 'greens' }, ...(s.opts.legend === false ? { legend: null } : { legend: { title: s.f('value') } }) },
					tooltip: [{ field: 'date' }, { field: 'value', type: 'quantitative' }],
				},
				config: { view: { stroke: null } },
			};
		},
	});

	/* ── Correlation matrix ─────────────────────────────────────────────── */

	function pearson(a, b) {
		const n = Math.min(a.length, b.length);
		let sa = 0, sb = 0;
		for (let i = 0; i < n; i++) { sa += a[i]; sb += b[i]; }
		const ma = sa / n, mb = sb / n;
		let num = 0, da = 0, db = 0;
		for (let i = 0; i < n; i++) { num += (a[i] - ma) * (b[i] - mb); da += (a[i] - ma) ** 2; db += (b[i] - mb) ** 2; }
		return da && db ? num / Math.sqrt(da * db) : 0;
	}

	C.type({
		id: 'correlation', group: 'matrix', label: 'Correlation matrix', desc: 'How strongly every pair of numbers moves together', sample: 'measures',
		roles: [role('cols', 'Numeric columns (2 or more)', 'num', true, { multi: true, min: 2, max: 10 })], options: ['labels', 'legend'], opts: { labels: true },
		build(s) {
			const cols = s.list('cols');
			const series = Object.fromEntries(cols.map((c) => [c, s.records.map((rec) => rec[c]).filter((v) => typeof v === 'number')]));
			const cells = [];
			for (const a of cols) for (const b of cols) cells.push({ a, b, r: r(pearson(series[a], series[b]), 2) });
			const axes = { x: { field: 'a', type: 'ordinal', sort: cols, axis: { title: null, labelAngle: -35 } }, y: { field: 'b', type: 'ordinal', sort: cols, axis: { title: null } } };
			const parts = [{ mark: { type: 'rect', stroke: 'white', strokeWidth: 1 }, encoding: { ...axes, color: { field: 'r', type: 'quantitative', scale: { domain: [-1, 0, 1], range: ['#d1495b', '#f4f4f1', '#2a78d6'], interpolate: 'rgb' }, legend: s.opts.legend === false ? null : { title: 'r' } } } }];
			if (s.opts.labels) parts.push({ mark: { type: 'text', fontSize: 11 }, encoding: { ...axes, text: { field: 'r', type: 'quantitative', format: '.2f' }, color: { condition: { test: 'abs(datum.r) > 0.6', value: 'white' }, value: '#1f2328' } } });
			return { data: { values: cells }, layer: parts };
		},
	});
})(typeof window !== 'undefined' ? window : globalThis);
