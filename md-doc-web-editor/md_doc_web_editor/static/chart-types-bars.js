/*
 * Chart types: bars and comparisons. See chart-core.js for the registration API.
 * Shared byte-for-byte with md-doc-pipeline's studio.
 */
(function (root) {
	'use strict';
	const C = root.ChartCatalog;
	const { at, q, n, o, t, axis, noLegend, agg, isCount, wrap, axisKind, sortFor, value, layers, r, distinct } = C.h;

	const role = (key, label, kind = 'any', required = true, extra) => ({ key, label, kind, required, ...extra });
	const X_CAT = role('x', 'Category (X axis)');
	const Y_VAL = role('y', 'Value (Y axis)', 'num');
	const GROUP = role('color', 'Group by (optional)', 'any', false);
	const GROUP_REQ = role('color', 'Group by', 'any', true);

	C.option('stack', { label: 'Groups appear', kind: 'select', default: 'stacked', choices: [['stacked', 'Stacked'], ['grouped', 'Side by side'], ['normalize', 'As percentages']] });
	C.option('total', { label: 'Add a total bar', kind: 'check', default: true });

	/* ── Samples ────────────────────────────────────────────────────────── */

	C.sample('categories', 'Region,Revenue\nNorth,42\nSouth,31\nEast,17\nWest,10');
	C.sample('grouped', 'Quarter,Product,Sales\nQ1,Alpha,32\nQ1,Beta,21\nQ1,Gamma,12\nQ2,Alpha,38\nQ2,Beta,25\nQ2,Gamma,18\nQ3,Alpha,41\nQ3,Beta,30\nQ3,Gamma,22\nQ4,Alpha,52\nQ4,Beta,34\nQ4,Gamma,27');
	C.sample('likert', 'Question,Response,Percent\nEasy to use,Strongly disagree,-4\nEasy to use,Disagree,-9\nEasy to use,Neutral,15\nEasy to use,Agree,42\nEasy to use,Strongly agree,30\nFast,Strongly disagree,-8\nFast,Disagree,-17\nFast,Neutral,20\nFast,Agree,35\nFast,Strongly agree,20\nGood value,Strongly disagree,-12\nGood value,Disagree,-24\nGood value,Neutral,22\nGood value,Agree,28\nGood value,Strongly agree,14');
	C.sample('change', 'Month,Change\nJan,12\nFeb,-5\nMar,18\nApr,-9\nMay,7\nJun,-14\nJul,21\nAug,6');
	C.sample('ranges', 'Region,Start,End\nNorth,20,45\nSouth,12,30\nEast,8,38\nWest,15,22');
	C.sample('targets', 'Metric,Actual,Target\nRevenue,270,300\nProfit,22,25\nSatisfaction,4.2,4.5\nRetention,88,85');
	C.sample('bridge', 'Step,Amount\nStart,100\nNew sales,45\nUpsell,20\nChurn,-30\nRefunds,-12\nFX,8');
	C.sample('funnel', 'Stage,Visitors\nVisited site,10000\nSigned up,4200\nActivated,2600\nSubscribed,1100\nRenewed,640');
	C.sample('pyramid', 'Age,Sex,Population\n0-9,Female,9.1\n0-9,Male,9.6\n10-19,Female,9.8\n10-19,Male,10.3\n20-29,Female,11.2\n20-29,Male,11.5\n30-39,Female,10.9\n30-39,Male,10.8\n40-49,Female,9.6\n40-49,Male,9.3\n50-59,Female,8.1\n50-59,Male,7.6\n60-69,Female,6.2\n60-69,Male,5.4\n70+,Female,5.5\n70+,Male,4.1');
	C.sample('slope', 'Item,Year,Score\nAlpha,2022,42\nAlpha,2024,58\nBeta,2022,65\nBeta,2024,51\nGamma,2022,30\nGamma,2024,47\nDelta,2022,55\nDelta,2024,56');
	C.sample('ranks', 'Team,Season,Points\nRed,2021,70\nRed,2022,64\nRed,2023,81\nRed,2024,77\nBlue,2021,75\nBlue,2022,80\nBlue,2023,66\nBlue,2024,79\nGreen,2021,60\nGreen,2022,72\nGreen,2023,74\nGreen,2024,70\nGold,2021,55\nGold,2022,58\nGold,2023,62\nGold,2024,85');
	C.sample('mosaic', 'Segment,Channel,Sales\nConsumer,Online,40\nConsumer,Retail,30\nConsumer,Partner,10\nBusiness,Online,25\nBusiness,Retail,10\nBusiness,Partner,35\nPublic,Online,8\nPublic,Retail,6\nPublic,Partner,14');
	C.sample('tasks', 'Task,Start,End,Owner\nResearch,2025-01-06,2025-01-31,Ana\nDesign,2025-01-20,2025-02-28,Ben\nBuild,2025-02-17,2025-04-18,Cai\nTest,2025-04-07,2025-05-09,Ana\nLaunch,2025-05-05,2025-05-23,Ben');

	/* ── Helpers ────────────────────────────────────────────────────────── */

	/** Text labels over the marks of a layer (used by the plain bar types). */
	function textLayer(part, field, extra) {
		const enc = { ...part.encoding };
		const keep = {};
		for (const k of ['x', 'y', 'xOffset', 'yOffset']) if (enc[k]) keep[k] = enc[k];
		return { mark: { type: 'text', dy: -6, fontSize: 11, ...extra }, encoding: { ...keep, text: field } };
	}

	function barPart(s, horizontal) {
		const xKind = axisKind(s, s.f('x'), true);
		const cat = { field: s.f('x'), type: xKind, ...sortFor(s, xKind), ...axis(s.opts.xTitle) };
		let stackMode = s.opts.stack;
		if (s.has('color') && stackMode !== 'grouped' && C.NON_SUMMATIVE.includes(s.opts.agg)) {
			stackMode = 'grouped'; // averages, minimums and maximums do not add up
			s.warn(`“${s.opts.agg}” values cannot be stacked, so the groups are shown side by side.`);
		}
		const normalize = s.has('color') && stackMode === 'normalize';
		const val = value(s, 'y', { ...axis(s.opts.yTitle), ...(normalize ? { stack: 'normalize', axis: { format: '%', ...(s.opts.yTitle ? { title: s.opts.yTitle } : {}) } } : {}) });
		let enc;
		if (horizontal) {
			const flip = { x: 'y', '-x': '-y', '-y': '-x' };
			enc = { y: { ...cat, ...(cat.sort !== undefined ? { sort: cat.sort === null ? null : flip[cat.sort] } : {}) }, x: val };
		} else enc = { x: cat, y: val };
		if (s.has('color')) {
			enc.color = { field: s.f('color'), type: 'nominal', ...noLegend(s) };
			if (stackMode === 'grouped') enc[horizontal ? 'yOffset' : 'xOffset'] = { field: s.f('color') };
		}
		return { mark: { type: 'bar', cornerRadiusEnd: 2 }, encoding: enc };
	}

	function barSpec(s, horizontal) {
		const part = barPart(s, horizontal);
		if (s.opts.labels && (!s.has('color') || part.encoding.xOffset || part.encoding.yOffset)) {
			const v = horizontal ? part.encoding.x : part.encoding.y;
			const label = { ...v, ...(isCount(s) ? {} : {}), axis: undefined };
			delete label.axis;
			const text = textLayer(part, label, horizontal ? { dx: 12, dy: 0, align: 'left', baseline: 'middle' } : {});
			return layersOf(s, part, text);
		}
		return wrap(s, part.mark, part.encoding);
	}

	function layersOf(s, ...parts) {
		return layers(s, parts.map((p) => ({ mark: p.mark, encoding: p.encoding })));
	}

	const barRoles = [X_CAT, Y_VAL, GROUP];
	const barOptions = ['agg', 'sort', 'stack', 'labels', 'legend'];

	/* ── Types ──────────────────────────────────────────────────────────── */

	C.type({ id: 'bar', group: 'compare', label: 'Bar', desc: 'Compare values across categories', sample: 'categories', roles: barRoles, options: barOptions, build: (s) => barSpec(s, false) });
	C.type({ id: 'hbar', group: 'compare', label: 'Horizontal bar', desc: 'Long labels or rankings', sample: 'categories', roles: barRoles, options: barOptions, build: (s) => barSpec(s, true) });
	C.type({ id: 'bar-grouped', group: 'compare', label: 'Grouped bar', desc: 'Groups side by side within each category', sample: 'grouped', roles: [X_CAT, Y_VAL, GROUP_REQ], options: ['agg', 'sort', 'labels', 'legend'], opts: { stack: 'grouped' }, build: (s) => barSpec({ ...s, opts: { ...s.opts, stack: 'grouped' } }, false) });
	C.type({ id: 'bar-stacked', group: 'compare', label: 'Stacked bar', desc: 'Parts that add up to each total', sample: 'grouped', roles: [X_CAT, Y_VAL, GROUP_REQ], options: ['aggSum', 'sort', 'legend'], opts: { stack: 'stacked' }, build: (s) => barSpec({ ...s, opts: { ...s.opts, stack: 'stacked' } }, false) });
	C.type({ id: 'bar-percent', group: 'compare', label: '100% stacked bar', desc: 'Each category’s mix, as percentages', sample: 'grouped', roles: [X_CAT, Y_VAL, GROUP_REQ], options: ['aggSum', 'sort', 'legend'], opts: { stack: 'normalize' }, build: (s) => barSpec({ ...s, opts: { ...s.opts, stack: 'normalize' } }, false) });

	C.type({
		id: 'bar-diverging', group: 'compare', label: 'Diverging bar', desc: 'Opposing responses either side of zero (Likert)', sample: 'likert',
		roles: [role('y', 'Category', 'cat'), role('color', 'Response level', 'cat'), role('x', 'Value (negative = left)', 'num')], options: ['legend'],
		build(s) {
			const levels = distinct(s.records, s.f('color'));
			// Stack outwards from zero: on the negative side the level nearest the middle goes first.
			const records = s.records.map((rec) => {
				const i = levels.indexOf(rec[s.f('color')]);
				return { ...rec, _order: rec[s.f('x')] < 0 ? -i : i };
			});
			return {
				data: { values: records },
				mark: { type: 'bar' },
				encoding: {
					y: { field: s.f('y'), type: 'nominal', sort: null, ...axis(s.opts.yTitle) },
					x: q(s.f('x'), { stack: 'zero', axis: { title: s.opts.xTitle || null, format: 's' } }),
					color: { field: s.f('color'), type: 'nominal', scale: { domain: levels, range: C.h.ramp([C.h.bad, '#d9dce1', C.h.good], levels.length) }, ...noLegend(s) },
					order: { field: '_order', type: 'quantitative' },
				},
			};
		},
	});

	C.type({
		id: 'bar-posneg', group: 'compare', label: 'Positive / negative bars', desc: 'Gains and losses coloured apart', sample: 'change',
		roles: [X_CAT, role('y', 'Change', 'num')], options: ['sort', 'labels'],
		build(s) {
			const y = s.f('y');
			const xKind = axisKind(s, s.f('x'), true);
			const records = s.records.map((rec) => ({ ...rec, _direction: rec[y] < 0 ? 'Decrease' : 'Increase' }));
			const part = {
				mark: { type: 'bar', cornerRadiusEnd: 2 },
				encoding: {
					x: { field: s.f('x'), type: xKind, ...sortFor(s, xKind), axis: { title: s.opts.xTitle || null, labelAngle: 0, labelPadding: 6, orient: 'bottom' } },
					y: q(y, axis(s.opts.yTitle)),
					color: { field: '_direction', type: 'nominal', scale: { domain: ['Increase', 'Decrease'], range: [C.h.good, C.h.bad] }, legend: s.opts.legend === false ? null : { title: null } },
				},
			};
			const spec = { data: { values: records }, layer: [part] };
			if (s.opts.labels) spec.layer.push(textLayer(part, q(y), { dy: -6 }));
			return spec;
		},
	});

	C.type({
		id: 'lollipop', group: 'compare', label: 'Lollipop', desc: 'Bars slimmed to a stick and a dot', sample: 'categories',
		roles: [X_CAT, Y_VAL], options: ['agg', 'sort', 'labels'],
		build(s) {
			const xKind = axisKind(s, s.f('x'), true);
			const x = { field: s.f('x'), type: xKind, ...sortFor(s, xKind), ...axis(s.opts.xTitle) };
			const y = value(s, 'y', axis(s.opts.yTitle));
			const stick = { mark: { type: 'rule', strokeWidth: 2, color: '#aab0ba' }, encoding: { x, y, y2: { datum: 0 } } };
			const dot = { mark: { type: 'point', filled: true, size: 140, opacity: 1 }, encoding: { x, y } };
			const parts = [stick, dot];
			if (s.opts.labels) parts.push(textLayer(dot, { ...y, axis: undefined }, { dy: -14 }));
			return layers(s, parts);
		},
	});

	C.type({
		id: 'dot-plot', group: 'compare', label: 'Dot plot', desc: 'Dots on a line, easy to rank', sample: 'grouped',
		roles: [role('y', 'Category', 'any'), role('x', 'Value', 'num'), GROUP], options: ['agg', 'sort', 'legend'], defaults: { color: 'Product' },
		build(s) {
			const cats = distinct(s.records, s.f('y')).map(String);
			const top = (c) => Math.max(...s.records.filter((rec) => String(rec[s.f('y')]) === c).map((rec) => rec[s.f('x')] || 0));
			// One category order for every layer (a sort channel on one layer would not reach the others).
			const order = s.opts.sort === 'asc' ? [...cats].sort() : s.opts.sort === 'desc' ? [...cats].sort().reverse() : s.opts.sort === 'value' ? [...cats].sort((a, b) => top(b) - top(a)) : cats;
			const y = { field: s.f('y'), type: 'ordinal', sort: order, ...axis(s.opts.yTitle) };
			const x = value(s, 'x', axis(s.opts.xTitle));
			const color = s.has('color') ? { color: { field: s.f('color'), type: 'nominal', ...noLegend(s) } } : {};
			const guide = { mark: { type: 'rule', stroke: '#c3c2b7', strokeDash: [2, 3] }, encoding: { y: { field: s.f('y'), type: 'ordinal', sort: order } } };
			return layers(s, [guide, { mark: { type: 'point', filled: true, size: 120, opacity: 1 }, encoding: { y, x, ...color } }]);
		},
	});

	C.type({
		id: 'dumbbell', group: 'compare', label: 'Dumbbell', desc: 'Change between two values per category', sample: 'ranges',
		roles: [role('y', 'Category', 'any'), role('x', 'From (number)', 'num'), role('x2', 'To (number)', 'num')], options: ['sort'],
		build(s) {
			const y = { field: s.f('y'), type: 'ordinal', sort: s.opts.sort === 'asc' ? 'y' : s.opts.sort === 'desc' ? '-y' : null, ...axis(s.opts.yTitle) };
			const from = s.f('x'), to = s.f('x2');
			return layers(s, [
				{ mark: { type: 'rule', strokeWidth: 3, color: '#c3c2b7' }, encoding: { y, x: q(from, { axis: { title: s.opts.xTitle || null } }), x2: { field: to } } },
				{ mark: { type: 'point', filled: true, size: 130, opacity: 1, color: '#8c959f' }, encoding: { y, x: q(from) } },
				{ mark: { type: 'point', filled: true, size: 130, opacity: 1 }, encoding: { y, x: q(to) } },
			]);
		},
	});

	C.type({
		id: 'bullet', group: 'kpi', label: 'Bullet', desc: 'Actual against a target, with quality bands', sample: 'targets',
		roles: [role('y', 'Measure', 'any'), role('x', 'Actual', 'num'), role('target', 'Target', 'num')], options: [],
		build(s) {
			const a = s.f('x'), tg = s.f('target');
			const records = s.records.map((rec) => ({ ...rec, _poor: rec[tg] * 1.25, _fair: rec[tg] * 1.0, _good: rec[tg] * 0.7 }));
			const y = { field: s.f('y'), type: 'nominal', sort: null, axis: { title: null, labelLimit: 140 } };
			// Each measure on its own scale: bands, bar and tick are all shown as a share of the target.
			const pct = (field) => `datum['${field}'] / datum['${tg}']`;
			const calc = (name, expr) => ({ calculate: expr, as: name });
			const band = (field, grey) => ({ mark: { type: 'bar', height: 26, color: grey }, encoding: { y, x: q(field, { axis: { title: null, format: '%' }, scale: { domain: [0, 1.25] } }) } });
			return {
				data: { values: records },
				transform: [calc('_a', pct(a)), calc('_t', '1'), calc('_b1', '1.25'), calc('_b2', '1'), calc('_b3', '0.7')],
				layer: [
					band('_b1', '#e4e6ea'), band('_b2', '#cdd1d8'), band('_b3', '#aab0ba'),
					{ mark: { type: 'bar', height: 9, color: '#1f2328' }, encoding: { y, x: q('_a', { scale: { domain: [0, 1.25] } }) } },
					{ mark: { type: 'tick', color: '#e34948', thickness: 3, size: 22 }, encoding: { y, x: q('_t') } },
				],
			};
		},
	});

	C.type({
		id: 'waterfall', group: 'compare', label: 'Waterfall', desc: 'How steps add up to a total', sample: 'bridge',
		roles: [role('x', 'Step', 'any'), role('y', 'Amount (+ / −)', 'num')], options: ['total', 'labels', 'legend'],
		build(s) {
			let running = 0;
			const x = s.f('x'), y = s.f('y');
			const bars = s.records.map((rec) => {
				const start = running;
				running += rec[y] || 0;
				return { step: String(rec[x]), start: r(start), end: r(running), amount: rec[y], kind: (rec[y] || 0) >= 0 ? 'Increase' : 'Decrease' };
			});
			if (s.opts.total) bars.push({ step: 'Total', start: 0, end: r(running), amount: r(running), kind: 'Total' });
			const xEnc = { field: 'step', type: 'ordinal', sort: null, axis: { title: s.opts.xTitle || null, labelAngle: 0 } };
			const bar = { mark: { type: 'bar', cornerRadiusEnd: 2 }, encoding: { x: xEnc, y: q('start', { axis: { title: s.opts.yTitle || null } }), y2: { field: 'end' }, color: { field: 'kind', type: 'nominal', scale: { domain: ['Increase', 'Decrease', 'Total'], range: [C.h.good, C.h.bad, C.h.neutral] }, legend: s.opts.legend === false ? null : { title: null } } } };
			const parts = [bar];
			if (s.opts.labels) parts.push({ mark: { type: 'text', dy: -6, fontSize: 11 }, encoding: { x: xEnc, y: q('end'), text: q('amount', { format: '+,.4~g' }) } });
			return { data: { values: bars }, layer: parts };
		},
	});

	C.type({
		id: 'funnel', group: 'compare', label: 'Funnel', desc: 'Stages that narrow, with the drop-off', sample: 'funnel',
		roles: [role('y', 'Stage', 'any'), role('x', 'Count', 'num')], options: ['labels', 'legend'], opts: { legend: false },
		build(s) {
			const stage = s.f('y'), count = s.f('x');
			const top = Math.max(...s.records.map((rec) => rec[count] || 0)) || 1;
			// Bars are laid out here (centred on zero) so the labels can sit beside each one.
			const rows = s.records.map((rec) => {
				const v = rec[count] || 0;
				return { stage: String(rec[stage]), lo: r(-v / 2, 2), hi: r(v / 2, 2), label: s.opts.labels ? `${rec[stage]}  ${C.h.fmt(v)} (${r((v / top) * 100, 0)}%)` : String(rec[stage]) };
			});
			const y = { field: 'stage', type: 'ordinal', sort: null, axis: null };
			const x = q('lo', { axis: null, scale: { domain: [-top / 2, top * 0.95] } });
			return {
				data: { values: rows },
				layer: [
					{ mark: { type: 'bar', cornerRadius: 2, height: { band: 0.92 } }, encoding: { y, x, x2: { field: 'hi' }, color: { field: 'stage', type: 'nominal', sort: null, legend: s.opts.legend === false ? null : { title: null } } } },
					{ mark: { type: 'text', align: 'left', dx: 8, fontSize: 12 }, encoding: { y, x: q('hi'), text: { field: 'label' } } },
				],
			};
		},
	});

	C.type({
		id: 'pyramid', group: 'compare', label: 'Population pyramid', desc: 'Two groups back to back across ages', sample: 'pyramid',
		roles: [role('y', 'Age / band', 'any'), role('color', 'Group (two values)', 'cat'), role('x', 'Amount', 'num')], options: ['legend'],
		build(s) {
			const groups = distinct(s.records, s.f('color')).slice(0, 2);
			const bands = distinct(s.records, s.f('y'));
			const sign = (rec) => (rec[s.f('color')] === groups[0] ? -1 : 1);
			const records = s.records.filter((rec) => groups.includes(rec[s.f('color')])).map((rec) => ({ ...rec, _signed: rec[s.f('x')] * sign(rec) }));
			return {
				data: { values: records },
				mark: { type: 'bar' },
				encoding: {
					y: { field: s.f('y'), type: 'ordinal', sort: null, scale: { domain: bands }, axis: { title: s.opts.yTitle || null } },
					x: q('_signed', { axis: { title: s.opts.xTitle || null, labelExpr: "format(abs(datum.value), ',')" } }),
					color: { field: s.f('color'), type: 'nominal', scale: { domain: groups }, ...noLegend(s) },
				},
			};
		},
	});

	C.type({
		id: 'slope', group: 'compare', label: 'Slope chart', desc: 'Change between two points, per item', sample: 'slope',
		roles: [role('color', 'Item', 'any'), role('x', 'Before / after', 'any'), role('y', 'Value', 'num')], options: ['labels', 'legend'],
		opts: { legend: false },
		build(s) {
			const periods = distinct(s.records, s.f('x'));
			const first = periods[0], last = periods[periods.length - 1];
			const x = { field: s.f('x'), type: 'ordinal', sort: null, scale: { padding: 0.5 }, axis: { title: s.opts.xTitle || null, orient: 'top', labelAngle: 0, domain: false, ticks: false, labelFontSize: 13, labelPadding: 14 } };
			const y = q(s.f('y'), { scale: { zero: false, padding: 24 }, axis: { title: s.opts.yTitle || null } });
			const color = { field: s.f('color'), type: 'nominal', legend: s.opts.legend === false ? null : { title: null } };
			const ends = (period, align, dx) => ({
				transform: [{ filter: { field: s.f('x'), equal: period } }],
				mark: { type: 'text', align, dx, fontSize: 11 },
				encoding: { x, y, color, text: { field: s.f('color'), type: 'nominal' } },
			});
			const parts = [
				{ mark: { type: 'line', strokeWidth: 2.5 }, encoding: { x, y, color } },
				{ mark: { type: 'point', filled: true, size: 90, opacity: 1 }, encoding: { x, y, color } },
				ends(first, 'right', -10), ends(last, 'left', 10),
			];
			if (s.opts.labels) {
				const value = (period, align, dx) => ({ transform: [{ filter: { field: s.f('x'), equal: period } }], mark: { type: 'text', align, dx: dx, dy: -12, fontSize: 10 }, encoding: { x, y, text: { field: s.f('y'), type: 'quantitative' }, color } });
				parts.push(value(first, 'center', 0), value(last, 'center', 0));
			}
			return layers(s, parts);
		},
	});

	C.type({
		id: 'bump', group: 'trend', label: 'Bump chart', desc: 'How ranks change over time', sample: 'ranks',
		roles: [role('color', 'Item', 'any'), role('x', 'Period', 'any'), role('y', 'Score (higher = better rank)', 'num')], options: ['legend', 'labels'],
		build(s) {
			const x = { field: s.f('x'), type: 'ordinal', axis: { title: s.opts.xTitle || null, labelAngle: 0 } };
			const rank = { field: '_rank', type: 'quantitative', scale: { reverse: true, zero: false }, axis: { title: s.opts.yTitle || 'Rank', tickMinStep: 1, format: 'd' } };
			const color = { field: s.f('color'), type: 'nominal', ...noLegend(s) };
			const parts = [
				{ mark: { type: 'line', strokeWidth: 3, interpolate: 'monotone' }, encoding: { x, y: rank, color } },
				{ mark: { type: 'point', filled: true, size: 140, opacity: 1 }, encoding: { x, y: rank, color } },
			];
			if (s.opts.labels) parts.push({ mark: { type: 'text', color: 'white', fontSize: 10, fontWeight: 600 }, encoding: { x, y: rank, text: { field: '_rank', type: 'quantitative' } } });
			return { data: { values: s.records }, transform: [{ window: [{ op: 'rank', as: '_rank' }], sort: [{ field: s.f('y'), order: 'descending' }], groupby: [s.f('x')] }], layer: parts };
		},
	});

	C.type({
		id: 'marimekko', group: 'composition', label: 'Marimekko', desc: 'Two-way proportions: widths and heights both count', sample: 'mosaic',
		roles: [role('x', 'Column (width)', 'any'), role('color', 'Segment (height)', 'any'), role('y', 'Amount', 'num')], options: ['legend'],
		build(s) {
			const xs = distinct(s.records, s.f('x'));
			const cells = new Map();
			for (const rec of s.records) {
				const key = `${rec[s.f('x')]}\u0000${rec[s.f('color')]}`;
				cells.set(key, (cells.get(key) || 0) + (rec[s.f('y')] || 0));
			}
			const total = [...cells.values()].reduce((a, b) => a + b, 0) || 1;
			const colTotal = Object.fromEntries(xs.map((c) => [c, [...cells].filter(([k]) => k.startsWith(`${c}\u0000`)).reduce((a, [, v]) => a + v, 0)]));
			let x0 = 0;
			const rects = [], mids = [];
			for (const c of xs) {
				const w = colTotal[c] / total;
				let y0 = 0;
				for (const [k, v] of cells) {
					if (!k.startsWith(`${c}\u0000`)) continue;
					const share = colTotal[c] ? v / colTotal[c] : 0;
					rects.push({ column: String(c), segment: k.split('\u0000')[1], x0: r(x0, 4), x1: r(x0 + w, 4), y0: r(y0, 4), y1: r(y0 + share, 4), amount: v });
					y0 += share;
				}
				mids.push(r(x0 + w / 2, 4));
				x0 += w;
			}
			const labelExpr = `${JSON.stringify(xs.map(String))}[indexof(${JSON.stringify(mids)}, datum.value)]`;
			return {
				data: { values: rects },
				mark: { type: 'rect', stroke: 'white', strokeWidth: 1 },
				encoding: {
					x: q('x0', { axis: { title: s.opts.xTitle || null, values: mids, labelExpr, tickSize: 0, labelAngle: 0, domain: false }, scale: { domain: [0, 1], nice: false } }),
					x2: { field: 'x1' },
					y: q('y0', { axis: { title: s.opts.yTitle || null, format: '%' }, scale: { domain: [0, 1], nice: false } }),
					y2: { field: 'y1' },
					color: { field: 'segment', type: 'nominal', sort: null, ...noLegend(s) },
					tooltip: [{ field: 'column' }, { field: 'segment' }, { field: 'amount', type: 'quantitative' }],
				},
			};
		},
	});

	C.type({
		id: 'gantt', group: 'trend', label: 'Gantt / timeline', desc: 'Tasks with start and end dates', sample: 'tasks',
		roles: [role('y', 'Task', 'any'), role('x', 'Start', 'date'), role('x2', 'End', 'date'), role('color', 'Colour by (optional)', 'any', false)], options: ['legend'], defaults: { color: 'Owner' },
		build(s) {
			const kind = s.kind(s.f('x')) === 'quantitative' ? 'quantitative' : 'temporal';
			const enc = {
				y: { field: s.f('y'), type: 'nominal', sort: { field: s.f('x'), op: 'min' }, axis: { title: s.opts.yTitle || null } },
				x: { field: s.f('x'), type: kind, axis: { title: s.opts.xTitle || null } },
				x2: { field: s.f('x2') },
			};
			if (s.has('color')) enc.color = { field: s.f('color'), type: 'nominal', ...noLegend(s) };
			return wrap(s, { type: 'bar', cornerRadius: 3, height: { band: 0.6 } }, enc);
		},
	});

	C.sample('defects', 'Cause,Count\nScratches,52\nDents,31\nMisalignment,18\nDiscolouration,12\nCracks,9\nBurrs,6\nOther,4');
	C.option('threshold', { label: 'Highlight line at (%)', kind: 'number', default: 80, min: 1, max: 100 });

	C.type({
		id: 'pareto', group: 'compare', label: 'Pareto', desc: 'Sorted bars with a running share line', sample: 'defects',
		roles: [role('x', 'Category', 'any'), role('y', 'Count / amount', 'num')], options: ['threshold', 'labels'],
		build(s) {
			const sums = new Map();
			for (const rec of s.records) sums.set(String(rec[s.f('x')]), (sums.get(String(rec[s.f('x')])) || 0) + (rec[s.f('y')] || 0));
			const rows = [...sums].sort((a, b) => b[1] - a[1]);
			const total = rows.reduce((a, b) => a + b[1], 0) || 1;
			let run = 0;
			const data = rows.map(([name, v]) => ({ name, value: r(v, 3), share: r((run += v) / total, 4) }));
			const x = { field: 'name', type: 'ordinal', sort: null, axis: { title: s.opts.xTitle || null, labelAngle: -35, labelAlign: 'right', labelOverlap: false, labelLimit: 120 } };
			const line = Math.max(1, Math.min(100, Number(s.opts.threshold) || 80)) / 100;
			const parts = [
				{ mark: { type: 'bar', cornerRadiusEnd: 2 }, encoding: { x, y: q('value', { axis: { title: s.opts.yTitle || s.f('y') } }) } },
				{ mark: { type: 'line', color: '#eb6834', strokeWidth: 2.5, point: { filled: true, color: '#eb6834', size: 60 } }, encoding: { x, y: q('share', { scale: { domain: [0, 1] }, axis: { title: 'Cumulative share', format: '%', orient: 'right', titleColor: '#eb6834', labelColor: '#eb6834' } }) } },
				{ mark: { type: 'rule', color: '#eb6834', strokeDash: [4, 4], opacity: 0.7 }, encoding: { y: at(line, { scale: { domain: [0, 1] }, axis: null }) } },
			];
			if (s.opts.labels) parts.splice(1, 0, { mark: { type: 'text', dy: -6, fontSize: 11 }, encoding: { x, y: q('value'), text: q('value') } });
			return { data: { values: data }, layer: parts, resolve: { scale: { y: 'independent' } } };
		},
	});
})(typeof window !== 'undefined' ? window : globalThis);
