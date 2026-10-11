# PastasDash v3 — werkinstructies

De browserversie: één HTML-bestand, Python via Pyodide, **rekenkern van v2**.
Lees `README.md` voor de opzet en de bekende grenzen.

```powershell
C:\GIS\.venv\Scripts\python.exe bouw.py
cd ..\pastasdash_v2; uv run --extra dev python -m pytest ..\pastasdash_v3\tests -q
C:\GIS\.venv\Scripts\python.exe tests\browsertest.py     # vanuit pastasdash_v3; paar minuten
```

## Regels

1. **v3 rekent niets zelf uit.** GxG, grondwatertrap, fit en figuren komen uit
   `pastasdash_v2.core` en `ui/components/plots.py`. Ontbreekt er iets, voeg
   het dan daar toe (met een test in v2), niet hier.
2. **Een fout in de kern repareer je in v2**, eerst met een test daar. Bouw
   daarna v3 opnieuw: de kern wordt ingebouwd, niet gedeeld.
3. **Adressen en versies alleen in `bronnen.json`.** Niet in Python of
   JavaScript. Versies van pakketten staan vast; verhoog ze bewust en draai
   daarna de browsertest.
4. **Alles moet werken als lokaal geopend bestand** (`file://`). Dat is strenger
   dan een webadres. Bewezen niet te werken vanaf een lokaal bestand: de
   kaartfiguren van Plotly (`scattermap`, punten blijven weg), OpenStreetMap-
   tegels (weigeren zonder herkomst) en de eigen opslag van de browser (OPFS).
5. **Niets verzinnen in de gegevens.** Een aangevulde of ingekorte KNMI-reeks
   gaat als melding terug naar de gebruiker (`meteo.py`).
6. **Na een wijziging: `bouw.py` en de browsertest.** De tests van de rekenlaag
   zien het scherm en de werker niet.

## Valkuilen

- `ouder.replaceChildren(a, null)` zet de tekst "null" neer. Gebruik `vul()`
  uit `app.js`, dat lege kinderen overslaat.
- Een klasse met `display:` wint van het attribuut `hidden`; daarom staat
  `[hidden] { display: none !important }` in `app.css`.
- `page.evaluate` van Playwright heeft geen tijdslimiet. Laat een test nooit
  wachten op een belofte van Plotly; wacht op `#bezig` (zie `rustig()`).
- De kern van v2 schrijft naar de thuismap (`~/.pastasdash_v2`). Tests zetten
  de thuismap daarom eerst om (`tests/conftest.py`).
- In de browser geeft de BRO bij een onbekend nummer een gewoon antwoord met
  een afwijzing; op de desktop een HTTP 400. `bro.py` vangt beide op.
- `STORE.load_from_path` verwacht dat de mapnaam gelijk is aan de naam in
  `<naam>.pastastore`. De pagina zet een geopende map daarom in het geheugen
  onder `/project/<naam>`, wat de map op schijf ook heet.
