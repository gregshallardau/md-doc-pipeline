/*
 * Chart types: distributions and uncertainty. See chart-core.js for the registration API.
 * Shared byte-for-byte with md-doc-pipeline's studio.
 */
(function (root) {
	'use strict';
	const C = root.ChartCatalog;
	const { q, axis, noLegend, wrap, layers, r, distinct, rng } = C.h;

	const role = (key, label, kind = 'any', required = true, extra) => ({ key, label, kind, required, ...extra });
	const VALUE = role('x', 'Values', 'num');
	const GROUP_REQ = role('color', 'Group', 'cat', true);
	const GROUP = role('color', 'Group (optional)', 'cat', false);

	C.option('bins', { label: 'Bins (about)', kind: 'number', default: 12, min: 3, max: 60 });
	C.option('bandwidth', { label: 'Smoothing (0 = automatic)', kind: 'number', default: 0, min: 0, max: 50 });
	C.option('errorKind', { label: 'Error bars show', kind: 'select', default: 'ci', choices: [['ci', 'Mean ± 95% confidence interval'], ['stderr', 'Mean ± standard error'], ['stdev', 'Mean ± standard deviation'], ['iqr', 'Median with interquartile range']] });
	C.option('overlap', { label: 'Groups overlap', kind: 'check', default: false });
	C.option('extent', { label: 'Whiskers reach', kind: 'select', default: '1.5', choices: [['1.5', '1.5 × IQR (outliers shown)'], ['min-max', 'Minimum to maximum']] });

	/* ── Samples ────────────────────────────────────────────────────────── */

	const normal = (rand) => Math.sqrt(-2 * Math.log(rand() || 1e-9)) * Math.cos(2 * Math.PI * rand());
	C.sample('distribution', 'Score\n52\n58\n61\n64\n66\n67\n68\n70\n71\n71\n72\n74\n75\n77\n78\n80\n83\n85\n91');
	C.sample('groups', () => {
		const rand = rng(3);
		const rows = ['Group,Score'];
		for (const [g, mean, sd] of [['Control', 62, 9], ['Method A', 71, 8], ['Method B', 78, 11]]) {
			for (let i = 0; i < 40; i++) rows.push(`${g},${Math.round((mean + normal(rand) * sd) * 10) / 10}`);
		}
		return rows.join('\n');
	});
	C.sample('replicates', () => {
		const rand = rng(9);
		const rows = ['Treatment,Response'];
		for (const [g, mean, sd] of [['Placebo', 4.1, 1.1], ['Low dose', 5.3, 1.2], ['Mid dose', 6.4, 1.0], ['High dose', 7.2, 1.4]]) {
			for (let i = 0; i < 12; i++) rows.push(`${g},${Math.round((mean + normal(rand) * sd) * 100) / 100}`);
		}
		return rows.join('\n');
	});
	C.sample('trials', () => {
		const rand = rng(13);
		const rows = ['Week,Reading'];
		for (let w = 1; w <= 10; w++) for (let i = 0; i < 8; i++) rows.push(`${w},${Math.round((20 + w * 1.6 + normal(rand) * 2.5) * 10) / 10}`);
		return rows.join('\n');
	});

	/* ── Histograms ─────────────────────────────────────────────────────── */

	const maxbins = (s) => Math.max(3, Math.min(60, Math.round(Number(s.opts.bins) || 12)));
	const histX = (s, extra) => q(s.f('x'), { bin: { maxbins: maxbins(s) }, axis: { title: s.opts.xTitle || s.f('x') }, ...extra });
	const countY = (s) => ({ aggregate: 'count', type: 'quantitative', axis: { title: s.opts.yTitle || 'Count' } });

	C.type({
		id: 'histogram', group: 'distribution', label: 'Histogram', desc: 'How a number is distributed', sample: 'distribution',
		roles: [VALUE], options: ['bins'],
		build: (s) => wrap(s, { type: 'bar', cornerRadiusEnd: 2 }, { x: histX(s), y: countY(s) }),
	});

	C.type({
		id: 'histogram-grouped', group: 'distribution', label: 'Histogram by group', desc: 'Compare distributions across groups', sample: 'groups',
		roles: [VALUE, GROUP_REQ], options: ['bins', 'overlap', 'legend'], sampleMap: { x: 'Score', color: 'Group' },
		build(s) {
			const color = { field: s.f('color'), type: 'nominal', ...noLegend(s) };
			const y = countY(s);
			if (s.opts.overlap) y.stack = null;
			return wrap(s, { type: 'bar', cornerRadiusEnd: 2, opacity: s.opts.overlap ? 0.6 : 1 }, { x: histX(s), y, color });
		},
	});

	C.type({
		id: 'dot-histogram', group: 'distribution', label: 'Dot histogram', desc: 'Each observation is a dot, stacked in bins', sample: 'distribution',
		roles: [VALUE], options: ['bins'],
		build(s) {
			const x = s.f('x');
			return {
				data: { values: s.records },
				transform: [
					{ bin: { maxbins: maxbins(s) }, field: x, as: ['_b0', '_b1'] },
					{ window: [{ op: 'rank', as: '_stack' }], groupby: ['_b0', '_b1'] },
				],
				mark: { type: 'circle', opacity: 1, size: 160 },
				encoding: {
					x: q('_b0', { bin: { binned: true }, axis: { title: s.opts.xTitle || x } }),
					x2: { field: '_b1' },
					y: q('_stack', { axis: { title: s.opts.yTitle || 'Count', tickMinStep: 1, format: 'd' }, scale: { domain: [0, Math.max(3, Math.ceil(s.records.length / 4))] } }),
				},
			};
		},
	});

	/* ── Density ────────────────────────────────────────────────────────── */

	const densityTransform = (s, groupby) => ({ density: s.f('x'), ...(groupby ? { groupby: [groupby] } : {}), ...(Number(s.opts.bandwidth) > 0 ? { bandwidth: Number(s.opts.bandwidth) } : {}), as: ['_value', '_density'] });

	C.type({
		id: 'density', group: 'distribution', label: 'Density', desc: 'A smooth curve of how values are spread', sample: 'distribution',
		roles: [VALUE], options: ['bandwidth'],
		build: (s) => ({
			data: { values: s.records },
			transform: [densityTransform(s)],
			mark: { type: 'area', opacity: 0.5, line: true },
			encoding: { x: q('_value', { axis: { title: s.opts.xTitle || s.f('x') } }), y: q('_density', { axis: { title: s.opts.yTitle || 'Density' } }) },
		}),
	});

	C.type({
		id: 'density-groups', group: 'distribution', label: 'Density by group', desc: 'Overlaid curves, one per group', sample: 'groups',
		roles: [VALUE, GROUP_REQ], options: ['bandwidth', 'legend'], sampleMap: { x: 'Score', color: 'Group' },
		build: (s) => ({
			data: { values: s.records },
			transform: [densityTransform(s, s.f('color'))],
			mark: { type: 'area', opacity: 0.4, line: true },
			encoding: {
				x: q('_value', { axis: { title: s.opts.xTitle || s.f('x') } }),
				y: q('_density', { stack: null, axis: { title: s.opts.yTitle || 'Density' } }),
				color: { field: s.f('color'), type: 'nominal', ...noLegend(s) },
			},
		}),
	});

	C.type({
		id: 'ridgeline', group: 'distribution', label: 'Ridgeline', desc: 'Stacked density curves, one row per group', sample: 'groups',
		roles: [VALUE, GROUP_REQ], options: ['bandwidth'], sampleMap: { x: 'Score', color: 'Group' },
		build(s) {
			const groups = distinct(s.records, s.f('color'));
			return {
				data: { values: s.records },
				transform: [densityTransform(s, s.f('color'))],
				width: 'container',
				height: Math.max(36, Math.round(230 / groups.length)),
				mark: { type: 'area', fillOpacity: 0.6, line: true, interpolate: 'monotone' },
				encoding: {
					x: q('_value', { axis: { title: s.opts.xTitle || s.f('x') } }),
					y: q('_density', { axis: null }),
					color: { field: s.f('color'), type: 'nominal', legend: null },
					row: { field: s.f('color'), type: 'nominal', sort: groups, header: { title: null, labelAngle: 0, labelAlign: 'left', labelPadding: 6 } },
				},
				spacing: -14,
				config: { view: { stroke: null } },
			};
		},
	});

	/* ── Box, violin, strip ─────────────────────────────────────────────── */

	C.type({
		id: 'box', group: 'distribution', label: 'Box plot', desc: 'Median, quartiles and outliers per group', sample: 'groups',
		roles: [role('y', 'Values', 'num'), role('x', 'Group (optional)', 'cat', false)], options: ['extent', 'legend'], sampleMap: { y: 'Score', x: 'Group' },
		build(s) {
			const extent = s.opts.extent === 'min-max' ? 'min-max' : 1.5;
			const enc = { y: q(s.f('y'), { scale: { zero: false }, axis: { title: s.opts.yTitle || s.f('y') } }) };
			if (s.has('x')) {
				enc.x = { field: s.f('x'), type: 'nominal', sort: null, axis: { title: s.opts.xTitle || null, labelAngle: 0 } };
				enc.color = { field: s.f('x'), type: 'nominal', legend: null };
			}
			return wrap(s, { type: 'boxplot', extent, size: 46 }, enc);
		},
	});

	C.type({
		id: 'violin', group: 'distribution', label: 'Violin', desc: 'The full shape of each group’s distribution', sample: 'groups',
		roles: [role('y', 'Values', 'num'), role('x', 'Group', 'cat', true)], options: ['bandwidth'], sampleMap: { y: 'Score', x: 'Group' },
		build(s) {
			const groups = distinct(s.records, s.f('x'));
			const ys = s.records.map((rec) => rec[s.f('y')]).filter((v) => typeof v === 'number');
			const span = Math.max(...ys) - Math.min(...ys) || 1;
			return {
				data: { values: s.records },
				transform: [{ density: s.f('y'), groupby: [s.f('x')], ...(Number(s.opts.bandwidth) > 0 ? { bandwidth: Number(s.opts.bandwidth) } : {}), extent: [r(Math.min(...ys) - span * 0.15), r(Math.max(...ys) + span * 0.15)], as: ['_value', '_density'] }],
				width: 90,
				mark: { type: 'area', orient: 'horizontal' },
				encoding: {
					y: q('_value', { axis: { title: s.opts.yTitle || s.f('y') } }),
					x: q('_density', { stack: 'center', impute: null, title: null, axis: { labels: false, values: [0], grid: true, ticks: false } }),
					color: { field: s.f('x'), type: 'nominal', legend: null },
					column: { field: s.f('x'), type: 'nominal', sort: groups, spacing: 0, header: { title: null, labelOrient: 'bottom', labelPadding: 6 } },
				},
				config: { view: { stroke: null }, facet: { spacing: 0 } },
			};
		},
	});

	C.type({
		id: 'strip', group: 'distribution', label: 'Strip plot', desc: 'Every observation as a dot, jittered', sample: 'groups',
		roles: [role('y', 'Values', 'num'), role('x', 'Group', 'cat', true)], options: ['legend'], sampleMap: { y: 'Score', x: 'Group' },
		build(s) {
			// Jitter is fixed here (not random() at render time) so the chart is identical everywhere.
			const rand = rng(17);
			const records = s.records.map((rec) => ({ ...rec, _jitter: r(rand() * 2 - 1, 3) }));
			return {
				data: { values: records },
				mark: { type: 'circle', opacity: 0.75, size: 60 },
				encoding: {
					x: { field: s.f('x'), type: 'nominal', sort: null, axis: { title: s.opts.xTitle || null, labelAngle: 0 } },
					xOffset: { field: '_jitter', type: 'quantitative', scale: { domain: [-1, 1], range: [-34, 34] } },
					y: q(s.f('y'), { scale: { zero: false }, axis: { title: s.opts.yTitle || s.f('y') } }),
					color: { field: s.f('x'), type: 'nominal', legend: null },
				},
			};
		},
	});

	/* ── Uncertainty ────────────────────────────────────────────────────── */

	/*
	 * Error bars and bands are built from plain aggregates (mean, standard error, standard deviation,
	 * quartiles). Vega-Lite's own `errorbar` mark bootstraps its confidence interval from random
	 * resamples, so the chart would change on every build and differ between a document and a slide.
	 */
	const SPREAD = { ci: ['_mean', 'datum._mean - 1.959964 * datum._se', 'datum._mean + 1.959964 * datum._se', 'mean ± 95% confidence interval (normal approximation)'], stderr: ['_mean', 'datum._mean - datum._se', 'datum._mean + datum._se', 'mean ± standard error'], stdev: ['_mean', 'datum._mean - datum._sd', 'datum._mean + datum._sd', 'mean ± standard deviation'], iqr: ['_med', 'datum._q1', 'datum._q3', 'median with the interquartile range'] };
	const spreadTransform = (field, groupby, kind) => {
		const [centre, lo, hi] = SPREAD[kind] || SPREAD.ci;
		return { transforms: [
			{ aggregate: [{ op: 'mean', field, as: '_mean' }, { op: 'stderr', field, as: '_se' }, { op: 'stdev', field, as: '_sd' }, { op: 'q1', field, as: '_q1' }, { op: 'median', field, as: '_med' }, { op: 'q3', field, as: '_q3' }], groupby },
			{ calculate: lo, as: '_lo' }, { calculate: hi, as: '_hi' },
		], centre };
	};

	C.type({
		id: 'error-bars', group: 'distribution', label: 'Error bars', desc: 'Group means with confidence or spread', sample: 'replicates',
		roles: [role('x', 'Group', 'any'), role('y', 'Measurements', 'num')], options: ['errorKind', 'points'], opts: { points: false, errorKind: 'ci' },
		build(s) {
			const x = { field: s.f('x'), type: 'ordinal', sort: null, axis: { title: s.opts.xTitle || null, labelAngle: 0 } };
			const { transforms, centre } = spreadTransform(s.f('y'), [s.f('x')], s.opts.errorKind);
			const yAxis = { title: s.opts.yTitle || s.f('y') };
			const stat = (field, extra) => q(field, { scale: { zero: false }, axis: yAxis, ...extra });
			const ink = '#57606a';
			const parts = [
				{ transform: transforms, mark: { type: 'bar', opacity: 0.35, cornerRadiusEnd: 2 }, encoding: { x, y: stat(centre) } },
				{ transform: transforms, mark: { type: 'rule', strokeWidth: 2, color: ink }, encoding: { x, y: stat('_lo'), y2: { field: '_hi' } } },
				{ transform: transforms, mark: { type: 'tick', thickness: 2, size: 14, color: ink }, encoding: { x, y: stat('_lo') } },
				{ transform: transforms, mark: { type: 'tick', thickness: 2, size: 14, color: ink }, encoding: { x, y: stat('_hi') } },
			];
			if (s.opts.points) parts.push({ mark: { type: 'point', filled: true, size: 20, opacity: 0.6, color: '#57606a' }, encoding: { x, y: stat(s.f('y')) } });
			return layers(s, parts);
		},
	});

	C.type({
		id: 'error-band', group: 'distribution', label: 'Confidence band', desc: 'A trend line with its uncertainty', sample: 'trials',
		roles: [role('x', 'X (number or date)', 'time'), role('y', 'Measurements', 'num')], options: ['errorKind'], opts: { errorKind: 'ci' }, sampleMap: { x: 'Week', y: 'Reading' },
		build(s) {
			const kind = s.kind(s.f('x')) === 'temporal' ? 'temporal' : s.kind(s.f('x')) === 'quantitative' ? 'quantitative' : 'ordinal';
			const x = { field: s.f('x'), type: kind, ...C.h.xAxis(s, kind) };
			const { transforms, centre } = spreadTransform(s.f('y'), [s.f('x')], s.opts.errorKind);
			const yAxis = { title: s.opts.yTitle || s.f('y') };
			return layers(s, [
				{ transform: transforms, mark: { type: 'area', opacity: 0.3 }, encoding: { x, y: q('_lo', { scale: { zero: false }, axis: yAxis }), y2: { field: '_hi' } } },
				{ transform: transforms, mark: { type: 'line', strokeWidth: 3 }, encoding: { x, y: q(centre, { scale: { zero: false }, axis: yAxis }) } },
			]);
		},
	});

	C.type({
		id: 'ecdf', group: 'distribution', label: 'Cumulative distribution', desc: 'Share of values at or below each point', sample: 'groups',
		roles: [VALUE, GROUP], options: ['legend'], sampleMap: { x: 'Score', color: 'Group' },
		build(s) {
			const x = s.f('x');
			const group = s.has('color') ? [s.f('color')] : [];
			const color = s.has('color') ? { color: { field: s.f('color'), type: 'nominal', ...noLegend(s) } } : {};
			return {
				data: { values: s.records },
				transform: [
					{ joinaggregate: [{ op: 'count', as: '_n' }], groupby: group },
					{ window: [{ op: 'count', as: '_cum' }], sort: [{ field: x }], frame: [null, 0], groupby: group },
					{ calculate: 'datum._cum / datum._n', as: '_share' },
				],
				mark: { type: 'line', interpolate: 'step-after', strokeWidth: 2.5 },
				encoding: { x: q(x, { scale: { zero: false }, axis: { title: s.opts.xTitle || x } }), y: q('_share', { axis: { title: s.opts.yTitle || 'Share of values', format: '%' }, scale: { domain: [0, 1] } }), ...color },
			};
		},
	});

	/** Inverse of the standard normal CDF (Acklam's rational approximation). */
	function probit(p) {
		const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
		const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
		const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
		const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
		const lo = 0.02425;
		if (p < lo) { const q2 = Math.sqrt(-2 * Math.log(p)); return (((((c[0] * q2 + c[1]) * q2 + c[2]) * q2 + c[3]) * q2 + c[4]) * q2 + c[5]) / ((((d[0] * q2 + d[1]) * q2 + d[2]) * q2 + d[3]) * q2 + 1); }
		if (p > 1 - lo) { const q2 = Math.sqrt(-2 * Math.log(1 - p)); return -(((((c[0] * q2 + c[1]) * q2 + c[2]) * q2 + c[3]) * q2 + c[4]) * q2 + c[5]) / ((((d[0] * q2 + d[1]) * q2 + d[2]) * q2 + d[3]) * q2 + 1); }
		const q2 = p - 0.5, t = q2 * q2;
		return (((((a[0] * t + a[1]) * t + a[2]) * t + a[3]) * t + a[4]) * t + a[5]) * q2 / (((((b[0] * t + b[1]) * t + b[2]) * t + b[3]) * t + b[4]) * t + 1);
	}

	C.type({
		id: 'qq-plot', group: 'distribution', label: 'Q–Q plot', desc: 'Are the values normally distributed?', sample: 'groups',
		roles: [VALUE, GROUP], options: ['legend'], sampleMap: { x: 'Score', color: 'Group' },
		build(s) {
			const col = s.f('x');
			const groups = s.has('color') ? distinct(s.records, s.f('color')) : [null];
			const data = [];
			for (const g of groups) {
				const vals = s.records.filter((rec) => g === null || rec[s.f('color')] === g).map((rec) => rec[col]).filter((v) => typeof v === 'number').sort((a, b) => a - b);
				vals.forEach((v, i) => data.push({ theory: r(probit((i + 0.5) / vals.length), 4), sample: v, group: g === null ? 'Values' : String(g) }));
			}
			const color = { field: 'group', type: 'nominal', ...(s.has('color') ? noLegend(s) : { legend: null }) };
			const x = q('theory', { axis: { title: s.opts.xTitle || 'Theoretical quantiles (normal)' } });
			const y = q('sample', { scale: { zero: false }, axis: { title: s.opts.yTitle || col } });
			return {
				data: { values: data },
				layer: [
					{ transform: [{ regression: 'sample', on: 'theory', groupby: ['group'] }], mark: { type: 'line', strokeWidth: 2, opacity: 0.6 }, encoding: { x: { field: 'theory', type: 'quantitative' }, y: { field: 'sample', type: 'quantitative' }, color } },
					{ mark: { type: 'point', filled: true, size: 55, opacity: 0.8 }, encoding: { x, y, color } },
				],
			};
		},
	});
})(typeof window !== 'undefined' ? window : globalThis);
