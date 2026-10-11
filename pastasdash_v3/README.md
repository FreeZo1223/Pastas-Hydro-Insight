# PastasDash v3 — in de browser

Eén HTML-bestand waarmee een ecohydroloog peilbuisreeksen uit de BRO bekijkt,
PASTAS-modellen fit en GxG, grondwatertrap, duurlijn en neerslagtekort afleest.
Er hoeft niets geïnstalleerd te worden: Python draait in de browser
(Pyodide, WebAssembly), met **dezelfde rekenkern als PastasDash v2**.

v3 staat naast v2. v2 blijft de desktopversie; v3 is voor collega's die niets
willen installeren, en wordt voorlopig als los bestand via Cowork uitgedeeld.

## Gebruiken

1. Open `dist\pastasdash.html` in **Edge of Chrome** (downloaden en dan openen;
   rechtstreeks vanuit SharePoint of Teams werkt niet). Het laden duurt ongeveer
   een kwart minuut en heeft internet nodig.
2. Kies onder *Project* een **projectmap**, bijvoorbeeld op OneDrive. Een lege
   map wordt een nieuw project; een map van PastasDash wordt geopend.
3. Plak BRO-putnummers (`GMW…`) en kies *Ophalen uit de BRO*.
4. Kies links de peilbuizen; de weergaven volgen die keuze.

Een bestandsnaam met `#put=GMW000000069526,GMW…` erachter haalt die putten
meteen op. Zo kan een andere pagina (de gebiedsverkenner) ernaar doorverwijzen.

| Weergave | Wat je ziet |
|---|---|
| Project | Projectmap kiezen, putten toevoegen of verwijderen, exporteren als zip |
| Reeksen | Grondwaterstanden over of onder elkaar, met neerslag en verdamping; ligging |
| Model | PASTAS-model fitten (één put of alle geselecteerde), resultaten, diagnostiek, parameters |
| Vergelijken | Metingen en simulatie van de geselecteerde modellen, met R² |
| Statistiek | GHG, GLG, GVG, grondwatertrap, duurlijn, regimecurve; tabel als CSV |
| Kaart | Putten gekleurd op R², verklaarde variantie, GxG of aantal metingen |
| Droogte | Cumulatief neerslagtekort per KNMI-station; werkt ook zonder project |

## Opslaan

