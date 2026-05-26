# Prefect-pipeline (migratie van .bat)

**Status**: skeleton, nog niet in productie. `run_pipeline.bat` blijft de
draaiende orchestrator. Dit is de blauwdruk voor de overstap.

## Wanneer migreren

Wanneer aan minstens 2 van deze 3 voldaan is:
- Pipeline draait minstens 2 weken stabiel met huidige fixes (Sprint 1+2)
- Iemand anders dan jij gaat ook runs/logs bekijken (UI > log-bestanden)
- We willen schedules version-controlled (terug van Taakplanner naar code)

## Eerste keer opzetten

```powershell
# In je venv
pip install "prefect>=2.14"

# Server lokaal starten (eenmalig, draait in achtergrond)
prefect server start
# UI op http://127.0.0.1:4200

# Test eenmalig draaien (geen schedule)
python flows/pipeline.py
```

## Schedule-deployment (vervangt Taakplanner)

```powershell
# Deployment maken voor dagelijks 10:00
prefect deployment build flows/pipeline.py:ewaarnemingen_pipeline `
    --name "ewaarnemingen-daily" `
    --cron "0 10 * * *" `
    --timezone "Europe/Amsterdam"

prefect deployment apply ewaarnemingen_pipeline-deployment.yaml

# Worker starten (kan in een service-wrapper voor auto-restart)
prefect worker start --pool default
```

## Wat de .bat-pipeline NIET goed kan, en Prefect wel

| Vraag | .bat | Prefect |
|---|---|---|
| Welke runs van afgelopen week faalden? | grep door 7 log-bestanden | UI: filter op FAILED |
| Wat duurde elke stap? | Niet zichtbaar | Per-task duration in UI |
| Welke retries zijn er gedaan? | Niet zichtbaar | Per-attempt log |
| Stap 3 opnieuw zonder 1+2? | Aparte handmatige stap | Klik in UI |
| Slack-notificatie bij fout? | Eigen script schrijven | Built-in `notify_*` blocks |
| Schedule wijzigen | regedit / taskschd.msc | git commit op deployment yaml |
| Run-history > 30 dagen | Logs roteren weg | Prefect DB (SQLite/Postgres) |

## Wat we BEWUST behouden

- Python-scripts blijven scripts — Prefect roept ze aan via subprocess.
- `run_pipeline.bat` blijft tijdens transitie als fallback. Eerst parallel
  draaien (Prefect deployment + Taakplanner-job tegelijk, op verschillende
  tijdstippen), vergelijken, dan Taakplanner uitzetten.
- Geen herschrijving naar Prefect-native taken — dat zou de testbaarheid
  van de huidige scripts breken.

## Alternative path: Dagster

Dagster heeft betere DAG-visualisatie en asset-tracking. Voor onze
ingest→transform→serve flow is Prefect simpeler. Heroverwegen als we
veel meer datasets gaan beheren.
