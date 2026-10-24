/*
 * Chart types: radar and word cloud (full Vega specs, laid out here so they are identical in
 * every renderer). See chart-core.js for the registration API.
 * Shared byte-for-byte with md-doc-pipeline's studio.
 */
(function (root) {
	'use strict';
	const C = root.ChartCatalog;
	const { r, vega, distinct } = C.h;

	const role = (key, label, kind = 'any', required = true, extra) => ({ key, label, kind, required, ...extra });
	const TAU = Math.PI * 2;

	C.option('radarScale', { label: 'Scale each axis', kind: 'select', default: 'shared', choices: [['shared', 'Together (same scale)'], ['axis', 'Separately (each to its own maximum)']] });
	C.option('rotateWords', { label: 'Word direction', kind: 'select', default: 'mixed', choices: [['mixed', 'Mostly across, some upright'], ['across', 'All across']] });

	C.sample('skills', 'Metric,Score,Team\nSpeed,8,Alpha\nQuality,6,Alpha\nCost,7,Alpha\nSupport,5,Alpha\nReach,9,Alpha\nSecurity,6,Alpha\nSpeed,5,Beta\nQuality,9,Beta\nCost,6,Beta\nSupport,8,Beta\nReach,5,Beta\nSecurity,9,Beta');
	C.sample('words', 'Word,Weight\ndata,60\ncharts,52\ninsight,44\ntrends,40\nreport,38\nmetrics,35\nforecast,31\nrevenue,30\nsegments,27\ngrowth,26\ndashboard,24\nanalysis,23\nsales,22\ncustomers,21\nquality,19\nregions,18\nretention,17\nchurn,16\nbudget,15\ntargets,14\nquarter,13\nmargin,12\npipeline,12\nsurvey,11\ncohort,10\nfunnel,10\nbenchmark,9\nmodel,9\nsignal,8\nvolume,8\nranking,7\nvariance,6\nmedian,6\noutlier,5');

	/* ── Radar ──────────────────────────────────────────────────────────── */

	C.type({
		id: 'radar', group: 'compare', label: 'Radar', desc: 'Several measures per item on spokes', sample: 'skills',
		roles: [role('x', 'Axis (metric)', 'any'), role('y', 'Value', 'num'), role('color', 'Series (optional)', 'any', false)], options: ['radarScale', 'legend'], sampleMap: { x: 'Metric', y: 'Score', color: 'Team' },
		build(s) {
			const metrics = distinct(s.records, s.f('x')).map(String);
			if (metrics.length < 3) throw new Error('A radar chart needs at least 3 different values in “Axis (metric)”.');
			const seriesOf = (rec) => (s.has('color') ? String(rec[s.f('color')]) : 'Value');
			const series = [...new Set(s.records.map(seriesOf))];
			const acc = new Map();
			for (const rec of s.records) {
				const key = `${seriesOf(rec)}\u0000${rec[s.f('x')]}`;
				const a = acc.get(key) || { sum: 0, n: 0 };
				a.sum += Number(rec[s.f('y')]) || 0; a.n += 1;
				acc.set(key, a);
			}
			const val = (se, m) => { const a = acc.get(`${se}\u0000${m}`); return a ? a.sum / a.n : 0; };
			const shared = Math.max(...[...acc.values()].map((a) => a.sum / a.n), 1e-9);
			const axisMax = Object.fromEntries(metrics.map((m) => [m, Math.max(...series.map((se) => val(se, m)), 1e-9)]));
			const frac = (se, m) => (s.opts.radarScale === 'axis' ? val(se, m) / axisMax[m] : val(se, m) / shared);
			const cx = 210, cy = 190, R = 128, n = metrics.length;
			const at = (i, f) => [r(cx + R * f * Math.sin((i * TAU) / n), 2), r(cy - R * f * Math.cos((i * TAU) / n), 2)];
			const points = [];
			series.forEach((se) => metrics.forEach((m, i) => { const [x, y] = at(i, frac(se, m)); points.push({ series: se, i, metric: m, x, y, value: r(val(se, m), 3) }); }));
			const rings = [0.25, 0.5, 0.75, 1].flatMap((f) => metrics.map((_, i) => ({ ring: f, i, x: at(i, f)[0], y: at(i, f)[1] })));
			const spokes = metrics.map((m, i) => ({ metric: m, i, x: at(i, 1)[0], y: at(i, 1)[1], lx: at(i, 1.13)[0], ly: at(i, 1.13)[1], align: Math.abs(Math.sin((i * TAU) / n)) < 0.2 ? 'center' : Math.sin((i * TAU) / n) > 0 ? 'left' : 'right' }));
			return vega(s, 420, 380, {
				data: [{ name: 'points', values: points }, { name: 'rings', values: rings }, { name: 'spokes', values: spokes }],
				scales: [{ name: 'color', type: 'ordinal', domain: series, range: 'category' }],
				legends: series.length > 1 && s.opts.legend !== false ? [{ stroke: 'color', fill: 'color', orient: 'top-right', symbolType: 'circle', title: s.has('color') ? s.f('color') : null }] : [],
				marks: [
					{ type: 'group', from: { facet: { name: 'ring', data: 'rings', groupby: 'ring' } }, marks: [{ type: 'line', from: { data: 'ring' }, interactive: false, encode: { update: { x: { field: 'x' }, y: { field: 'y' }, interpolate: { value: 'linear-closed' }, stroke: { value: '#d9dbd7' }, strokeWidth: { value: 1 } } } }] },
					{ type: 'rule', from: { data: 'spokes' }, interactive: false, encode: { update: { x: { value: cx }, y: { value: cy }, x2: { field: 'x' }, y2: { field: 'y' }, stroke: { value: '#d9dbd7' } } } },
					{ type: 'group', from: { facet: { name: 'poly', data: 'points', groupby: 'series' } }, marks: [
						{ type: 'line', from: { data: 'poly' }, encode: { update: { x: { field: 'x' }, y: { field: 'y' }, interpolate: { value: 'linear-closed' }, stroke: { scale: 'color', field: 'series' }, strokeWidth: { value: 2.5 }, fill: { scale: 'color', field: 'series' }, fillOpacity: { value: 0.18 } } } },
						{ type: 'symbol', from: { data: 'poly' }, encode: { update: { x: { field: 'x' }, y: { field: 'y' }, size: { value: 50 }, fill: { scale: 'color', field: 'series' }, stroke: { value: 'white' }, strokeWidth: { value: 1 }, tooltip: { signal: "{title: datum.series + ' · ' + datum.metric, value: datum.value}" } } } },
					] },
					{ type: 'text', from: { data: 'spokes' }, interactive: false, encode: { update: { x: { field: 'lx' }, y: { field: 'ly' }, text: { field: 'metric' }, align: { field: 'align' }, baseline: { value: 'middle' }, fontSize: { value: 11 }, fill: { value: '#1f2328' } } } },
				],
			});
		},
	});

	/* ── Word cloud ─────────────────────────────────────────────────────── */

	function cloudLayout(words, W, H, mixed) {
		const boxes = [];
		const hits = (b) => boxes.some((o) => !(b.x1 < o.x0 || b.x0 > o.x1 || b.y1 < o.y0 || b.y0 > o.y1));
		const placed = [];
		let hash = 7;
		for (const [rank, w] of words.entries()) {
			hash = (Math.imul(hash, 31) + w.text.length * 17 + rank) >>> 0;
			const upright = mixed && rank > 1 && hash % 5 === 0;
			const bw = (upright ? w.size : w.text.length * w.size * 0.56) + 6, bh = (upright ? w.text.length * w.size * 0.56 : w.size * 1.05) + 4;
			// Walk an Archimedean spiral out from the centre in ~5px steps until the word fits.
			let a = 0, done = false;
			for (let t = 0; t < 40000 && !done; t++) {
				const rad = 1.6 * a;
				a += 5 / (rad + 5);
				const x = W / 2 + rad * Math.cos(a * 1) * 1.45, y = H / 2 + rad * Math.sin(a * 1);
				const box = { x0: x - bw / 2, x1: x + bw / 2, y0: y - bh / 2, y1: y + bh / 2 };
				if (box.x0 < 2 || box.x1 > W - 2 || box.y0 < 2 || box.y1 > H - 2 || hits(box)) continue;
				boxes.push(box);
				placed.push({ ...w, x: r(x, 1), y: r(y, 1), angle: upright ? 90 : 0 });
				done = true;
			}
		}
		return placed;
	}

	C.type({
		id: 'word-cloud', group: 'text', label: 'Word cloud', desc: 'Words sized by how much they weigh', sample: 'words',
		roles: [role('x', 'Word', 'cat'), role('y', 'Weight (blank = count)', 'num', false)], options: ['rotateWords'], sampleMap: { x: 'Word', y: 'Weight' },
		build(s) {
			const totals = new Map();
			for (const rec of s.records) {
				const word = String(rec[s.f('x')] ?? '').trim();
				if (!word) continue;
				totals.set(word, (totals.get(word) || 0) + (s.has('y') ? Number(rec[s.f('y')]) || 0 : 1));
			}
			const ranked = [...totals].filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).slice(0, 80);
			if (!ranked.length) throw new Error('Add some words with a positive weight.');
			const hi = ranked[0][1], lo = ranked[ranked.length - 1][1];
			const W = 560, H = 340;
			const words = ranked.map(([text, v], i) => ({ text, weight: v, size: r(11 + (hi === lo ? 1 : Math.sqrt((v - lo) / (hi - lo))) * 35, 1), band: Math.min(3, Math.floor((i / ranked.length) * 4)) }));
			const placed = cloudLayout(words, W, H, s.opts.rotateWords !== 'across');
			if (placed.length < words.length) s.warn(`${words.length - placed.length} lowest-weight word(s) did not fit and were left out.`);
			return vega(s, W, H, {
				data: [{ name: 'words', values: placed }],
				scales: [{ name: 'color', type: 'ordinal', domain: [0, 1, 2, 3], range: 'category' }],
				marks: [{ type: 'text', from: { data: 'words' }, encode: { update: { x: { field: 'x' }, y: { field: 'y' }, text: { field: 'text' }, fontSize: { field: 'size' }, fontWeight: { signal: 'datum.size > 30 ? 600 : 400' }, angle: { field: 'angle' }, align: { value: 'center' }, baseline: { value: 'middle' }, fill: { scale: 'color', field: 'band' }, tooltip: { signal: '{title: datum.text, value: datum.weight}' } } } }],
			});
		},
	});
})(typeof window !== 'undefined' ? window : globalThis);
