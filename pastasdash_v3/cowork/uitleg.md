# PastasDash — uitleg voor collega's

Gebruik dit bestand om een collega door PastasDash te leiden en vragen te
beantwoorden. Het beschrijft wat de pagina kan, welke keuzes de collega maakt
en hoe de koppeling met de gebiedsverkenner werkt. Zeg niets wat hier niet
staat; weet je het niet, zeg dat dan.

## Wat PastasDash is

Eén HTML-bestand. Het rekent in de browser van de collega, met dezelfde
rekenkern als PastasDash op de desktop (PASTAS 2.0). Er hoeft niets
geïnstalleerd te worden; wel nodig: Edge of Chrome en internet.

## Wat je ermee kunt

| Weergave | Waarvoor | Nodig |
|---|---|---|
| Project | Projectmap kiezen, putten toevoegen of verwijderen, exporteren | — |
| Reeksen | Grondwaterstanden bekijken, over of onder elkaar, met neerslag en verdamping, en de ligging | Putten |
| Model | Een tijdreeksmodel fitten: hoeveel van de stijghoogte verklaren neerslag en verdamping | Putten met minstens 50 metingen |
| Vergelijken | Metingen en model van meerdere putten naast elkaar, met R² | Gefitte modellen |
| Statistiek | GHG, GLG, GVG, grondwatertrap, duurlijn, regimecurve; tabel als CSV | Minstens acht hydrologische jaren voor een GxG |
| Kaart | Putten gekleurd op R², verklaarde variantie, GxG of aantal metingen | Putten |
| Droogte | Cumulatief neerslagtekort per KNMI-station, tegen een referentieperiode | Niets: werkt zonder project |

Wat het **niet** kan: eigen meetreeksen inlezen (csv, Excel, Menyanthes),
DINO-nummers, peilen of onttrekkingen als verklarende reeks, niet-lineaire
modellen. Putten kiezen op de kaart doe je in de gebiedsverkenner (zie
hieronder).

## De keuzes die een collega maakt

**1. Waar het project staat.**

- *Projectmap* (aanbevolen): een map op OneDrive of in een gesynchroniseerde
  SharePoint-bibliotheek. Alles wat de collega doet, komt daar direct in te
  staan. Een andere collega opent dezelfde map en ziet hetzelfde, ook met
  PastasDash op de desktop. Kies per project één map; een lege map wordt een
  nieuw project. Twee mensen tegelijk in dezelfde map schrijven over elkaar
  heen.
- *Zonder map*: het werk staat alleen in het tabblad. Aan het eind
  *Exporteer als zip*, anders is het weg. Firefox en Safari kunnen alleen zo.

**2. Welke putten.** BRO-putnummers (`GMW` en twaalf cijfers), op drie
manieren: kiezen op de kaart in de gebiedsverkenner, de projectgrens aan
Cowork geven (dan worden alle putten erin opgezocht, eventueel met een marge
erbuiten), of zelf plakken. Van elke put
komen alle filters met metingen mee, als daggemiddelde in m NAP. Een put
zonder meetreeks in de BRO meldt de pagina; dat kan, veel putten hebben er
geen.

**3. Hoe het model eruitziet** (onder *Model*):

- *Responsfunctie*: hoe de grondwaterstand in de tijd op een regenbui
  reageert. **Gamma** is de standaard en past meestal. *Exponential* is
  eenvoudiger (snelle, gladde reactie); *DoubleExponential* en *Hantush*
  voor reeksen met een snelle én een trage component. Probeer bij twijfel
  Gamma en vergelijk.
- *Ruismodel*: laat aan. Het houdt rekening met het naijlen van de fouten
  en geeft eerlijkere onzekerheden.
- *Vanaf / Tot en met*: alleen invullen om een periode uit te sluiten,
  bijvoorbeeld van vóór een ingreep.
- *Fit alle geselecteerde*: rekent de putten na elkaar, ongeveer een seconde
  per put.

