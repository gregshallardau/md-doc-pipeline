/*
 * Chart types: change over time. See chart-core.js for the registration API.
 * Shared byte-for-byte with md-doc-pipeline's studio.
 */
(function (root) {
	'use strict';
	const C = root.ChartCatalog;
	const { at, q, n, t, axis, noLegend, wrap, axisKind, value, layers, r, distinct, rng, day } = C.h;

	const role = (key, label, kind = 'any', required = true, extra) => ({ key, label, kind, required, ...extra });
	const X_TIME = role('x', 'X axis (time or order)', 'time');
	const Y_VAL = role('y', 'Value (Y axis)', 'num');
	const SERIES = role('color', 'Series (optional)', 'any', false);
	const SERIES_REQ = role('color', 'Series', 'any', true);

	C.option('window', { label: 'Average over (points)', kind: 'number', default: 7, min: 2, max: 60 });
	C.option('bands', { label: 'Horizon bands', kind: 'number', default: 3, min: 2, max: 6 });
	C.option('mean', { label: 'Draw the average line', kind: 'check', default: true });

	/* ── Samples ────────────────────────────────────────────────────────── */

	C.sample('series', 'Month,Revenue,Region\nJan,12,North\nFeb,19,North\nMar,14,North\nApr,23,North\nMay,27,North\nJun,31,North\nJan,8,South\nFeb,15,South\nMar,21,South\nApr,18,South\nMay,24,South\nJun,29,South');
	C.sample('daily', () => {
		const rand = rng(7);
		let v = 50;
		const rows = ['Date,Visits'];
		for (let i = 0; i < 90; i++) { v += (rand() - 0.46) * 8; rows.push(`${day(i)},${Math.round(v * 10) / 10}`); }
		return rows.join('\n');
	});
	C.sample('dailySeries', () => {
		const rand = rng(11);
		const rows = ['Date,Visits,Channel'];
		const level = { Organic: 60, Paid: 35, Social: 20 };
		for (let i = 0; i < 60; i++) for (const k of Object.keys(level)) { level[k] += (rand() - 0.47) * 5; rows.push(`${day(i)},${Math.round(level[k] * 10) / 10},${k}`); }
		return rows.join('\n');
	});
	C.sample('prices', () => {
		const rand = rng(21);
		let close = 100;
		const rows = ['Date,Open,High,Low,Close'];
		for (let i = 0; i < 24; i++) {
			const open = close, c = open + (rand() - 0.48) * 6;
			const high = Math.max(open, c) + rand() * 3, low = Math.min(open, c) - rand() * 3;
			close = c;
			rows.push(`${day(i)},${[open, high, low, c].map((x) => Math.round(x * 100) / 100).join(',')}`);
		}
		return rows.join('\n');
	});
	C.sample('range', 'Month,Low,High,Average\nJan,-2,6,2\nFeb,-1,8,3\nMar,2,12,7\nApr,5,17,11\nMay,9,21,15\nJun,12,25,18\nJul,14,28,21\nAug,14,27,20\nSep,11,23,17\nOct,7,16,11\nNov,3,10,6\nDec,0,7,3');
	C.sample('combo', 'Month,Revenue,Margin\nJan,120,18\nFeb,135,21\nMar,128,19\nApr,160,24\nMay,172,26\nJun,190,27\nJul,185,25\nAug,205,29');
	C.sample('stream', () => {
		const rand = rng(5);
		const rows = ['Year,Genre,Listeners'];
		const base = { Rock: 40, Pop: 30, Jazz: 12, Folk: 18 };
		for (let y = 2014; y <= 2024; y++) for (const k of Object.keys(base)) { base[k] = Math.max(4, base[k] + (rand() - 0.5) * 8); rows.push(`${y},${k},${Math.round(base[k])}`); }
		return rows.join('\n');
	});

	/* ── Line family ────────────────────────────────────────────────────── */

	function lineLike(s, mark) {
		const kind = axisKind(s, s.f('x'), false);
		const x = { field: s.f('x'), type: kind, ...(kind === 'ordinal' ? { sort: null } : {}), ...C.h.xAxis(s, kind) };
		const y = value(s, 'y', axis(s.opts.yTitle));
		const enc = { x, y };
		if (s.has('color')) enc.color = { field: s.f('color'), type: 'nominal', ...noLegend(s) };
		return { x, y, enc, mark };
	}

	const lineOptions = ['agg', 'xKind', 'points', 'smooth', 'labels', 'legend'];

	function lineSpec(s, interpolate) {
		const { x, y, enc } = lineLike(s, null);
		const mark = { type: 'line', point: !!s.opts.points, interpolate };
		const spec = wrap(s, mark, enc);
		if (!s.opts.labels) return spec;
		const text = { mark: { type: 'text', dy: -10, fontSize: 10 }, encoding: { x, y: { ...y, axis: undefined }, text: { ...y, axis: undefined }, ...(enc.color ? { color: enc.color } : {}) } };
		delete text.encoding.y.axis; delete text.encoding.text.axis;
		return layers(s, [{ mark, encoding: enc }, text]);
	}

	C.type({ id: 'line', group: 'trend', label: 'Line', desc: 'Change over time or order', sample: 'series', roles: [X_TIME, Y_VAL, SERIES], options: lineOptions, defaults: { color: 'Region' }, build: (s) => lineSpec(s, s.opts.smooth ? 'monotone' : 'linear') });
	C.type({ id: 'step', group: 'trend', label: 'Step line', desc: 'Values that hold until they change', sample: 'series', roles: [X_TIME, Y_VAL, SERIES], options: ['agg', 'xKind', 'points', 'labels', 'legend'], defaults: { color: 'Region' }, opts: { points: false }, build: (s) => lineSpec(s, 'step-after') });

	function areaSpec(s, stack, center) {
		const kind = axisKind(s, s.f('x'), false);
		const x = { field: s.f('x'), type: kind, ...(kind === 'ordinal' ? { sort: null } : {}), ...C.h.xAxis(s, kind) };
		const y = value(s, 'y', { ...(center ? { stack: 'center', axis: null } : axis(s.opts.yTitle)), ...(stack === 'normalize' ? { stack: 'normalize', axis: { format: '%', ...(s.opts.yTitle ? { title: s.opts.yTitle } : {}) } } : {}) });
		const enc = { x, y };
		if (s.has('color')) enc.color = { field: s.f('color'), type: 'nominal', ...noLegend(s) };
		const mark = { type: 'area', opacity: stack === 'overlap' ? 0.55 : 0.9, line: stack !== 'normalize' && !center, interpolate: s.opts.smooth ? 'monotone' : 'linear' };
		if (stack === 'overlap' && s.has('color')) enc.y.stack = null;
		return wrap(s, mark, enc);
	}
	const areaRoles = [X_TIME, Y_VAL, SERIES];
	C.type({ id: 'area', group: 'trend', label: 'Area', desc: 'Volume over time (series overlap)', sample: 'dailySeries', roles: areaRoles, options: ['agg', 'xKind', 'smooth', 'legend'], defaults: { color: 'Channel' }, build: (s) => areaSpec(s, 'overlap') });
	C.type({ id: 'area-stacked', group: 'trend', label: 'Stacked area', desc: 'How parts add up over time', sample: 'dailySeries', roles: [X_TIME, Y_VAL, SERIES_REQ], options: ['aggSum', 'xKind', 'smooth', 'legend'], build: (s) => areaSpec(s, 'stack') });
	C.type({ id: 'area-percent', group: 'trend', label: '100% stacked area', desc: 'How the mix changes over time', sample: 'dailySeries', roles: [X_TIME, Y_VAL, SERIES_REQ], options: ['aggSum', 'xKind', 'smooth', 'legend'], build: (s) => areaSpec(s, 'normalize') });
	C.type({ id: 'streamgraph', group: 'trend', label: 'Streamgraph', desc: 'Stacked area centred on a middle line', sample: 'stream', roles: [X_TIME, Y_VAL, SERIES_REQ], options: ['aggSum', 'xKind', 'legend'], opts: { smooth: true }, sampleMap: { x: 'Year', y: 'Listeners', color: 'Genre' }, build: (s) => areaSpec({ ...s, opts: { ...s.opts, smooth: true } }, 'stack', true) });

	C.type({
		id: 'range-area', group: 'trend', label: 'Range band', desc: 'A band between a low and a high, with an average', sample: 'range',
		roles: [X_TIME, role('y', 'Low', 'num'), role('y2', 'High', 'num'), role('mean', 'Average (optional)', 'num', false)], options: ['xKind', 'smooth', 'mean'], defaults: { mean: 'Average' },
		build(s) {
			const kind = axisKind(s, s.f('x'), false);
			const x = { field: s.f('x'), type: kind, ...(kind === 'ordinal' ? { sort: null } : {}), ...C.h.xAxis(s, kind) };
			const interpolate = s.opts.smooth ? 'monotone' : 'linear';
			const parts = [{ mark: { type: 'area', opacity: 0.35, interpolate }, encoding: { x, y: q(s.f('y'), { axis: { title: s.opts.yTitle || null } }), y2: { field: s.f('y2') } } }];
			if (s.has('mean') && s.opts.mean) parts.push({ mark: { type: 'line', strokeWidth: 2.5, interpolate }, encoding: { x, y: q(s.f('mean')) } });
			return layers(s, parts);
		},
	});

	C.type({
		id: 'cumulative', group: 'trend', label: 'Running total', desc: 'Values added up over time', sample: 'daily',
		roles: [X_TIME, Y_VAL], options: ['xKind', 'smooth'],
		build(s) {
			const kind = axisKind(s, s.f('x'), false);
			const x = { field: s.f('x'), type: kind, ...(kind === 'ordinal' ? { sort: null } : {}), ...C.h.xAxis(s, kind) };
			return {
				data: { values: s.records },
				transform: [{ window: [{ op: 'sum', field: s.f('y'), as: '_total' }], sort: [{ field: s.f('x') }], frame: [null, 0] }],
				mark: { type: 'area', line: true, opacity: 0.35, interpolate: s.opts.smooth ? 'monotone' : 'linear' },
				encoding: { x, y: q('_total', { axis: { title: s.opts.yTitle || `Running total of ${s.f('y')}` } }) },
			};
		},
	});

	C.type({
		id: 'moving-average', group: 'trend', label: 'Moving average', desc: 'The raw series with a smoothed trend', sample: 'daily',
		roles: [X_TIME, Y_VAL], options: ['window', 'xKind'],
		build(s) {
			const kind = axisKind(s, s.f('x'), false);
			const x = { field: s.f('x'), type: kind, ...(kind === 'ordinal' ? { sort: null } : {}), ...C.h.xAxis(s, kind) };
			const k = Math.max(2, Math.round(Number(s.opts.window) || 7));
			return {
				data: { values: s.records },
				transform: [{ window: [{ op: 'mean', field: s.f('y'), as: '_average' }], sort: [{ field: s.f('x') }], frame: [-(k - 1), 0] }],
				layer: [
					{ mark: { type: 'line', opacity: 0.4, strokeWidth: 1.5 }, encoding: { x, y: q(s.f('y'), { axis: { title: s.opts.yTitle || s.f('y') } }) } },
					{ mark: { type: 'line', strokeWidth: 3 }, encoding: { x, y: q('_average', { axis: null }) } },
				],
			};
		},
	});

	C.type({
		id: 'combo', group: 'trend', label: 'Bars and line (dual axis)', desc: 'Two measures on their own scales', sample: 'combo',
		roles: [X_TIME, role('y', 'Bars (left axis)', 'num'), role('y2', 'Line (right axis)', 'num')], options: ['points', 'xKind'],
		build(s) {
			const kind = axisKind(s, s.f('x'), true);
			const x = { field: s.f('x'), type: kind, ...(kind === 'ordinal' ? { sort: null } : {}), axis: { title: s.opts.xTitle || null, labelAngle: 0 } };
			return {
				data: { values: s.records },
				layer: [
					{ mark: { type: 'bar', opacity: 0.85, cornerRadiusEnd: 2 }, encoding: { x, y: q(s.f('y'), { axis: { title: s.opts.yTitle || s.f('y') } }) } },
					{ mark: { type: 'line', strokeWidth: 3, color: '#eb6834', point: s.opts.points ? { filled: true, color: '#eb6834', size: 70 } : false }, encoding: { x, y: q(s.f('y2'), { axis: { title: s.f('y2'), orient: 'right', titleColor: '#eb6834', labelColor: '#eb6834' } }) } },
				],
				resolve: { scale: { y: 'independent' } },
			};
		},
	});

	/* ── Financial ──────────────────────────────────────────────────────── */

	const ohlcRoles = [role('x', 'Date', 'date'), role('open', 'Open', 'num'), role('high', 'High', 'num'), role('low', 'Low', 'num'), role('close', 'Close', 'num')];
	const upDown = (s) => ({ condition: { test: `datum['${s.f('open')}'] < datum['${s.f('close')}']`, value: C.h.good }, value: C.h.bad });

	C.type({
		id: 'candlestick', group: 'trend', label: 'Candlestick', desc: 'Open, high, low and close per period', sample: 'prices', roles: ohlcRoles, options: [],
		build(s) {
			const x = { field: s.f('x'), type: s.kind(s.f('x')) === 'quantitative' ? 'quantitative' : 'temporal', axis: { title: s.opts.xTitle || null, format: '%b %d', labelAngle: -45 } };
			const yAxis = axis(s.opts.yTitle).axis || { title: null };
			const y = (field, extra) => q(field, { scale: { zero: false }, axis: yAxis, ...extra });
			return layers(s, [
				{ mark: { type: 'rule' }, encoding: { x, y: y(s.f('low')), y2: { field: s.f('high') }, color: upDown(s) } },
				{ mark: { type: 'bar', size: 9 }, encoding: { x, y: y(s.f('open')), y2: { field: s.f('close') }, color: upDown(s) } },
			]);
		},
	});

	C.type({
		id: 'ohlc', group: 'trend', label: 'OHLC bars', desc: 'High-low bar with open and close ticks', sample: 'prices', roles: ohlcRoles, options: [],
		build(s) {
			const x = { field: s.f('x'), type: s.kind(s.f('x')) === 'quantitative' ? 'quantitative' : 'temporal', axis: { title: s.opts.xTitle || null, format: '%b %d', labelAngle: -45 } };
			const yAxis = axis(s.opts.yTitle).axis || { title: null };
			const y = (field, extra) => q(field, { scale: { zero: false }, axis: yAxis, ...extra });
			const color = upDown(s);
			return layers(s, [
				{ mark: { type: 'rule' }, encoding: { x, y: y(s.f('low')), y2: { field: s.f('high') }, color } },
				{ mark: { type: 'tick', orient: 'horizontal', xOffset: -5, size: 10, thickness: 2 }, encoding: { x, y: y(s.f('open')), color } },
				{ mark: { type: 'tick', orient: 'horizontal', xOffset: 5, size: 10, thickness: 2 }, encoding: { x, y: y(s.f('close')), color } },
			]);
		},
	});

	/* ── Horizon ────────────────────────────────────────────────────────── */

	C.type({
		id: 'horizon', group: 'trend', label: 'Horizon graph', desc: 'A long series folded into bands to save height', sample: 'daily',
		roles: [X_TIME, Y_VAL], options: ['bands', 'xKind'],
		build(s) {
			const kind = axisKind(s, s.f('x'), false);
			const bands = Math.max(2, Math.min(6, Math.round(Number(s.opts.bands) || 3)));
			const ys = s.records.map((rec) => rec[s.f('y')]).filter((v) => typeof v === 'number');
			const lo = Math.min(...ys), hi = Math.max(...ys);
			const step = r((hi - lo) / bands, 3) || 1;
			const x = { field: s.f('x'), type: kind, ...C.h.xAxis(s, kind) };
			const layer = [];
			for (let i = 0; i < bands; i++) {
				layer.push({
					transform: [{ calculate: `datum['${s.f('y')}'] - ${r(lo, 3)} - ${r(step * i, 3)}`, as: `_b${i}` }],
					mark: { type: 'area', clip: true, orient: 'vertical', opacity: 0.45, interpolate: 'monotone' },
					encoding: { x, y: q(`_b${i}`, { scale: { domain: [0, step], nice: false }, axis: i === 0 ? { title: s.opts.yTitle || null, values: [] } : null }) },
				});
			}
			return { data: { values: s.records }, height: 90, layer };
		},
	});

	/* ── Sparkline (kpi) ────────────────────────────────────────────────── */

	C.type({
		id: 'sparkline', group: 'kpi', label: 'Sparkline', desc: 'A tiny trend line for tables and callouts', sample: 'daily',
		roles: [X_TIME, Y_VAL], options: ['smooth'], opts: { smooth: true },
		build(s) {
			const kind = axisKind(s, s.f('x'), false);
			const sorted = [...s.records].sort((a, b) => (a[s.f('x')] < b[s.f('x')] ? -1 : 1));
			const lastRow = sorted[sorted.length - 1];
			const x = { field: s.f('x'), type: kind, axis: null };
			const y = q(s.f('y'), { axis: null, scale: { zero: false } });
			return {
				data: { values: s.records },
				width: 220, height: 50,
				layer: [
					{ mark: { type: 'line', strokeWidth: 2, interpolate: s.opts.smooth ? 'monotone' : 'linear' }, encoding: { x, y } },
					{ data: { values: [lastRow] }, mark: { type: 'point', filled: true, size: 70, opacity: 1 }, encoding: { x, y } },
				],
				config: { view: { stroke: null } },
			};
		},
	});

	C.option('sigma', { label: 'Control limits (standard deviations)', kind: 'number', default: 3, min: 1, max: 6 });
	C.sample('process', () => {
		const rand = rng(77);
		const rows = ['Sample,Measurement'];
		for (let i = 1; i <= 30; i++) {
			let v = 50 + (rand() - 0.5) * 6 + (rand() - 0.5) * 6;
			if (i === 17) v += 15;
			if (i === 24) v -= 14;
			rows.push(`${i},${Math.round(v * 100) / 100}`);
		}
		return rows.join('\n');
	});
	C.sample('events', 'Date,Event,Track\n2025-01-08,Kick-off,Plan\n2025-02-03,Prototype,Build\n2025-02-27,Design review,Plan\n2025-03-19,Beta,Build\n2025-04-14,Security audit,Ship\n2025-05-06,Launch,Ship\n2025-06-02,Retrospective,Plan');

	C.type({
		id: 'control-chart', group: 'trend', label: 'Control chart', desc: 'A process against its mean and control limits', sample: 'process',
		roles: [X_TIME, role('y', 'Measurement', 'num')], options: ['sigma'], sampleMap: { x: 'Sample', y: 'Measurement' },
		build(s) {
			const ys = s.records.map((rec) => rec[s.f('y')]).filter((v) => typeof v === 'number');
			const n = ys.length, mean = ys.reduce((a, b) => a + b, 0) / n;
			const sd = Math.sqrt(ys.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(1, n - 1));
			const k = Math.max(1, Number(s.opts.sigma) || 3);
			const ucl = r(mean + k * sd, 3), lcl = r(mean - k * sd, 3), centre = r(mean, 3);
			const kind = axisKind(s, s.f('x'), false);
			const x = { field: s.f('x'), type: kind, ...(kind === 'ordinal' ? { sort: null } : {}), ...C.h.xAxis(s, kind) };
			const y = q(s.f('y'), { scale: { zero: false }, axis: { title: s.opts.yTitle || s.f('y') } });
			const out = `datum['${s.f('y')}'] > ${ucl} || datum['${s.f('y')}'] < ${lcl}`;
			const rule = (v, color, dash) => ({ mark: { type: 'rule', color, strokeDash: dash, strokeWidth: 1.5 }, encoding: { y: at(v) } });
			const note = (v, text, color) => ({ mark: { type: 'text', align: 'left', dx: 4, dy: -6, fontSize: 10, color }, encoding: { y: at(v), x: { value: { expr: 'width' } }, text: { value: text } } });
			return layers(s, [
				rule(centre, '#57606a', null), rule(ucl, C.h.bad, [5, 4]), rule(lcl, C.h.bad, [5, 4]),
				{ mark: { type: 'line', strokeWidth: 2 }, encoding: { x, y } },
				{ mark: { type: 'point', filled: true, size: 70, opacity: 1 }, encoding: { x, y, color: { condition: { test: out, value: C.h.bad }, value: C.h.neutral } } },
				{ mark: { type: 'text', align: 'right', dx: -4, dy: -6, fontSize: 10, color: C.h.bad }, encoding: { y: at(ucl), x: { value: { expr: 'width' } }, text: { value: `UCL ${ucl}` } } },
				{ mark: { type: 'text', align: 'right', dx: -4, dy: 12, fontSize: 10, color: C.h.bad }, encoding: { y: at(lcl), x: { value: { expr: 'width' } }, text: { value: `LCL ${lcl}` } } },
				{ mark: { type: 'text', align: 'right', dx: -4, dy: -6, fontSize: 10, color: '#57606a' }, encoding: { y: at(centre), x: { value: { expr: 'width' } }, text: { value: `Mean ${centre}` } } },
			]);
		},
	});

	C.type({
		id: 'timeline', group: 'trend', label: 'Event timeline', desc: 'Milestones along a date line', sample: 'events',
		roles: [role('x', 'Date', 'date'), role('label', 'Event', 'any'), role('color', 'Track (optional)', 'any', false)], options: ['legend'], sampleMap: { x: 'Date', label: 'Event', color: 'Track' },
		build(s) {
			const rows = s.records.filter((rec) => rec[s.f('x')] !== null).sort((a, b) => (String(a[s.f('x')]) < String(b[s.f('x')]) ? -1 : 1));
			const records = rows.map((rec, i) => ({ ...rec, _lift: (i % 2 ? -1 : 1) * (28 + (i % 3) * 20) }));
			const x = { field: s.f('x'), type: s.kind(s.f('x')) === 'quantitative' ? 'quantitative' : 'temporal', axis: { title: s.opts.xTitle || null, orient: 'bottom', format: '%b %Y', labelAngle: 0 } };
			const lift = { field: '_lift', type: 'quantitative', scale: { domain: [-100, 100] }, axis: null };
			const color = s.has('color') ? { color: { field: s.f('color'), type: 'nominal', ...noLegend(s) } } : {};
			return {
				data: { values: records },
				layer: [
					{ mark: { type: 'rule', color: '#c3c2b7', strokeWidth: 1.5 }, encoding: { y: at(0, { scale: { domain: [-100, 100] }, axis: null }) } },
					{ mark: { type: 'rule', strokeWidth: 1.2, opacity: 0.7 }, encoding: { x, y: lift, y2: { datum: 0 }, ...color } },
					{ mark: { type: 'point', filled: true, size: 90, opacity: 1 }, encoding: { x, y: at(0, { scale: { domain: [-100, 100] }, axis: null }), ...color } },
					{ mark: { type: 'text', fontSize: 11, align: 'center', baseline: { expr: "datum._lift > 0 ? 'bottom' : 'top'" }, dy: { expr: 'datum._lift > 0 ? -4 : 4' } }, encoding: { x, y: lift, text: { field: s.f('label'), type: 'nominal' } } },
				],
			};
		},
	});
})(typeof window !== 'undefined' ? window : globalThis);
