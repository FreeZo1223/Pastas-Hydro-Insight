# CHANGELOG

Alle wijzigingen aan dit project worden hier bijgehouden.
Versienummering volgt [Semantic Versioning](https://semver.org/): MAJOR.MINOR.PATCH

---

## [Unreleased]

## [0.2.0] — gepland
### Toe te voegen
- Gewogen soortenrijkdom op basis van beschermingsstatus (versie 2)
- Ecologische waardekaart (5 klassen)
- Gewogen soortentabel met kolom `ecologisch_gewicht`

## [0.1.0] — initiële versie
### Toegevoegd
- Projectstructuur opgezet
- `config/settings.py` met centrale parameterconfiguratie
- `config/species_metadata.csv` met 235 soorten, cutoffs en gewichten
- `CLAUDE_CODE_PROMPT.md` met volledige bouwspecificaties
- Ondersteuning voor shapefile en GeoPackage als invoer
- Analyse versie 1: soortenrijkdom per 25m-cel
- Prioriteringskaart (5 klassen)
- Soortentabel als CSV en Excel
- Samenvattende statistieken
- `run_metadata.json` per analyse-run
- Logging naar bestand en console

---

## Toekomstige versies (roadmap)

### [0.3.0] — NDFF-vergelijking
- Koppeling met NDFF-waarnemingen per onderzoeksgebied
- Vergelijking verwacht (BeSI) vs. waargenomen (NDFF)
- Kennishiatenanalyse: verwacht maar nooit gemeld

### [0.4.0] — Batchverwerking
- Meerdere onderzoeksgebieden tegelijk verwerken
- Vergelijkende output tussen gebieden

### [0.5.0] — Rapportage
- Geautomatiseerde PDF-rapportage per project
- Kaarten en tabellen geïntegreerd in rapport
