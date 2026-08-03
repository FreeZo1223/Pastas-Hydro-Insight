# PastasDash v2 — Claude werkinstructies

## Doel

NiceGUI-gebaseerd grondwaterdashboard als vervanger voor de oude Streamlit `dashboard/app.py`.
Laadt een **PastaStore** (Zarr-database met peilbuis-tijdreeksen en PASTAS-modellen) en biedt
ecohydrologen een interactieve analyse-omgeving zonder programmeerkennis.

---

## Opstarten

```powershell
cd C:\GIS_Projecten\PASTAS\pastasdash_v2

uv sync --extra dev          # eerste keer of na wijziging pyproject.toml
uv run pastasdash-v2         # start server → http://127.0.0.1:8051
uv run pytest tests/         # voer 13 tests uit (4 test-files, alle groen)
```

Poort **8051** — 8050 is gereserveerd voor pastasdash v1 (de oude conda env).

---

## Projectstructuur

```
C:\GIS_Projecten\PASTAS\pastasdash_v2\
├── pyproject.toml                      # uv project; entry: pastasdash-v2 → cli:main
├── README.md
├── CLAUDE.md                           # dit bestand
├── tests/
│   ├── test_cache.py                   # memoize decorator + invalidatie (3 tests)
│   ├── test_droogte_compute.py         # pure droogte-functies (4 tests)
│   └── test_persistence.py            # AppState + UIState roundtrips (5 tests)
└── pastasdash_v2/
    ├── __init__.py
    ├── __main__.py                     # python -m pastasdash_v2
    ├── cli.py                          # argparse → run()
    ├── config.py                       # constanten, paden, ColumnMapping
    ├── main.py                         # run() + @ui.page + app.on_startup  ← KRITISCH
    ├── tasks.py                        # TaskRegistry, run_task, run_in_thread
    ├── state/
    │   ├── persistence.py              # AppState (globaal) + UIState (per store)
    │   ├── cache.py                    # @memoize decorator (diskcache)
    │   └── store.py                    # StoreManager + STORE singleton
    ├── compute/
    │   ├── droogte.py                  # pure functies: deficit, pivot, percentielbanden
    │   ├── fitting.py                  # fit_model(oseries_name, FitOptions)
    │   ├── timeseries.py               # @memoize stats/gxg/summary
    │   ├── knmi.py                     # KNMI ophalen + parquet cache
    │   └── stations.py                 # dichtstbijzijnde KNMI-stations
    ├── components/
    │   ├── header.py                   # render_header(active_tab)
    │   ├── store_loader.py             # render_store_loader()
    │   └── plots.py                    # Plotly figure-factories
    └── pages/
        ├── home.py                     # render() → store loader + samenvatting
        ├── overview.py                 # render() → kaart + tabel + tijdreeks
        ├── model.py                    # render() → model viewer + fit UI
        ├── compare.py                  # render() → multi-model grafiek
        ├── maps.py                     # render() → choropleth R²/GHG/GLG/GVG
        └── droogte.py                  # render() → KNMI neerslagtekort
```

---

## Architectuur

### Data-flow

```
PastaStore (Zarr ZIP / BRO-dir / BRO-ZIP)
        │
        ▼
StoreManager (state/store.py)        ← STORE singleton
        │
        ├── oseries()  → DataFrame met lat/lon (EPSG:4326)
        ├── stresses() → DataFrame
        ├── model_names() / oseries_names()
        └── pstore     → pastastore.PastaStore object
                │
                ├── compute/fitting.py   → fit_model()  (schrijft terug naar pstore)
                ├── compute/timeseries.py → @memoize stats, gxg, summary
                ├── compute/knmi.py      → KNMI neerslag/verdamping (parquet cache)
                └── compute/droogte.py  → pure functies: deficit, percentielen

State (persistente opslag)
        ├── AppState (SQLite WAL)     → globale instellingen, "last_store_path"
        ├── UIState(store_key)        → selecties, filters per store
        └── diskcache (compute_cache) → @memoize resultaten (2 GB limiet)
```

### NiceGUI page-routing

Elke pagina is een module in `pages/` met één publieke functie `render() -> None`.
Registratie in `main.py`:

```python
def run(...) -> None:
    @ui.page("/")
    def page_home() -> None:
        home.render()
    # ... alle overige pagina's ...
    app.on_startup(lambda: ui.colors(primary=BRAND_COLOR))
    ui.run(...)
```

Elke `render()` roept `render_header(active_tab)` aan als eerste stap,
gevolgd door de pagina-specifieke NiceGUI-widgets.

### Reactieve updates

`StoreManager.on_change(callback)` registreert listeners die worden aangeroepen
zodra een nieuwe store is geladen. Elke pagina die verversing nodig heeft
abonneert zich hierop in `render()`.

