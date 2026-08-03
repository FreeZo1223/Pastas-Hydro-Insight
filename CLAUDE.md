# Pastas-Hydro-Insight — werkinstructies

Standalone repo voor de PASTAS-dashboardtool (`PASTAS/pastasdash`,
`PASTAS/pastasdash_v2`, `PASTAS/pastas_adapter`). Geen onderdeel meer van de
bredere Eelerwoude GIS-workspace — die packages (`geo_stack`, `BeSI`,
`lesa-agent-v2`, `ArcGIS_online`) hebben elk hun eigen repo.

- `pastasdash`: huidige Dash-gebaseerde GUI, geen externe project-dependencies.
- `pastasdash_v2`: nieuwere NiceGUI-variant, hangt via git-dependencies af van
  de privé repo's `geo_stack` en `lesa-agent-v2` (zie
  `PASTAS/pastasdash_v2/pyproject.toml`) — vereist GitHub-toegang tot die repo's.
- `pastas_adapter`: gedeelde adapter, blijft lokaal binnen deze repo.
