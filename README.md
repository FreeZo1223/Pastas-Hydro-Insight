# Pastas-Hydro-Insight

Dashboard-tool voor ecohydrologen om [PASTAS](https://pastas.dev)-tijdreeksmodellen
(grondwaterstanden) interactief te bekijken en bij te stellen — een lichtgewicht
vervanging voor Menyanthes/Hydromonitor.

## Structuur

```
PASTAS/
├── pastasdash/       ← huidige dashboard (Dash), start hiermee
├── pastasdash_v2/    ← nieuwere dashboard (NiceGUI), i.o.
├── pastas_adapter/   ← gedeelde adapter tussen PASTAS/PastaStore en pastasdash_v2
├── notebooks/        ← uitleg-notebooks, start hier voor de PASTAS-basis
├── Mantel_Test/       data/  scripts/  output/  ← voorbeelddata en hulpscripts
```

## Snel starten

```powershell
cd PASTAS\pastasdash
uv run pastasdash
```

`pastasdash_v2` is een nieuwere variant en heeft twee losse (privé) packages nodig
naast `pastas_adapter` — `geo_stack` en `lesa-agent-v2` — via git-dependencies in
`PASTAS/pastasdash_v2/pyproject.toml`. Vraag toegang tot die repo's als je
`pastasdash-v2` wilt draaien.

## Herkomst

Dit was ooit een volledige workspace-snapshot (incl. `geo_stack`, `BeSI`,
`lesa-agent-v2`, `ArcGIS_online`). Die projecten leven inmiddels in hun eigen
repo's; deze repo bevat alleen nog de PASTAS-tooling.
