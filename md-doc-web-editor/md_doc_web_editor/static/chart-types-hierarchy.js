/*
 * Chart types: hierarchies (full Vega specs). See chart-core.js for the registration API.
 * Nodes come from a table of (name, parent, size); the layouts are Vega transforms, so the
 * chart follows the data. Shared byte-for-byte with md-doc-pipeline's studio.
 */
(function (root) {
	'use strict';
	const C = root.ChartCatalog;
	const { tree, treeData, groupScale, groupFill, vega } = C.h;

	const role = (key, label, kind = 'any', required = true, extra) => ({ key, label, kind, required, ...extra });
	const treeRoles = [role('id', 'Name', 'any'), role('parent', 'Parent (blank for the top)', 'any'), role('size', 'Size', 'num', false)];
	const treeMap = { id: 'Name', parent: 'Parent', size: 'Size' };

	C.option('rotate', { label: 'Rotate the layout (degrees)', kind: 'number', default: 0, min: 0, max: 360 });
	C.option('padding', { label: 'Gap between shapes', kind: 'number', default: 2, min: 0, max: 12 });

	C.sample('hierarchy', 'Name,Parent,Size\nCompany,,\nEngineering,Company,\nProduct,Company,\nSales,Company,\nOperations,Company,\nPlatform,Engineering,420\nMobile,Engineering,260\nData,Engineering,310\nDesign,Product,180\nResearch,Product,90\nPricing,Product,70\nEnterprise,Sales,380\nSMB,Sales,240\nPartners,Sales,120\nSupport,Operations,210\nFinance,Operations,150\nPeople,Operations,110\nLegal,Operations,60');


	/* ── Treemap ────────────────────────────────────────────────────────── */

	C.type({
		id: 'treemap', group: 'hierarchy', label: 'Treemap', desc: 'Nested rectangles sized by value', sample: 'hierarchy',
		roles: treeRoles, options: ['padding', 'labels'], sampleMap: treeMap, opts: { labels: true },
		build(s) {
			const t = tree(s, 'id', 'parent', 'size');
			const pad = Number(s.opts.padding) || 0;
			return vega(s, 560, 360, {
				data: [
					treeData(t, [{ type: 'treemap', field: 'size', sort: { field: 'value' }, round: true, method: 'squarify', ratio: 1.618, size: [{ signal: 'width' }, { signal: 'height' }], paddingInner: pad, paddingOuter: pad * 2, paddingTop: 18, as: ['x0', 'y0', 'x1', 'y1', 'depth', 'children'] }]),
					{ name: 'parents', source: 'tree', transform: [{ type: 'filter', expr: 'datum.children && datum.depth > 0' }] },
					{ name: 'leaves', source: 'tree', transform: [{ type: 'filter', expr: '!datum.children' }] },
				],
				scales: [groupScale(t)],
				marks: [
					{ type: 'rect', from: { data: 'parents' }, interactive: false, encode: { update: { x: { field: 'x0' }, y: { field: 'y0' }, x2: { field: 'x1' }, y2: { field: 'y1' }, fill: { scale: 'color', field: 'group' }, fillOpacity: { signal: '0.14 + 0.06 * datum.depth' }, cornerRadius: { value: 3 } } } },
					{ type: 'rect', from: { data: 'leaves' }, encode: { update: { x: { field: 'x0' }, y: { field: 'y0' }, x2: { field: 'x1' }, y2: { field: 'y1' }, fill: { scale: 'color', field: 'group' }, stroke: { value: 'white' }, strokeWidth: { value: 1 }, cornerRadius: { value: 2 }, tooltip: { signal: "{title: datum.name, value: datum.size}" } } } },
					{ type: 'text', from: { data: 'parents' }, interactive: false, encode: { update: { x: { signal: 'datum.x0 + 5' }, y: { signal: 'datum.y0 + 11' }, text: { field: 'name' }, fontWeight: { value: 'bold' }, fontSize: { value: 11 }, baseline: { value: 'middle' }, limit: { signal: 'max(0, datum.x1 - datum.x0 - 8)' }, fill: { value: '#1f2328' } } } },
					...(s.opts.labels ? [{ type: 'text', from: { data: 'leaves' }, interactive: false, encode: { update: { x: { signal: '0.5 * (datum.x0 + datum.x1)' }, y: { signal: '0.5 * (datum.y0 + datum.y1)' }, align: { value: 'center' }, baseline: { value: 'middle' }, text: { field: 'name' }, fontSize: { value: 11 }, fill: { value: 'white' }, limit: { signal: 'max(0, datum.x1 - datum.x0 - 6)' }, fillOpacity: { signal: '(datum.x1 - datum.x0 > 34 && datum.y1 - datum.y0 > 16) ? 1 : 0' } } } }] : []),
				],
			});
		},
	});

	/* ── Sunburst / icicle ──────────────────────────────────────────────── */

	C.type({
		id: 'sunburst', group: 'hierarchy', label: 'Sunburst', desc: 'Nested rings, one per level', sample: 'hierarchy',
		roles: treeRoles, options: ['labels'], sampleMap: treeMap, opts: { labels: true },
		build(s) {
			const t = tree(s, 'id', 'parent', 'size');
			return vega(s, 380, 380, {
				signals: [{ name: 'cx', update: 'width / 2' }, { name: 'cy', update: 'height / 2' }, { name: 'ring', update: 'min(width, height) / 2' }],
				data: [
					treeData(t, [{ type: 'partition', field: 'size', sort: { field: 'value' }, size: [{ signal: '2 * PI' }, { signal: 'ring' }], as: ['a0', 'r0', 'a1', 'r1', 'depth', 'children'] }]),
					{ name: 'arcs', source: 'tree', transform: [{ type: 'filter', expr: 'datum.depth > 0' }] },
				],
				scales: [groupScale(t)],
				marks: [
					{ type: 'arc', from: { data: 'arcs' }, encode: { update: { x: { signal: 'cx' }, y: { signal: 'cy' }, startAngle: { field: 'a0' }, endAngle: { field: 'a1' }, innerRadius: { field: 'r0' }, outerRadius: { field: 'r1' }, fill: { scale: 'color', field: 'group' }, fillOpacity: { signal: '1.05 - 0.17 * datum.depth' }, stroke: { value: 'white' }, strokeWidth: { value: 1 }, tooltip: { signal: '{title: datum.name, value: datum.value}' } } } },
					...(s.opts.labels ? [{ type: 'text', from: { data: 'arcs' }, interactive: false, encode: { update: { x: { signal: 'cx + 0.5 * (datum.r0 + datum.r1) * sin(0.5 * (datum.a0 + datum.a1))' }, y: { signal: 'cy - 0.5 * (datum.r0 + datum.r1) * cos(0.5 * (datum.a0 + datum.a1))' }, align: { value: 'center' }, baseline: { value: 'middle' }, text: { field: 'name' }, fontSize: { value: 10 }, fill: { value: 'white' }, angle: { signal: '(0.5 * (datum.a0 + datum.a1) * 180 / PI + 270) % 360 > 90 && (0.5 * (datum.a0 + datum.a1) * 180 / PI + 270) % 360 < 270 ? (0.5 * (datum.a0 + datum.a1) * 180 / PI + 180) % 360 - 90 : (0.5 * (datum.a0 + datum.a1) * 180 / PI) % 360 - 90' }, limit: { signal: '(datum.r1 - datum.r0) * 0.95' }, fillOpacity: { signal: '(datum.a1 - datum.a0) * 0.5 * (datum.r0 + datum.r1) > 14 ? 1 : 0' } } } }] : []),
				],
			});
		},
	});

	C.type({
		id: 'icicle', group: 'hierarchy', label: 'Icicle', desc: 'Nested bars, one row per level', sample: 'hierarchy',
		roles: treeRoles, options: ['labels'], sampleMap: treeMap, opts: { labels: true },
		build(s) {
			const t = tree(s, 'id', 'parent', 'size');
			return vega(s, 560, 300, {
				data: [
					treeData(t, [{ type: 'partition', field: 'size', sort: { field: 'value' }, size: [{ signal: 'width' }, { signal: 'height' }], as: ['x0', 'y0', 'x1', 'y1', 'depth', 'children'] }]),
				],
				scales: [groupScale(t)],
				marks: [
					{ type: 'rect', from: { data: 'tree' }, encode: { update: { x: { field: 'x0' }, y: { field: 'y0' }, x2: { field: 'x1' }, y2: { field: 'y1' }, fill: groupFill, fillOpacity: { signal: '1.05 - 0.14 * datum.depth' }, stroke: { value: 'white' }, strokeWidth: { value: 1 }, tooltip: { signal: '{title: datum.name, value: datum.value}' } } } },
					...(s.opts.labels ? [{ type: 'text', from: { data: 'tree' }, interactive: false, encode: { update: { x: { signal: 'datum.x0 + 5' }, y: { signal: '0.5 * (datum.y0 + datum.y1)' }, baseline: { value: 'middle' }, text: { field: 'name' }, fontSize: { value: 11 }, fill: { signal: 'datum.depth == 0 ? "#1f2328" : "white"' }, limit: { signal: 'max(0, datum.x1 - datum.x0 - 8)' }, fillOpacity: { signal: 'datum.x1 - datum.x0 > 30 ? 1 : 0' } } } }] : []),
				],
			});
		},
	});

	/* ── Circle packing ─────────────────────────────────────────────────── */

	C.type({
		id: 'circle-pack', group: 'hierarchy', label: 'Circle packing', desc: 'Nested circles sized by value', sample: 'hierarchy',
		roles: treeRoles, options: ['padding', 'labels'], sampleMap: treeMap, opts: { labels: true, padding: 4 },
		build(s) {
			const t = tree(s, 'id', 'parent', 'size');
			return vega(s, 380, 380, {
				data: [
					treeData(t, [{ type: 'pack', field: 'size', sort: { field: 'value' }, padding: Number(s.opts.padding) || 0, size: [{ signal: 'width' }, { signal: 'height' }] }]),
					{ name: 'groups', source: 'tree', transform: [{ type: 'filter', expr: 'datum.children' }] },
					{ name: 'leaves', source: 'tree', transform: [{ type: 'filter', expr: '!datum.children' }] },
				],
				scales: [groupScale(t)],
				marks: [
					{ type: 'symbol', from: { data: 'groups' }, interactive: false, encode: { update: { x: { field: 'x' }, y: { field: 'y' }, size: { signal: '4 * datum.r * datum.r' }, shape: { value: 'circle' }, fill: groupFill, fillOpacity: { signal: '0.1 + 0.05 * datum.depth' }, stroke: groupFill, strokeOpacity: { value: 0.5 } } } },
					{ type: 'symbol', from: { data: 'leaves' }, encode: { update: { x: { field: 'x' }, y: { field: 'y' }, size: { signal: '4 * datum.r * datum.r' }, shape: { value: 'circle' }, fill: { scale: 'color', field: 'group' }, stroke: { value: 'white' }, strokeWidth: { value: 1 }, tooltip: { signal: '{title: datum.name, value: datum.size}' } } } },
					...(s.opts.labels ? [{ type: 'text', from: { data: 'leaves' }, interactive: false, encode: { update: { x: { field: 'x' }, y: { field: 'y' }, align: { value: 'center' }, baseline: { value: 'middle' }, text: { field: 'name' }, fontSize: { value: 10 }, fill: { value: 'white' }, limit: { signal: '2 * datum.r - 4' }, fillOpacity: { signal: 'datum.r > 16 ? 1 : 0' } } } }] : []),
				],
			});
		},
	});

	/* ── Node-link trees ────────────────────────────────────────────────── */

	function nodeLink(s, t, kind) {
		const radial = kind === 'radial';
		const cluster = kind === 'dendrogram';
		const layout = { type: 'tree', method: cluster ? 'cluster' : 'tidy', separation: false, size: radial ? [1, 1] : [{ signal: 'height' }, { signal: 'width - 90' }], as: radial ? ['alpha', 'beta', 'depth', 'children'] : ['y', 'x', 'depth', 'children'] };
		const extra = radial
			? [
				{ type: 'formula', expr: '(rotate + 360 * datum.alpha + 270) % 360', as: 'angle' },
				{ type: 'formula', expr: 'inrange(datum.angle, [90, 270])', as: 'left' },
				{ type: 'formula', expr: '(width / 2) + (min(width, height) / 2 - 62) * datum.beta * cos(PI * datum.angle / 180)', as: 'px' },
				{ type: 'formula', expr: '(height / 2) + (min(width, height) / 2 - 62) * datum.beta * sin(PI * datum.angle / 180)', as: 'py' },
			]
			: [
				{ type: 'formula', expr: 'datum.x + 12', as: 'px' },
				{ type: 'formula', expr: 'datum.y', as: 'py' },
			];
		const w = radial ? 420 : 560, hgt = radial ? 420 : Math.max(240, Math.min(560, 20 * t.nodes.filter((n) => !t.nodes.some((m) => m.parent === n.name)).length + 40));
		return vega(s, w, hgt, {
			signals: radial ? [{ name: 'rotate', value: Number(s.opts.rotate) || 0 }] : [],
			data: [
				treeData(t, [layout, ...extra]),
				{ name: 'links', source: 'tree', transform: [{ type: 'treelinks' }] },
			],
			scales: [groupScale(t)],
			marks: [
				{ type: 'path', from: { data: 'links' }, interactive: false, encode: { update: { stroke: { value: '#b8bec6' }, strokeWidth: { value: 1.3 } } }, transform: [{ type: 'linkpath', shape: radial ? 'line' : cluster ? 'orthogonal' : 'diagonal', orient: 'horizontal', sourceX: 'datum.source.px', sourceY: 'datum.source.py', targetX: 'datum.target.px', targetY: 'datum.target.py' }] },
				{ type: 'symbol', from: { data: 'tree' }, encode: { update: { x: { field: 'px' }, y: { field: 'py' }, size: { value: 70 }, fill: groupFill, stroke: { value: 'white' }, strokeWidth: { value: 1 }, tooltip: { signal: '{title: datum.name}' } } } },
				{ type: 'text', from: { data: 'tree' }, interactive: false, encode: { update: radial
					? { x: { field: 'px' }, y: { field: 'py' }, text: { field: 'name' }, fontSize: { value: 10 }, align: { signal: 'datum.left ? "right" : "left"' }, baseline: { value: 'middle' }, dx: { signal: '(datum.left ? -1 : 1) * 7' }, angle: { signal: 'datum.left ? datum.angle - 180 : datum.angle' } }
					: { x: { field: 'px' }, y: { field: 'py' }, text: { field: 'name' }, fontSize: { value: 11 }, align: { signal: 'datum.children ? "right" : "left"' }, baseline: { signal: 'datum.children ? "bottom" : "middle"' }, dx: { signal: 'datum.children ? -6 : 8' }, dy: { signal: 'datum.children ? -4 : 0' } } } },
			],
		});
	}
	C.type({ id: 'tree', group: 'hierarchy', label: 'Tree', desc: 'Parent-child links, left to right', sample: 'hierarchy', roles: treeRoles.slice(0, 2), options: [], sampleMap: treeMap, build: (s) => nodeLink(s, tree(s, 'id', 'parent'), 'tree') });
	C.type({ id: 'dendrogram', group: 'hierarchy', label: 'Dendrogram', desc: 'A tree with all leaves aligned', sample: 'hierarchy', roles: treeRoles.slice(0, 2), options: [], sampleMap: treeMap, build: (s) => nodeLink(s, tree(s, 'id', 'parent'), 'dendrogram') });
	C.type({ id: 'radial-tree', group: 'hierarchy', label: 'Radial tree', desc: 'A tree spread around a circle', sample: 'hierarchy', roles: treeRoles.slice(0, 2), options: ['rotate'], sampleMap: treeMap, build: (s) => nodeLink(s, tree(s, 'id', 'parent'), 'radial') });
})(typeof window !== 'undefined' ? window : globalThis);
