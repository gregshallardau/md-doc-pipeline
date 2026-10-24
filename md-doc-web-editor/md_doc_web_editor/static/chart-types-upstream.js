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
})(typeof window !== 'undefined' ? window : globalThis);
