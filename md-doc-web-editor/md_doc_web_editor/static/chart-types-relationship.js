/*
 * Chart types: relationships between measures. See chart-core.js for the registration API.
 * Shared byte-for-byte with md-doc-pipeline's studio.
 */
(function (root) {
	'use strict';
	const C = root.ChartCatalog;
	const { at, q, axis, noLegend, wrap, layers, r, distinct, rng } = C.h;

	const role = (key, label, kind = 'any', required = true, extra) => ({ key, label, kind, required, ...extra });
	const X_NUM = role('x', 'X (number)', 'num');
	const Y_NUM = role('y', 'Y (number)', 'num');
	const COLOR = role('color', 'Colour by (optional)', 'any', false);

	C.option('regression', { label: 'Trend line', kind: 'select', default: 'linear', choices: [['linear', 'Straight line'], ['poly', 'Polynomial curve'], ['loess', 'Smoothed (LOESS)'], ['log', 'Logarithmic'], ['exp', 'Exponential'], ['pow', 'Power']] });
	C.option('order', { label: 'Polynomial order', kind: 'number', default: 2, min: 2, max: 6 });

	/* ── Samples ────────────────────────────────────────────────────────── */

	const normal = (rand) => Math.sqrt(-2 * Math.log(rand() || 1e-9)) * Math.cos(2 * Math.PI * rand());
	C.sample('points', 'Height,Weight,Group\n150,52,A\n160,58,A\n165,63,B\n172,70,B\n180,82,A\n185,88,B\n158,55,A\n170,68,B\n176,74,A\n168,66,B\n155,54,A\n183,85,B');
	C.sample('relation', () => {
		const rand = rng(31);
		const rows = ['Hours,Score,Class'];
		for (let i = 0; i < 40; i++) {
			const hours = Math.round((1 + rand() * 9) * 10) / 10;
			rows.push(`${hours},${Math.round(38 + hours * 5.2 - hours * hours * 0.18 + normal(rand) * 4.5)},${i % 2 ? 'Evening' : 'Day'}`);
		}
		return rows.join('\n');
	});
	C.sample('bubbles', 'Country,Income,LifeExpectancy,Population,Region\nAlgeria,13000,76,44,Africa\nBrazil,15000,76,214,Americas\nChina,17000,78,1412,Asia\nEgypt,11000,72,109,Africa\nFrance,48000,83,68,Europe\nIndia,6900,70,1408,Asia\nJapan,42000,85,125,Asia\nMexico,20000,75,128,Americas\nNigeria,5200,53,218,Africa\nSweden,56000,83,10,Europe\nUSA,70000,79,332,Americas\nGermany,53000,81,83,Europe');
	C.sample('journey', 'Year,Miles,Cost\n1956,3600,2.4\n1961,3700,2.5\n1966,3900,2.6\n1971,4100,3.1\n1976,3950,3.9\n1981,3600,5.0\n1986,3500,3.7\n1991,3800,3.6\n1996,3900,3.9\n2001,4150,4.6\n2006,4300,6.4\n2011,4150,9.0');
	C.sample('flowers', () => {
		const rand = rng(41);
		const rows = ['Species,SepalLength,SepalWidth,PetalLength,PetalWidth'];
		for (const [sp, a, b, c, d] of [['Setosa', 5.0, 3.4, 1.5, 0.25], ['Versicolor', 5.9, 2.8, 4.3, 1.3], ['Virginica', 6.6, 3.0, 5.5, 2.0]]) {
			for (let i = 0; i < 10; i++) rows.push([sp, a + normal(rand) * 0.35, b + normal(rand) * 0.25, c + normal(rand) * 0.3, d + normal(rand) * 0.15].map((v, k) => (k ? Math.round(v * 10) / 10 : v)).join(','));
		}
		return rows.join('\n');
	});

	/* ── Scatter family ─────────────────────────────────────────────────── */

	const colorEnc = (s) => (s.has('color') ? { color: { field: s.f('color'), type: s.kind(s.f('color')) === 'quantitative' ? 'quantitative' : 'nominal', ...noLegend(s) } } : {});
	const xy = (s) => ({ x: q(s.f('x'), { scale: { zero: false }, axis: { title: s.opts.xTitle || s.f('x') } }), y: q(s.f('y'), { scale: { zero: false }, axis: { title: s.opts.yTitle || s.f('y') } }) });

	C.type({
		id: 'scatter', group: 'relationship', label: 'Scatter', desc: 'Relationship between two numbers', sample: 'points',
		roles: [X_NUM, Y_NUM, COLOR, role('size', 'Size by (optional)', 'num', false)], options: ['legend'], defaults: { color: 'Group' },
		build(s) {
			const enc = { ...xy(s), ...colorEnc(s) };
			if (s.has('size')) enc.size = q(s.f('size'));
			return wrap(s, { type: 'point', filled: true, opacity: 0.8, size: s.has('size') ? undefined : 90 }, enc);
		},
	});

	C.type({
		id: 'bubble', group: 'relationship', label: 'Bubble', desc: 'Scatter with a third number as size', sample: 'bubbles',
		roles: [X_NUM, Y_NUM, role('size', 'Size (number)', 'num'), role('color', 'Colour by', 'cat', false), role('label', 'Label (optional)', 'cat', false)], options: ['legend', 'labels'],
		sampleMap: { x: 'Income', y: 'LifeExpectancy', size: 'Population', color: 'Region', label: 'Country' }, opts: { labels: true },
		build(s) {
			const enc = { ...xy(s), size: q(s.f('size'), { scale: { range: [60, 1400] }, legend: null }), ...colorEnc(s) };
			enc.x.scale = { type: 'log' };
			enc.x.axis = { ...enc.x.axis, grid: false, tickCount: 5 };
			const parts = [{ mark: { type: 'circle', opacity: 0.7, stroke: 'white', strokeWidth: 1 }, encoding: enc }];
			if (s.opts.labels && s.has('label')) parts.push({ mark: { type: 'text', dy: -14, fontSize: 10 }, encoding: { x: enc.x, y: enc.y, text: { field: s.f('label'), type: 'nominal' } } });
			return layers(s, parts);
		},
	});

	C.type({
		id: 'scatter-trend', group: 'relationship', label: 'Scatter with trend line', desc: 'Points plus a fitted line or curve', sample: 'relation',
		roles: [X_NUM, Y_NUM, COLOR], options: ['regression', 'order', 'legend'], sampleMap: { x: 'Hours', y: 'Score' },
		build(s) {
			const method = s.opts.regression || 'linear';
			const group = s.has('color') ? { groupby: [s.f('color')] } : {};
			const base = xy(s);
			const color = colorEnc(s);
			// LOESS is its own transform; the others are `regression` methods.
			const reg = method === 'loess'
				? { loess: s.f('y'), on: s.f('x'), bandwidth: 0.5, ...group }
				: { regression: s.f('y'), on: s.f('x'), method, ...(method === 'poly' ? { order: Math.max(2, Math.round(Number(s.opts.order) || 2)) } : {}), ...group };
			return {
				data: { values: s.records },
				layer: [
					{ mark: { type: 'point', filled: true, opacity: 0.55, size: 70 }, encoding: { ...base, ...color } },
					{ transform: [reg], mark: { type: 'line', strokeWidth: 3 }, encoding: { x: { field: s.f('x'), type: 'quantitative' }, y: { field: s.f('y'), type: 'quantitative' }, ...color } },
				],
			};
		},
	});

	C.type({
		id: 'connected-scatter', group: 'relationship', label: 'Connected scatter', desc: 'Two measures traced through time', sample: 'journey',
		roles: [X_NUM, Y_NUM, role('order', 'Order by (time)', 'time')], options: ['labels'], sampleMap: { x: 'Miles', y: 'Cost', order: 'Year' }, opts: { labels: true },
		build(s) {
			const o = s.f('order');
			const e = xy(s);
			const order = { field: o, type: s.kind(o) === 'temporal' ? 'temporal' : 'quantitative' };
			const parts = [
				{ mark: { type: 'line', strokeWidth: 2, point: { filled: true, size: 60, opacity: 1 } }, encoding: { ...e, order } },
			];
			if (s.opts.labels) parts.push({ mark: { type: 'text', dy: -10, fontSize: 10 }, encoding: { ...e, text: { field: o, type: 'ordinal' } } });
			return layers(s, parts);
		},
	});

	C.type({
		id: 'scatter-matrix', group: 'relationship', label: 'Scatter matrix', desc: 'Every number against every other', sample: 'flowers',
		roles: [role('cols', 'Numeric columns (2 or more)', 'num', true, { multi: true, min: 2, max: 5 }), role('color', 'Colour by (optional)', 'cat', false)], options: ['legend'], defaults: { color: 'Species' },
		build(s) {
			const cols = s.list('cols');
			const enc = {
				x: { field: { repeat: 'column' }, type: 'quantitative', scale: { zero: false }, axis: { labelFontSize: 9, titleFontSize: 10 } },
				y: { field: { repeat: 'row' }, type: 'quantitative', scale: { zero: false }, axis: { labelFontSize: 9, titleFontSize: 10, minExtent: 28 } },
				...colorEnc(s),
			};
			const side = Math.round(480 / cols.length);
			return {
				data: { values: s.records },
				repeat: { row: cols, column: [...cols].reverse() },
				spec: { width: side, height: side, mark: { type: 'point', filled: true, size: 28, opacity: 0.75 }, encoding: enc },
			};
		},
	});

	C.type({
		id: 'parallel', group: 'relationship', label: 'Parallel coordinates', desc: 'Each row as a line across many measures', sample: 'flowers',
		roles: [role('cols', 'Numeric columns (3 or more)', 'num', true, { multi: true, min: 3, max: 8 }), role('color', 'Colour by (optional)', 'cat', false)], options: ['legend'], defaults: { color: 'Species' },
		build(s) {
			const cols = s.list('cols');
			const color = s.has('color') ? { color: { field: s.f('color'), type: 'nominal', ...noLegend(s) } } : {};
			const key = { field: '_key', type: 'nominal', sort: cols, axis: { title: null, labelAngle: 0, orient: 'bottom', labelPadding: 26, labelFontWeight: 600 } };
			return {
				data: { values: s.records },
				transform: [
					{ window: [{ op: 'row_number', as: '_row' }] },
					{ fold: cols, as: ['_key', '_value'] },
					{ joinaggregate: [{ op: 'min', field: '_value', as: '_min' }, { op: 'max', field: '_value', as: '_max' }], groupby: ['_key'] },
					{ calculate: '(datum._value - datum._min) / ((datum._max - datum._min) || 1)', as: '_norm' },
				],
				layer: [
					{ mark: { type: 'rule', color: '#c3c2b7' }, encoding: { x: key } },
					{ mark: { type: 'line', opacity: 0.6, strokeWidth: 1.8 }, encoding: { x: key, y: q('_norm', { axis: null }), detail: { field: '_row', type: 'nominal' }, ...color } },
					{ mark: { type: 'text', align: 'center', dy: -8, fontSize: 10, color: '#57606a' }, encoding: { x: key, y: { datum: 1 }, text: { aggregate: 'max', field: '_max', type: 'quantitative' } } },
					{ mark: { type: 'text', align: 'center', dy: 12, fontSize: 10, color: '#57606a' }, encoding: { x: key, y: { datum: 0 }, text: { aggregate: 'min', field: '_min', type: 'quantitative' } } },
				],
			};
		},
	});

	C.option('split', { label: 'Quadrants split at', kind: 'select', default: 'median', choices: [['median', 'The median'], ['mean', 'The average']] });
	C.sample('portfolio', 'Product,Growth,Share,Revenue\nAlpha,34,22,120\nBeta,12,40,210\nGamma,28,8,60\nDelta,4,12,35\nEpsilon,22,31,150\nZeta,8,5,28\nEta,40,14,90\nTheta,16,48,260\nIota,2,30,95\nKappa,31,36,170');

	C.type({
		id: 'quadrant', group: 'relationship', label: 'Quadrant chart', desc: 'Items sorted into four boxes (e.g. growth vs share)', sample: 'portfolio',
		roles: [X_NUM, Y_NUM, role('label', 'Label (optional)', 'cat', false), role('size', 'Size by (optional)', 'num', false)], options: ['split', 'labels'], sampleMap: { x: 'Share', y: 'Growth', label: 'Product', size: 'Revenue' }, opts: { labels: true },
		build(s) {
			const xs = s.records.map((rec) => rec[s.f('x')]).filter((v) => typeof v === 'number').sort((a, b) => a - b);
			const ys = s.records.map((rec) => rec[s.f('y')]).filter((v) => typeof v === 'number').sort((a, b) => a - b);
			const mid = (v) => (s.opts.split === 'mean' ? v.reduce((a, b) => a + b, 0) / v.length : v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2);
			const mx = r(mid(xs), 3), my = r(mid(ys), 3);
			const x = q(s.f('x'), { scale: { zero: false, padding: 14 }, axis: { title: s.opts.xTitle || s.f('x') } });
			const y = q(s.f('y'), { scale: { zero: false, padding: 14 }, axis: { title: s.opts.yTitle || s.f('y') } });
			const corner = (text, hx, hy) => ({ data: { values: [{ t: text }] }, mark: { type: 'text', align: hx, baseline: hy, fontSize: 11, color: '#8c959f', fontWeight: 600 }, encoding: { x: { value: { expr: hx === 'left' ? '6' : 'width - 6' } }, y: { value: { expr: hy === 'top' ? '6' : 'height - 6' } }, text: { field: 't' } } });
			const parts = [
				{ mark: { type: 'rule', strokeDash: [5, 4], color: '#aab0ba' }, encoding: { x: at(mx) } },
				{ mark: { type: 'rule', strokeDash: [5, 4], color: '#aab0ba' }, encoding: { y: at(my) } },
				{ mark: { type: 'circle', opacity: 0.75, stroke: 'white', strokeWidth: 1, size: s.has('size') ? undefined : 130 }, encoding: { x, y, ...(s.has('size') ? { size: q(s.f('size'), { scale: { range: [80, 900] }, legend: null }) } : {}) } },
				corner(`low ${s.f('x')} · high ${s.f('y')}`, 'left', 'top'), corner(`high ${s.f('x')} · high ${s.f('y')}`, 'right', 'top'),
				corner(`low ${s.f('x')} · low ${s.f('y')}`, 'left', 'bottom'), corner(`high ${s.f('x')} · low ${s.f('y')}`, 'right', 'bottom'),
			];
			if (s.opts.labels && s.has('label')) parts.push({ mark: { type: 'text', dy: -13, fontSize: 10 }, encoding: { x, y, text: { field: s.f('label'), type: 'nominal' } } });
			return { data: { values: s.records }, layer: parts };
		},
	});
})(typeof window !== 'undefined' ? window : globalThis);