---

## Kritische NiceGUI-beperkingen

> **Lees dit vóór je iets aan `main.py` wijzigt.**

### 1. `@ui.page` MOET binnen `run()` staan

NiceGUI-decorators mogen **nooit** op module-niveau staan (buiten een functie).
Als dat wel gebeurt, worden ze uitgevoerd bij import → `script_mode = True` →
`RuntimeError: ui.page cannot be used in NiceGUI scripts when UI is defined in the global scope`.

### 2. `ui.colors()` NOOIT vóór `ui.run()`

`ui.colors()` (en elke andere NiceGUI-aanroep die de slot-stack benadert)
activeert intern `core.script_mode = True`. Als die vlag daarna nog `@ui.page`-routes
ziet, crasht `ui.run()` met diezelfde RuntimeError.

**Correct patroon:**
```python
app.on_startup(lambda: ui.colors(primary=BRAND_COLOR))  # ✓
ui.run(...)
```

**Fout patroon:**
```python
ui.colors(primary=BRAND_COLOR)  # ✗  — vóór ui.run()
ui.run(...)
```

### 3. Cosmetic startup-fout (geen actie nodig)

Direct na het starten verschijnt in de terminal:
```
RuntimeError: Request is not set
```
Dit komt uit NiceGUI's interne session-pruning timer die vuurt vóór er een echte
browserverbinding is. De server werkt normaal (HTTP 200). **Geen fix nodig.**

---

## State-laag

### Persistente opslag (`state/persistence.py`)

| Klasse | Gebruik | Sleutel-formaat |
|--------|---------|-----------------|
| `AppState` | Globale app-instellingen | vrije string (bijv. `"last_store_path"`) |
| `UIState(store_key)` | Selecties per store (welke peilbuis, welke filter) | vrije string |

Beide gebruiken SQLite WAL-mode en JSON-geserialiseerde waarden.

### Compute cache (`state/cache.py`)

```python
@memoize("namespace")
def mijn_functie(store_key: str, arg2, ...) -> ...:
    ...
```

- Eerste argument **moet** `store_key: str` zijn — het memoize-systeem gebruikt dit
  om cache-entries per store te scheiden.
- Cache-sleutel: `"{namespace}:{store_key}:{sha1(rest)}"`.
- `invalidate_store(store_key)` verwijdert alle entries voor die store.
- Limiet: 2 GB (diskcache).

### Opslaglocaties (overleven herstarts)

| Doel | Pad |
|------|-----|
| SQLite state DB | `~/.pastasdash_v2/state.db` |
| Compute cache | `~/.pastasdash_v2/cache/` |
| KNMI parquet cache | `~/.pastasdash_v2/knmi_cache/` |

---

## StoreManager (`state/store.py`)

```python
STORE = StoreManager()   # module-niveau singleton — nooit opnieuw instantiëren
```

| Methode | Beschrijving |
|---------|-------------|
| `load_from_path(path)` | Auto-detecteert: BRO-dir, BRO-ZIP, PastaStore-ZIP |
| `load_from_zip_bytes(blob, name)` | Voor `ui.upload` in NiceGUI |
| `close()` | Sluit de onderliggende PastaStore |
| `on_change(callback)` | Registreer een luisteraar voor store-wijzigingen |
| `oseries()` | DataFrame met lat/lon (EPSG:4326) |
| `stresses()` | DataFrame met stressoren |
| `model_names()` | Lijst van gefikte modelnames |
| `oseries_names()` | Lijst van peilbuisnamen |
| `ui_state` (property) | Geeft `UIState(self.store_key)` terug |

`restore_last_store()` wordt aangeroepen bij startup en laadt automatisch de
laatste gebruikte store (via `AppState["last_store_path"]`).

---

## Achtergrondtaken (`tasks.py`)

```python
REGISTRY = TaskRegistry()

# Context manager (async):
async with run_task("label", notify_on_success=True):
    zware_operatie()

# Blocking functie in threadpool:
await run_in_thread("label", blocking_fn, arg1, arg2, notify=True)
```

Actieve taken zijn zichtbaar als spinner in de header (`header.py`).

---

## Model-fitten (`compute/fitting.py`)

```python
@dataclass(frozen=True)
class FitOptions:
    rfunc: str = "Gamma"
    noise_model: bool = True
    tmin: str | None = None
    tmax: str | None = None
    stresses: tuple[str, ...] = ("neerslag_KNMI", "verdamping_KNMI")

success, message, model = fit_model("B42C0133_001", FitOptions())
```

- Gebruikt `ps.RechargeModel` + `ps.ArNoiseModel` (fallback: `ArmaNoiseModel`).
- Slaat het model op in `STORE.pstore`.
- Invalideert automatisch de compute-cache voor die store.
- Retourneert `(bool, str, ps.Model | None)`.

