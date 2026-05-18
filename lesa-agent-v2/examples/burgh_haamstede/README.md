# Burgh-Haamstede — testcase

Canonieke testcase voor de LESA-agent. Locatie: zandwinplas en
ijsbaan ten zuiden van Burgh-Haamstede, Kop van Schouwen, Zeeland.
Grenst aan Natura2000-gebied **Zeepeduinen**.

## Bestanden

- [`aoi.geojson`](aoi.geojson) — bounding box rondom de zandwinplas
  in EPSG:28992 (RD New). Gebruik `AOI.from_geojson_file()` om te
  laden.

## Achtergrond

Briefing in v1: `C:\GIS_Projecten\lesa-agent\LESA_Test_Burgh.md`.
Het gebied is geselecteerd omdat het:

- klein genoeg is voor snelle end-to-end runs (~3,5 km × 3 km bbox);
- alle relevante landschapsdimensies bevat (duin, kwelzone, natte
  laagte, antropogene ingreep zandwinning);
- aan een Natura2000-gebied grenst — geschikt voor de
  `natura2000_nabijheid`-plugin;
- geen gevoelige eigendomsdata bevat;
- in v1 al deels is doorlopen — vergelijkmateriaal voor evaluatie.

## Sessie starten (zodra een CLI bestaat)

```bash
uv run lesa session new \
    --project "Burgh-Haamstede LESA test" \
    --aoi examples/burgh_haamstede/aoi.geojson \
    --scale-level 2 \
    --landscape-type duinen
```

Dit maakt `sessions/<uuid>/state.json` aan en logt vervolgens elke
plugin-run. De agent wordt aangeroepen via `uv run lesa chat`.

## Verwachte plugin-volgorde (rangordemodel)

1. **geologie** — REGIS-doorsnede, ondergrond-stratigrafie
2. **geomorfologie** — duinmorfologie, paleo-stuifkuil-spores
3. **bodem** — BRO Bodemkaart, AHN-relief-analyse
4. **hydrologie** — kwelkansenkaart, peilbuizen NHI, PASTAS-modellen
5. **vegetatie** — N2000-habitattypen, vegetatie-indicatoren
6. **fauna** — NDFF-waarnemingen (alleen als data-toegang geregeld)
7. **mens** — historische topografie (Topotijdreis), beheer

Niveau 1 ("oriëntatie") draait alleen 1–4 in beperkte vorm. Niveau 2
draait 1–5 volledig. Niveau 3 voegt veldwerk-voorbereiding toe.
