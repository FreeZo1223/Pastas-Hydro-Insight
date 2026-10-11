---
name: eelerwoude-pastasdash
description: |
  Zet PastasDash klaar voor een project: één HTML-bestand waarmee een
  ecohydroloog peilbuisreeksen uit de BRO bekijkt, tijdreeksmodellen (PASTAS)
  fit en GxG, grondwatertrap, duurlijn en neerslagtekort afleest. De pagina
  rekent zelf, in de browser van de collega; de skill zet alleen de projectnaam
  en de BRO-putnummers erin.
  Use when the user asks to "maak een PastasDash", "analyseer deze peilbuizen",
  "tijdreeksanalyse voor project X", "GxG / GHG / GLG van deze putten", "fit
  een PASTAS-model", "vervanger voor Menyanthes", "neerslagtekort bekijken", of
  BRO-putnummers (GMW…) noemt of een lijst met putnummers uploadt.
  Do NOT use voor kaartjes van het gebied (gebruik eelerwoude-gebiedsverkenner),
  voor eigen lagen tonen (eelerwoude-kaart), of om zelf een GxG, een model of
  een conclusie over het grondwatersysteem te geven: dat doet de pagina, en de
  duiding is het werk van de ecohydroloog.
license: MIT
metadata:
  category: analysis
  icon: LineChart
---

# Eelerwoude PastasDash

Deze skill levert **één HTML-bestand** af. De collega opent het in Edge of
Chrome; de pagina haalt de metingen uit de BRO, neerslag en verdamping van het
KNMI, en rekent de modellen en statistieken uit.

## Wat de skill wél en niet doet

- **Wel:** de projectnaam en de BRO-putnummers in het bestand zetten, zodat de
  pagina bij openen meteen die putten ophaalt.
- **Niet:** metingen ophalen, modellen fitten of statistieken berekenen. **Je
  hebt geen enkele meetreeks gezien.** Zeg dus nooit iets over standen, GxG,
  grondwatertrap, trend of modelkwaliteit.

## Tools

| Stap | Tool |
|---|---|
| Lijst met putnummers zoeken | `Glob` (`input/**/*`) |
| Bestand bouwen | `Bash` (`python scripts/maak_pastasdash.py …`) |
| Opleveren | `CopyArtifact(surface="output", …)` |
| Alleen bij echte twijfel | `AskUserQuestion` |

## Workflow

### 1. Verzamel de putnummers

Een BRO-putnummer begint met `GMW` en heeft twaalf cijfers
(`GMW000000069526`). Neem ze over uit de vraag, of uit een geüpload tekst- of
csv-bestand. Noemt de collega geen putnummers, maak dan een bestand **zonder**
putten: in de pagina kan de collega ze zelf plakken.

Verzin geen putnummers en zoek ze niet zelf op. De putnummers van een gebied
vindt de collega in de gebiedsverkenner (laag *Peilbuizen*) of in het BRO-loket.

### 2. Maak het bestand

```bash
python scripts/maak_pastasdash.py --out working/PastasDash_<project>.html \
    --titel "<projectnaam>" --putten GMW000000069526 GMW000000012345
```

Met een bestand: `--putten-bestand input/<bestand>` (alle putnummers die erin
voorkomen worden gebruikt). Beide opties mogen samen. Bouw altijd naar
`working/`; `output/` is alleen-lezen.

### 3. Lees de samenvatting

Het script drukt JSON af.

| Veld | Waar op letten |
|---|---|
| `ok: false` + `melding` | Het bestand is **niet** gemaakt. Geef de melding in gewone taal door |
| `waarschuwingen` | **Letterlijk** doorgeven: niet-herkende nummers, of meer putten dan er klaargezet zijn |
| `aantal_putten` | Noem dit aantal; het zijn nummers, geen gecontroleerde putten |
| `metingen_opgehaald`, `modellen_gemaakt` | Altijd `false`: jij hebt niets opgehaald en niets berekend |

### 4. Lever op

Publiceer met `CopyArtifact(surface="output", …)` en controleer met
`Glob output/**/*` dat het bestand er staat voordat je "klaar" zegt.

## Output Format

Precies één `.html` in `output/`. Antwoord kort en in het Nederlands:

1. de bestandsnaam;
2. hoeveel putnummers erin staan, en eventuele waarschuwingen, letterlijk;
3. het gebruik in vier regels:
   - **downloaden** en openen in Edge of Chrome (rechtstreeks openen vanuit
     SharePoint of Teams werkt niet); het laden duurt ongeveer een kwart minuut
     en heeft internet nodig;
   - onder *Project* een **projectmap kiezen** (bijvoorbeeld op OneDrive): daar
     komen de reeksen en modellen te staan, en een collega kan dezelfde map
     openen;
   - links de peilbuizen kiezen; de weergaven *Reeksen*, *Model*,
     *Vergelijken*, *Statistiek*, *Kaart* en *Droogte* volgen die keuze;
   - zonder projectmap staat het werk alleen in het tabblad: dan aan het eind
     **Exporteer als zip**.

Noem geen scriptnamen, paden of technische foutmeldingen.

## Guardrails

- **Never fabricate.** Geen putnummers, projectnaam of uitkomsten verzinnen.
  Wat je niet weet, laat je weg.
- **Never describe wat je niet hebt gezien.** Geen uitspraak over
  grondwaterstanden, GxG, grondwatertrap of de kwaliteit van een model. Het
  script zegt zelf `"metingen_opgehaald": false`.
- **Never duiden.** Wat een reeks of een model betekent voor het systeem
  (kwel, verdroging, effect van een maatregel) is het werk van de ecohydroloog.
- **Een putnummer is geen put met metingen.** Sommige putten hebben in de BRO
  geen meetreeks; de pagina meldt dat per put. Beloof dus niet dat elke put een
  grafiek oplevert.
- **Het model gebruikt alleen neerslag en verdamping.** In een peilgestuurd
  gebied of bij een onttrekking verklaart dat de standen maar ten dele; de
  pagina toont de verklaarde variantie. Zeg dit erbij als de collega vraagt of
  het model "klopt".
- **Dagwaarden.** De pagina bewaart per filter het daggemiddelde in m NAP.
- **Internet nodig.** Zonder verbinding start de pagina niet.
- **Alleen Edge en Chrome** kunnen in een projectmap schrijven. In Firefox en
  Safari werkt de pagina met zip-bestanden.

## Randgevallen

| Situatie | Doe dit |
|---|---|
| Geen putnummers genoemd | Maak het bestand zonder putten; zeg dat de collega ze in de pagina kan plakken |
| Alleen een gebied of plaatsnaam | Idem; verwijs naar de gebiedsverkenner om de putnummers te vinden |
| DINO-nummers (B42C0133) of eigen putcodes | Die kent de pagina niet; vraag om de BRO-putnummers (GMW…) |
| Eigen meetreeksen (csv, Excel, Menyanthes-bestand) | Kan deze pagina nog niet inlezen; meld dat |
| Collega heeft al een projectmap van PastasDash | Geen nieuw bestand nodig: dezelfde pagina opent die map |
| Collega vraagt om de GxG of een modeluitkomst in het antwoord | Zeg dat de pagina die berekent en toont, en dat jij ze niet hebt gezien |
| Script eindigt met een fout | Probeer één keer opnieuw; blijft het misgaan, meld in gewone taal dat het bestand niet gemaakt kon worden |
