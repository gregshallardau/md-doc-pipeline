/*
 * Chart types backed by upstream Vega / Vega-Lite examples (chart-templates.js). Each type names the
 * template it fills, which of the example's fields the user's columns replace, and any edit the
 * template needs, with the reason. See ChartCatalog.upstream in chart-core.js.
 * Shared byte-for-byte with md-doc-pipeline's studio.
 */
(function (root) {
	'use strict';
	const C = root.ChartCatalog;
	const { rng, day } = C.h;
	const role = (key, label, kind = 'any', required = true, extra) => ({ key, label, kind, required, ...extra });

	/** An edit that drops the transform steps matching `test`, for the stated reason. */
	const dropTransform = (why, test) => ({ why, apply(spec) { spec.transform = (spec.transform || []).filter((t) => !test(t)); if (!spec.transform.length) delete spec.transform; } });
	const dropChannelProp = (why, channel, prop) => ({ why, apply(spec) { const visit = (n) => { if (n && n.encoding && n.encoding[channel]) delete n.encoding[channel][prop]; (n.layer || []).forEach(visit); }; visit(spec); } });

	/* ── Sample data ────────────────────────────────────────────────────── */

	C.sample('u_people', () => {
		const next = rng(7);
		const rows = ['Height,Weight,Age'];
		for (let i = 0; i < 60; i++) { const h = 150 + Math.round(next() * 45); rows.push(`${h},${Math.round((h - 100) * 0.9 + next() * 18)},${20 + Math.round(next() * 40)}`); }
		return rows.join('\n');
	});
	C.sample('u_prices', () => ['Date,Price', ...Array.from({ length: 24 }, (_, i) => `${day(i * 30)},${Math.round(100 + i * 3 + Math.sin(i / 2) * 12)}`)].join('\n'));
	C.sample('u_counts', () => ['Date,Count', ...Array.from({ length: 24 }, (_, i) => `${day(i * 30)},${Math.round(900 + Math.sin(i / 3) * 300 + i * 20)}`)].join('\n'));
	C.sample('u_series', () => {
		const rows = ['Date,Series,Count'];
		for (let i = 0; i < 24; i++) for (const [k, name] of ['Retail', 'Services', 'Construction'].entries()) rows.push(`${day(i * 30)},${name},${Math.round(300 + k * 150 + Math.sin(i / 3 + k) * 120 + i * (6 - k))}`);
		return rows.join('\n');
	});
	C.sample('u_shares', 'Category,Value\nNorth,42\nSouth,31\nEast,17\nWest,10');
	C.sample('u_bars', 'Category,Value\nNorth,42\nSouth,31\nEast,17\nWest,10\nCentral,24');
	C.sample('u_groups', 'Category,Group,Value\nQ1,Online,28\nQ1,Retail,55\nQ2,Online,43\nQ2,Retail,91\nQ3,Online,81\nQ3,Retail,53\nQ4,Online,19\nQ4,Retail,87');
	C.sample('u_stack', 'Product,Region,Sales\nWidgets,North,48\nWidgets,South,32\nWidgets,East,21\nGadgets,North,36\nGadgets,South,44\nGadgets,East,19\nGizmos,North,22\nGizmos,South,28\nGizmos,East,41');
	C.sample('u_split', 'Age,Gender,People\n0,Female,9735\n0,Male,10119\n5,Female,9310\n5,Male,9757\n10,Female,9660\n10,Male,10141\n15,Female,10240\n15,Male,10867\n20,Female,10425\n20,Male,11043');
	C.sample('u_grid', () => {
		const next = rng(3);
		const rows = ['Origin,Cylinders,Horsepower'];
		for (const [o, base] of [['USA', 160], ['Europe', 80], ['Japan', 85]]) for (const c of [3, 4, 5, 6, 8]) for (let i = 0; i < 3; i++) rows.push(`${o},${c},${Math.round(base + c * 8 + next() * 25)}`);
		return rows.join('\n');
	});
	C.sample('u_ratings', () => {
		const next = rng(11);
		return ['Rating', ...Array.from({ length: 120 }, () => ((next() + next() + next()) / 3 * 7 + 2.5).toFixed(1))].join('\n');
	});

	const cat = role('x', 'Category', 'any'), val = role('y', 'Value', 'num');

	/* ── Bars ───────────────────────────────────────────────────────────── */

	C.upstream({
		id: 'bar', group: 'compare', label: 'Bar', desc: 'One bar per category', sample: 'u_bars',
		roles: [cat, val], options: [],
		templates: [{ key: 'vega-lite/bar', fields: { x: 'a', y: 'b' } }],
	});
	C.upstream({
		id: 'hbar', group: 'compare', label: 'Horizontal bar', desc: 'Bars read left to right; long names fit', sample: 'u_bars',
		roles: [cat, val], options: ['labels'],
		templates: [
			{ key: 'vega-lite/layer_bar_labels', when: (o) => o.labels === true, fields: { x: 'a', y: 'b' }, edits: [{ why: 'its x scale domain [0, 60] fits the example’s three values', apply(spec) { delete spec.encoding.x.scale; } }] },
			{ key: 'vega-lite/bar_aggregate', fields: { x: 'age', y: 'people' }, edits: [
				dropTransform('it keeps one year (`datum.year == 2000`) of a multi-year file; your table is the data', (t) => t.filter),
				dropChannelProp('its x axis title “population” names the example’s own field', 'x', 'title'),
			] },
		],
	});
	// the roles of the two hbar templates differ: x/y above name the same two columns for both
	C.upstream({
		id: 'bar-grouped', group: 'compare', label: 'Grouped bar', desc: 'Bars side by side within each category', sample: 'u_groups',
		roles: [role('x', 'Category', 'any'), role('y', 'Value', 'num'), role('group', 'Group', 'any')], options: ['legend'],
		templates: [{ key: 'vega-lite/bar_grouped', fields: { x: 'category', y: 'value', group: 'group' } }],
	});
	C.upstream({
		id: 'bar-stacked', group: 'compare', label: 'Stacked bar', desc: 'Parts of each category, stacked', sample: 'u_stack', sampleMap: { x: 'Product', y: 'Sales', group: 'Region' },
		roles: [role('x', 'Category', 'any'), role('y', 'Value', 'num'), role('group', 'Stack by', 'any')], options: ['legend'],
		templates: [{ key: 'vega-lite/stacked_bar_h', fields: { x: 'variety', y: 'yield', group: 'site' } }],
	});
	C.upstream({
		id: 'bar-percent', group: 'compare', label: '100% stacked bar', desc: 'Each category’s mix, as shares', sample: 'u_split', sampleMap: { x: 'Age', y: 'People', group: 'Gender' },
		roles: [role('x', 'Category', 'any'), role('y', 'Value', 'num'), role('group', 'Stack by', 'any')], options: ['legend'],
		templates: [{ key: 'vega-lite/stacked_bar_normalize', fields: { x: 'age', y: 'people', group: 'gender' }, edits: [
			dropTransform('it filters one year and derives `gender` from the example’s `sex` code; your table already has the split', () => true),
			dropChannelProp('its y axis title “population” names the example’s own field', 'y', 'title'),
		] }],
	});

	/* ── Change over time ───────────────────────────────────────────────── */

	const noSymbol = dropTransform('it plots one stock (`symbol === \'GOOG\'`) from a multi-stock file; your table is the series', (t) => t.filter);
	C.upstream({
		id: 'line', group: 'trend', label: 'Line', desc: 'A value over time', sample: 'u_prices',
		roles: [role('x', 'Date', 'time'), role('y', 'Value', 'num')], options: [],
		templates: [{ key: 'vega-lite/line', fields: { x: 'date', y: 'price' }, edits: [noSymbol] }],
	});
	C.upstream({
		id: 'step', group: 'trend', label: 'Step line', desc: 'Holds each value until the next change', sample: 'u_prices',
		roles: [role('x', 'Date', 'time'), role('y', 'Value', 'num')], options: [],
		templates: [{ key: 'vega-lite/line_step', fields: { x: 'date', y: 'price' }, edits: [noSymbol] }],
	});
	const areaTitle = dropChannelProp('its y axis title “count” names the example’s own field', 'y', 'title');
	C.upstream({
		id: 'area', group: 'trend', label: 'Area', desc: 'A value over time, filled', sample: 'u_counts',
		roles: [role('x', 'Date', 'time'), role('y', 'Value', 'num')], options: [],
		templates: [{ key: 'vega-lite/area', fields: { x: 'date', y: 'count' }, edits: [areaTitle] }],
	});
	const stackRoles = [role('x', 'Date', 'time'), role('y', 'Value', 'num'), role('group', 'Series', 'any')];
	C.upstream({
		id: 'area-stacked', group: 'trend', label: 'Stacked area', desc: 'Parts of a total over time', sample: 'u_series',
		roles: stackRoles, options: ['legend'],
		templates: [{ key: 'vega-lite/stacked_area', fields: { x: 'date', y: 'count', group: 'series' } }],
	});
	C.upstream({
		id: 'area-percent', group: 'trend', label: '100% stacked area', desc: 'The mix over time, as shares', sample: 'u_series',
		roles: stackRoles, options: ['legend'],
		templates: [{ key: 'vega-lite/stacked_area_normalize', fields: { x: 'date', y: 'count', group: 'series' } }],
	});
	C.upstream({
		id: 'streamgraph', group: 'trend', label: 'Streamgraph', desc: 'Stacked area, centred on the middle', sample: 'u_series',
		roles: stackRoles, options: ['legend'],
		templates: [{ key: 'vega-lite/stacked_area_stream', fields: { x: 'date', y: 'count', group: 'series' } }],
	});

	/* ── Relationships, distribution, matrix, parts of a whole ──────────── */

	C.upstream({
		id: 'scatter', group: 'relationship', label: 'Scatter', desc: 'Two numbers against each other', sample: 'u_people', sampleMap: { x: 'Height', y: 'Weight' },
		roles: [role('x', 'X (number)', 'num'), role('y', 'Y (number)', 'num')], options: [],
		templates: [{ key: 'vega-lite/point_2d', fields: { x: 'Horsepower', y: 'Miles_per_Gallon' } }],
	});
	C.upstream({
		id: 'bubble', group: 'relationship', label: 'Bubble', desc: 'A scatter whose point size is a third number', sample: 'u_people', sampleMap: { x: 'Height', y: 'Weight', size: 'Age' },
		roles: [role('x', 'X (number)', 'num'), role('y', 'Y (number)', 'num'), role('size', 'Size (number)', 'num')], options: ['legend'],
		templates: [{ key: 'vega-lite/point_bubble', fields: { x: 'Horsepower', y: 'Miles_per_Gallon', size: 'Acceleration' } }],
	});
	C.upstream({
		id: 'histogram', group: 'distribution', label: 'Histogram', desc: 'How many values fall in each range', sample: 'u_ratings', sampleMap: { x: 'Rating' },
		roles: [role('x', 'Values (number)', 'num')], options: [],
		templates: [{ key: 'vega-lite/histogram', fields: { x: 'IMDB Rating' } }],
	});
	C.upstream({
		id: 'heatmap', group: 'matrix', label: 'Heatmap', desc: 'Colour shows a value for each row and column', sample: 'u_grid', sampleMap: { y: 'Origin', x: 'Cylinders', color: 'Horsepower' },
		roles: [role('y', 'Rows', 'any'), role('x', 'Columns', 'any'), role('color', 'Colour (number, averaged)', 'num')], options: ['legend'],
		templates: [{ key: 'vega-lite/rect_heatmap', fields: { y: 'Origin', x: 'Cylinders', color: 'Horsepower' } }],
	});
	C.upstream({
		id: 'pie', group: 'composition', label: 'Pie', desc: 'Share of a whole (few slices)', sample: 'u_shares',
		roles: [role('color', 'Slice label', 'any'), role('theta', 'Slice size', 'num')], options: ['legend'], sampleMap: { color: 'Category', theta: 'Value' },
		templates: [{ key: 'vega-lite/arc_pie', fields: { color: 'category', theta: 'value' } }],
	});
	C.upstream({
		id: 'donut', group: 'composition', label: 'Donut', desc: 'Share of a whole, with a centre', sample: 'u_shares',
		roles: [role('color', 'Slice label', 'any'), role('theta', 'Slice size', 'num')], options: ['legend'], sampleMap: { color: 'Category', theta: 'Value' },
		templates: [{ key: 'vega-lite/arc_donut', fields: { color: 'category', theta: 'value' } }],
	});

	/* ── More edits ─────────────────────────────────────────────────────── */

	/** An edit that runs `fn(spec, s)` for the stated reason. */
	const edit = (why, fn) => ({ why, apply: fn });
	/** Every `title` found under an encoding channel (any layer) is the example's own wording. */
	const dropTitles = (why, ...channels) => edit(why, (spec) => { const visit = (n) => { for (const ch of channels) if (n.encoding && n.encoding[ch]) { delete n.encoding[ch].title; if (n.encoding[ch].axis) delete n.encoding[ch].axis.title; } (n.layer || []).forEach(visit); }; visit(spec); });
	/** Title the channel with the user's column in place of the example's own wording. `get` finds the title holder. */
	const retitle = (why, role, get) => edit(why, (spec, s) => { const h = get(spec); if (h) h.title = s.f(role); });
	const dropTopTitle = edit('its chart title names the example’s own data', (spec) => { delete spec.title; });

	/* ── Sample data (second batch) ─────────────────────────────────────── */

	C.sample('u_period', 'Site,Year,Yield\nGrand Rapids,1931,26\nGrand Rapids,1932,27\nDuluth,1931,24\nDuluth,1932,30\nMorris,1931,31\nMorris,1932,29\nCrookston,1931,33\nCrookston,1932,34');
	C.sample('u_rank', 'Team,Matchday,Points\nGermany,1,0\nMexico,1,3\nSouth Korea,1,0\nSweden,1,3\nGermany,2,0\nMexico,2,6\nSouth Korea,2,3\nSweden,2,3\nGermany,3,3\nMexico,3,6\nSouth Korea,3,6\nSweden,3,3');
	C.sample('u_dumbbell', 'Country,Year,Life expectancy\nChina,1955,50\nChina,2000,72\nIndia,1955,41\nIndia,2000,62\nBrazil,1955,53\nBrazil,2000,70\nIndonesia,1955,42\nIndonesia,2000,66');
	C.sample('u_bullet', 'Measure,Low,Mid,High,Actual,Prior,Target\nRevenue,150,225,300,270,220,250\nProfit,20,25,30,23,21,26\nOrders,350,500,600,550,480,570\nSatisfaction,3.5,4.25,5,4.6,4.2,4.4');
	C.sample('u_waterfall', 'Label,Amount\nBegin,4000\nJan,1707\nFeb,-1425\nMar,-1030\nApr,1812\nMay,-1067\nJun,-1481\nJul,1228\nAug,1176\nSep,1146\nOct,1205\nNov,-1388\nDec,1492\nEnd,0');
	C.sample('u_pyramid', 'Age,Gender,People\n0,Female,9735\n0,Male,10119\n10,Female,9660\n10,Male,10141\n20,Female,10425\n20,Male,11043\n30,Female,10560\n30,Male,10990\n40,Female,10990\n40,Male,10650\n50,Female,9640\n50,Male,9080\n60,Female,7020\n60,Male,6310\n70,Female,4510\n70,Male,3380\n80,Female,2400\n80,Male,1260');
	C.sample('u_mosaic', () => { const next = rng(5); const rows = ['Origin,Cylinders']; for (const [o, cyls] of [['USA', [4, 6, 8, 8, 8]], ['Europe', [4, 4, 4, 6]], ['Japan', [4, 4, 4, 4, 6]]]) for (let i = 0; i < 18; i++) rows.push(`${o},${cyls[Math.floor(next() * cyls.length)]}`); return rows.join('\n'); });
	C.sample('u_gantt', 'Task,Start,End\nResearch,1,4\nDesign,3,8\nBuild,7,15\nTest,13,18\nLaunch,17,19');
	C.sample('u_temps', () => { const next = rng(2); return ['Date,Max temperature', ...Array.from({ length: 90 }, (_, i) => `${day(i)},${Math.round(8 + Math.sin(i / 14) * 7 + next() * 6)}`)].join('\n'); });
	C.sample('u_weather', () => ['Date,Max,Min,Precipitation', ...Array.from({ length: 12 }, (_, i) => `${day(i * 30 + 10)},${Math.round(8 + Math.sin(i / 2 - 1.2) * 9)},${Math.round(1 + Math.sin(i / 2 - 1.2) * 6)},${(3 + Math.cos(i / 2) * 2).toFixed(1)}`)].join('\n'));
	C.sample('u_ohlc', () => { const next = rng(9); let price = 100; return ['Date,Open,High,Low,Close', ...Array.from({ length: 24 }, (_, i) => { const open = price; price = open + (next() - 0.48) * 8; return `${day(i)},${open.toFixed(1)},${(Math.max(open, price) + next() * 3).toFixed(1)},${(Math.min(open, price) - next() * 3).toFixed(1)},${price.toFixed(1)}`; })].join('\n'); });
	C.sample('u_wave', 'Step,Value\n1,28\n2,55\n3,43\n4,91\n5,81\n6,53\n7,19\n8,87\n9,52\n10,48\n11,24\n12,49\n13,87\n14,66\n15,17\n16,27\n17,68\n18,16\n19,49\n20,15');
	C.sample('u_cars', () => { const next = rng(13); const rows = ['Origin,Horsepower,Cylinders,Miles per gallon,Acceleration']; for (const [o, base, cyl] of [['USA', 140, [6, 8]], ['Europe', 80, [4, 4, 6]], ['Japan', 82, [4, 4, 4]]]) for (let i = 0; i < 30; i++) { const hp = Math.round(base + next() * 60); rows.push(`${o},${hp},${cyl[Math.floor(next() * cyl.length)]},${Math.round(45 - hp / 5 + next() * 8)},${(10 + next() * 10).toFixed(1)}`); } return rows.join('\n'); });
	C.sample('u_penguins', () => { const next = rng(17); const rows = ['Species,Body mass,Beak length,Beak depth,Flipper length']; for (const [sp, m, l, d, f] of [['Adelie', 3700, 38, 18.3, 190], ['Chinstrap', 3730, 49, 18.4, 196], ['Gentoo', 5070, 47, 15, 217]]) for (let i = 0; i < 25; i++) rows.push(`${sp},${Math.round(m + (next() - 0.5) * 900)},${(l + (next() - 0.5) * 6).toFixed(1)},${(d + (next() - 0.5) * 2.4).toFixed(1)},${Math.round(f + (next() - 0.5) * 16)}`); return rows.join('\n'); });
	C.sample('u_barley', () => { const next = rng(19); const rows = ['Variety,Yield']; for (const v of ['Manchuria', 'Glabron', 'Svansota', 'Velvet', 'Peatland', 'Trebi']) for (let i = 0; i < 8; i++) rows.push(`${v},${Math.round(22 + next() * 18 + (v === 'Trebi' ? 8 : 0))}`); return rows.join('\n'); });
	C.sample('u_mpg_years', () => { const next = rng(23); const rows = ['Year,Miles per gallon']; for (let y = 1970; y <= 1982; y++) for (let i = 0; i < 12; i++) rows.push(`${y}-01-01,${(14 + (y - 1970) * 1.1 + (next() - 0.5) * 9).toFixed(1)}`); return rows.join('\n'); });
	C.sample('u_pairs', () => { const next = rng(29); const rows = ['Critics,Audience']; for (let i = 0; i < 70; i++) { const r = Math.round(10 + next() * 85); rows.push(`${r},${(2 + r / 14 + (next() - 0.5) * 2.4).toFixed(1)}`); } return rows.join('\n'); });
	C.sample('u_driving', 'Year,Miles,Gas\n1956,3600,2.3\n1960,3700,2.5\n1964,3920,2.4\n1968,4100,2.45\n1972,4400,2.6\n1974,4350,3.4\n1976,4600,3.2\n1978,4800,3.1\n1980,4700,4.1\n1984,4900,3.4\n1988,5400,2.9\n1992,5900,2.8\n1996,6300,2.9\n2000,6800,3.3\n2004,7000,3.9');
	C.sample('u_uniform', () => { const next = rng(31); return ['Value', ...Array.from({ length: 80 }, () => (next() + next() + next() + next() - 2).toFixed(2))].join('\n'); });
	C.sample('u_dots', 'Value\n1\n1\n1\n1\n2\n2\n2\n3\n3\n3\n3\n3\n4\n4\n5\n5\n5\n6\n7\n7\n8');

	/* ── Bars and comparison ────────────────────────────────────────────── */

	C.upstream({
		id: 'slope', group: 'compare', label: 'Slope chart', desc: 'Two or more points in time, joined by lines', sample: 'u_period', sampleMap: { x: 'Year', y: 'Yield', group: 'Site' },
		roles: [role('x', 'Period', 'any'), role('y', 'Value (median)', 'num'), role('group', 'Series', 'any')], options: ['legend'],
		templates: [{ key: 'vega-lite/line_slope', fields: { x: 'year', y: 'yield', group: 'site' } }],
	});
	C.upstream({
		id: 'bump', group: 'compare', label: 'Bump chart', desc: 'Each item’s rank over time', sample: 'u_rank', sampleMap: { x: 'Matchday', y: 'Points', group: 'Team' },
		roles: [role('x', 'Period', 'any'), role('y', 'Score (ranked, high first)', 'num'), role('group', 'Item', 'any')], options: ['legend'],
		templates: [{ key: 'vega-lite/window_rank', fields: { x: 'matchday', y: 'point', group: 'team' }, edits: [
			dropTopTitle,
			edit('its ranking breaks ties on a second column (`diff`) your table does not have', (spec) => { spec.transform[0].sort = spec.transform[0].sort.filter((x) => x.field !== 'diff'); }),
			edit('its colour scale lists the example’s four teams with fixed colours', (spec) => { delete spec.encoding.color.scale; }),
		] }],
	});
	C.upstream({
		id: 'dumbbell', group: 'compare', label: 'Dumbbell', desc: 'Two values per item, joined by a line', sample: 'u_dumbbell', sampleMap: { x: 'Life expectancy', y: 'Country', group: 'Year' },
		roles: [role('x', 'Value', 'num'), role('y', 'Item', 'any'), role('group', 'Which of the two', 'any')], options: ['legend'],
		templates: [{ key: 'vega-lite/layer_ranged_dot', fields: { x: 'life_expect', y: 'country', group: 'year' }, edits: [
			dropTransform('it keeps five named countries and two years of a larger file', (t) => t.filter),
			dropTitles('its axis and legend titles are the example’s own wording', 'x', 'y', 'color'),
			edit('its colour scale pins the example’s two years (1955, 2000)', (spec) => { delete spec.layer[1].encoding.color.scale; }),
		] }],
	});
	C.upstream({
		id: 'bullet', group: 'kpi', label: 'Bullet chart', desc: 'Actual against target, over bands', sample: 'u_bullet', sampleMap: { title: 'Measure', low: 'Low', mid: 'Mid', high: 'High', actual: 'Actual', prior: 'Prior', target: 'Target' },
		roles: [role('title', 'Measure', 'any'), role('low', 'Band 1 (to)', 'num'), role('mid', 'Band 2 (to)', 'num'), role('high', 'Band 3 (to)', 'num'), role('actual', 'Actual', 'num'), role('prior', 'Comparison', 'num'), role('target', 'Target', 'num')], options: [],
		templates: [{ key: 'vega-lite/facet_bullet', fields: { title: 'title', low: 'ranges[0]', mid: 'ranges[1]', high: 'ranges[2]', actual: 'measures[0]', prior: 'measures[1]', target: 'markers[0]' } }],
	});
	C.upstream({
		id: 'waterfall', group: 'compare', label: 'Waterfall', desc: 'A running total built from ups and downs (rows named Begin and End)', sample: 'u_waterfall', sampleMap: { x: 'Label', y: 'Amount' },
		roles: [role('x', 'Step', 'any'), role('y', 'Change', 'num')], options: [],
		templates: [{ key: 'vega-lite/waterfall_chart', rename: 'data', fields: { x: 'label', y: 'amount' }, edits: [
			retitle('its x axis title “Months” is the example’s own wording; here it is your column', 'x', (spec) => spec.encoding.x.axis),
			retitle('its y axis title “Amount” is the example’s own wording; here it is your column', 'y', (spec) => spec.layer[0].encoding.y),
		] }],
	});
	C.upstream({
		id: 'pyramid', group: 'compare', label: 'Population pyramid', desc: 'Two groups back to back (Female and Male)', sample: 'u_pyramid', sampleMap: { x: 'Age', y: 'People', group: 'Gender' },
		roles: [role('x', 'Category', 'any'), role('y', 'Value', 'num'), role('group', 'Side (Female / Male)', 'any')], options: [],
		templates: [{ key: 'vega-lite/bar_diverging_stack_population_pyramid', fields: { x: 'age', y: 'people', group: 'gender' }, edits: [
			edit('it filters one year and derives `gender` from the example’s `sex` code; your table has Gender (Female / Male) already, which also decides which side a bar is drawn on', (spec) => {
				spec.transform = [{ calculate: "datum.gender == 'Female' ? -datum.people : datum.people", as: 'signed_people' }];
			}),
			retitle('its x axis title “population” names the example’s own field; here it is your value column', 'y', (spec) => spec.encoding.x),
		] }],
	});
	C.upstream({
		id: 'marimekko', group: 'compare', label: 'Mosaic (Marimekko)', desc: 'Rectangles sized by how many rows share two categories', sample: 'u_mosaic', sampleMap: { y: 'Origin', x: 'Cylinders' },
		roles: [role('y', 'Rows', 'any'), role('x', 'Columns', 'any')], options: [],
		templates: [{ key: 'vega-lite/rect_mosaic_labelled_with_offset', fields: { y: 'Origin', x: 'Cylinders' } }],
	});
	C.upstream({
		id: 'gantt', group: 'trend', label: 'Gantt', desc: 'Tasks as bars from start to end', sample: 'u_gantt',
		roles: [role('task', 'Task', 'any'), role('start', 'Start', 'num'), role('end', 'End', 'num')], options: [],
		templates: [{ key: 'vega-lite/bar_gantt', fields: { task: 'task', start: 'start', end: 'end' } }],
	});

	/* ── Change over time (second batch) ────────────────────────────────── */

	C.upstream({
		id: 'moving-average', group: 'trend', label: 'Rolling average', desc: 'Raw points with their 31-step rolling mean', sample: 'u_temps',
		roles: [role('x', 'Date', 'time'), role('y', 'Value', 'num')], options: [],
		templates: [{ key: 'vega-lite/layer_line_rolling_mean_point_raw', fields: { x: 'date', y: 'temp_max' }, edits: [
			edit('its layer titles (“Max Temperature”, “Rolling Mean of Max Temperature”) and axis title name the example’s own field; the axis is titled with your column', (spec, s) => { for (const l of spec.layer) delete l.encoding.y.title; spec.encoding.y.axis.title = s.f('y'); delete spec.encoding.x.title; }),
		] }],
	});
	C.upstream({
		id: 'combo', group: 'trend', label: 'Range and line', desc: 'A shaded range with a second measure on its own axis', sample: 'u_weather', sampleMap: { x: 'Date', y: 'Max', y2: 'Min', line: 'Precipitation' },
		roles: [role('x', 'Date', 'time'), role('y', 'Range top', 'num'), role('y2', 'Range bottom', 'num'), role('line', 'Line (own axis)', 'num')], options: [],
		templates: [{ key: 'vega-lite/layer_dual_axis', fields: { x: 'date', y: 'temp_max', y2: 'temp_min', line: 'precipitation' }, edits: [
			dropTransform('it keeps one city (`location == "Seattle"`) of a multi-city file', (t) => t.filter),
			edit('its range axis is fixed to [0, 30] °C and titled “Avg. Temperature (°C)” / “Precipitation (inches)” for the example’s data', (spec) => { for (const l of spec.layer) { delete l.encoding.y.scale; delete l.encoding.y.title; delete l.encoding.y.axis.titleColor; } }),
		] }],
	});
	C.upstream({
		id: 'candlestick', group: 'trend', label: 'Candlestick', desc: 'Open, high, low and close per period', sample: 'u_ohlc',
		roles: [role('date', 'Date', 'time'), role('open', 'Open', 'num'), role('high', 'High', 'num'), role('low', 'Low', 'num'), role('close', 'Close', 'num')], options: [],
		templates: [{ key: 'vega-lite/layer_candlestick', fields: { date: 'date', open: 'open', high: 'high', low: 'low', close: 'close' }, edits: [
			edit('its x axis title “Date in 2009” and %m/%d format describe the example’s data', (spec) => { delete spec.encoding.x.title; delete spec.encoding.x.axis.title; delete spec.encoding.x.axis.format; }),
		] }],
	});
	C.upstream({
		id: 'horizon', group: 'trend', label: 'Horizon', desc: 'A compact band chart; higher values wrap into darker layers', sample: 'u_wave', sampleMap: { x: 'Step', y: 'Value' },
		roles: [role('x', 'Position', 'num'), role('y', 'Value', 'num')], options: [],
		templates: [{ key: 'vega-lite/area_horizon', fields: { x: 'x', y: 'y' }, edits: [
			edit('its band height 50 (domain [0, 50] and `datum.y - 50`) is half of the example’s largest value; here it is half of yours', (spec, s) => {
				const top = Math.max(...s.records.map((r) => Number(r[s.f('y')]) || 0));
				const band = Math.max(1, Math.round(top / 2));
				spec.encoding.y.scale.domain = [0, band];
				spec.layer[1].transform[0].calculate = `datum.y - ${band}`;
				spec.layer[1].encoding.y.scale.domain = [0, band];
			}),
		] }],
	});
	C.upstream({
		id: 'cumulative', group: 'trend', label: 'Cumulative total', desc: 'The running count of values up to each point', sample: 'u_uniform', sampleMap: { x: 'Value' },
		roles: [role('x', 'Values (number)', 'num')], options: [],
		templates: [{ key: 'vega-lite/area_cumulative_freq', fields: { x: 'IMDB Rating' } }],
	});

	/* ── Distribution (second batch) ────────────────────────────────────── */

	C.upstream({
		id: 'histogram-grouped', group: 'distribution', label: 'Histogram by group', desc: 'One histogram per group, stacked in rows', sample: 'u_cars', sampleMap: { x: 'Horsepower', row: 'Origin' },
		roles: [role('x', 'Values (number)', 'num'), role('row', 'Group', 'any')], options: [],
		templates: [{ key: 'vega-lite/trellis_bar_histogram', fields: { x: 'Horsepower', row: 'Origin' } }],
	});
	C.upstream({
		id: 'dot-histogram', group: 'distribution', label: 'Dot histogram', desc: 'Each value is a dot, stacked where equal', sample: 'u_dots', sampleMap: { x: 'Value' },
		roles: [role('x', 'Values (whole numbers)', 'num')], options: [],
		templates: [{ key: 'vega-lite/circle_wilkinson_dotplot', fields: { x: 'data' } }],
	});
	C.upstream({
		id: 'density', group: 'distribution', label: 'Density', desc: 'A smooth curve of how values are spread', sample: 'u_ratings', sampleMap: { x: 'Rating' },
		roles: [role('x', 'Values (number)', 'num')], options: [],
		templates: [{ key: 'vega-lite/area_density', fields: { x: 'IMDB Rating' }, edits: [dropTitles('its x axis title “IMDB Rating” names the example’s own field', 'x')] }],
	});
	const penguinEdits = [
		dropTopTitle,
		edit('its density extent [2500, 6500] is the range of the example’s body masses', (spec) => { delete spec.transform[0].extent; }),
		dropTitles('its x axis title “Body Mass (g)” names the example’s own field', 'x'),
	];
	C.upstream({
		id: 'density-groups', group: 'distribution', label: 'Density by group', desc: 'Overlaid density curves, one per group', sample: 'u_penguins', sampleMap: { x: 'Body mass', group: 'Species' },
		roles: [role('x', 'Values (number)', 'num'), role('group', 'Group', 'any')], options: ['legend'],
		templates: [{ key: 'vega-lite/area_density_stacked', fields: { x: 'Body Mass (g)', group: 'Species' }, edits: penguinEdits }],
	});
	C.upstream({
		id: 'ridgeline', group: 'distribution', label: 'Ridgeline', desc: 'One density curve per group, in rows', sample: 'u_penguins', sampleMap: { x: 'Body mass', group: 'Species' },
		roles: [role('x', 'Values (number)', 'num'), role('group', 'Group', 'any')], options: [],
		templates: [{ key: 'vega-lite/area_density_facet', fields: { x: 'Body Mass (g)', group: 'Species' }, edits: penguinEdits }],
	});
	C.upstream({
		id: 'box', group: 'distribution', label: 'Box plot', desc: 'Median, quartiles and spread per group', sample: 'u_penguins', sampleMap: { x: 'Species', y: 'Body mass' },
		roles: [role('x', 'Group', 'any'), role('y', 'Values (number)', 'num')], options: [],
		templates: [{ key: 'vega-lite/boxplot_2D_vertical', fields: { x: 'Species', y: 'Body Mass (g)' } }],
	});
	C.upstream({
		id: 'strip', group: 'distribution', label: 'Strip plot', desc: 'Every value as a tick, by group', sample: 'u_cars', sampleMap: { x: 'Horsepower', y: 'Cylinders' },
		roles: [role('x', 'Values (number)', 'num'), role('y', 'Group', 'any')], options: [],
		templates: [{ key: 'vega-lite/tick_strip', fields: { x: 'Horsepower', y: 'Cylinders' } }],
	});
	C.upstream({
		random: 'Vega-Lite bootstraps this confidence interval, so it differs slightly on every render', id: 'error-bars', group: 'distribution', label: 'Mean with error bars', desc: 'Mean and 95% confidence interval per group', sample: 'u_barley', sampleMap: { y: 'Variety', x: 'Yield' },
		roles: [role('y', 'Group', 'any'), role('x', 'Values (number)', 'num')], options: [],
		templates: [{ key: 'vega-lite/layer_point_errorbar_ci', fields: { y: 'variety', x: 'yield' }, edits: [dropTitles('its x axis title “Barley Yield” names the example’s own field', 'x')] }],
	});
	C.upstream({
		random: 'Vega-Lite bootstraps this confidence band, so it differs slightly on every render', id: 'error-band', group: 'trend', label: 'Mean with confidence band', desc: 'A yearly mean with its 95% confidence band', sample: 'u_mpg_years', sampleMap: { x: 'Year', y: 'Miles per gallon' },
		roles: [role('x', 'Date', 'time'), role('y', 'Values (number)', 'num')], options: [],
		templates: [{ key: 'vega-lite/layer_line_errorband_ci', fields: { x: 'Year', y: 'Miles_per_Gallon' }, edits: [dropTitles('its y axis title “Mean of Miles per Gallon (95% CIs)” names the example’s own field', 'y')] }],
	});
	C.upstream({
		id: 'ecdf', group: 'distribution', label: 'Cumulative distribution', desc: 'How much of the data lies at or below each value', sample: 'u_ratings', sampleMap: { x: 'Rating' },
		roles: [role('x', 'Values (number)', 'num')], options: [],
		templates: [{ key: 'vega-lite/area_cumulative_freq', fields: { x: 'IMDB Rating' } }],
	});
	C.upstream({
		id: 'qq-plot', group: 'distribution', label: 'Q-Q plot', desc: 'Your quantiles against a uniform and a normal distribution', sample: 'u_uniform', sampleMap: { x: 'Value' },
		roles: [role('x', 'Values (number)', 'num')], options: [],
		templates: [{ key: 'vega-lite/point_quantile_quantile', fields: { x: 'u' } }],
	});

	/* ── Relationships and matrices (second batch) ──────────────────────── */

	C.option('fit', { label: 'Trend line', kind: 'select', default: 'linear', hint: 'Straight line (regression, with R²) or LOESS smoothing', choices: [['linear', 'Linear regression'], ['loess', 'LOESS']] });
	C.upstream({
		id: 'scatter-trend', group: 'relationship', label: 'Scatter with trend', desc: 'Points with a fitted line', sample: 'u_pairs', sampleMap: { x: 'Critics', y: 'Audience' },
		roles: [role('x', 'X (number)', 'num'), role('y', 'Y (number)', 'num')], options: ['fit'],
		templates: [
			{ key: 'vega-lite/layer_point_line_loess', when: (o) => o.fit === 'loess', fields: { x: 'Rotten Tomatoes Rating', y: 'IMDB Rating' } },
			{ key: 'vega-lite/layer_point_line_regression', fields: { x: 'Rotten Tomatoes Rating', y: 'IMDB Rating' } },
		],
	});
	C.upstream({
		id: 'connected-scatter', group: 'relationship', label: 'Connected scatter', desc: 'A path through two measures over time', sample: 'u_driving', sampleMap: { x: 'Miles', y: 'Gas', order: 'Year' },
		roles: [role('x', 'X (number)', 'num'), role('y', 'Y (number)', 'num'), role('order', 'Order (year or step)', 'num')], options: [],
		templates: [{ key: 'vega-lite/connected_scatterplot', fields: { x: 'miles', y: 'gas', order: 'year' } }],
	});
	C.upstream({
		id: 'parallel', group: 'relationship', label: 'Parallel coordinates', desc: 'One line per row across several measures', sample: 'u_penguins', sampleMap: { group: 'Species', measures: ['Body mass', 'Beak length', 'Beak depth', 'Flipper length'] },
		roles: [role('group', 'Colour by', 'any'), role('measures', 'Measures (2 or more)', 'num', true, { multi: true, min: 2 })], options: [],
		templates: [{ key: 'vega-lite/parallel_coordinate', fields: { group: 'Species' }, edits: [
			edit('its four measures (Beak Length, Beak Depth, Flipper Length, Body Mass) are the example’s columns; they become the columns you choose', (spec, s) => {
				const cols = s.list('measures');
				spec.transform[0].filter = `datum[${JSON.stringify(cols[0])}]`;
				spec.transform.find((t) => t.fold).fold = cols;
				const tip = spec.layer[1].encoding.tooltip;
				spec.layer[1].encoding.tooltip = cols.map((c) => ({ type: 'quantitative', field: c }));
				void tip;
			}),
		] }],
	});
	C.upstream({
		id: 'scatter-matrix', group: 'relationship', label: 'Scatter matrix', desc: 'Every pair of measures against each other', sample: 'u_cars', sampleMap: { measures: ['Horsepower', 'Miles per gallon', 'Acceleration'], group: 'Origin' },
		roles: [role('measures', 'Measures (2 or more)', 'num', true, { multi: true, min: 2 }), role('group', 'Colour by', 'any', false)], options: [],
		templates: [{ key: 'vega-lite/interactive_splom', fields: { group: 'Origin' }, edits: [
			edit('its repeat lists the example’s three columns (Horsepower, Acceleration, Miles_per_Gallon); they become the columns you choose', (spec, s) => { spec.repeat = { row: s.list('measures'), column: [...s.list('measures')].reverse() }; }),
		] }],
	});
	C.upstream({
		id: 'heatmap-annotated', group: 'matrix', label: 'Heatmap with counts', desc: 'How many rows fall in each row and column, written in the cell', sample: 'u_mosaic', sampleMap: { y: 'Origin', x: 'Cylinders' },
		roles: [role('y', 'Rows', 'any'), role('x', 'Columns', 'any')], options: [],
		templates: [{ key: 'vega-lite/layer_text_heatmap', fields: { y: 'Origin', x: 'Cylinders' } }],
	});
	C.upstream({
		id: 'hist2d', group: 'matrix', label: '2D histogram', desc: 'Counts of points in a grid of two numbers', sample: 'u_pairs', sampleMap: { x: 'Audience', y: 'Critics' },
		roles: [role('x', 'X (number)', 'num'), role('y', 'Y (number)', 'num')], options: [],
		templates: [{ key: 'vega-lite/rect_binned_heatmap', fields: { x: 'IMDB Rating', y: 'Rotten Tomatoes Rating' } }],
	});
	C.upstream({
		id: 'rose', group: 'composition', label: 'Nightingale rose', desc: 'Slices of equal angle whose reach shows the value', sample: 'u_dots', sampleMap: { x: 'Value' },
		roles: [role('x', 'Values (number)', 'num')], options: [],
		templates: [{ key: 'vega-lite/arc_radial', fields: { x: 'data' } }],
	});

	/* ── Full Vega: hierarchies, radar, word cloud, calendar, violin, contour ─ */

	C.sample('u_tree', 'Id,Name,Parent,Size\n1,Company,,\n2,Engineering,1,\n3,Sales,1,\n4,Support,1,\n5,Platform,2,48\n6,Mobile,2,30\n7,Data,2,22\n8,Direct,3,35\n9,Partners,3,20\n10,Online,3,40\n11,Helpdesk,4,18\n12,Training,4,9');
	C.sample('u_radar', () => ['Skill,Score,Person', ...['Ana', 'Ben'].flatMap((who, p) => ['Design', 'Code', 'Data', 'Talk', 'Plan', 'Test'].map((k, i) => `${k},${Math.round(40 + ((i * 17 + p * 31) % 55))},${who}`))].join('\n'));
	C.sample('u_text', 'Text\n"Declarative visualization grammars can accelerate development, facilitate retargeting across platforms, and allow language-level optimizations. However, existing declarative visualization languages are primarily concerned with visual encoding, and rely on imperative event handlers for interactive behaviors. In response, we introduce a model of declarative interaction design for data visualizations."\n"We present Reactive Vega, a system architecture that provides the first robust and comprehensive treatment of declarative visual and interaction design for data visualization. Starting from a single declarative specification, Reactive Vega constructs a dataflow graph in which input data, scene graph elements, and interaction events are all treated as first-class streaming data sources."');
	C.sample('u_closes', () => { const next = rng(41); let price = 1400; return ['Date,Close', ...Array.from({ length: 200 }, (_, i) => { price *= 1 + (next() - 0.48) * 0.03; return `${day(i)},${price.toFixed(2)}`; })].join('\n'); });
	const treeRoles = [role('id', 'Id', 'any'), role('name', 'Label (defaults to the id)', 'any', false), role('parent', 'Parent id (blank for the root)', 'any'), role('size', 'Size (leaves)', 'num')];
	const treeFields = { id: 'id', name: 'name', parent: 'parent', size: 'size' };
	/** The example stratifies the rows: unique ids, every parent present, exactly one root. */
	const checkTree = (s) => {
		const ids = s.records.map((r) => r[s.f('id')]);
		const dup = ids.find((v, i) => ids.indexOf(v) !== i);
		if (dup !== undefined) throw new Error(`Id “${dup}” appears twice; every row needs its own id.`);
		const known = new Set(ids);
		const blank = (v) => v === null || v === undefined || v === '';
		const roots = s.records.filter((r) => blank(r[s.f('parent')]));
		if (roots.length !== 1) throw new Error(roots.length ? `${roots.length} rows have no parent; a tree has exactly one root.` : 'No row is the root: leave one row’s parent blank.');
		const orphan = s.records.find((r) => !blank(r[s.f('parent')]) && !known.has(r[s.f('parent')]));
		if (orphan) throw new Error(`Parent “${orphan[s.f('parent')]}” is not the id of any row.`);
	};
	const treeDef = (id, label, desc, key) => C.upstream({
		check: checkTree,
		id, group: 'hierarchy', label, desc, sample: 'u_tree', sampleMap: { id: 'Id', name: 'Name', parent: 'Parent', size: 'Size' },
		roles: treeRoles, options: [],
		templates: [{ key, fields: treeFields, fallback: { name: 'id' } }],
	});
	treeDef('treemap', 'Treemap', 'Nested rectangles sized by value', 'vega/treemap');
	treeDef('sunburst', 'Sunburst', 'Nested rings sized by value', 'vega/sunburst');
	treeDef('circle-pack', 'Circle packing', 'Nested circles sized by value', 'vega/circle-packing');
	treeDef('tree', 'Tree', 'The hierarchy as a node-link tree', 'vega/tree-layout');
	treeDef('radial-tree', 'Radial tree', 'The hierarchy as a tree around a circle', 'vega/radial-tree-layout');
	C.upstream({
		id: 'radar', group: 'compare', label: 'Radar', desc: 'Several measures per item on spokes', sample: 'u_radar', sampleMap: { key: 'Skill', value: 'Score', category: 'Person' },
		roles: [role('key', 'Spoke', 'any'), role('value', 'Value', 'num'), role('category', 'Series', 'any')], options: [],
		templates: [{ key: 'vega/radar-chart', fields: { key: 'key', value: 'value', category: 'category' } }],
	});
	C.upstream({
		browserOnly: 'its word layout needs a canvas to measure text', id: 'word-cloud', group: 'text', label: 'Word cloud', desc: 'The most frequent words in your text, sized by count', sample: 'u_text', sampleMap: { text: 'Text' },
		roles: [role('text', 'Text (one passage per row)', 'any')], options: [],
		templates: [{ key: 'vega/word-cloud', fields: { text: 'data' } }],
	});
	C.upstream({
		id: 'calendar', group: 'matrix', label: 'Calendar', desc: 'Daily change laid out by week and weekday', sample: 'u_closes', sampleMap: { date: 'Date', close: 'Close' },
		roles: [role('date', 'Date', 'time'), role('close', 'Closing value', 'num')], options: [],
		templates: [{ key: 'vega/calendar-view', rename: 'data', fields: { date: 'date', close: 'close' } }],
	});
	C.upstream({
		id: 'violin', group: 'distribution', label: 'Violin', desc: 'The shape of each group’s distribution, with quartiles', sample: 'u_penguins', sampleMap: { group: 'Species', value: 'Body mass' },
		roles: [role('group', 'Group', 'any'), role('value', 'Values (number)', 'num')], options: [],
		templates: [{ key: 'vega/violin-plot', fields: { group: 'Species', value: 'Body Mass (g)' } }],
	});
	C.upstream({
		browserOnly: 'its density grid needs a canvas', id: 'contour', group: 'matrix', label: 'Contour plot', desc: 'Density contours of a scatter, by group', sample: 'u_cars', sampleMap: { x: 'Horsepower', y: 'Miles per gallon', group: 'Origin' },
		roles: [role('x', 'X (number)', 'num'), role('y', 'Y (number)', 'num'), role('group', 'Group', 'any')], options: [],
		templates: [{ key: 'vega/contour-plot', fields: { x: 'Horsepower', y: 'Miles_per_Gallon', group: 'Origin' } }],
	});
})(typeof window !== 'undefined' ? window : globalThis);
