# Changelog

Alle breaking changes worden hier bijgehouden.
Format: [versie] datum — omschrijving.

## [Unreleased]

### geo_stack
- **Hernoemd:** `services.yaml` → `data_sources.yaml`
- **Hernoemd:** package `tools/` → `geo_stack/` (subpakketten: `core/`, `skills/`)
- **Verplaatst:** `geo_utils.py`, `cache.py`, `normalizer.py`, `discovery.py` → `geo_stack/core/`
- **Verplaatst:** `bgt_fetcher.py` → `geo_stack/skills/bgt.py`
- **Verplaatst:** `ahn_tiles.py` → `geo_stack/skills/ahn.py`
- **Verplaatst:** `provenance.py`, `report.py` → `geo_stack/`
- **Nieuw:** `geo_stack/async_http.py` — httpx async client met retry
- **Fix:** `cache.py` — atomic rename (thread-safe voor parallelle writes)
- **Fix:** `discovery.py` — laadt `data_sources.yaml` i.p.v. `services.yaml`
- **Imports:** alle interne imports bijgewerkt van `tools.*` naar `geo_stack.core.*` of `geo_stack.skills.*`

### Migratie vanuit geo_stack standalone
```python
# Oud
from tools.geo_utils import validate_rd_crs, http_session
from tools.cache import cached_fetch
from tools.bgt_fetcher import fetch_bgt
from tools.ahn_tiles import fetch_ahn_tile

# Nieuw
from geo_stack.core.geo_utils import validate_rd_crs, http_session
from geo_stack.core.cache import cached_fetch
from geo_stack.skills.bgt import fetch_bgt
from geo_stack.skills.ahn import fetch_ahn_tile
```