De **projectmap** is een gewone PastaStore-map (`<naam>.pastastore` met
`oseries\`, `stresses\` en `models\`), hetzelfde formaat als v2. Elke wijziging
gaat direct naar de map. Een collega opent dezelfde map, in de browser of met
v2 op de desktop.

Zonder projectmap staat het werk alleen in het tabblad; de kop zegt dat dan.
*Exporteer als zip* maakt een zip die v3 en v2 beide kunnen openen. Firefox en
Safari kunnen niet in een map schrijven en werken alleen met zip-bestanden.

De browser vraagt na het herladen opnieuw toestemming voor de map; de knop
*Heropen "<map>"* doet dat in één klik.

## Bouwen en testen

```powershell
C:\GIS\.venv\Scripts\python.exe bouw.py                    # dist\pastasdash.html + de skill-zip
cd ..\pastasdash_v2
uv run --extra dev python -m pytest ..\pastasdash_v3\tests -q   # rekenlaag, zonder netwerk
cd ..\pastasdash_v3
C:\GIS\.venv\Scripts\python.exe tests\browsertest.py       # echte browser, echte BRO en KNMI
```

`bouw.py` gebruikt alleen de standaardbibliotheek. De tests van de rekenlaag
lenen de omgeving van v2 (daar staan pastas en pastastore); de browsertest
heeft Playwright nodig en duurt een paar minuten. Hij opent aan het eind de
projectmap en de zip met de rekenkern van v2, om te bewijzen dat de twee
versies elkaars bestanden lezen.

**Na elke wijziging in `pastasdash_v2\pastasdash_v2\core\` opnieuw bouwen**: de
kern wordt in de pagina ingebouwd, niet gedeeld.

| Uitvoer in `dist\` | Voor wie |
|---|---|
| `pastasdash.html` | De pagina zelf |
| `eelerwoude-pastasdash.zip` | M365 Copilot Cowork: de skill |
| `eelerwoude-pastasdash\` | Dezelfde skill, uitgepakt |

`dist\` staat niet in git; het is in een seconde opnieuw te bouwen.

## Bij collega's krijgen

**Met Cowork.** De collega noemt de putnummers of uploadt een lijst; de skill
zet ze in het bestand. De skill rekent niets uit en ziet geen metingen.
Alleen voor jezelf: pak de zip uit in OneDrive onder
`Documenten\Cowork\skills\eelerwoude-pastasdash\`.

**Zonder Cowork.** Zet `dist\pastasdash.html` in een SharePoint-map; collega's
downloaden het.

## Hoe het in elkaar zit

| Pad | Inhoud |
|---|---|
| `bronnen.json` | De enige plek met adressen en versies: Pyodide, Plotly, pakketten, BRO, kaarttegels |
| `pastasdash_v3\brug.py` | De ingang voor de pagina: elke knop is één handeling, JSON erin en eruit |
| `pastasdash_v3\bro.py` | Put en meetreeksen uit de BRO |
| `pastasdash_v3\meteo.py` | Neerslag en verdamping van het dichtstbijzijnde KNMI-station, zonder gaten |
| `pastasdash_v3\project.py` | De store aanmaken en openen, en bijhouden welke bestanden veranderd zijn |
| `pastasdash_v3\figuren.py` | Wat in v2 in de NiceGUI-pagina's zelf staat (vergelijking, kaartwaarden) |
| `src\werker.js` | De rekenwerker: Python buiten het scherm om, zodat de pagina niet bevriest |
| `src\app.js`, `app.css`, `app.html` | Het scherm |
| `vendor\` | Leaflet 1.9.4, wordt ingebouwd |
| `cowork\` | De skill en het script dat de putnummers in het bestand zet |

- **Eén rekenkern.** GxG, grondwatertrap, fit en figuren komen uit
  `pastasdash_v2.core` en `ui\components\plots.py`. v3 rekent niets zelf uit.
- **Opslaan via de pagina.** De store staat in het geheugen van de werker.
  Na elke handeling die iets verandert, vergelijkt `project.gewijzigd()` de
  bestanden met wat er op schijf staat; de pagina schrijft alleen de
  verschillen naar de projectmap.
- **KNMI zonder gaten.** PASTAS weigert reeksen met gaten. Ontbrekende dagen
  komen van het dichtstbijzijnde station dat ze wel heeft. Een gat van meer dan
  een week dat geen enkel station kan vullen, wordt niet verzonnen: de reeks
  begint erna. Wat er is aangevuld, staat in het verslag van de fit.
- **Dagwaarden.** Per filter worden alle dossiers (GLD) samengevoegd tot één
  reeks met het daggemiddelde in m NAP. Een beoordeelde meting gaat voor een
  voorlopige.
- **Kaart met Leaflet.** De kaartfiguren van Plotly tekenen hun punten niet in
  een pagina die als los bestand is geopend. De kaart is daarom Leaflet op de
  BRT-achtergrondkaart; de OpenStreetMap-tegels van v2 weigeren een lokaal
  bestand ook.

## Bekende grenzen

- **Opstarten duurt 15 tot 20 seconden**, elke keer.
- **Alleen het lineaire aanvullingsmodel.** Niet-lineaire modellen (FlexModel)
  zijn in de browser ongeveer negen keer zo traag, omdat de versneller numba
  daar niet bestaat. v2 biedt ze ook niet aan.
- **Het model kent alleen neerslag en verdamping.** Geen peilen, onttrekkingen
  of andere verklarende reeksen.
- **Eén rekenwerker.** "Fit alle geselecteerde" rekent de putten na elkaar,
  ongeveer een seconde per put. Meer werkers starten kost per stuk meer tijd
  dan het oplevert, tot een batch van tientallen putten.
- **Alleen BRO-putnummers.** Eigen meetreeksen (csv, Menyanthes), DINO-nummers
  en BRO Loket-exports kan v3 niet inlezen. Een store die met v2 is gemaakt
  wel.
- **De mappenkiezer zelf is niet automatisch getest**: die vraagt een
  muisklik. De test gebruikt hetzelfde soort map-object zonder het venster.
- **pastastore heeft een noodgreep nodig** (een nagemaakt slot uit
  `multiprocessing`, in `src\werker.js`). Bij een nieuwe pastastore-versie kan
  dat breken; de versies staan daarom vast in `bronnen.json`.
- **Twee mensen tegelijk in dezelfde map** schrijven over elkaar heen; er is
  geen vergrendeling.
- **Putnummers zoeken op de kaart** kan nog niet; die komen uit de
  gebiedsverkenner of het BRO-loket.
