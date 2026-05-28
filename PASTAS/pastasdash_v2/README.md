# PastasDash v2

NiceGUI-gebaseerd grondwaterdashboard voor [PASTAS](https://pastas.dev) met persistente caching.

**Wat is anders dan v1 (`PASTAS/pastasdash/`):**

- ✅ Workflow-georiënteerde navigatie (Start → Overzicht → Model → Vergelijken → Kaart → Droogte)
- ✅ Premium persistentie: SQLite onthoudt laatste store, tab, selecties, filters
- ✅ Diskcache voor zware berekeningen (model-fit, GxG, KNMI-fetch)
- ✅ Zichtbare achtergrond-taken: header-spinner toont welke berekeningen lopen
- ✅ Eén klasse die de PastaStore wrapt — geen monkey-patching
- ✅ Tabs als echte pagina's (URL `/model`, `/droogte`, ...) i.p.v. Dash-callback-spaghetti
- ✅ Accepteert ZIP, BRO Loket-export-ZIP **én** uitgepakte BRO-map rechtstreeks

## Installatie

```bash
# Vanuit project-root
cd PASTAS/pastasdash_v2
uv sync
```

Path-dependencies worden automatisch opgepakt:
- `../../geo_stack` (BRO-parser, KNMI)
- `../pastas_adapter` (fit helpers)
- `../../lesa-agent-v2/packages/lesa_agent` (BRO Loket → PastaStore)

## Starten

```bash
uv run pastasdash-v2
# of:
uv run python -m pastasdash_v2
```

Open vervolgens [http://127.0.0.1:8051](http://127.0.0.1:8051) in je browser.

Optioneel: `--port 8052`, `--reload` (auto-restart bij file-change).

> Poort `8050` blijft vrij voor de oude pastasdash zodat je beide naast elkaar kunt draaien.

## Data-locaties (persistent state)

| Doel | Pad |
|---|---|
| App-state DB | `~/.pastasdash_v2/state.db` |
| Compute-cache | `~/.pastasdash_v2/cache/` |
| KNMI-cache (parquet) | `~/.pastasdash_v2/knmi_cache/` |

Bij eerste start zijn deze leeg. Een schone start = directory weggooien.

## Pagina's

| Pagina | Wat | Bron-status |
|---|---|---|
| **/** (Start) | Store laden + samenvatting | Werkt zodra je een store laadt |
| **/overview** | Kaart + tabel + multi-select tijdreeksen | Werkt; vereist `x, y`-kolommen in oseries |
| **/model** | Bekijk + fit modellen per peilbuis | Fit gebruikt RechargeModel + Gamma (configureerbaar) |
| **/compare** | Vergelijk meerdere modellen (chart + tabel) | Vereist gefitte modellen |
| **/maps** | Kleur peilbuizen op R², EVP, GHG/GLG/GVG of N obs | GxG-berekening werkt zonder model |
| **/droogte** | KNMI cumulatief neerslagtekort + percentielbanden | Onafhankelijk van store; werkt direct |

## Cache leegmaken

Per store via Python:
```python
from pastasdash_v2.state.cache import invalidate_store
invalidate_store("/volledig/pad/naar/store.zip")
```

Of alles: `rm -rf ~/.pastasdash_v2/cache`

## Tests

```bash
uv run pytest tests/
```

## Architectuur in één diagram

```
            ┌─────────────────────────────────────────┐
            │  NiceGUI pages (URL-based routing)      │
            │  home, overview, model, compare, ...    │
            └───────────┬─────────────────────────────┘
                        │ leest/schrijft
            ┌───────────▼─────────────────────────────┐
            │  StoreManager (singleton)               │
            │  - Wrapt PastaStore zonder monkey-patch │
            │  - Publiceert on_change events          │
            └─────┬──────────────────────────┬────────┘
                  │                          │
        ┌─────────▼──────────┐    ┌─────────▼──────────────┐
        │  AppState/UIState  │    │  compute_cache         │
        │  (SQLite + JSON)   │    │  (diskcache, memoize)  │
        └────────────────────┘    └────────────────────────┘
```
