# PastasDash — werkinstructies

Zelfstandige app. **Geen onderdeel van de `C:\GIS` uv-workspace** (staat daar
in `exclude`) en zonder afhankelijkheden op privérepo's — collega's moeten dit
kunnen klonen en draaien zonder GitHub-account. Houd dat zo: elke nieuwe
dependency moet op PyPI staan.

```powershell
uv run pastasdash-v2              # start op http://127.0.0.1:8051
uv run python -m pytest tests/ -q
uv run ruff check pastasdash_v2/
```

`uv run pytest` faalt op sommige werkplekken op de virusscanner
(`Failed to spawn: Toegang geweigerd`); `uv run python -m pytest` werkt wel.

## Motor en schil

```
pastasdash_v2/
├── core/   rekenwerk, opslag, caching — importeert NOOIT nicegui
└── ui/     NiceGUI: theme.py, shell.py, components/, pages/
```

`tests/test_architectuur.py` faalt zodra `core` iets uit `ui` of `nicegui`
importeert. Moet een berekening iets aan de gebruiker melden? Geef het resultaat
terug en laat de schil het tonen.

## Vaste omlijsting

`ui/shell.py` levert `pagina(actief)`, een context manager die kop, peilbuizen-
lijst en weergavekiezer tekent. Een pagina ziet er zo uit:

```python
def render() -> None:
    with pagina("statistics"):
        _inhoud()
```

De peilbuisselectie is **gedeeld** en staat in de zijbalk — `geselecteerd()` en
`zet_selectie()`. Bouw geen tweede keuzelijst in een pagina: dat was precies de
verwarring die de oude opzet had. Een keuzelijst voor iets anders (één model,
een kaartmetriek) mag wel; laat die dan wel starten bij de zijbalkselectie.

Selecties leven in `UIState` (SQLite) en overleven een herstart.

## NiceGUI-valkuilen

1. **`@ui.page` moet binnen `run()` staan.** Op moduleniveau wordt de decorator
   bij import uitgevoerd → `script_mode = True` → `RuntimeError` in `ui.run()`.
2. **`ui.colors()` nooit vóór `ui.run()`.** Zet dezelfde vlag aan. Gebruik
   `app.on_startup(...)`, zoals in `main.py`.
3. `RuntimeError: Request is not set` vlak na het starten is cosmetisch — de
   sessie-opruimtimer vuurt vóór de eerste browserverbinding.

## Plotly

Plotly 6 verving Mapbox door MapLibre: `Scattermapbox` → `Scattermap` en
`mapbox_*` → `map_*`. Gebruik `plots.map_trace_cls()`, dat kiest op basis van de
geïnstalleerde versie. Nieuwe kaartcode niet zelf laten kiezen.

## GxG

Komt uit `pastas.stats.ghg/glg/gvg` — niet zelf uitrekenen. Een eerdere eigen
implementatie rekende onvolledige hydrologische jaren mee en gaf daardoor een
14 cm te hoge GLG, wat doorwerkte in de grondwatertrap. Drempels staan in
`core/config.py`; `gxg()` geeft ook `n_years` terug zodat de UI kan uitleggen
waarom een uitkomst leeg is.

## Storelocaties

`core/store.py` herkent PasConnector-mappen (`.pastastore`-descriptor), ZIP's en
BRO Loket-exports. Het `path`-veld *in* de descriptor wordt genegeerd — dat
verwijst vaak nog naar de machine waar de store gemaakt is.