---

## Droogte-compute (`compute/droogte.py`)

Pure functies — geen I/O, eenvoudig te testen:

| Functie | Invoer | Uitvoer |
|---------|--------|---------|
| `compute_deficit(neerslag, verdamping)` | pd.Series | pd.Series (cumulatief tekort) |
| `pivot_by_year(deficit)` | pd.Series | pd.DataFrame (jaar × dag) |
| `compute_percentile_bands(pivoted)` | pd.DataFrame | dict met P10/P50/P90 |

---

## Afhankelijkheden

Editable path-dependencies (gedefinieerd in `pyproject.toml [tool.uv.sources]`):

| Package | Pad |
|---------|-----|
| `geo-stack-nl` | `C:\GIS_Projecten\geo_stack\` |
| `pastas-adapter` | `C:\GIS_Projecten\PASTAS\pastas_adapter\` |
| `lesa-agent` | `C:\GIS_Projecten\lesa-agent-v2\packages\lesa_agent\` |

`lesa-agent` verzorgt de conversie BRO Loket (GMW XML + GLD CSV) → PastaStore.

---

## Bekende issues / nog te doen

| Item | Status | Notitie |
|------|--------|---------|
| Server start succesvol | ✓ Opgelost | `script_mode`-bug gefixed in `main.py` |
| ValueError: cannot convert float NaN | ✓ Opgelost | `pd.isna()` toegevoegd bij rij-parsing in `overview.py` |
| TypeError: Timestamp not serializable | ✓ Opgelost | `clean_fig()` wrapper toegevoegd in `components/plots.py` en op pagina's |
| FileNotFoundError: Item not in models | ✓ Opgelost | `get_models()` binnen `try-except` geplaatst in `model_summary` |
| 13 unit-tests groen | ✓ | `uv run pytest tests/` (inclusief nieuwe plot/JSON-test) |
| Browser-UX volledig getest | ⚠ Gedeeltelijk | Port 8052 succesvol live geverifieerd in browser |
| `overview.py` multi-select peilbuizen | ? | Werking niet volledig geverifieerd in browser |
| `maps.py` choropleth | ? | Vereist gefikte modellen in store |
| `droogte.py` KNMI-fetch | ? | Vereist KNMI API of gecachete data |
| Testen per page uitbreiden | – | Alleen compute-laag en plots hebben tests |

---

## Pagina-overzicht

| URL | Module | Functie |
|-----|--------|---------|
| `/` | `pages/home.py` | Store laden + statistieken-kaart |
| `/overview` | `pages/overview.py` | Kaart + tabel + tijdreeks, persistente selectie via `UIState` |
| `/model` | `pages/model.py` | Model bekijken + handmatig fitten via UI |
| `/compare` | `pages/compare.py` | Meerdere modellen naast elkaar |
| `/maps` | `pages/maps.py` | Choropleth op R², EVP, GHG/GLG/GVG, N obs |
| `/droogte` | `pages/droogte.py` | KNMI cumulatief neerslagtekort + percentielbanden |

---

## Component-API

### `components/header.py`

```python
render_header(active_tab: str) -> None
# active_tab moet overeenkomen met de tab-label ("Home", "Overview", etc.)
```

### `components/store_loader.py`

```python
render_store_loader() -> None
# Toont 3 tabs: Upload ZIP | Pad op schijf | Recent
```

### `components/plots.py`

Alle functies retourneren een `plotly.graph_objects.Figure`:

| Functie | Beschrijving |
|---------|-------------|
| `empty_figure(message)` | Lege placeholder |
| `timeseries_overlay(series_list)` | Meerdere tijdreeksen op één as |
| `timeseries_stacked(series_list)` | Gestapelde subplots |
| `map_oseries(oseries_df)` | Mapbox scatter van peilbuizen |
| `model_results_figure(model)` | Geobserveerd vs gesimuleerd |
| `model_diagnostics_figure(model)` | Residuen, ACF, etc. |
| `droogte_figure(deficit, bands)` | Neerslagtekort + percentielbanden |

---

## Config-constanten (`config.py`)

```python
APP_NAME = "pastasdash_v2"
APP_DIR  = Path.home() / ".pastasdash_v2"
STATE_DB_PATH    = APP_DIR / "state.db"
COMPUTE_CACHE_DIR = APP_DIR / "cache"
KNMI_CACHE_DIR   = APP_DIR / "knmi_cache"
BRAND_COLOR = "#006f92"
DEFAULT_PORT = 8051
CRS_RD    = "EPSG:28992"
CRS_WGS84 = "EPSG:4326"
```
