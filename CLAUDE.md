# Pastas-Hydro-Insight — werkinstructies

Zelfstandige repo voor de PASTAS-gereedschapskist. Geen onderdeel meer van de
bredere Eelerwoude GIS-workspace — `geo_stack`, `BeSI`, `lesa-agent-v2` en
`ArcGIS_online` hebben elk hun eigen repo.

> Deze map ligt fysiek binnen `C:\GIS\EcoHydrologie\`, maar de repo begint
> hier. Alles wat naast deze map staat (`modflow/`, `lesa-agent-v2/`) hoort er
> niet bij en staat in `.gitignore`.

## Rolverdeling v1 / v2

Beide versies blijven draaien, met verschillende status:

| | Status | Wat mag erin |
|---|---|---|
| `pastasdash/` (v1, Dash) | **In gebruik bij collega's, bevroren** | Alleen bugfixes. Geen nieuwe functies, geen refactors. |
| `pastasdash_v2/` (v2, NiceGUI) | **In ontwikkeling** | Nieuwe functies. Doel: alles overnemen wat collega's in v1 waarderen. |

v1 draait op poort 8050, v2 op 8051 — ze kunnen tegelijk aan staan.

Nog open: collega's vinden de Neerslagtekort-pagina in v1 makkelijker te
bereiken en mooier dan in v2. Achterhalen wát dat precies is (plek in de
navigatie of de vormgeving van de grafiek) vóór er iets aan v2 verandert.

## Packages

- `pastasdash` — Dash-GUI, fork van upstream `pastas/pastasdash` met een extra
  Droogte-tab. Workspace-member.
- `pastasdash_v2` — NiceGUI-variant. **Zelfstandig**: eigen `pyproject.toml`,
  `.python-version` en `uv.lock`, en bewust géén workspace-member. Eigen
  werkinstructies in `pastasdash_v2/CLAUDE.md`.
- `pastas_adapter` — gedeelde adapter tussen PASTAS/PastaStore en de rest.
  Workspace-member.

**v2 heeft geen afhankelijkheden op privérepo's.** Alles komt van PyPI, zodat
een collega zonder GitHub-account kan klonen en draaien. Houd dat zo: elke
nieuwe dependency moet op PyPI staan. (`lesa_agent` is optioneel en alleen
nodig voor ruwe BRO Loket-exports; het dashboard vraagt er zelf om.)

## Draaien

```powershell
cd pastasdash_v2 && uv run python -m pastasdash_v2   # v2, poort 8051
cd pastasdash    && uv run python -m pastasdash      # v1, poort 8050
```

**Altijd `python -m`, nooit de console-scripts.** `uv run pastasdash-v2` start
een `.exe` die uv net heeft aangemaakt; de virusscanner blokkeert dat met
`Failed to spawn: Toegang geweigerd` (os error 5), juist bij de eerste start na
klonen. Bewezen in één en dezelfde omgeving: de console-script faalde,
`python -m` startte. v1 kreeg hiervoor een `__main__.py`.

## Werkwijze

De opdrachtgever programmeert niet. Dat betekent:

1. **Spreek "klaar" af in waarneembare stappen** vóór je begint — "ik start de
   app, klik X, en zie Y" — niet in code-termen.
2. **Elke door een collega gemelde fout wordt eerst een test, dan pas een fix.**
   Anders komt dezelfde fout terug.
3. **Eén zichtbare verandering per opdracht.** Geen refactors of hernoemingen
   die er niet om gevraagd zijn.
4. **Test installatie-instructies voordat je ze opschrijft.** De README wees
   eerder naar een repo die niet bestaat; dat kost een collega een halve dag.