Neerslag en verdamping komen automatisch van het dichtstbijzijnde
KNMI-station; welk station, en of er dagen zijn aangevuld uit een
buurstation, staat in het verslag onder de knop.

**4. Hoe je het leest.**

- *R²* en *verklaarde variantie*: welk deel van het op en neer gaan het model
  verklaart. Laag in een peilgestuurde polder of bij een onttrekking is
  normaal: daar stuurt iets anders dan regen. Het model kent alleen neerslag
  en verdamping.
- *GxG*: volgens de standaardmethode (14e en 28e van de maand, hydrologisch
  jaar april–maart). De kolom *Jaren* zegt hoeveel jaren bruikbaar waren;
  onder de acht blijft de GxG leeg.
- *Grondwatertrap*: alleen als de maaiveldhoogte van de put in de BRO staat.
- *Ten opzichte van maaiveld*: zet de grafieken om naar meters onder maaiveld.

## De koppeling met de gebiedsverkenner

De gebiedsverkenner laat zien wélke putten er in en rond het projectgebied
staan; PastasDash analyseert hun meetreeksen.

**Eenmalig:** zet `pastasdash.html` in **dezelfde map** als de
gebiedsverkenner (bijvoorbeeld de projectmap op OneDrive). De knop in de
gebiedsverkenner zoekt PastasDash daar. Staat hij ergens anders, vul dan op het
tabblad *Putten* onder *Waar PastasDash staat* het pad in.

1. Open de gebiedsverkenner en ga naar het tabblad **Putten**.
2. Kies de peilbuizen, op een van drie manieren:
   - **Alle putten binnen de projectgrens**, eventueel met een marge in meters
     erbuiten;
   - **Gebied tekenen op de kaart**: klik de hoekpunten, dubbelklik om af te
     sluiten (Esc breekt af);
   - **Ctrl-klik** op losse peilbuizen (laag *BRO peilbuizen*, ingezoomd) om
     ze toe te voegen of weg te halen. Een gewone klik toont de gegevens van
     de put met een knop *Openen in PastasDash*.

   Gekozen putten krijgen een roze ring; de lijst staat op het tabblad.
3. **Openen in PastasDash**: PastasDash opent in een nieuw tabblad en haalt de
   metingen van de gekozen putten op.

Ook zonder gebiedsverkenner: geef Cowork de projectgrens, dan zoekt de skill de
putten erin op. Heeft Cowork geen internet, dan zoekt de pagina ze zelf zodra
de collega hem opent.

Putten op precies dezelfde plek (een putnest) liggen op de kaart over elkaar;
Ctrl-klik raakt dan alleen de bovenste. Teken er een gebiedje omheen om ze
allemaal te kiezen.

De gebiedsverkenner toont alleen putten die in de BRO staan. Meetnetten van
terreinbeheerders en waterschappen ontbreken vaak. Een verwijderde put
(gemarkeerd in de lijst) heeft vaak nog een lange oude meetreeks.

## Veelgestelde vragen

| Vraag | Antwoord |
|---|---|
| De pagina toont broncode of doet niets | Hij is in SharePoint of Teams geopend. Downloaden, of openen uit de met OneDrive gesynchroniseerde map |
| Het laden blijft hangen | Internet nodig; de eerste keer duurt het tot een halve minuut. Daarna opnieuw laden |
| "Heropen" vraagt om toestemming | Klopt: de browser vraagt na het herladen opnieuw of de pagina in de map mag schrijven |
| Kan ik verder op een andere computer? | Ja, via dezelfde projectmap op OneDrive, of via de zip |
| Kan ik het in Word of een rapport zetten? | Elke grafiek heeft rechtsboven een cameraknop (PNG); de statistiektabel kan als CSV |
| Klopt dit model? | Het model zegt hoeveel neerslag en verdamping verklaren, niet waarom de rest afwijkt. Dat is het oordeel van de ecohydroloog |
