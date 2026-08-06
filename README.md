# Pastas-Hydro-Insight

Gereedschap voor ecohydrologen om grondwaterreeksen te analyseren met
[PASTAS](https://pastas.dev) — een lichtgewicht vervanging voor
Menyanthes/Hydromonitor.

## Het makkelijkst: dubbelklikken

Naast deze repo staan twee startbestanden, ook op de J-schijf:

| Bestand | Wat het start |
|---|---|
| `Start PastasDash v2.cmd` | Het dashboard (aanbevolen), poort 8051 |
| `Start PastasDash v1.cmd` | De oorspronkelijke versie, poort 8050 |

Dubbelklikken is genoeg. Ze halen de software zelf op naar
`%LOCALAPPDATA%\PastasDash`, werken hem bij bij elke start, en openen de
browser zodra het dashboard klaar is. Je hebt alleen `uv` en `git` nodig; het
venster zegt het als er iets ontbreekt, met het commando erbij.

De eerste start duurt een paar minuten — Python, de pakketten en de eerste
virusscan. Daarna is het een kwestie van seconden. Laat het zwarte venster
openstaan zolang je het dashboard gebruikt; sluiten stopt het.

Beide kunnen tegelijk aan staan; ze gebruiken dezelfde kopie van de software en
verschillende poorten.

## Zelf starten vanaf de opdrachtregel

Je hebt alleen [uv](https://docs.astral.sh/uv/) nodig; die regelt Python en
alle pakketten zelf. Een GitHub-account is niet nodig: deze repo is openbaar en
alle afhankelijkheden komen van PyPI.

```powershell
git clone https://github.com/FreeZo1223/Pastas-Hydro-Insight.git
cd Pastas-Hydro-Insight
```

## Wat wil je draaien?

De twee commando's hieronder start je allebei **vanuit de map
`Pastas-Hydro-Insight`** (waar je na het klonen staat). Wil je na v2 ook v1
starten, open dan een tweede venster — of ga eerst met `cd ..` terug.

### PastasDash v2 — het dashboard (aanbevolen)

Peilbuizen kiezen, reeksen bekijken, modellen fitten en GxG/grondwatertrap
aflezen.

```powershell
cd pastasdash_v2
uv run python -m pastasdash_v2
```

Open daarna <http://127.0.0.1:8051>. De eerste keer duurt even omdat uv Python
en de pakketten ophaalt. Volledige uitleg staat in
[`pastasdash_v2/README.md`](pastasdash_v2/README.md).

### PastasDash v1 — de oorspronkelijke Dash-versie

De upstream [`pastas/pastasdash`](https://github.com/pastas/pastasdash) met een
extra Droogte-tab. Nog in gebruik bij collega's; blijft beschikbaar zolang v2
niet alles overneemt wat hier fijner werkte.

```powershell
cd pastasdash
uv run python -m pastasdash
```

Draait op <http://127.0.0.1:8050>, dus v1 en v2 kunnen tegelijk aan staan.

## Waarom `python -m` en niet gewoon `uv run pastasdash-v2`?

Die kortere vorm bestaat ook en doet hetzelfde, maar hij start een `.exe` die
uv net zelf heeft aangemaakt. Een strenge virusscanner blokkeert dat:

```
error: Failed to spawn: `pastasdash-v2`
  Caused by: Toegang geweigerd. (os error 5)
```

Dat treft juist de eerste start ná het klonen. Met `python -m` komt er geen
nieuw uitvoerbaar bestand aan te pas en werkt het wel — op dezelfde machine, in
dezelfde omgeving, getest. Gebruik daarom `python -m`; als de korte vorm bij
jou werkt, is die net zo goed.

## Bijwerken

```powershell
git pull
```

Daarna opnieuw starten; uv installeert gewijzigde pakketten zelf.

## Werkt er iets niet?

Meld een fout met: **wat je deed**, **wat je verwachtte**, en de **volledige
foutmelding** uit het venster (niet alleen de laatste regel). Zonder die tekst
is een fout meestal niet te vinden zonder eerst te raden.

## Verder in deze repo

| Map | Inhoud |
|---|---|
| `pastasdash_v2/` | Het dashboard (NiceGUI). Zelfstandig, met eigen `uv.lock`. |
| `pastasdash/` | De oorspronkelijke Dash-versie. |
| `pastas_adapter/` | Gedeelde adapter tussen PASTAS/PastaStore en de rest. |
| `notebooks/` | Uitleg-notebooks: van ruwe peilbuisdata naar een model. |
| `Mantel_Test/`, `data/`, `scripts/`, `output/` | Voorbeelddata en hulpscripts. |

### De voorbeelddataset

De notebooks en scripts draaien op één peilbuis bij Axel (Zeeland):

| Eigenschap | Waarde |
|---|---|
| DINO-ID | B42C0133 |
| BRO-ID | GMW000000069526 |
| Locatie | 3,537° O, 51,578° N |
| Periode | 1995–2004 (~230 metingen per filter) |
| Filters | 001 (ondiep), 002 (dieper) |
| Referentie | NAP (m) |
| KNMI-station | Terneuzen (nr. 742) |

> De neerslag- en verdampingsreeksen in `data/knmi/` zijn **gesimuleerd** — ze
> zijn ooit gemaakt toen de KNMI-API offline was. Gebruik ze om de werkwijze te
> leren, niet voor uitspraken over een gebied. Echte data haal je op met
> `scripts/haal_knmi_data.py`.

Notebooks in volgorde: `01_data_verkenning.ipynb` (data inladen en bekijken),
daarna `02_pastas_model.ipynb` (model bouwen, kalibreren, GVG/GHG/GLG).

## Herkomst

Dit was ooit een volledige workspace-snapshot (inclusief `geo_stack`, `BeSI`,
`lesa-agent-v2` en `ArcGIS_online`). Die projecten leven inmiddels in hun eigen
repo's; hier staat alleen nog de PASTAS-gereedschapskist.
