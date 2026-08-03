# Pastas-Hydro-Insight

Gereedschap voor ecohydrologen om grondwaterreeksen te analyseren met
[PASTAS](https://pastas.dev) — een lichtgewicht vervanging voor
Menyanthes/Hydromonitor.

## Wat wil je draaien?

### PastasDash v2 — het dashboard (aanbevolen)

Peilbuizen kiezen, reeksen bekijken, modellen fitten en GxG/grondwatertrap
aflezen. Je hebt alleen [uv](https://docs.astral.sh/uv/) nodig; die regelt
Python en alle pakketten zelf.

```powershell
cd PASTAS\pastasdash_v2
uv run pastasdash-v2
```

Open daarna <http://127.0.0.1:8051>. De eerste keer duurt even omdat uv Python
en de pakketten ophaalt. Volledige uitleg staat in
[`PASTAS/pastasdash_v2/README.md`](PASTAS/pastasdash_v2/README.md).

### PastasDash v1 — de oorspronkelijke Dash-versie

De upstream [`pastas/pastasdash`](https://github.com/pastas/pastasdash) met een
extra Droogte-tab.

```powershell
cd PASTAS\pastasdash
uv run pastasdash
```

Draait op <http://127.0.0.1:8050>, dus v1 en v2 kunnen tegelijk aan staan.

## Bijwerken

```powershell
git pull
```

Daarna opnieuw starten; uv installeert gewijzigde pakketten zelf. Je hebt geen
GitHub-account nodig: deze repo is openbaar en alle afhankelijkheden komen van
PyPI.

## Verder in deze repo

| Map | Inhoud |
|---|---|
| `PASTAS/pastasdash_v2/` | Het dashboard (NiceGUI). Zelfstandig, met eigen `uv.lock`. |
| `PASTAS/pastasdash/` | De oorspronkelijke Dash-versie. |
| `PASTAS/pastas_adapter/` | Gedeelde adapter tussen PASTAS/PastaStore en de rest. |
| `PASTAS/notebooks/` | Uitleg-notebooks: van ruwe peilbuisdata naar een model. |
| `PASTAS/Mantel_Test/`, `data/`, `scripts/`, `output/` | Voorbeelddata en hulpscripts. |

## Herkomst

Dit was ooit een volledige workspace-snapshot (inclusief `geo_stack`, `BeSI`,
`lesa-agent-v2` en `ArcGIS_online`). Die projecten leven inmiddels in hun eigen
repo's; hier staat alleen nog de PASTAS-gereedschapskist.
