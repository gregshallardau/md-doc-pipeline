# Built-in chart data

Basemaps for `chart` blocks, referenced as `url: vega-datasets:<name>` (resolved locally by
`md_doc.charts`, never fetched):

| Name | Content |
|------|---------|
| `world-110m` | World countries and land, TopoJSON, 1:110m (ISO 3166-1 numeric ids) |
| `us-10m` | US states and counties, TopoJSON, 1:10m (FIPS ids) |

From the [vega-datasets](https://github.com/vega/vega-datasets) package (BSD-3-Clause,
Copyright (c) 2015-2023 University of Washington Interactive Data Lab), which derives them from
Natural Earth (public domain) and the US Census Bureau (public domain).
