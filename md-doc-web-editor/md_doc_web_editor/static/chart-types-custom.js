/*
 * Chart types with no upstream Vega / Vega-Lite example. Each is plain Vega-Lite (or an edit of an upstream
 * Vega spec, declared) built from the same primitives and idioms as the nearest upstream example, named in
 * its comment: the user's rows go in `data.values`, and layout happens in `transform`s at render time.
 * No computed geometry is written into the spec. Shared byte-for-byte with md-doc-pipeline's studio.
 */
(function (root) {
	'use strict';
	const C = root.ChartCatalog;
	const { rng, day, noLegend, isCount, value } = C.h;
	const role = (key, label, kind = 'any', required = true, extra) => ({ key, label, kind, required, ...extra });
	const col = (c) => `datum[${JSON.stringify(c)}]`;
	const TAU = Math.PI * 2;
	const edit = (why, fn) => ({ why, apply: fn });

	C.option('gaugeMin', { label: 'Gauge minimum', kind: 'number', default: 0 });
	C.option('gaugeMax', { label: 'Gauge maximum', kind: 'number', default: 100 });
	C.option('unit', { label: 'Unit after the value', kind: 'text', default: '%' });
	C.option('icon', { label: 'Icon', kind: 'select', default: 'person', choices: [['person', 'Person'], ['circle', 'Circle'], ['square', 'Square'], ['diamond', 'Diamond'], ['triangle', 'Triangle'], ['heart', 'Heart'], ['drop', 'Drop'], ['star', 'Star']] });
	C.option('pictoUnit', { label: 'Each icon stands for (0 = automatic)', kind: 'number', default: 0, min: 0 });

	C.sample('c_quota', 'Team,Attainment\nPlatform,92\nGrowth,74\nSupport,61\nPartners,48');
	C.sample('c_shares', 'Region,Revenue\nNorth,42\nSouth,31\nEast,17\nWest,10');
	C.sample('c_gauge', 'Metric,Value\nCustomer satisfaction,72');
	C.sample('c_people', 'Group,People\nStudents,420\nEmployed,310\nRetired,180\nSeeking work,60');
	C.sample('c_funnel', 'Stage,Count\nVisitors,12000\nSign-ups,4300\nTrials,1800\nCustomers,620');
	C.sample('c_pareto', 'Cause,Count\nLate delivery,48\nDamaged,31\nWrong item,17\nBilling,9\nOther,5');
	C.sample('c_range', () => ['Date,Low,High', ...Array.from({ length: 24 }, (_, i) => `${day(i * 30)},${Math.round(8 + Math.sin(i / 2) * 6)},${Math.round(20 + Math.sin(i / 2) * 7)}`)].join('\n'));
	C.sample('c_ohlc', () => { const next = rng(9); let price = 100; return ['Date,Open,High,Low,Close', ...Array.from({ length: 24 }, (_, i) => { const open = price; price = open + (next() - 0.48) * 8; return `${day(i)},${open.toFixed(1)},${(Math.max(open, price) + next() * 3).toFixed(1)},${(Math.min(open, price) - next() * 3).toFixed(1)},${price.toFixed(1)}`; })].join('\n'); });
	C.sample('c_spark', () => ['Date,Value', ...Array.from({ length: 30 }, (_, i) => `${day(i)},${Math.round(50 + Math.sin(i / 3) * 18 + i)}`)].join('\n'));
	C.sample('c_control', () => { const next = rng(61); return ['Sample,Measurement', ...Array.from({ length: 40 }, (_, i) => `${i + 1},${(50 + (next() - 0.5) * 8 + (i === 27 ? 9 : 0)).toFixed(2)}`)].join('\n'); });
	C.sample('c_events', 'Date,Event\n2025-01-15,Kick-off\n2025-03-02,Prototype\n2025-04-20,Beta\n2025-06-10,Launch\n2025-08-01,"First 1,000 users"\n2025-10-05,v2');
	C.sample('c_quadrant', () => { const next = rng(67); return ['Item,Effort,Impact', ...Array.from({ length: 24 }, (_, i) => `Item ${i + 1},${Math.round(10 + next() * 80)},${Math.round(10 + next() * 80)}`)].join('\n'); });
	C.sample('c_measures', () => { const next = rng(71); return ['Height,Weight,Age,Income', ...Array.from({ length: 50 }, () => { const h = 150 + next() * 45; const age = 20 + next() * 40; return [h.toFixed(0), ((h - 100) * 0.9 + next() * 14).toFixed(0), age.toFixed(0), (20 + age * 0.9 + next() * 30).toFixed(0)].join(','); })].join('\n'); });
	C.sample('c_overlaps', 'Sets,Size\nPython,72\nSQL,47\nR,29\nPython & SQL,32\nPython & R,12\nSQL & R,7\nPython & SQL & R,8');


	/* ── Bars and comparison ────────────────────────────────────────────── */

	// Pattern: layer_ranged_dot (a rule and a point on shared encodings), with the rule running to zero.
	C.type({
		id: 'lollipop', group: 'compare', label: 'Lollipop', desc: 'A dot on a stick instead of a bar', sample: 'c_shares',
		roles: [role('x', 'Category', 'any'), role('y', 'Value', 'num')], options: [], sampleMap: { x: 'Region', y: 'Revenue' },
		build(s) {
			const x = { aggregate: 'sum', field: s.f('y'), type: 'quantitative' };
			return {
				data: { values: s.records },
				encoding: { y: { field: s.f('x'), type: 'nominal', sort: null } },
				layer: [
					{ mark: 'rule', encoding: { x, x2: { datum: 0 } } },
					{ mark: { type: 'circle', size: 140, opacity: 1 }, encoding: { x } },
				],
			};
		},
	});
	// Pattern: tick_dot / layer_ranged_dot (a point per row on one quantitative axis), one row per category.
	C.type({
		id: 'dot-plot', group: 'compare', label: 'Dot plot', desc: 'One dot per category on a shared axis', sample: 'c_shares', sampleMap: { x: 'Region', y: 'Revenue' },
		roles: [role('x', 'Category', 'any'), role('y', 'Value', 'num')], options: [],
		build(s) {
			return { data: { values: s.records }, mark: { type: 'point', filled: true, size: 140, opacity: 1 }, encoding: { y: { field: s.f('x'), type: 'nominal', sort: '-x' }, x: { aggregate: 'sum', field: s.f('y'), type: 'quantitative' } } };
		},
	});
	// Pattern: stacked_bar_h with `stack: "center"`, one bar per stage, plus the layer_bar_labels text layer.
	C.type({
		id: 'funnel', group: 'compare', label: 'Funnel', desc: 'Stages narrowing from top to bottom', sample: 'c_funnel', sampleMap: { x: 'Stage', y: 'Count' },
		roles: [role('x', 'Stage (top to bottom)', 'any'), role('y', 'Count', 'num')], options: [],
		build(s) {
			const y = { field: s.f('x'), type: 'ordinal', sort: null, axis: { title: null, ticks: false, domain: false } };
			return {
				data: { values: s.records },
				transform: [
					{ aggregate: [{ op: 'sum', field: s.f('y'), as: 'v' }], groupby: [s.f('x')] },
					{ calculate: '-datum.v / 2', as: 'lo' },
					{ calculate: 'datum.v / 2', as: 'hi' },
				],
				encoding: { y },
				layer: [
					{ mark: 'bar', encoding: { x: { field: 'lo', type: 'quantitative', axis: null }, x2: { field: 'hi' }, color: { field: s.f('x'), type: 'nominal', sort: null, legend: null } } },
					{ mark: { type: 'text', color: 'white', fontWeight: 600 }, encoding: { x: { datum: 0, type: 'quantitative', axis: null }, text: { field: 'v', type: 'quantitative', format: ',' } } },
				],
				config: { view: { stroke: null } },
			};
		},
	});
	// Pattern: layer_dual_axis (two layers, independent y scales) with window_rank / cumulative_freq transforms.
	C.type({
		id: 'pareto', group: 'compare', label: 'Pareto', desc: 'Bars largest first, with the running share as a line', sample: 'c_pareto', sampleMap: { x: 'Cause', y: 'Count' },
		roles: [role('x', 'Category', 'any'), role('y', 'Count', 'num')], options: [],
		build(s) {
			return {
				data: { values: s.records },
				transform: [
					{ aggregate: [{ op: 'sum', field: s.f('y'), as: 'v' }], groupby: [s.f('x')] },
					{ window: [{ op: 'sum', field: 'v', as: 'cum' }], sort: [{ field: 'v', order: 'descending' }], frame: [null, 0] },
					{ joinaggregate: [{ op: 'sum', field: 'v', as: 'total' }] },
					{ calculate: 'datum.cum / datum.total', as: 'share' },
				],
				encoding: { x: { field: s.f('x'), type: 'ordinal', sort: { field: 'v', order: 'descending' } } },
				layer: [
					{ mark: 'bar', encoding: { y: { field: 'v', type: 'quantitative', title: s.f('y') } } },
					{ mark: { type: 'line', point: true, color: '#e8742a' }, encoding: { y: { field: 'share', type: 'quantitative', axis: { format: '%', title: 'Cumulative share' }, scale: { domain: [0, 1] } } } },
				],
				resolve: { scale: { y: 'independent' } },
			};
		},
	});

	/* ── Change over time ───────────────────────────────────────────────── */

	// Pattern: area with y and y2 (as in layer_dual_axis's temperature range).
	C.type({
		id: 'range-area', group: 'trend', label: 'Range area', desc: 'The band between a low and a high over time', sample: 'c_range', sampleMap: { x: 'Date', lo: 'Low', hi: 'High' },
		roles: [role('x', 'Date', 'time'), role('lo', 'Low', 'num'), role('hi', 'High', 'num')], options: [],
		build(s) {
			return { data: { values: s.records }, mark: { type: 'area', opacity: 0.55 }, encoding: { x: { field: s.f('x'), type: 'temporal' }, y: { field: s.f('hi'), type: 'quantitative', title: `${s.f('lo')} – ${s.f('hi')}` }, y2: { field: s.f('lo') } } };
		},
	});
	// Pattern: layer_candlestick (a rule from low to high), with ticks for open (left) and close (right).
	C.type({
		id: 'ohlc', group: 'trend', label: 'OHLC bars', desc: 'High–low bars with open and close ticks', sample: 'c_ohlc', sampleMap: { date: 'Date', open: 'Open', high: 'High', low: 'Low', close: 'Close' },
		roles: [role('date', 'Date', 'time'), role('open', 'Open', 'num'), role('high', 'High', 'num'), role('low', 'Low', 'num'), role('close', 'Close', 'num')], options: [],
		build(s) {
			const x = { field: s.f('date'), type: 'temporal' };
			const tick = (field, dx) => ({ mark: { type: 'tick', orient: 'horizontal', size: 9, xOffset: dx, thickness: 1.5 }, encoding: { x, y: { field: s.f(field), type: 'quantitative' } } });
			return {
				data: { values: s.records }, width: 400,
				encoding: { x, color: { condition: { test: `${col(s.f('open'))} < ${col(s.f('close'))}`, value: '#06982d' }, value: '#ae1325' } },
				layer: [
					{ mark: 'rule', encoding: { y: { field: s.f('low'), type: 'quantitative', scale: { zero: false }, title: 'Price' }, y2: { field: s.f('high') } } },
					tick('open', -5), tick('close', 5),
				],
			};
		},
	});
	C.type({
		id: 'sparkline', group: 'trend', label: 'Sparkline', desc: 'A word-sized line with its last value marked', sample: 'c_spark', sampleMap: { x: 'Date', y: 'Value' },
		roles: [role('x', 'Date', 'time'), role('y', 'Value', 'num')], options: [],
		build(s) {
			const enc = { x: { field: s.f('x'), type: 'temporal', axis: null }, y: { field: s.f('y'), type: 'quantitative', axis: null, scale: { zero: false } } };
			return {
				data: { values: s.records }, width: 200, height: 40,
				layer: [
					{ mark: 'line', encoding: enc },
					{ transform: [{ window: [{ op: 'row_number', as: 'i' }] }, { joinaggregate: [{ op: 'count', as: 'n' }] }, { filter: 'datum.i === datum.n' }], mark: { type: 'point', filled: true, color: '#e8742a', size: 50 }, encoding: enc },
				],
				config: { view: { stroke: null } },
			};
		},
	});
	// Pattern: layer_line_mean_point_raw (points and line over shared data) with joinaggregate statistics as in joinaggregate_mean_difference.
	C.type({
		id: 'control-chart', group: 'trend', label: 'Control chart', desc: 'A process against its mean and ±3σ limits', sample: 'c_control', sampleMap: { x: 'Sample', y: 'Measurement' },
		roles: [role('x', 'Sample (in order)', 'num'), role('y', 'Measurement', 'num')], options: [],
		build(s) {
			const y = (field) => ({ field, type: 'quantitative' });
			const x = { field: s.f('x'), type: 'quantitative', scale: { zero: false } };
			return {
				data: { values: s.records },
				transform: [
					{ joinaggregate: [{ op: 'mean', field: s.f('y'), as: 'mean' }, { op: 'stdev', field: s.f('y'), as: 'sd' }] },
					{ calculate: 'datum.mean + 3 * datum.sd', as: 'ucl' },
					{ calculate: 'datum.mean - 3 * datum.sd', as: 'lcl' },
				],
				layer: [
					{ mark: { type: 'rule', color: '#6e7781' }, encoding: { y: { ...y('mean'), scale: { zero: false }, title: s.f('y') } } },
					{ mark: { type: 'rule', color: '#d1242f', strokeDash: [6, 4] }, encoding: { y: y('ucl') } },
					{ mark: { type: 'rule', color: '#d1242f', strokeDash: [6, 4] }, encoding: { y: y('lcl') } },
					{ mark: 'line', encoding: { x, y: { ...y(s.f('y')), scale: { zero: false } } } },
					{ mark: { type: 'point', filled: true, size: 55, opacity: 1 }, encoding: { x, y: y(s.f('y')), color: { condition: { test: `${col(s.f('y'))} > datum.ucl || ${col(s.f('y'))} < datum.lcl`, value: '#d1242f' }, value: '#2a78d6' } } },
				],
			};
		},
	});
	// Pattern: layer_bar_annotations / layer_falkensee (marks and text over a time axis), labels alternating above and below.
	C.type({
		id: 'timeline', group: 'trend', label: 'Timeline', desc: 'Events as labelled points along a date line', sample: 'c_events', sampleMap: { x: 'Date', label: 'Event' },
		roles: [role('x', 'Date', 'time'), role('label', 'Event', 'any')], options: [], opts: {},
		build(s) {
			const x = { field: s.f('x'), type: 'temporal', axis: { title: null } };
			const y = { datum: 0, type: 'quantitative', axis: null };
			return {
				data: { values: s.records }, width: 480, height: 90,
				transform: [{ window: [{ op: 'row_number', as: 'i' }] }],
				layer: [
					{ mark: { type: 'rule', color: '#9aa0ac' }, encoding: { y } },
					{ mark: { type: 'point', filled: true, size: 90, opacity: 1 }, encoding: { x, y } },
					{ mark: { type: 'text', fontSize: 11, dy: { expr: 'datum.i % 2 ? -16 : 16' } }, encoding: { x, y, text: { field: s.f('label'), type: 'nominal' } } },
				],
				config: { view: { stroke: null } },
			};
		},
	});

	/* ── Relationships and matrices ─────────────────────────────────────── */

	// Pattern: layer_point_line_regression's layered shapes, with rule marks at the means (aggregate transforms as in layer_precipitation_mean).
	C.type({
		id: 'quadrant', group: 'relationship', label: 'Quadrant', desc: 'A scatter split into four by the averages', sample: 'c_quadrant', sampleMap: { x: 'Effort', y: 'Impact', label: 'Item' },
		roles: [role('x', 'X (number)', 'num'), role('y', 'Y (number)', 'num'), role('label', 'Label (optional)', 'any', false)], options: [],
		build(s) {
			const q = (field) => ({ field, type: 'quantitative' });
			const mean = (field, as) => [{ aggregate: [{ op: 'mean', field, as }] }];
			return {
				data: { values: s.records },
				layer: [
					{ mark: { type: 'point', filled: true, size: 70, opacity: 0.85 }, encoding: { x: { ...q(s.f('x')), scale: { zero: false } }, y: { ...q(s.f('y')), scale: { zero: false } }, ...(s.has('label') ? { tooltip: { field: s.f('label'), type: 'nominal' } } : {}) } },
					{ transform: mean(s.f('x'), 'mx'), mark: { type: 'rule', strokeDash: [5, 4], color: '#6e7781' }, encoding: { x: { ...q('mx'), title: s.f('x') } } },
					{ transform: mean(s.f('y'), 'my'), mark: { type: 'rule', strokeDash: [5, 4], color: '#6e7781' }, encoding: { y: { ...q('my'), title: s.f('y') } } },
				],
			};
		},
	});
	// Pattern: layer_text_heatmap (rect + text over the same cells); the cells come from fold / pivot / flatten transforms.
	C.type({
		id: 'correlation', group: 'matrix', label: 'Correlation matrix', desc: 'How strongly every pair of measures moves together', sample: 'c_measures', sampleMap: { measures: ['Height', 'Weight', 'Age', 'Income'] },
		roles: [role('measures', 'Measures (2 or more)', 'num', true, { multi: true, min: 2 })], options: [],
		build(s) {
			const cols = s.list('measures');
			const pairs = cols.flatMap((a) => cols.map((b) => [a, b]));
			return {
				data: { values: s.records },
				transform: [
					{ window: [{ op: 'row_number', as: '_row' }] },
					{ fold: cols, as: ['_var', '_v'] },
					{ joinaggregate: [{ op: 'mean', field: '_v', as: '_m' }, { op: 'stdevp', field: '_v', as: '_s' }], groupby: ['_var'] },
					{ calculate: 'datum._s ? (datum._v - datum._m) / datum._s : 0', as: '_z' },
					{ pivot: '_var', value: '_z', groupby: ['_row'] },
					{ calculate: JSON.stringify(pairs), as: '_pair' },
					{ flatten: ['_pair'] },
					{ calculate: 'datum[datum._pair[0]] * datum[datum._pair[1]]', as: '_p' },
					{ aggregate: [{ op: 'mean', field: '_p', as: 'r' }], groupby: ['_pair'] },
					{ calculate: 'datum._pair[0]', as: 'x' },
					{ calculate: 'datum._pair[1]', as: 'y' },
				],
				encoding: { x: { field: 'x', type: 'ordinal', sort: cols, title: null }, y: { field: 'y', type: 'ordinal', sort: cols, title: null } },
				layer: [
					{ mark: 'rect', encoding: { color: { field: 'r', type: 'quantitative', scale: { domain: [-1, 1], scheme: 'redblue', reverse: true }, title: 'Correlation' } } },
					{ mark: { type: 'text', fontSize: 11 }, encoding: { text: { field: 'r', type: 'quantitative', format: '.2f' }, color: { condition: { test: 'abs(datum.r) > 0.6', value: 'white' }, value: 'black' } } },
				],
				config: { axis: { grid: false } },
			};
		},
	});


	/* ── Parts of a whole and KPIs ──────────────────────────────────────── */

	/** Vega-Lite transforms: one row per category with its `amount`, in first-seen order, as `cat`. */
	function perCategory(s, catRole, valRole) {
		const cat = s.f(catRole);
		const op = isCount(s) ? 'count' : s.opts.agg && s.opts.agg !== 'none' ? s.opts.agg : 'sum';
		return [
			{ aggregate: [{ op, ...(op === 'count' ? {} : { field: s.f(valRole) }), as: 'amount' }], groupby: [cat] },
			{ calculate: `datum[${JSON.stringify(cat)}]`, as: 'cat' },
			{ window: [{ op: 'row_number', as: 'i' }] },
			{ joinaggregate: [{ op: 'count', as: 'n' }, { op: 'max', field: 'amount', as: 'top' }, { op: 'sum', field: 'amount', as: 'total' }] },
		];
	}


	/* ── Radial bar ─────────────────────────────────────────────────────── */

	C.type({
		id: 'radial-bar', group: 'composition', label: 'Radial bar', desc: 'Concentric rings, each filled to its value', sample: 'c_quota',
		roles: [role('x', 'Ring label', 'any'), role('y', 'Value', 'num')], options: ['agg', 'legend'], opts: { legend: false },
		build(s) {
			const outer = 160, inner = 34;
			const band = `(${outer - inner} / datum.n)`;
			const theta = { field: 't0', type: 'quantitative', scale: null };
			const radius = { field: 'r1', type: 'quantitative', scale: null };
			return {
				data: { values: s.records },
				transform: [
					...perCategory(s, 'x', 'y'),
					{ calculate: '0', as: 't0' },
					{ calculate: `datum.amount / datum.top * ${TAU * 0.75}`, as: 't1' },
					{ calculate: `${outer} - datum.i * ${band} + ${band} * 0.14`, as: 'r0' },
					{ calculate: `${outer} - (datum.i - 1) * ${band} - ${band} * 0.14`, as: 'r1' },
					{ calculate: `${outer} - (datum.i - 0.5) * ${band}`, as: 'mid' },
				],
				width: 340, height: 340, autosize: { type: 'pad' },
				layer: [
					{ mark: { type: 'arc', theta: 0, theta2: TAU * 0.75, fill: '#eceae4' }, encoding: { radius, radius2: { field: 'r0' } } },
					{ mark: { type: 'arc', cornerRadius: 3 }, encoding: { theta, theta2: { field: 't1' }, radius, radius2: { field: 'r0' }, color: { field: 'cat', type: 'nominal', sort: null, ...noLegend(s) } } },
					{ mark: { type: 'text', align: 'right', dx: -6, fontSize: 11 }, encoding: { theta: { value: 0 }, radius: { field: 'mid', type: 'quantitative', scale: null }, text: { field: 'cat' } } },
				],
				view: { stroke: null },
			};
		},
	});


	/* ── Waffle ─────────────────────────────────────────────────────────── */

	C.type({
		id: 'waffle', group: 'composition', label: 'Waffle', desc: '100 squares, shared out by proportion', sample: 'c_shares',
		roles: [role('x', 'Category', 'any'), role('y', 'Amount', 'num')], options: ['agg', 'legend'],
		build(s) {
			return {
				data: { values: s.records },
				transform: [
					...perCategory(s, 'x', 'y'),
					// each category owns the squares between its running share and the one before (cumulative rounding makes exactly 100)
					{ window: [{ op: 'sum', field: 'amount', as: 'cum' }], frame: [null, 0] },
					{ calculate: "datum.cat + ' (' + round(datum.amount / datum.total * 100) + '%)'", as: 'group' },
					{ calculate: 'sequence(round((datum.cum - datum.amount) / datum.total * 100), round(datum.cum / datum.total * 100))', as: 'cells' },
					{ flatten: ['cells'], as: ['k'] },
					{ calculate: 'datum.k % 10', as: 'col' },
					{ calculate: 'floor(datum.k / 10)', as: 'row' },
				],
				width: 260, height: 260, autosize: { type: 'pad' },
				mark: { type: 'rect', cornerRadius: 3 },
				encoding: {
					x: { field: 'col', type: 'ordinal', axis: null, scale: { paddingInner: 0.12 } },
					y: { field: 'row', type: 'ordinal', axis: null, scale: { paddingInner: 0.12 }, sort: 'descending' },
					color: { field: 'group', type: 'nominal', sort: null, legend: s.opts.legend === false ? null : { title: null } },
				},
				view: { stroke: null },
			};
		},
	});


	/* ── Gauge ──────────────────────────────────────────────────────────── */

	C.type({
		id: 'gauge', group: 'kpi', label: 'Gauge', desc: 'One number against a range', sample: 'c_gauge',
		roles: [role('label', 'Label (optional)', 'any', false), role('y', 'Value', 'num')], options: ['gaugeMin', 'gaugeMax', 'unit'], opts: { gaugeMin: 0, gaugeMax: 100, unit: '%' }, sampleMap: { label: 'Metric', y: 'Value' },
		build(s) {
			const lo = Number(s.opts.gaugeMin) || 0, hi = Number(s.opts.gaugeMax);
			const top = Number.isFinite(hi) && hi > lo ? hi : lo + 100;
			const half = Math.PI / 2;
			const unit = JSON.stringify(s.opts.unit || '');
			const val = JSON.stringify(s.f('y'));
			const cx = 170, cy = 188; // the arc's centre, in view pixels
			const centre = { x: { value: cx }, y: { value: cy } };
			const arc = { type: 'arc', innerRadius: 96, outerRadius: 150, cornerRadius: 6 };
			const angle = (f0, f1) => ({ theta: { field: f0, type: 'quantitative', scale: null }, theta2: { field: f1 } });
			return {
				data: { values: s.records },
				// the gauge reads the first row
				transform: [
					{ window: [{ op: 'row_number', as: 'row' }] },
					{ filter: 'datum.row === 1' },
					{ calculate: `datum[${val}]`, as: 'v' },
					{ calculate: s.has('label') ? `datum[${JSON.stringify(s.f('label'))}]` : JSON.stringify(s.f('y')), as: 'name' },
					{ calculate: `max(0, min(1, (datum.v - ${lo}) / ${top - lo}))`, as: 'frac' },
					{ calculate: String(-half), as: 'a0' },
					{ calculate: String(half), as: 'a1' },
					{ calculate: `${-half} + datum.frac * ${Math.PI}`, as: 'av' },
					{ calculate: `format(datum.v, ',.2~f') + ${unit}`, as: 'text' },
				],
				width: 340, height: 210, autosize: { type: 'pad' },
				layer: [
					{ mark: arc, encoding: { ...centre, ...angle('a0', 'a1'), color: { value: '#eceae4' } } },
					{ mark: arc, encoding: { ...centre, ...angle('a0', 'av') } },
					{ mark: { type: 'text', fontSize: 34, fontWeight: 600 }, encoding: { ...centre, text: { field: 'text' } } },
					{ mark: { type: 'text', fontSize: 13, color: '#57606a', dy: 26 }, encoding: { ...centre, text: { field: 'name' } } },
				],
				view: { stroke: null },
			};
		},
	});


	/* ── Pictogram ──────────────────────────────────────────────────────── */

	// Icons are SVG paths in a [-1, 1] box (Vega scales a custom path shape from its symbol size).
	const ICONS = {
		person: 'M0,-1 a0.28,0.28 0 1,1 0,0.56 a0.28,0.28 0 1,1 0,-0.56 M-0.5,-0.3 h1 v0.8 h-0.28 v0.7 h-0.44 v-0.7 h-0.28 Z',
		circle: 'circle',
		square: 'square',
		diamond: 'diamond',
		triangle: 'triangle-up',
		cross: 'cross',
		heart: 'M0,0.95 C-1.1,0.1 -1,-0.7 -0.5,-0.8 C-0.2,-0.85 0,-0.6 0,-0.45 C0,-0.6 0.2,-0.85 0.5,-0.8 C1,-0.7 1.1,0.1 0,0.95 Z',
		drop: 'M0,-1 C0.5,-0.3 0.85,0.1 0.85,0.45 C0.85,0.85 0.45,1 0,1 C-0.45,1 -0.85,0.85 -0.85,0.45 C-0.85,0.1 -0.5,-0.3 0,-1 Z',
		star: 'M0,-1 L0.29,-0.4 L0.95,-0.31 L0.47,0.15 L0.59,0.81 L0,0.5 L-0.59,0.81 L-0.47,0.15 L-0.95,-0.31 L-0.29,-0.4 Z',
	};

	C.type({
		id: 'pictogram', group: 'composition', label: 'Pictogram', desc: 'Rows of icons, each standing for a quantity', sample: 'c_people',
		roles: [role('x', 'Category', 'any'), role('y', 'Amount', 'num')], options: ['agg', 'icon', 'pictoUnit'], sampleMap: { x: 'Group', y: 'People' },
		build(s) {
			const given = Number(s.opts.pictoUnit) > 0 ? Number(s.opts.pictoUnit) : 0;
			// automatic unit: the smallest round number (1, 2, 2.5, 5, 10 × a power of ten) that keeps the longest row to 12 icons
			const auto = [
				{ calculate: 'datum.top / 12', as: 'raw' },
				{ calculate: 'pow(10, floor(log(datum.raw) / LN10))', as: 'mag' },
				{ calculate: 'datum.raw / datum.mag <= 1 ? 1 : datum.raw / datum.mag <= 2 ? 2 : datum.raw / datum.mag <= 2.5 ? 2.5 : datum.raw / datum.mag <= 5 ? 5 : 10', as: 'mult' },
			];
			const shape = ICONS[s.opts.icon] || ICONS.person;
			const y = { field: 'cat', type: 'nominal', sort: null, axis: { title: null, domain: false, ticks: false, labelPadding: 8 } };
			const x = { type: 'quantitative', axis: null, scale: { domainMin: -0.5, padding: 30 } };
			return {
				data: { values: s.records },
				transform: [
					...perCategory(s, 'x', 'y'),
					...(given ? [{ calculate: String(given), as: 'unit' }] : [...auto, { calculate: 'datum.mult * datum.mag', as: 'unit' }]),
					{ calculate: 'round(datum.amount / datum.unit)', as: 'count' },
					{ calculate: "format(datum.amount, ',.2~f')", as: 'label' },
					{ calculate: "'1 icon = ' + format(datum.unit, ',.2~f')", as: 'note' },
				],
				layer: [
					{ transform: [{ calculate: 'sequence(0, datum.count)', as: 'cells' }, { flatten: ['cells'], as: ['k'] }], mark: { type: 'point', filled: true, shape, size: 340, opacity: 1, strokeWidth: 0 }, encoding: { x: { ...x, field: 'k' }, y, color: { field: 'cat', type: 'nominal', sort: null, legend: null } } },
					{ mark: { type: 'text', align: 'left', dx: 12, fontSize: 12, fontWeight: 600 }, encoding: { x: { ...x, field: 'count' }, y, text: { field: 'label' } } },
					{ transform: [{ filter: 'datum.i === 1' }], mark: { type: 'text', align: 'right', baseline: 'top', fontSize: 11, color: '#57606a', dy: 2 }, encoding: { x: { value: { expr: 'width' } }, y: { value: 0 }, text: { field: 'note' } } },
				],
				width: 360,
				config: { view: { stroke: null } },
			};
		},
	});


	/* ── Overlaps ───────────────────────────────────────────────────────── */

	/* ── Venn diagram ───────────────────────────────────────────────────── */


	// Circle centres and where each region's count sits, in view pixels. Two circles or three.
	const VENN = {
		2: { w: 400, h: 270, r: 95, c: [[150, 130], [250, 130]], names: [[150, 250], [250, 250]], at: { A: [105, 130], B: [295, 130], AB: [200, 130] } },
		3: { w: 400, h: 340, r: 85, c: [[150, 205], [250, 205], [200, 120]], names: [[150, 306], [250, 306], [200, 22]], at: { A: [112, 230], B: [288, 230], C: [200, 85], AB: [200, 245], AC: [155, 150], BC: [245, 150], ABC: [200, 180] } },
	};

	C.type({
		id: 'venn', group: 'relationship', label: 'Venn diagram', desc: 'Overlaps between two or three sets', sample: 'c_overlaps',
		roles: [role('x', 'Sets in the region (A & B)', 'any'), role('y', 'Items in exactly that region', 'num')], options: ['labels'], sampleMap: { x: 'Sets', y: 'Size' }, opts: { labels: true },
		build(s) {
			const split = (txt) => String(txt).split(/\s*[&,;|\u2229]\s*/).map((x) => x.trim()).filter(Boolean);
			const sets = [];
			for (const rec of s.records) { const names = split(rec[s.f('x')]); if (names.length === 1 && !sets.includes(names[0])) sets.push(names[0]); }
			for (const rec of s.records) for (const nm of split(rec[s.f('x')])) if (!sets.includes(nm)) sets.push(nm);
			if (sets.length < 2 || sets.length > 3) throw new Error(`A Venn diagram needs 2 or 3 sets; found ${sets.length}${sets.length ? ` (${sets.join(', ')})` : ''}.`);
			const g = VENN[sets.length], letters = ['A', 'B', 'C'].slice(0, sets.length);
			const col = JSON.stringify(s.f('x')), size = JSON.stringify(s.f('y'));
			const px = (axis) => ({ type: 'quantitative', scale: null, axis: null, ...axis });
			const parts = `split(trim(replace(datum[${col}], regexp('\\\\s*[&,;|\\u2229]\\\\s*', 'g'), '&')), '&')`;
			const has = (set) => `indexof(datum.parts, ${JSON.stringify(set)}) >= 0`;
			// A region's key is the letters of the sets it lies in (A, AB, ABC...), so its count can be placed by lookup.
			const key = letters.map((l, i) => `(${has(sets[i])} ? '${l}' : '')`).join(' + ');
			const mark = (extra) => ({ type: 'text', ...extra });
			const layers = [
				{ data: { values: sets.map((nm, i) => ({ set: nm, x: g.c[i][0], y: g.c[i][1], area: Math.round(Math.PI * g.r * g.r) })) },
					mark: { type: 'circle', opacity: 0.42, strokeWidth: 2, strokeOpacity: 1 },
					encoding: { x: px({ field: 'x' }), y: px({ field: 'y' }), size: { field: 'area', type: 'quantitative', scale: null, legend: null }, color: { field: 'set', type: 'nominal', sort: null, legend: null }, stroke: { field: 'set', type: 'nominal', sort: null, legend: null } } },
			];
			// one total per set, written beside its circle
			sets.forEach((nm, i) => layers.push({
				data: { values: s.records },
				transform: [
					{ calculate: parts, as: 'parts' },
					{ calculate: `${has(nm)} ? datum[${size}] : 0`, as: 'inside' },
					{ aggregate: [{ op: 'sum', field: 'inside', as: 'total' }] },
					{ calculate: `${JSON.stringify(nm)} + ' (' + format(datum.total, ',') + ')'`, as: 'label' },
				],
				mark: mark({ fontSize: 12 }),
				encoding: { x: { value: g.names[i][0] }, y: { value: g.names[i][1] }, text: { field: 'label' } },
			}));
			if (s.opts.labels !== false) layers.push({
				data: { values: s.records },
				transform: [
					{ calculate: parts, as: 'parts' },
					{ calculate: key, as: 'region' },
					{ aggregate: [{ op: 'sum', field: s.f('y'), as: 'count' }], groupby: ['region'] },
					{ lookup: 'region', from: { data: { values: letters.length === 2 ? Object.entries(g.at).map(([k, v]) => ({ region: k, px: v[0], py: v[1] })) : Object.entries(g.at).map(([k, v]) => ({ region: k, px: v[0], py: v[1] })) }, key: 'region', fields: ['px', 'py'] } },
				],
				mark: mark({ fontSize: 13, fontWeight: 600 }),
				encoding: { x: px({ field: 'px' }), y: px({ field: 'py' }), text: { field: 'count', type: 'quantitative', format: ',' } },
			});
			return { width: g.w, height: g.h, padding: 6, autosize: { type: 'pad' }, layer: layers, view: { stroke: null } };
		},
	});

	/* ── Flows ──────────────────────────────────────────────────────────── */

	C.sample('c_flows', 'From,To,Amount\nSolar,Grid,35\nWind,Grid,28\nGas,Grid,40\nCoal,Grid,22\nGrid,Homes,60\nGrid,Industry,45\nGrid,Transport,12\nGas,Industry,18\nGas,Homes,9\nWind,Industry,6');
	const flowRoles = [role('source', 'From', 'any'), role('target', 'To', 'any'), role('value', 'Amount (optional)', 'num', false)];
	/** Vega data steps shared by chord and Sankey: the user's rows as src / tgt / w, and one row per item with its in and out totals. */
	const flowData = (s) => [
		{ name: 'edges', values: s.records, transform: [
			{ type: 'formula', expr: `toString(${col(s.f('source'))})`, as: 'src' },
			{ type: 'formula', expr: `toString(${col(s.f('target'))})`, as: 'tgt' },
			{ type: 'formula', expr: s.has('value') ? `+${col(s.f('value'))} || 1` : '1', as: 'w' },
		] },
		{ name: 'ends', source: 'edges', transform: [
			{ type: 'formula', expr: '[{n: datum.src, o: datum.w, i: 0}, {n: datum.tgt, o: 0, i: datum.w}]', as: 'pair' },
			{ type: 'flatten', fields: ['pair'], as: ['p'] },
			{ type: 'formula', expr: 'datum.p.n', as: 'node' },
			{ type: 'formula', expr: 'datum.p.o', as: 'out' },
			{ type: 'formula', expr: 'datum.p.i', as: 'inn' },
		] },
	];

	// Pattern: Vega's arc-diagram and radial examples (data-driven nodes, `stack` for extents, `lookup` between datasets,
	// `path` marks with expression-built paths). Each node owns an arc of the circle sized by its total flow; each link is a
	// ribbon from a slice of the source's arc to a slice of the target's.
	C.type({
		id: 'chord', group: 'flow', label: 'Chord', desc: 'Connections between items around a circle', sample: 'c_flows', sampleMap: { source: 'From', target: 'To', value: 'Amount' },
		roles: flowRoles, options: [],
		build(s) {
			const pt = (a) => `radius * sin(datum.${a}) + ',' + (-radius * cos(datum.${a}))`;
			const ribbon = `'M' + ${pt('sa0')} + 'A' + radius + ',' + radius + ',0,0,1,' + ${pt('sa1')} + 'Q0,0,' + ${pt('ta0')} + 'A' + radius + ',' + radius + ',0,0,1,' + ${pt('ta1')} + 'Q0,0,' + ${pt('sa0')} + 'Z'`;
			const angle = (field) => `datum.${field} / datum.grand * 2 * PI`;
			return {
				$schema: C.VEGA_SCHEMA, width: 460, height: 460, padding: { left: 90, right: 90, top: 30, bottom: 30 }, autosize: 'pad',
				signals: [{ name: 'radius', value: 190 }, { name: 'band', value: 14 }],
				data: [
					...flowData(s),
					{ name: 'nodes', source: 'ends', transform: [
						{ type: 'aggregate', groupby: ['node'], ops: ['sum', 'sum'], fields: ['out', 'inn'], as: ['out', 'inn'] },
						{ type: 'formula', expr: 'datum.out + datum.inn', as: 'total' },
						{ type: 'stack', field: 'total', as: ['t0', 't1'] },
						{ type: 'joinaggregate', ops: ['sum'], fields: ['total'], as: ['grand'] },
						{ type: 'formula', expr: angle('t0'), as: 'a0' },
						{ type: 'formula', expr: angle('t1'), as: 'a1' },
						{ type: 'formula', expr: '(datum.a0 + datum.a1) / 2', as: 'am' },
					] },
					{ name: 'links', source: 'edges', transform: [
						{ type: 'stack', groupby: ['src'], field: 'w', sort: { field: 'tgt' }, as: ['so0', 'so1'] },
						{ type: 'stack', groupby: ['tgt'], field: 'w', sort: { field: 'src' }, as: ['ti0', 'ti1'] },
						{ type: 'lookup', from: 'nodes', key: 'node', fields: ['src'], values: ['t0', 'grand'], as: ['s0', 'grand'] },
						{ type: 'lookup', from: 'nodes', key: 'node', fields: ['tgt'], values: ['t0', 'out'], as: ['t0', 'tout'] },
						// a node's arc holds its outgoing slices first, then its incoming ones
						{ type: 'formula', expr: '(datum.s0 + datum.so0) / datum.grand * 2 * PI', as: 'sa0' },
						{ type: 'formula', expr: '(datum.s0 + datum.so1) / datum.grand * 2 * PI', as: 'sa1' },
						{ type: 'formula', expr: '(datum.t0 + datum.tout + datum.ti0) / datum.grand * 2 * PI', as: 'ta0' },
						{ type: 'formula', expr: '(datum.t0 + datum.tout + datum.ti1) / datum.grand * 2 * PI', as: 'ta1' },
						{ type: 'formula', expr: ribbon, as: 'ribbon' },
					] },
				],
				scales: [{ name: 'color', type: 'ordinal', domain: { data: 'nodes', field: 'node' }, range: { scheme: 'category10' } }],
				marks: [
					{ type: 'path', from: { data: 'links' }, encode: { enter: { x: { signal: 'width / 2' }, y: { signal: 'height / 2' }, path: { field: 'ribbon' }, fill: { scale: 'color', field: 'src' }, fillOpacity: { value: 0.55 }, stroke: { value: 'white' }, strokeWidth: { value: 0.5 }, tooltip: { signal: "datum.src + ' → ' + datum.tgt + ': ' + datum.w" } } } },
					{ type: 'arc', from: { data: 'nodes' }, encode: { enter: { x: { signal: 'width / 2' }, y: { signal: 'height / 2' }, startAngle: { field: 'a0' }, endAngle: { field: 'a1' }, innerRadius: { signal: 'radius' }, outerRadius: { signal: 'radius + band' }, fill: { scale: 'color', field: 'node' }, tooltip: { signal: "datum.node + ': ' + datum.total" } } } },
					{ type: 'text', from: { data: 'nodes' }, encode: { enter: { x: { signal: "width / 2 + (radius + band + 8) * sin(datum.am)" }, y: { signal: 'height / 2 - (radius + band + 8) * cos(datum.am)' }, text: { field: 'node' }, align: { signal: "sin(datum.am) > 0 ? 'left' : 'right'" }, baseline: { value: 'middle' }, fontSize: { value: 12 } } } },
				],
			};
		},
	});

	// Pattern: the same data steps, with `window` and `lookup` passes to find each item's column (an item sits one column
	// right of the furthest of its sources; eight passes cover chains up to eight columns), `stack` to size and place the
	// nodes, and thick `path` strokes for the links, as in Vega's stacked bar and arc examples.
	const PASSES = 8;
	C.type({
		id: 'sankey', group: 'flow', label: 'Sankey', desc: 'Quantities flowing between stages (up to eight columns)', sample: 'c_flows', sampleMap: { source: 'From', target: 'To', value: 'Amount' },
		roles: flowRoles, options: [],
		build(s) {
			const data = [
				...flowData(s),
				{ name: 'nodes0', source: 'ends', transform: [
					{ type: 'aggregate', groupby: ['node'], ops: ['sum', 'sum'], fields: ['out', 'inn'], as: ['out', 'inn'] },
					{ type: 'formula', expr: 'max(datum.out, datum.inn)', as: 'value' },
					{ type: 'formula', expr: '0', as: 'd0' },
				] },
			];
			for (let k = 1; k <= PASSES; k++) {
				data.push(
					{ name: `via${k}`, source: 'edges', transform: [
						{ type: 'lookup', from: `nodes${k - 1}`, key: 'node', fields: ['src'], values: [`d${k - 1}`], as: ['sd'] },
						{ type: 'aggregate', groupby: ['tgt'], ops: ['max'], fields: ['sd'], as: ['dm'] },
					] },
					{ name: `nodes${k}`, source: `nodes${k - 1}`, transform: [
						{ type: 'lookup', from: `via${k}`, key: 'tgt', fields: ['node'], values: ['dm'], as: ['dm'], default: -1 },
						{ type: 'formula', expr: 'datum.dm + 1', as: `d${k}` },
					] },
				);
			}
			data.push(
				{ name: 'nodes', source: `nodes${PASSES}`, transform: [
					{ type: 'formula', expr: `datum.d${PASSES}`, as: 'depth' },
					{ type: 'joinaggregate', ops: ['max'], fields: ['depth'], as: ['lastDepth'] },
					{ type: 'stack', groupby: ['depth'], field: 'value', sort: { field: 'node' }, as: ['v0', 'v1'] },
					{ type: 'window', ops: ['row_number'], as: ['rank'], groupby: ['depth'], sort: { field: 'node' } },
					{ type: 'joinaggregate', groupby: ['depth'], ops: ['sum', 'count'], fields: ['value', 'value'], as: ['colTotal', 'colCount'] },
					{ type: 'joinaggregate', ops: ['max', 'max'], fields: ['colTotal', 'colCount'], as: ['maxTotal', 'maxCount'] },
					{ type: 'formula', expr: '(height - gap * (datum.maxCount - 1)) / datum.maxTotal', as: 'ky' },
					{ type: 'formula', expr: 'datum.v0 * datum.ky + (datum.rank - 1) * gap', as: 'y0' },
					{ type: 'formula', expr: 'datum.y0 + datum.value * datum.ky', as: 'y1' },
					{ type: 'formula', expr: 'datum.lastDepth ? datum.depth / datum.lastDepth * (width - nodeWidth) : 0', as: 'x0' },
					{ type: 'formula', expr: 'datum.x0 + nodeWidth', as: 'x1' },
				] },
				{ name: 'links', source: 'edges', transform: [
					{ type: 'lookup', from: 'nodes', key: 'node', fields: ['src'], values: ['x1', 'y0', 'ky'], as: ['sx', 'sy', 'ky'] },
					{ type: 'lookup', from: 'nodes', key: 'node', fields: ['tgt'], values: ['x0', 'y0'], as: ['tx', 'ty'] },
					{ type: 'stack', groupby: ['src'], field: 'w', sort: { field: 'ty' }, as: ['so0', 'so1'] },
					{ type: 'stack', groupby: ['tgt'], field: 'w', sort: { field: 'sy' }, as: ['ti0', 'ti1'] },
					{ type: 'formula', expr: 'datum.sy + (datum.so0 + datum.so1) / 2 * datum.ky', as: 'yA' },
					{ type: 'formula', expr: 'datum.ty + (datum.ti0 + datum.ti1) / 2 * datum.ky', as: 'yB' },
					{ type: 'formula', expr: "'M' + datum.sx + ',' + datum.yA + 'C' + (datum.sx + datum.tx) / 2 + ',' + datum.yA + ',' + (datum.sx + datum.tx) / 2 + ',' + datum.yB + ',' + datum.tx + ',' + datum.yB", as: 'curve' },
					{ type: 'formula', expr: 'datum.w * datum.ky', as: 'thick' },
				] },
			);
			return {
				$schema: C.VEGA_SCHEMA, width: 520, height: 320, padding: { left: 10, right: 90, top: 10, bottom: 10 }, autosize: 'pad',
				signals: [{ name: 'nodeWidth', value: 14 }, { name: 'gap', value: 12 }],
				data,
				scales: [{ name: 'color', type: 'ordinal', domain: { data: 'nodes', field: 'node' }, range: { scheme: 'category10' } }],
				marks: [
					{ type: 'path', from: { data: 'links' }, encode: { enter: { path: { field: 'curve' }, stroke: { scale: 'color', field: 'src' }, strokeOpacity: { value: 0.45 }, strokeWidth: { field: 'thick' }, fill: { value: null }, tooltip: { signal: "datum.src + ' → ' + datum.tgt + ': ' + datum.w" } } } },
					{ type: 'rect', from: { data: 'nodes' }, encode: { enter: { x: { field: 'x0' }, x2: { field: 'x1' }, y: { field: 'y0' }, y2: { field: 'y1' }, fill: { scale: 'color', field: 'node' }, tooltip: { signal: "datum.node + ': ' + datum.value" } } } },
					{ type: 'text', from: { data: 'nodes' }, encode: { enter: { x: { signal: 'datum.depth === datum.lastDepth ? datum.x1 + 6 : datum.x0 - 6' }, y: { signal: '(datum.y0 + datum.y1) / 2' }, text: { field: 'node' }, align: { signal: "datum.depth === datum.lastDepth ? 'left' : 'right'" }, baseline: { value: 'middle' }, fontSize: { value: 12 } } } },
				],
			};
		},
	});
})(typeof window !== 'undefined' ? window : globalThis);
