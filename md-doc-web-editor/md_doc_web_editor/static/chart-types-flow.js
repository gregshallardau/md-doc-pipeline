/*
 * Chart types: flows and networks (full Vega specs). See chart-core.js for the registration API.
 *
 * Sankey, chord, arc and bundled-edge layouts are computed here and drawn with Vega marks
 * (Vega has no transform for them). The computation is deterministic, so the chart is the same
 * in documents and on slides. The force-directed network uses Vega's own `force` transform.
 * Shared byte-for-byte with md-doc-pipeline's studio.
 */
(function (root) {
	'use strict';
	const C = root.ChartCatalog;
	const { r, vega, tree } = C.h;

	const role = (key, label, kind = 'any', required = true, extra) => ({ key, label, kind, required, ...extra });
	const TAU = Math.PI * 2;
	const flowRoles = [role('source', 'From', 'any'), role('target', 'To', 'any'), role('value', 'Amount', 'num', false)];
	const flowMap = { source: 'Source', target: 'Target', value: 'Value' };

	C.option('nodeWidth', { label: 'Node width', kind: 'number', default: 14, min: 4, max: 40 });
	C.option('curvature', { label: 'Bundle tightness (0–1)', kind: 'number', default: 0.85, min: 0, max: 1 });

	C.sample('flows', 'Source,Target,Value\nSolar,Grid,30\nWind,Grid,45\nGas,Grid,60\nCoal,Grid,25\nGrid,Homes,80\nGrid,Industry,55\nGrid,Transport,15\nGrid,Losses,10\nGas,Industry,20\nOil,Transport,50\nOil,Industry,15');
	C.sample('network', 'Source,Target,Value\nAda,Ben,5\nAda,Cleo,3\nAda,Dev,2\nBen,Cleo,4\nBen,Eli,1\nCleo,Dev,3\nDev,Fay,2\nEli,Fay,4\nEli,Gus,2\nFay,Gus,3\nGus,Hal,1\nHal,Ivy,2\nIvy,Eli,1\nCleo,Hal,1');
	C.sample('modules', 'Name,Parent,Imports\nApp,,\nUI,App,\nData,App,\nCore,App,\nButton,UI,Logger\nForm,UI,Button;Store\nChart,UI,Store;Cache\nStore,Data,Api\nCache,Data,Api\nApi,Data,Auth;Logger\nRouter,Core,Auth\nAuth,Core,Logger\nLogger,Core,');

	/** Edges with a numeric weight (1 when no amount column is chosen). */
	function edgesOf(s) {
		const out = [];
		for (const rec of s.records) {
			const a = rec[s.f('source')], b = rec[s.f('target')];
			if (a === null || a === undefined || b === null || b === undefined || String(a) === '' || String(b) === '') continue;
			const v = s.has('value') ? Number(rec[s.f('value')]) : 1;
			if (Number.isFinite(v) && v > 0) out.push({ source: String(a), target: String(b), value: v });
		}
		if (!out.length) throw new Error('Add at least one row with a From, a To and a positive Amount.');
		return out;
	}

	const nodeScale = (names) => ({ name: 'color', type: 'ordinal', domain: names, range: 'category' });

	/* ── Sankey ─────────────────────────────────────────────────────────── */

	function sankeyLayout(edges, W, H, nodeW, pad) {
		const names = [], index = new Map();
		const id = (n) => { if (!index.has(n)) { index.set(n, names.length); names.push(n); } return index.get(n); };
		const links = edges.map((e) => ({ s: id(e.source), t: id(e.target), v: e.value })).filter((l) => l.s !== l.t);
		const n = names.length;
		const depth = new Array(n).fill(0);
		for (let it = 0; it < n; it++) {
			let changed = false;
			for (const l of links) if (depth[l.t] < depth[l.s] + 1 && depth[l.s] + 1 < n) { depth[l.t] = depth[l.s] + 1; changed = true; }
			if (!changed) break;
		}
		const out = new Array(n).fill(0), inn = new Array(n).fill(0);
		for (const l of links) { out[l.s] += l.v; inn[l.t] += l.v; }
		const maxDepth = Math.max(0, ...depth);
		for (let i = 0; i < n; i++) if (out[i] === 0 && inn[i] > 0) depth[i] = maxDepth; // sinks line up on the right
		const nodes = names.map((name, i) => ({ i, name, depth: depth[i], value: Math.max(out[i], inn[i]), y: 0, h: 0, outL: [], inL: [] }));
		for (const l of links) { nodes[l.s].outL.push(l); nodes[l.t].inL.push(l); l.src = nodes[l.s]; l.dst = nodes[l.t]; }
		const columns = Array.from({ length: maxDepth + 1 }, () => []);
		for (const nd of nodes) columns[nd.depth].push(nd);
		const ky = Math.min(...columns.filter((c) => c.length).map((c) => (H - (c.length - 1) * pad) / (c.reduce((a, b) => a + b.value, 0) || 1)));
		for (const nd of nodes) nd.h = nd.value * ky;
		for (const col of columns) { let y = 0; for (const nd of col) { nd.y = y; y += nd.h + pad; } }
		const centre = (nd) => nd.y + nd.h / 2;
		const resolve = (col) => {
			col.sort((a, b) => a.y - b.y);
			let cursor = 0;
			for (const nd of col) { if (nd.y < cursor) nd.y = cursor; cursor = nd.y + nd.h + pad; }
			let limit = H;
			for (let k = col.length - 1; k >= 0; k--) { if (col[k].y + col[k].h > limit) col[k].y = limit - col[k].h; limit = col[k].y - pad; }
		};
		for (let it = 0; it < 12; it++) {
			const alpha = Math.pow(0.9, it);
			for (let c = 1; c < columns.length; c++) {
				for (const nd of columns[c]) { const w = nd.inL.reduce((a, l) => a + l.v, 0); if (w) nd.y += (nd.inL.reduce((a, l) => a + centre(l.src) * l.v, 0) / w - centre(nd)) * alpha; }
				resolve(columns[c]);
			}
			for (let c = columns.length - 2; c >= 0; c--) {
				for (const nd of columns[c]) { const w = nd.outL.reduce((a, l) => a + l.v, 0); if (w) nd.y += (nd.outL.reduce((a, l) => a + centre(l.dst) * l.v, 0) / w - centre(nd)) * alpha; }
				resolve(columns[c]);
			}
		}
		for (const nd of nodes) {
			let sy = 0, ty = 0;
			for (const l of [...nd.outL].sort((a, b) => a.dst.y - b.dst.y)) { l.sy = sy; sy += l.v * ky; }
			for (const l of [...nd.inL].sort((a, b) => a.src.y - b.src.y)) { l.ty = ty; ty += l.v * ky; }
		}
		const step = maxDepth ? (W - nodeW) / maxDepth : 0;
		for (const nd of nodes) { nd.x0 = nd.depth * step; nd.x1 = nd.x0 + nodeW; }
		return { nodes, links, ky, maxDepth };
	}

	C.type({
		id: 'sankey', group: 'flow', label: 'Sankey', desc: 'Quantities flowing between stages', sample: 'flows',
		roles: flowRoles, options: ['nodeWidth', 'labels'], sampleMap: flowMap, opts: { labels: true },
		build(s) {
			const edges = edgesOf(s);
			const W = 380, H = 300, left = 64, right = 84, top = 6;
			const nodeW = Math.max(4, Math.min(40, Number(s.opts.nodeWidth) || 14));
			const L = sankeyLayout(edges, W, H, nodeW, 12);
			const nodes = L.nodes.map((nd) => ({ name: nd.name, x0: r(nd.x0 + left, 1), x1: r(nd.x1 + left, 1), y0: r(nd.y + top, 1), y1: r(nd.y + nd.h + top, 1), last: nd.depth === L.maxDepth && L.maxDepth > 0, total: r(nd.value, 3) }));
			const links = L.links.map((l) => {
				const x0 = l.src.x1 + left, x1 = l.dst.x0 + left, xm = (x0 + x1) / 2;
				const w = l.v * L.ky;
				const y0 = l.src.y + top + l.sy + w / 2, y1 = l.dst.y + top + l.ty + w / 2;
				return { source: l.src.name, target: l.dst.name, value: r(l.v, 3), w: r(Math.max(w, 0.6), 2), d: `M${r(x0, 1)},${r(y0, 1)}C${r(xm, 1)},${r(y0, 1)} ${r(xm, 1)},${r(y1, 1)} ${r(x1, 1)},${r(y1, 1)}` };
			});
			return vega(s, W + left + right, H + top * 2, {
				data: [{ name: 'nodes', values: nodes }, { name: 'links', values: links }],
				scales: [nodeScale(L.nodes.map((nd) => nd.name))],
				marks: [
					{ type: 'path', from: { data: 'links' }, encode: { update: { path: { field: 'd' }, stroke: { scale: 'color', field: 'source' }, strokeWidth: { field: 'w' }, strokeOpacity: { value: 0.36 }, fill: { value: null }, tooltip: { signal: "{title: datum.source + ' → ' + datum.target, value: datum.value}" } }, hover: { strokeOpacity: { value: 0.6 } } } },
					{ type: 'rect', from: { data: 'nodes' }, encode: { update: { x: { field: 'x0' }, x2: { field: 'x1' }, y: { field: 'y0' }, y2: { field: 'y1' }, fill: { scale: 'color', field: 'name' }, cornerRadius: { value: 2 }, tooltip: { signal: '{title: datum.name, value: datum.total}' } } } },
					...(s.opts.labels ? [{ type: 'text', from: { data: 'nodes' }, interactive: false, encode: { update: { x: { signal: 'datum.last ? datum.x1 + 6 : (datum.x0 < ' + (left + 1) + ' ? datum.x0 - 6 : datum.x1 + 6)' }, y: { signal: '(datum.y0 + datum.y1) / 2' }, align: { signal: 'datum.last ? "left" : (datum.x0 < ' + (left + 1) + ' ? "right" : "left")' }, baseline: { value: 'middle' }, text: { field: 'name' }, fontSize: { value: 11 }, fill: { value: '#1f2328' } } } }] : []),
				],
			});
		},
	});

	/* ── Chord ──────────────────────────────────────────────────────────── */

	C.type({
		id: 'chord', group: 'flow', label: 'Chord', desc: 'Connections between items around a circle', sample: 'flows',
		roles: flowRoles, options: ['labels'], sampleMap: flowMap, opts: { labels: true },
		build(s) {
			const edges = edgesOf(s);
			const names = [...new Set(edges.flatMap((e) => [e.source, e.target]))];
			const n = names.length, ix = new Map(names.map((nm, i) => [nm, i]));
			const m = Array.from({ length: n }, () => new Array(n).fill(0));
			for (const e of edges) { if (e.source === e.target) continue; m[ix.get(e.source)][ix.get(e.target)] += e.value; m[ix.get(e.target)][ix.get(e.source)] += e.value; }
			const pad = 0.04, total = m.flat().reduce((a, b) => a + b, 0) || 1;
			const k = Math.max(0, TAU - pad * n) / total;
			const groups = [], sub = new Array(n * n);
			let x = 0;
			for (let i = 0; i < n; i++) {
				const x0 = x;
				for (let j = 0; j < n; j++) { const v = m[i][j], a0 = x; x += v * k; sub[i * n + j] = { index: i, a0, a1: x, value: v }; }
				groups.push({ index: i, a0: x0, a1: x, name: names[i] });
				x += pad;
			}
			const R = 150, ri = 140;
			const pt = (a, rad) => `${r(rad * Math.sin(a), 2)},${r(-rad * Math.cos(a), 2)}`;
			const arcFlag = (a0, a1) => (a1 - a0 > Math.PI ? 1 : 0);
			const ribbons = [];
			for (let i = 0; i < n; i++) for (let j = 0; j <= i; j++) {
				const a = sub[i * n + j], b = sub[j * n + i];
				if (!a.value) continue;
				const d = `M${pt(a.a0, ri)}A${ri},${ri} 0 ${arcFlag(a.a0, a.a1)} 1 ${pt(a.a1, ri)}Q0,0 ${pt(b.a0, ri)}A${ri},${ri} 0 ${arcFlag(b.a0, b.a1)} 1 ${pt(b.a1, ri)}Q0,0 ${pt(a.a0, ri)}Z`;
				ribbons.push({ a: names[i], b: names[j], value: r(a.value, 3), d });
			}
			return vega(s, 420, 420, {
				data: [{ name: 'groups', values: groups.map((g) => ({ ...g, a0: r(g.a0, 4), a1: r(g.a1, 4), mid: r((g.a0 + g.a1) / 2, 4) })) }, { name: 'ribbons', values: ribbons }],
				scales: [nodeScale(names)],
				marks: [
					{ type: 'path', from: { data: 'ribbons' }, encode: { update: { x: { signal: 'width / 2' }, y: { signal: 'height / 2' }, path: { field: 'd' }, fill: { scale: 'color', field: 'a' }, fillOpacity: { value: 0.55 }, stroke: { value: 'white' }, strokeWidth: { value: 0.5 }, tooltip: { signal: "{title: datum.a + ' ↔ ' + datum.b, value: datum.value}" } }, hover: { fillOpacity: { value: 0.85 } } } },
					{ type: 'arc', from: { data: 'groups' }, encode: { update: { x: { signal: 'width / 2' }, y: { signal: 'height / 2' }, startAngle: { field: 'a0' }, endAngle: { field: 'a1' }, innerRadius: { value: ri + 2 }, outerRadius: { value: R }, fill: { scale: 'color', field: 'name' }, tooltip: { signal: 'datum.name' } } } },
					...(s.opts.labels ? [{ type: 'text', from: { data: 'groups' }, interactive: false, encode: { update: { x: { signal: "width / 2 + (" + (R + 8) + ") * sin(datum.mid)" }, y: { signal: "height / 2 - (" + (R + 8) + ") * cos(datum.mid)" }, text: { field: 'name' }, fontSize: { value: 11 }, baseline: { value: 'middle' }, align: { signal: 'sin(datum.mid) > 0.1 ? "left" : sin(datum.mid) < -0.1 ? "right" : "center"' }, fill: { value: '#1f2328' } } } }] : []),
				],
			});
		},
	});

	/* ── Arc diagram ────────────────────────────────────────────────────── */

	C.type({
		id: 'arc-diagram', group: 'flow', label: 'Arc diagram', desc: 'Nodes on a line, links as arcs', sample: 'network',
		roles: flowRoles, options: ['labels'], sampleMap: flowMap, opts: { labels: true },
		build(s) {
			const edges = edgesOf(s);
			const names = [...new Set(edges.flatMap((e) => [e.source, e.target]))];
			const W = 560, left = 30, step = (W - left * 2) / Math.max(1, names.length - 1);
			const xOf = new Map(names.map((nm, i) => [nm, r(left + i * step, 1)]));
			const maxV = Math.max(...edges.map((e) => e.value));
			let top = 0;
			const arcs = edges.filter((e) => e.source !== e.target).map((e) => {
				const x1 = xOf.get(e.source), x2 = xOf.get(e.target);
				const [a, b] = x1 < x2 ? [x1, x2] : [x2, x1];
				const rad = (b - a) / 2;
				top = Math.max(top, rad);
				return { source: e.source, target: e.target, value: e.value, w: r(1 + (e.value / maxV) * 4, 2), d: `M${a},0A${r(rad, 1)},${r(rad, 1)} 0 0 1 ${b},0` };
			});
			const baseline = r(top + 16, 1), H = r(baseline + 56, 1);
			const degree = Object.fromEntries(names.map((nm) => [nm, 0]));
			for (const e of edges) { degree[e.source] += e.value; degree[e.target] += e.value; }
			return vega(s, W, H, {
				data: [{ name: 'nodes', values: names.map((nm) => ({ name: nm, x: xOf.get(nm), size: r(60 + (degree[nm] / (2 * maxV)) * 120, 0) })) }, { name: 'arcs', values: arcs }],
				scales: [nodeScale(names)],
				marks: [
					{ type: 'path', from: { data: 'arcs' }, encode: { update: { x: { value: 0 }, y: { value: baseline }, path: { field: 'd' }, fill: { value: null }, stroke: { scale: 'color', field: 'source' }, strokeWidth: { field: 'w' }, strokeOpacity: { value: 0.5 }, tooltip: { signal: "{title: datum.source + ' – ' + datum.target, value: datum.value}" } }, hover: { strokeOpacity: { value: 0.9 } } } },
					{ type: 'symbol', from: { data: 'nodes' }, encode: { update: { x: { field: 'x' }, y: { value: baseline }, size: { field: 'size' }, fill: { scale: 'color', field: 'name' }, stroke: { value: 'white' }, strokeWidth: { value: 1.2 } } } },
					...(s.opts.labels ? [{ type: 'text', from: { data: 'nodes' }, interactive: false, encode: { update: { x: { field: 'x' }, y: { value: baseline + 14 }, text: { field: 'name' }, fontSize: { value: 11 }, angle: { value: 40 }, align: { value: 'left' }, baseline: { value: 'top' }, fill: { value: '#1f2328' } } } }] : []),
				],
			});
		},
	});

	/* ── Force-directed network ─────────────────────────────────────────── */

	C.type({
		id: 'force', group: 'flow', label: 'Network (force-directed)', desc: 'Linked items pulled into clusters', sample: 'network',
		roles: flowRoles, options: ['labels'], sampleMap: flowMap, opts: { labels: true },
		build(s) {
			const edges = edgesOf(s);
			const names = [...new Set(edges.flatMap((e) => [e.source, e.target]))];
			const ix = new Map(names.map((nm, i) => [nm, i]));
			const degree = names.map(() => 0);
			for (const e of edges) { degree[ix.get(e.source)] += e.value; degree[ix.get(e.target)] += e.value; }
			const maxDeg = Math.max(...degree);
			return vega(s, 440, 360, {
				signals: [{ name: 'cx', update: 'width / 2' }, { name: 'cy', update: 'height / 2' }],
				data: [
					{ name: 'node-data', values: names.map((name, i) => ({ name, index: i, size: r(160 + (degree[i] / maxDeg) * 420, 0) })) },
					{ name: 'link-data', values: edges.filter((e) => e.source !== e.target).map((e) => ({ source: ix.get(e.source), target: ix.get(e.target), value: e.value, w: r(0.8 + (e.value / Math.max(...edges.map((x) => x.value))) * 3, 2) })) },
				],
				scales: [nodeScale(names)],
				marks: [
					{
						name: 'nodes', type: 'symbol', zindex: 1, from: { data: 'node-data' },
						encode: { update: { size: { field: 'size' }, fill: { scale: 'color', field: 'name' }, stroke: { value: 'white' }, strokeWidth: { value: 1.5 }, tooltip: { signal: 'datum.name' } } },
						transform: [{ type: 'force', iterations: 300, static: true, signal: 'force', forces: [{ force: 'center', x: { signal: 'cx' }, y: { signal: 'cy' } }, { force: 'collide', radius: 14 }, { force: 'nbody', strength: -90 }, { force: 'link', links: 'link-data', distance: 60 }] }],
					},
					{ type: 'path', from: { data: 'link-data' }, interactive: false, encode: { update: { stroke: { value: '#aab0ba' }, strokeWidth: { field: 'w' }, strokeOpacity: { value: 0.7 } } }, transform: [{ type: 'linkpath', require: { signal: 'force' }, shape: 'line', sourceX: 'datum.source.x', sourceY: 'datum.source.y', targetX: 'datum.target.x', targetY: 'datum.target.y' }] },
					...(s.opts.labels ? [{ type: 'text', from: { data: 'nodes' }, interactive: false, zindex: 2, encode: { update: { x: { field: 'x' }, y: { field: 'y' }, dy: { value: -13 }, text: { field: 'datum.name' }, align: { value: 'center' }, fontSize: { value: 11 }, fill: { value: '#1f2328' } } } }] : []),
				],
			});
		},
	});

	/* ── Hierarchical edge bundling ─────────────────────────────────────── */

	C.type({
		id: 'edge-bundling', group: 'flow', label: 'Edge bundling', desc: 'Links between leaves, routed through the hierarchy', sample: 'modules',
		roles: [role('id', 'Name', 'any'), role('parent', 'Parent (blank for the top)', 'any'), role('links', 'Links to (names, separated by ;)', 'any')], options: ['curvature', 'labels'], sampleMap: { id: 'Name', parent: 'Parent', links: 'Imports' }, opts: { labels: true },
		build(s) {
			const t = tree(s, 'id', 'parent');
			const kids = new Map(t.nodes.map((n) => [n.name, []]));
			for (const n of t.nodes) if (n.parent !== null) kids.get(n.parent).push(n.name);
			const by = new Map(t.nodes.map((n) => [n.name, n]));
			// Radial cluster layout: leaves evenly around the circle, parents at the mean angle.
			const leaves = [];
			const walk = (nm) => { const c = kids.get(nm); if (!c.length) leaves.push(nm); else c.forEach(walk); };
			walk(t.rootName);
			const depthOf = (nm) => { let d = 0, cur = by.get(nm); while (cur.parent !== null) { d++; cur = by.get(cur.parent); } return d; };
			const maxDepth = Math.max(...t.nodes.map((n) => depthOf(n.name))) || 1;
			const ang = new Map();
			leaves.forEach((nm, i) => ang.set(nm, ((i + 0.5) / leaves.length) * TAU));
			const place = (nm) => { const c = kids.get(nm); if (c.length) { c.forEach(place); ang.set(nm, c.reduce((a, k) => a + ang.get(k), 0) / c.length); } };
			place(t.rootName);
			const R = 140;
			const pos = (nm) => { const rad = (depthOf(nm) / maxDepth) * R, a = ang.get(nm); return [r(rad * Math.sin(a), 2), r(-rad * Math.cos(a), 2)]; };
			const chain = (nm) => { const out = [nm]; let cur = by.get(nm); while (cur.parent !== null) { out.push(cur.parent); cur = by.get(cur.parent); } return out; };
			const pts = [];
			let id = 0;
			const linkCol = s.f('links'), nameCol = s.f('id');
			for (const rec of s.records) {
				const from = String(rec[nameCol] ?? '').trim();
				if (!by.has(from) || kids.get(from).length) continue;
				for (const to of String(rec[linkCol] ?? '').split(/[;|]/).map((x) => x.trim()).filter(Boolean)) {
					if (!by.has(to) || to === from) continue;
					const a = chain(from), b = chain(to);
					const common = a.find((x) => b.includes(x));
					const path = [...a.slice(0, a.indexOf(common) + 1), ...b.slice(0, b.indexOf(common)).reverse()];
					path.forEach((nm, i) => { const [x, y] = pos(nm); pts.push({ link: id, i, x, y, g: by.get(from).group }); });
					id++;
				}
			}
			if (!id) throw new Error('No links found: put the names a leaf links to in the “Links to” column, separated by ;');
			const leafRows = leaves.map((nm) => { const [x, y] = pos(nm); const a = ang.get(nm); return { name: nm, x, y, g: by.get(nm).group, deg: r((a * 180) / Math.PI, 1), right: Math.sin(a) >= 0 }; });
			const tension = Math.max(0, Math.min(1, Number(s.opts.curvature)));
			return vega(s, 420, 420, {
				data: [{ name: 'points', values: pts }, { name: 'leaves', values: leafRows }],
				scales: [{ name: 'color', type: 'ordinal', domain: t.groups, range: 'category' }],
				marks: [
					{ type: 'group', from: { facet: { name: 'path', data: 'points', groupby: 'link' } }, encode: { update: { x: { signal: 'width / 2' }, y: { signal: 'height / 2' } } }, marks: [{ type: 'line', from: { data: 'path' }, interactive: false, encode: { update: { x: { field: 'x' }, y: { field: 'y' }, interpolate: { value: 'bundle' }, tension: { value: tension }, stroke: { scale: 'color', field: 'g' }, strokeOpacity: { value: 0.55 }, strokeWidth: { value: 1.6 } } } }] },
					{ type: 'symbol', from: { data: 'leaves' }, encode: { update: { x: { signal: 'width / 2 + datum.x' }, y: { signal: 'height / 2 + datum.y' }, size: { value: 60 }, fill: { scale: 'color', field: 'g' }, stroke: { value: 'white' }, strokeWidth: { value: 1 }, tooltip: { signal: 'datum.name' } } } },
					...(s.opts.labels ? [{ type: 'text', from: { data: 'leaves' }, interactive: false, encode: { update: { x: { signal: 'width / 2 + datum.x * 1.08' }, y: { signal: 'height / 2 + datum.y * 1.08' }, text: { field: 'name' }, fontSize: { value: 10 }, baseline: { value: 'middle' }, align: { signal: 'datum.right ? "left" : "right"' }, angle: { signal: 'datum.right ? datum.deg - 90 : datum.deg + 90' }, fill: { value: '#1f2328' } } } }] : []),
				],
			});
		},
	});
})(typeof window !== 'undefined' ? window : globalThis);
