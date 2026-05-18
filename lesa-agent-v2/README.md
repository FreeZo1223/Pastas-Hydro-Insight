# LESA Agent v2

Agentic pipeline voor LandschapsEcologische Systeem Analyse (LESA).

**Bureauondersteuner + hypothesegenerator + veldwerk-voorbereider.**
Niet een rapport-generator. De expert is eindverantwoordelijk.

## Snelstart

```bash
# Installeer uv als je dat nog niet hebt
pip install uv

# Kloon en installeer
git clone ...
cd lesa-agent-v2
uv sync

# Configureer
cp .env.example .env
# Vul ANTHROPIC_API_KEY in

# Draai
uv run lesa --help
```

## Structuur

```
packages/
  geo_stack/   — data-laag: WFS/WCS/STAC fetch, CRS-validatie, cache
  lesa/        — LESA-logica: plugins, agent, sessie, rapporten
examples/
  burgh_haamstede/   — referentie testcase (Provincie Zeeland)
docs/
  ARCHITECTURE.md    — architectuurvoorstel + beslissingen
```

## Documentatie

- Architectuur: `docs/ARCHITECTURE.md`
- Plugin bouwen: `docs/PLUGIN_AUTHORING.md` (nog te schrijven)
- Methodologie: `docs/METHODOLOGY.md` (nog te schrijven)

## Testcase: Burgh-Haamstede

Hydrologische impact peilverlaging ijsbaan op duingebied (Kop van Schouwen, Zeeland).
Zie `examples/burgh_haamstede/`.
