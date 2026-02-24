# Handleiding: Pastas Hydro-Insight

Welkom bij **Pastas Hydro-Insight**, jouw nieuwe tool voor moderne tijdreeksanalyse van grondwater.

## Installatie
1. Navigeer naar de map: `C:\R_Data\Pastas-Hydro-Insight`
2. Installeer de benodigdheden:
   ```bash
   pip install -r requirements.txt
   ```
3. Start de applicatie:
   ```bash
   streamlit run app.py
   ```

## Gebruik

### 📥 Tab 1: Data Ingestie
- Voer een **BRO-ID** in (bijv. `B12C3456`) en klik op 'Haal BRO Data op'.
- Zodra de grondwaterstand is geladen, verschijnen de dichtstbijzijnde **KNMI-stations**.
- Kies een station en klik op 'Koppel Neerslag & Verdamping'. De meteo-data wordt automatisch afgehaald voor de periode van de metingen.

### 🧹 Tab 2: Data Cleaning
- Hier zie je de ruwe grondwaterstand.
- Gebruik de **Lasso** tool (icoontje rechtsboven de grafiek) om uitschieters of meetfouten te selecteren.
- Geselecteerde punten worden rood gemarkeerd en automatisch genegeerd door het computermodel.

### 📊 Tab 3: Dashboard
- Klik op **🚀 Voer Pastas Simulatie uit**.
- Bekijk de statistieken: **GHG** (overstromingsrisico), **GVG** (gemiddelde) en **GLG** (droogterisico).
- De **Decompositie** grafiek laat zien welk deel van de fluctuatie komt door regen en welk deel door verdamping (of andere factoren).
- Let op het 'stoplicht' voor de betrouwbaarheid van het model.

### 💾 Tab 4: Export
- Klik op **🚀 Maak Excel Export** om een compleet overzicht te downloaden voor je rapportage.

## Onderhoud & Support
De code is modulair opgebouwd in de map `modules/`. Fouten worden gelogd in de terminal waar Streamlit draait.
