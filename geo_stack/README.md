# geo_stack — Grounded Geospatial Automation voor Nederlandse data

Herbruikbare Python-package voor data-acquisitie uit PDOK, BGT, AHN4, BRO,
Kadaster, Sentinel-2 en Google Earth Engine. Iedere bron is gescheiden in een
**skill** (markdown-contract: intent + signature) en een **tool**
(Python-implementatie).

**Versie:** 0.2.1
**Python:** ≥3.11
**Default CRS:** EPSG:28992 (RD-stelsel)

---

## Waarom geo_stack?

Vóór deze package werd Nederlandse geo-data in elk project anders opgehaald —
hardcoded URLs, geen retry, geen cache, dezelfde valkuilen (CQL_FILTER op
tile-cached WFS) opnieuw uitgevonden. `geo_stack` centraliseert dat:

- Eén plek voor endpoints (`data_sources.yaml`)
- Retry-logica + HTTP-sessie-hergebruik (`core.geo_utils.http_session`)
- Disk-cache voor fetches (`core.cache.cached_fetch`)
- Cloud-native streaming via DuckDB voor grote datasets (3DBAG, BAG-bulk)
- **Smart dispatcher** (`fetch.fetch_features`): probeert automatisch
  cloud-native, valt terug op WFS — downstream callers kennen geen URLs
- Geoptimaliseerde GeoParquet-output: Z-order spatial sort + covering bbox
  + ZSTD-compressie voor 10–100× snellere bbox-queries
- Provenance-registratie per fetch

---

## Installatie

### Optie B — editable install (aanbevolen)

```bash
pip install -e C:\GIS_Projecten\geo_stack
```

Daarna in elk project:

```python
from geo_stack import kadaster, ahn_tiles, gee_fetcher
```

### Optie C — path-dependency in pyproject.toml (uv / poetry)

Voor monorepo-projecten zoals lesa-agent-v2:

**uv:**
```toml
[tool.uv.sources]
geo_stack = { path = "C:/GIS_Projecten/geo_stack", editable = true }
```

**poetry:**
```toml
[tool.poetry.dependencies]
geo_stack = { path = "C:/GIS_Projecten/geo_stack", develop = true }
```

### Met optionele Earth Engine support

```bash
pip install -e "C:\GIS_Projecten\geo_stack[gee]"
```

### Voor development (tests, ruff, mypy)

```bash
pip install -e "C:\GIS_Projecten\geo_stack[dev]"
```

---

## Quickstart

### Smart dispatcher — aanbevolen voor downstream callers

Eén entrypoint dat per dataset het snelste pad kiest. Probeert eerst
cloud-native streaming, valt terug op WFS/REST.

```python
from geo_stack.fetch import fetch_features

# bag_3d heeft cloud_native_url → DuckDB-streaming wordt gebruikt
panden_3d = fetch_features("bag_3d", bbox=(125_000, 460_000, 145_000, 480_000))

# bgt heeft alleen WFS → directe fetcher wordt gebruikt
sloten = fetch_features(
    "bgt",
    bbox=(125_000, 460_000, 145_000, 480_000),
    feature_type="bgt:waterdeel",
)

# Inspect welke backends per dataset bestaan
from geo_stack.fetch import list_datasets
print(list_datasets())
# {'bgt': {'cloud_native': False, 'fallback': True},
#  'bag_3d': {'cloud_native': True, 'fallback': False}, ...}
```

### Kadastrale percelen via PDOK Locatieserver

```python
from geo_stack.kadaster import fetch_parcels_by_kadastraal_id

out = fetch_parcels_by_kadastraal_id(
    ids=["LLS00-B-10", "LLS00-B-11"],
    output_dir=Path("data/kadaster/"),
)
```

### AHN4 hoogteraster via WCS

```python
from geo_stack.ahn_tiles import fetch_ahn_tile

# Stichtse Vecht-deel, 0.5m resolutie
tile = fetch_ahn_tile(
    bbox=(125000, 460000, 130000, 465000),
    product="DSM",
    resolution=0.5,
    output_path="data/ahn_dsm_05m.tif",
)
```

### BGT vectordata via WFS

```python
from geo_stack.bgt_fetcher import fetch_bgt

panden = fetch_bgt(
    bbox=(125000, 460000, 145000, 480000),
    feature_type="bgt:pand",
)
```

### 3DBAG via cloud-native streaming (10x sneller dan WFS)

```python
from geo_stack.cloud_native import stream_3dbag

panden_3d = stream_3dbag(
    bbox=(125000, 460000, 145000, 480000),
    layer="lod22_2d",
)
```

### Google Earth Engine — AlphaEarth embeddings

