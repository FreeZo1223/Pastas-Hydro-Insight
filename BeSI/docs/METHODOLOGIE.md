# Methodologie — BeSI Analyse Tool

## Databron

De analyses zijn gebaseerd op de **BeSI Kansenkaarten 2025** (Sierdsema et al. 2026, 
Sovon-rapport 2025/78), ontwikkeld door Sovon Vogelonderzoek Nederland in opdracht van BIJ12.

- **Resolutie**: 25 × 25 meter
- **Projectie**: EPSG:28992 (RD New)
- **Soorten**: 235 beschermde soorten (vogels, zoogdieren, reptielen, amfibieën, 
  vissen, insecten, vaatplanten, weekdieren)
- **Modelmethode**: Random Forest regressie op aanwezigheid/afwezigheid, gecombineerd 
  met ruimtelijke interpolatie van residuen
- **Maskers**: areaalmasker (bekende verspreiding) + habitatmasker (relevant habitattype)

De kansenkaarten geven een **kans op voorkomen** (0–1), geen bevestigd voorkomen. 
Ze zijn bedoeld als bureaustudie-instrument, niet als vervanging van veldonderzoek.

---

## Versie 1 — Soortenrijkdom

### Methode
Per 25×25m cel wordt het **aantal soorten boven de cutoffwaarde** geteld.

De cutoffwaarde per soort is ontleend aan bijlage 3 van het Sovon-rapport. Deze waarde 
is bepaald op basis van de True Skill Statistic (TSS) met een lichte correctie voor 
BeSI-gebruik: type I fouten (soort aanwezig, model zegt afwezig) worden sterker gewogen 
dan type II fouten (soort afwezig, model zegt aanwezig). Dit resulteert in een 
conservatieve drempel die de kans op het missen van aanwezige soorten minimaliseert.

**Formule:**
```
soortenrijkdom(cel) = Σ [kansscore(soort, cel) > cutoff(soort)]
```

### Output
- **Soortenrijkdomkaart**: integer raster, waarde = aantal verwachte soorten per cel
- **Prioriteringskaart**: 5 gelijke klassen op basis van soortenrijkdom binnen het gebied
- **Soortentabel**: lijst van alle soorten met aanwezigheid, oppervlakte en gemiddelde score

### Interpretatie
Cellen met hoge soortenrijkdom verdienen meer veldaandacht. De prioriteringskaart 
(klasse 5 = hoogste prioriteit) geeft aan waar de inspanning het meest efficiënt is.

---

## Versie 2 — Gewogen soortenrijkdom

### Methode
Identiek aan versie 1, maar elke soort krijgt een **ecologisch gewicht** op basis van 
beschermingsstatus voordat de som wordt berekend.

**Gewichtenlogica** (zie `config/settings.py` voor actuele waarden):
- Rode Lijst categorieën: CR=5, EN=4, VU=3, NT=2, LC/DD/NE=1
- Habitatrichtlijn Bijlage IV: +3 punt extra
- Habitatrichtlijn Bijlage II: +2 punt extra
- Beide bijlagen: +4 punt extra

**Formule:**
```
gewogen_rijkdom(cel) = Σ [aanwezig(soort, cel) × gewicht(soort)]
```

### Output
Alle outputs van versie 1, aangevuld met:
- **Gewogen rijkdomkaart**: float raster met gesommeerde gewichten per cel
- **Ecologische waardekaart**: 5 klassen op gewogen rijkdom

### Interpretatie
De gewogen kaart benadrukt gebieden waar zeldzame en zwaar beschermde soorten 
samenkomen, ook als de absolute soortenrijkdom daar niet het hoogst is. Dit is 
methodologisch robuuster voor het identificeren van ecologisch prioritaire zones.

---

## Beperkingen

1. **Modelonzekerheid**: de kansenkaarten zijn modellen, geen garanties. 
   Hoge kansscore ≠ soort is zeker aanwezig.

2. **Temporele dekking**: de modellen zijn gebaseerd op waarnemingen uit 
   verschillende perioden (2003–2024 afhankelijk van soortengroep). 
   Recentere populatieveranderingen kunnen niet weerspiegeld zijn.

3. **Areaalmasker**: buiten het bekende verspreidingsareaal geeft het model 
   altijd 0, ook als het habitat geschikt lijkt.

4. **Geen connectiviteitsanalyse**: de tool analyseert de inhoud van het 
   onderzoeksgebied, niet de ecologische samenhang met de omgeving.

5. **Zwartkop ontbreekt**: het bronbestand was corrupt bij verwerking 
   (zie walkthrough). Alle andere 235 soorten zijn beschikbaar.

---

## Referenties

Sierdsema, H., Kampichler, C & Gallego Zamorano, J. 2026. Toelichting kansenkaarten 
beschermde soorten 2025. Sovon-rapport 2025/78. Sovon Vogelonderzoek Nederland, Nijmegen.
