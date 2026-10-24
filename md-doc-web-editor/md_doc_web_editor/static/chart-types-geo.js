/*
 * Chart types: maps. See chart-core.js for the registration API.
 * Basemaps are built in (`vega-datasets:world-110m` / `us-10m`), so nothing is fetched.
 * Shared byte-for-byte with md-doc-pipeline's studio.
 */
(function (root) {
	'use strict';
	const C = root.ChartCatalog;
	const { q, noLegend, layers, r, isCount } = C.h;

	const role = (key, label, kind = 'any', required = true, extra) => ({ key, label, kind, required, ...extra });

	C.option('scheme', { label: 'Colour ramp', kind: 'select', default: 'blues', choices: [['blues', 'Blue'], ['greens', 'Green'], ['oranges', 'Orange'], ['purples', 'Purple'], ['reds', 'Red'], ['viridis', 'Viridis'], ['yelloworangered', 'Yellow–orange–red']] });
	C.option('projection', { label: 'Projection', kind: 'select', default: 'equalEarth', choices: [['equalEarth', 'Equal Earth'], ['naturalEarth1', 'Natural Earth'], ['mercator', 'Mercator'], ['equirectangular', 'Equirectangular'], ['orthographic', 'Globe']] });

	C.sample('countries', 'Country,Value\nUnited States,82\nCanada,74\nMexico,58\nBrazil,63\nArgentina,49\nUnited Kingdom,79\nFrance,77\nGermany,81\nSpain,66\nItaly,68\nSweden,85\nNorway,88\nRussia,54\nTurkey,52\nEgypt,41\nNigeria,38\nSouth Africa,57\nKenya,36\nSaudi Arabia,61\nIndia,47\nChina,69\nJapan,83\nSouth Korea,80\nIndonesia,45\nAustralia,86');
	C.sample('states', 'State,Value\nCalifornia,88\nTexas,76\nFlorida,69\nNew York,82\nIllinois,64\nPennsylvania,61\nOhio,55\nGeorgia,58\nMichigan,52\nWashington,79\nColorado,73\nArizona,57\nMassachusetts,84\nMinnesota,66\nOregon,70\nUtah,62\nMontana,34\nAlaska,41\nMaine,38\nMississippi,31');
	C.sample('cities', 'City,Latitude,Longitude,Population,Region\nTokyo,35.68,139.69,37.4,Asia\nDelhi,28.61,77.21,31.0,Asia\nShanghai,31.23,121.47,27.1,Asia\nSao Paulo,-23.55,-46.63,22.0,Americas\nMexico City,19.43,-99.13,21.8,Americas\nCairo,30.04,31.24,20.9,Africa\nLagos,6.52,3.38,14.9,Africa\nNew York,40.71,-74.01,18.8,Americas\nLondon,51.51,-0.13,9.0,Europe\nParis,48.86,2.35,11.1,Europe\nMoscow,55.76,37.62,12.5,Europe\nSydney,-33.87,151.21,5.3,Oceania');
	C.sample('uscities', 'City,Latitude,Longitude,Population,Region\nNew York,40.71,-74.01,8.3,East\nLos Angeles,34.05,-118.24,3.9,West\nChicago,41.88,-87.63,2.7,Midwest\nHouston,29.76,-95.37,2.3,South\nPhoenix,33.45,-112.07,1.6,West\nPhiladelphia,39.95,-75.17,1.6,East\nSan Antonio,29.42,-98.49,1.5,South\nSeattle,47.61,-122.33,0.75,West\nDenver,39.74,-104.99,0.71,West\nBoston,42.36,-71.06,0.65,East\nMiami,25.76,-80.19,0.44,South\nMinneapolis,44.98,-93.27,0.43,Midwest');

	const norm = (x) => String(x ?? '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/&/g, 'and').replace(/[^a-z0-9]+/g, ' ').replace(/\bthe\b/g, '').trim();
	const index = (rows, keysOf) => { const m = new Map(); for (const row of rows) for (const k of keysOf(row)) if (k && !m.has(norm(k))) m.set(norm(k), row); return m; };
	let countryIndex, stateIndex;
	const findCountry = (v) => (countryIndex ??= index(C.geo.COUNTRIES, (c) => [String(c[0]), c[1], c[2], ...c[3]])).get(norm(v));
	const findState = (v) => (stateIndex ??= index(C.geo.STATES, (s) => [String(s[0]), String(s[0]).padStart(2, '0'), s[1], s[2]])).get(norm(v));
	C.geoMatch = { country: (v) => findCountry(v), state: (v) => findState(v) };

	const BASE = { world: 'vega-datasets:world-110m', us: 'vega-datasets:us-10m' };
	const topo = (name, feature) => ({ url: BASE[name], format: { type: 'topojson', feature } });
	const LAND = '#eceae4';

	/** Join the table's regions to basemap ids; collect what could not be matched. */
	function joinRegions(s, find, nameOf) {
		const sums = new Map(), unmatched = [];
		const op = s.opts.agg && s.opts.agg !== 'none' ? s.opts.agg : 'sum';
		for (const rec of s.records) {
			const hit = find(rec[s.f('x')]);
			if (!hit) { if (rec[s.f('x')] !== null) unmatched.push(String(rec[s.f('x')])); continue; }
			const v = isCount(s) ? 1 : Number(rec[s.f('y')]);
			if (!Number.isFinite(v)) continue;
			const a = sums.get(hit[0]) || { n: 0, sum: 0, min: Infinity, max: -Infinity, hit };
			a.n++; a.sum += v; a.min = Math.min(a.min, v); a.max = Math.max(a.max, v);
			sums.set(hit[0], a);
		}
		if (!sums.size) throw new Error(`None of the values in “${s.f('x')}” were recognised. Use names, ISO codes or numeric codes.`);
		if (unmatched.length) s.warn(`Not recognised, so left off the map: ${[...new Set(unmatched)].slice(0, 8).join(', ')}${new Set(unmatched).size > 8 ? '…' : ''}`);
		return [...sums.values()].map((a) => ({ id: a.hit[0], region: nameOf(a.hit), value: r(op === 'mean' ? a.sum / a.n : op === 'min' ? a.min : op === 'max' ? a.max : op === 'count' ? a.n : a.sum, 4) }));
	}

	function choropleth(s, which) {
		const world = which === 'world';
		const rows = joinRegions(s, world ? findCountry : findState, world ? (c) => c[3][0] : (st) => st[2]);
		const feature = world ? 'countries' : 'states';
		const color = { field: 'value', type: 'quantitative', scale: { scheme: s.opts.scheme || 'blues' }, legend: s.opts.legend === false ? null : { title: s.f('y') } };
		return {
			width: world ? 560 : 520, height: world ? 300 : 320,
			projection: { type: world ? s.opts.projection || 'equalEarth' : 'albersUsa' },
			layer: [
				{ data: topo(which, feature), mark: { type: 'geoshape', fill: LAND, stroke: 'white', strokeWidth: 0.5 } },
				{
					data: topo(which, feature),
					transform: [{ lookup: 'id', from: { data: { values: rows }, key: 'id', fields: ['region', 'value'] } }, { filter: 'isValid(datum.value)' }],
					mark: { type: 'geoshape', stroke: 'white', strokeWidth: 0.5 },
					encoding: { color, tooltip: [{ field: 'region', type: 'nominal', title: world ? 'Country' : 'State' }, { field: 'value', type: 'quantitative', title: s.f('y') }] },
				},
			],
			view: { stroke: null },
		};
	}

	const choroRoles = (label) => [role('x', label, 'any'), role('y', 'Value (colour)', 'num')];
	C.type({ id: 'map-world', group: 'geo', label: 'World map (countries)', desc: 'Countries shaded by a value', sample: 'countries', roles: choroRoles('Country (name or ISO code)'), options: ['scheme', 'projection', 'agg', 'legend'], sampleMap: { x: 'Country', y: 'Value' }, build: (s) => choropleth(s, 'world') });
	C.type({ id: 'map-us', group: 'geo', label: 'US map (states)', desc: 'States shaded by a value', sample: 'states', roles: choroRoles('State (name, code or FIPS)'), options: ['scheme', 'agg', 'legend'], sampleMap: { x: 'State', y: 'Value' }, build: (s) => choropleth(s, 'us') });

	function bubbles(s, which) {
		const world = which === 'world';
		const lat = s.f('lat'), lon = s.f('lon');
		const pts = s.records.filter((rec) => Number.isFinite(rec[lat]) && Number.isFinite(rec[lon]));
		if (!pts.length) throw new Error('Latitude and longitude need numbers (for example 51.5 and -0.13).');
		const enc = {
			latitude: q(lat), longitude: q(lon),
			size: s.has('size') ? q(s.f('size'), { scale: { range: [40, 1100] }, legend: s.opts.legend === false ? null : { title: s.f('size') } }) : { value: 120 },
		};
		if (s.has('color')) enc.color = { field: s.f('color'), type: 'nominal', ...noLegend(s) };
		const mark = { type: 'circle', opacity: 0.7, stroke: 'white', strokeWidth: 1, ...(s.has('color') ? {} : {}) };
		const tip = [s.has('label') ? { field: s.f('label'), type: 'nominal' } : null, s.has('size') ? { field: s.f('size'), type: 'quantitative' } : null].filter(Boolean);
		if (tip.length) enc.tooltip = tip;
		const parts = [
			{ data: topo(which, world ? 'land' : 'states'), mark: { type: 'geoshape', fill: LAND, stroke: 'white', strokeWidth: 0.5 } },
			{ data: { values: pts }, mark, encoding: enc },
		];
		if (s.opts.labels && s.has('label')) parts.push({ data: { values: pts }, mark: { type: 'text', dy: -11, fontSize: 10 }, encoding: { latitude: q(lat), longitude: q(lon), text: { field: s.f('label'), type: 'nominal' } } });
		return { width: world ? 560 : 520, height: world ? 300 : 320, projection: { type: world ? s.opts.projection || 'equalEarth' : 'albersUsa' }, layer: parts, view: { stroke: null } };
	}
	const bubbleRoles = [role('lat', 'Latitude', 'num'), role('lon', 'Longitude', 'num'), role('size', 'Size (optional)', 'num', false), role('color', 'Colour by (optional)', 'cat', false), role('label', 'Label (optional)', 'cat', false)];
	C.type({ id: 'bubble-map-world', group: 'geo', label: 'World bubble map', desc: 'Circles at latitude and longitude', sample: 'cities', roles: bubbleRoles, options: ['projection', 'labels', 'legend'], sampleMap: { lat: 'Latitude', lon: 'Longitude', size: 'Population', color: 'Region', label: 'City' }, opts: { labels: true }, build: (s) => bubbles(s, 'world') });
	C.type({ id: 'bubble-map-us', group: 'geo', label: 'US bubble map', desc: 'Circles over the United States', sample: 'uscities', roles: bubbleRoles, options: ['labels', 'legend'], sampleMap: { lat: 'Latitude', lon: 'Longitude', size: 'Population', color: 'Region', label: 'City' }, opts: { labels: true }, build: (s) => bubbles(s, 'us') });
})(typeof window !== 'undefined' ? window : globalThis);