```python
from geo_stack.gee_fetcher import fetch_alpha_earth

# Eenmalig: earthengine authenticate
emb = fetch_alpha_earth(
    bbox=(125000, 460000, 145000, 480000),  # RD-New
    year=2024,
    output_path="data/embeddings_64.tif",   # output in EPSG:32631
)
```

### Caching — herhaalde fetch is gratis

```python
from pathlib import Path
from geo_stack.cache import cached_fetch
from geo_stack.bgt_fetcher import fetch_bgt

@cached_fetch(cache_dir=Path("data/cache"), suffix=".parquet")
def cached_bgt(bbox, feature_type):
    return fetch_bgt(bbox, feature_type)
```

---

## Skills (markdown-contracten)

Elke tool heeft een bijbehorende skill in `skills/`. LLM's gebruiken deze om
te beslissen welke tool aan te roepen.

| Skill | Tool | Bron |
|-------|------|------|
| [ahn-tiles.md](skills/ahn-tiles.md) | `ahn_tiles.fetch_ahn_tile` | PDOK AHN4 WCS |
| [bgt-fetcher.md](skills/bgt-fetcher.md) | `bgt_fetcher.fetch_bgt` | PDOK BGT WFS |
| [cache.md](skills/cache.md) | `cache.cached_fetch` | (decorator) |
| [cloud-native.md](skills/cloud-native.md) | `cloud_native.stream_*` | DuckDB streaming |
| [discovery.md](skills/discovery.md) | `discovery.discover_services` | Capabilities check |
| [gee-fetcher.md](skills/gee-fetcher.md) | `gee_fetcher.fetch_alpha_earth` | Google Earth Engine |
| [ndvi-stac.md](skills/ndvi-stac.md) | `ndvi_stac.fetch_ndvi` | Sentinel-2 STAC |
| [normalizer.md](skills/normalizer.md) | `normalizer.normalize_to_geoparquet` | (utility) |

---

## Endpoints — `services.yaml`

Alle endpoints, versies en bekende beperkingen staan in `services.yaml`.
Code (`discovery.py`, `cloud_native.py`) leest dit bestand — endpoints worden
nooit hardcoded in business-logica.

Bekijk de geregistreerde bronnen:

```python
import yaml, pathlib
data = yaml.safe_load(pathlib.Path("services.yaml").read_text(encoding="utf-8"))
print(list(data["services"].keys()))
# ['bgt', 'ahn', 'kadaster', 'bag_3d', 'bag', 'cbs', 'top10nl', 'ndvi', 'fgr', 'gee']
```

---

## Tests

```bash
python -m pytest                    # alle tests
python -m pytest tests/test_imports.py -v   # alleen smoke
python -m pytest --cov=geo_stack    # met coverage (vereist [dev] extras)
```

39 tests draaien zonder netwerkverbinding. Voor integratietests met live
endpoints zou een `pytest -m integration` marker toegevoegd moeten worden.

---

## Design-keuzes

- **CRS-default** — alle outputs in EPSG:28992. Validatie via
  `geo_utils.validate_rd_crs` voor elke skill.
- **BBOX-volgorde** — altijd `(minx, miny, maxx, maxy)`. Geen lon/lat-flip.
- **HTTP** — `requests` met retry-decorator op 5xx. Sessie-hergebruik via
  `http_session()`.
- **Cache** — disk-cache via SHA1 op (functie, args, kwargs). Default-dir
  `data/cache/`.
- **Vector-output** — GeoParquet (EPSG:28992).
- **Raster-output** — Cloud-Optimized GeoTIFF (LZW, 512px tiles, BIGTIFF).
- **Errors** — per skill een eigen `*FetchError`-klasse, alle ervan erven van
  `RuntimeError`.
- **Logging** — module-level `log = logging.getLogger(__name__)`. Geen `print()`.

---

## Bijdragen

1. Nieuwe skill toevoegen: `skills/<naam>.md` + `geo_stack/<naam>.py` +
   smoke-test in `tests/test_<naam>.py` + entry in `services.yaml`
2. Pas `geo_stack/__init__.py` aan om de module te exporteren
3. Run `python -m pytest` — alle tests moeten slagen
4. Bij breaking change: bump versie in `pyproject.toml` + `__init__.py`

---

## Roadmap

- [ ] CI via GitHub Actions (pytest + ruff + mypy)
- [ ] Integratietest-suite met opgeslagen HTTP-fixtures
- [ ] Skill voor NDFF (soortendata) — vereist API-key
- [ ] Skill voor Waarneming.nl REST API
- [ ] Skill voor RIVM Stikstof / Donkerte
- [ ] Async parallel-fetch voor batch-operaties
- [ ] Publiceren op interne Gitea/PyPI

---

## Licentie

MIT
