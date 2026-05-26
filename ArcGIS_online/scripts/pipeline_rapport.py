"""
Pipeline Rapport & Notificaties — Ewaarnemingen
================================================
Genereert wekelijks HTML-rapport met:
  - Record-delta per tabel (nieuw t.o.v. vorige run)
  - Datumkwaliteitscheck (datum%)
  - Actiepunten: HTTP-fouten, stagnerende lagen, record-dalingen
  - Windows toast-notificatie bij fouten of succes
  - Optioneel e-mailrapport (SMTP_HOST instellen in .env)

Gebruik (wordt aangeroepen vanuit run_pipeline.bat):
    python pipeline_rapport.py --agol-exit 0 --gpkg-exit 0 --j-beschikbaar 1 --logbestand pad/naar/pipeline.log
"""

import argparse
import duckdb
import json
import os
import re
import subprocess
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
_SCRIPT_DIR  = Path(__file__).parent
_PROJECT_DIR = _SCRIPT_DIR.parent

load_dotenv(_PROJECT_DIR / ".env")

DUCKDB_PAD     = _PROJECT_DIR / "Databeheer" / "00_kern" / "ewaarnemingen.duckdb"
STATUS_PAD     = _PROJECT_DIR / "Databeheer" / "00_kern" / "pipeline_status.json"
RAPPORT_LOKAAL = _PROJECT_DIR / "Databeheer" / "03_logs" / "rapport_wekelijks.html"
RAPPORT_J      = Path(r"J:\Databeheer\Ewaarnemingen_databeheer\rapport_wekelijks.html")

# E-mail instellingen (optioneel — laat leeg om e-mail over te slaan)
SMTP_HOST  = os.getenv("SMTP_HOST", "")
SMTP_PORT  = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER  = os.getenv("SMTP_USER", "")
SMTP_PASS  = os.getenv("SMTP_PASS", "")
EMAIL_VAN  = os.getenv("EMAIL_VAN", "")
EMAIL_NAAR = os.getenv("EMAIL_NAAR", "")

# Drempelwaarden
DREMPEL_DATUM_PCT  = 50.0   # Datum% onder deze waarde krijgt rode cel
DREMPEL_DALING_PCT = 5.0    # Waarschuw als datum% >5% daalt t.o.v. vorige run

# Stagnatie: laag zonder nieuwe records waarvan de recentste meting ouder is dan dit
STAGNATION_DAYS = 30

# Lagen die worden uitgesloten van het rapport (worden niet structureel ingevoerd)
EXCLUDE_FROM_REPORT = [
    "waarnemingen_baarn_vleermuizen",
    "waarnemingen_baarn_vogels",
]


# ─────────────────────────────────────────────
# LOG PARSING — PER-LAAG STATUS
# ─────────────────────────────────────────────

def parse_log_laagstatus(logbestand: str) -> dict:
    """Parse pipeline-log voor per-laag AGOL fetch status.

    Geeft dict terug met:
      geslaagd: lijst laagnamen die ✅ kregen
      gefaald:  lijst (laagnaam, foutcode) tuples
    """
    resultaat = {"geslaagd": [], "gefaald": []}
    if not logbestand:
        return resultaat
    pad = Path(logbestand)
    if not pad.exists():
        return resultaat
    tekst = pad.read_text(encoding="utf-8", errors="replace")
    for regel in tekst.splitlines():
        m = re.search(r'✅\s+(\S+):\s+\d+\s+records', regel)
        if m:
            resultaat["geslaagd"].append(m.group(1))
            continue
        m = re.search(r'❌\s+(\S+):\s+ophalen gestopt.*?:\s+(.+)', regel)
        if m:
            naam = m.group(1)
            fout = m.group(2)[:120]
            ft   = re.search(r'(\d{3})\s+\w+\s+Error', fout)
            kort = f"HTTP {ft.group(1)}" if ft else fout[:60]
            resultaat["gefaald"].append((naam, kort))
    return resultaat


# ─────────────────────────────────────────────
# DUCKDB STATISTIEKEN
# ─────────────────────────────────────────────

def haal_statistieken() -> dict:
    """Lees record-aantallen en datum-kwaliteit uit DuckDB."""
    stats = {}
    try:
        con = duckdb.connect(str(DUCKDB_PAD), read_only=True)
        tabellen = [r[0] for r in con.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name LIKE 'waarnemingen_%'
            ORDER BY table_name
        """).fetchall()]

        for t in tabellen:
            cols        = [r[1] for r in con.execute(f"PRAGMA table_info('{t}')").fetchall()]
            n           = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            datum_pct   = None
            recent_datum = None

            if "datum_beste" in cols:
                datum_pct = con.execute(
                    f"SELECT ROUND(100.0*COUNT(datum_beste)/COUNT(1),1) FROM {t}"
                ).fetchone()[0]
                recent_datum = str(con.execute(
                    f"SELECT MAX(datum_beste) FROM {t}"
                ).fetchone()[0])

            stats[t] = {
                "records":      n,
                "datum_pct":    datum_pct,
                "recent_datum": recent_datum,
            }
        con.close()
    except Exception as e:
        print(f"Fout bij DuckDB lezen: {e}")
    return stats


# ─────────────────────────────────────────────
# VORIGE RUN LADEN / OPSLAAN
# ─────────────────────────────────────────────

def laad_vorige_status() -> dict:
    if STATUS_PAD.exists():
        try:
            return json.loads(STATUS_PAD.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def sla_status_op(run_ts: str, stats: dict, pipeline_ok: bool):
    status = {
        "run_timestamp": run_ts,
        "pipeline_ok":   pipeline_ok,
        "tabellen":      stats,
    }
    STATUS_PAD.write_text(json.dumps(status, indent=2, default=str), encoding="utf-8")


# ─────────────────────────────────────────────
# ACTIEPUNTEN DETECTIE
# ─────────────────────────────────────────────

def detecteer_actiepunten(
    stats: dict, vorige: dict, run_date: date,
    agol_exit: int, gpkg_exit: int,
    laagstatus: dict,
) -> list:
    """Geeft lijst van actiepunten terug (excl. J:-sync).

    Elk item: {"ernst", "tag", "laag", "toelichting"}
    """
    actiepunten = []
    laagstatus  = laagstatus or {"geslaagd": [], "gefaald": []}
    vorige_tab  = vorige.get("tabellen", {})
    n_ok        = len(laagstatus["geslaagd"])
    n_fout      = len(laagstatus["gefaald"])

    # ── AGOL fetch fouten ──────────────────────
    if agol_exit != 0:
        if n_ok == 0:
            actiepunten.append({
                "ernst":      "KRITIEK",
                "tag":        "Pipeline fout",
                "laag":       "AGOL → DuckDB",
                "toelichting": (
                    f"Pipeline volledig gefaald (exit {agol_exit}). "
                    "Mogelijk AGOL onbereikbaar of credentials verlopen."
                ),
            })
        else:
            for naam, kort in laagstatus["gefaald"]:
                actiepunten.append({
                    "ernst":      "WAARSCHUWING",
                    "tag":        kort,
                    "laag":       naam,
                    "toelichting": "Niet opgehaald — laagnaam of service mogelijk gewijzigd in AGOL.",
                })

    # ── GeoPackage export fout ─────────────────
    if gpkg_exit != 0:
        actiepunten.append({
            "ernst":      "WAARSCHUWING",
            "tag":        "Export fout",
            "laag":       "GeoPackage export",
            "toelichting": f"Export gefaald (exit {gpkg_exit}). QGIS-bestanden zijn mogelijk verouderd.",
        })

    # ── Per-laag checks ────────────────────────
    for tabel, huidig in stats.items():
        if tabel in EXCLUDE_FROM_REPORT:
            continue

        prev   = vorige_tab.get(tabel, {})
        prev_n = prev.get("records", 0)
        curr_n = huidig["records"]
        naam   = tabel.replace("waarnemingen_", "").replace("_", " ").title()

        # Record daling (>5%)
        if prev_n > 0 and curr_n < prev_n * 0.95:
            actiepunten.append({
                "ernst":      "KRITIEK",
                "tag":        "Record daling",
                "laag":       naam,
                "toelichting": (
                    f"Records gedaald van {prev_n:,} naar {curr_n:,} "
                    f"({prev_n - curr_n:,} minder). "
                    "Mogelijk laagnaam of structuur veranderd in AGOL."
                ),
            })

        # Stagnatie: geen nieuwe records én recentste datum te oud
        delta            = curr_n - prev_n
        recent_datum_str = huidig.get("recent_datum") or ""
        if delta == 0 and prev_n > 0 and recent_datum_str not in ("", "None", "none"):
            try:
                recent_d = date.fromisoformat(str(recent_datum_str)[:10])
                ouderdom = (run_date - recent_d).days
                if ouderdom > STAGNATION_DAYS:
                    actiepunten.append({
                        "ernst":      "WAARSCHUWING",
                        "tag":        "Stagnatie",
                        "laag":       naam,
                        "toelichting": (
                            f"Geen nieuwe records, recentste meting {recent_datum_str[:10]} "
                            f"({ouderdom} dagen geleden)."
                        ),
                    })
            except (ValueError, TypeError):
                pass

        # Datum-kwaliteitsdaling t.o.v. vorige run
        curr_d = huidig.get("datum_pct")
        prev_d = prev.get("datum_pct")
        if curr_d is not None and prev_d is not None and prev_d - curr_d > DREMPEL_DALING_PCT:
            actiepunten.append({
                "ernst":      "WAARSCHUWING",
                "tag":        "Datumkwaliteit",
                "laag":       naam,
                "toelichting": f"Datum%-kwaliteit gedaald van {prev_d}% naar {curr_d}%.",
            })

    return actiepunten


# ─────────────────────────────────────────────
# HTML RAPPORT
# ─────────────────────────────────────────────

def _fmt_datum_pct(val) -> str:
    if val is None:
        return "<td style='color:#bbb'>—</td>"
    stijl = "color:#d93025;font-weight:bold" if val < DREMPEL_DATUM_PCT else "color:#555"
    return f"<td style='{stijl}'>{val}%</td>"


def genereer_html(
    run_ts: str, stats: dict, vorige: dict,
    actiepunten: list, agol_exit: int, gpkg_exit: int,
    j_beschikbaar: bool, logbestand: str,
    laagstatus: dict, run_date: date,
) -> str:
    vorige_ts  = vorige.get("run_timestamp", "—")
    vorige_tab = vorige.get("tabellen", {})

    # ── Badge logica ───────────────────────────
    n_kritiek    = sum(1 for a in actiepunten if a["ernst"] == "KRITIEK")
    n_actie      = len(actiepunten)
    n_ok_lagen   = len(laagstatus["geslaagd"])
    gedeeltelijk = agol_exit != 0 and n_ok_lagen > 0

    if n_kritiek > 0:
        badge_kleur = "#d93025"
        badge_tekst = "FOUTEN"
    elif n_actie > 0 or gedeeltelijk:
        badge_kleur = "#f57c00"
        badge_tekst = "GEDEELTELIJK"
    else:
        badge_kleur = "#1e8e3e"
        badge_tekst = "GESLAAGD"

    # ── Stapstatus ─────────────────────────────
    n_fout_lagen = len(laagstatus["gefaald"])
    if agol_exit == 0:
        stap1 = "✅ Geslaagd"
    elif n_ok_lagen > 0:
        namen = ", ".join(n for n, _ in laagstatus["gefaald"])
        stap1 = (
            f"⚠️ Gedeeltelijk ({n_ok_lagen}/{n_ok_lagen + n_fout_lagen} lagen geslaagd)"
            f" — gefaald: {namen}"
        )
    else:
        stap1 = f"❌ Mislukt (exit {agol_exit})"

    stap2 = "✅ Geslaagd" if gpkg_exit == 0 else f"⚠️ Mislukt (exit {gpkg_exit})"
    stap3 = "✅ Geslaagd" if j_beschikbaar else "⚠️ Overgeslagen (J: onbereikbaar)"

    # ── Actiepunten-tabel ──────────────────────
    kleur_map = {"KRITIEK": "#d93025", "WAARSCHUWING": "#f57c00"}
    if actiepunten:
        rijen = ""
        for a in actiepunten:
            c = kleur_map.get(a["ernst"], "#555")
            rijen += (
                f"<tr>"
                f"<td><strong style='color:{c}'>{a['ernst']}</strong></td>"
                f"<td style='white-space:nowrap'>{a['laag']}</td>"
                f"<td style='color:#555;font-size:12px'>"
                f"<span style='background:#f1f3f4;padding:2px 6px;border-radius:3px;"
                f"font-size:11px;margin-right:6px'>{a['tag']}</span>"
                f"{a['toelichting']}</td>"
                f"</tr>\n"
            )
        actiepunten_html = (
            "<table>\n"
            "<tr><th>Ernst</th><th>Laag / onderdeel</th><th>Toelichting</th></tr>\n"
            f"{rijen}</table>\n"
        )
    else:
        actiepunten_html = "<p style='color:#1e8e3e;font-weight:bold'>Geen actiepunten.</p>"

    j_melding = ""
    if not j_beschikbaar:
        j_melding = (
            "<p style='font-size:12px;color:#f57c00;margin-top:6px'>"
            "⚠️ J:-sync overgeslagen — J:-schijf was niet bereikbaar. "
            "Collega's werken met verouderde data.</p>"
        )

    # ── Stagnerende lagen (voor oranje naam in tabel) ──
    stagnerende = {
        a["laag"] for a in actiepunten if a["tag"] == "Stagnatie"
    }

    # ── Lagenrijen ─────────────────────────────
    stats_gefilterd = {
        t: v for t, v in stats.items()
        if t not in EXCLUDE_FROM_REPORT
    }
    totaal_huidig = sum(v["records"] for v in stats_gefilterd.values())
    totaal_vorig  = sum(
        vorige_tab.get(t, {}).get("records", 0)
        for t in stats_gefilterd
    )
    totaal_delta  = totaal_huidig - totaal_vorig

    laag_rijen = ""
    for t, h in sorted(stats_gefilterd.items()):
        naam   = t.replace("waarnemingen_", "").replace("_", " ").title()
        prev_n = vorige_tab.get(t, {}).get("records", 0)
        delta  = h["records"] - prev_n

        if delta > 0:
            delta_str  = f"+{delta:,}"
            delta_stijl = "color:#1e8e3e;font-weight:bold"
        elif delta < 0:
            delta_str  = f"{delta:,}"
            delta_stijl = "color:#d93025;font-weight:bold"
        else:
            delta_str  = "—"
            delta_stijl = "color:#bbb"

        naam_stijl = "color:#f57c00;font-weight:bold" if naam in stagnerende else ""
        naam_cel   = f"<td style='{naam_stijl}'>{naam}</td>" if naam_stijl else f"<td>{naam}</td>"

        recent = (h.get("recent_datum") or "—")[:10]
        if recent in ("None", "none"):
            recent = "—"

        laag_rijen += (
            f"<tr>"
            f"{naam_cel}"
            f"<td style='text-align:right'>{h['records']:,}</td>"
            f"<td style='text-align:right;{delta_stijl}'>{delta_str}</td>"
            f"{_fmt_datum_pct(h.get('datum_pct'))}"
            f"<td style='font-size:11px;color:#555'>{recent}</td>"
            f"</tr>\n"
        )

    delta_prefix = "+" if totaal_delta >= 0 else ""

    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<title>Ewaarnemingen Pipeline Rapport {run_ts[:10]}</title>
<style>
  body  {{ font-family: Segoe UI, Arial, sans-serif; max-width: 960px; margin: 40px auto; color: #202124; }}
  h1   {{ color: {badge_kleur}; }}
  h2   {{ margin-top: 28px; border-bottom: 1px solid #e8eaed; padding-bottom: 4px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th   {{ background: #f1f3f4; text-align: left; padding: 8px; border-bottom: 2px solid #dadce0; }}
  td   {{ padding: 6px 8px; border-bottom: 1px solid #e8eaed; }}
  .badge {{ display:inline-block; padding:4px 10px; border-radius:4px;
            background:{badge_kleur}; color:white; font-weight:bold; font-size:14px; }}
  .meta  {{ color: #555; font-size: 13px; margin-bottom: 20px; }}
</style>
</head>
<body>
<h1>Ewaarnemingen Pipeline Rapport</h1>
<p class="meta">
  Run: <strong>{run_ts}</strong> &nbsp;|&nbsp;
  Vorige run: {vorige_ts} &nbsp;|&nbsp;
  Status: <span class="badge">{badge_tekst}</span>
</p>

<h2>Stapstatus</h2>
<ul>
  <li>Stap 1 AGOL→DuckDB: {stap1}</li>
  <li>Stap 2 GeoPackage export: {stap2}</li>
  <li>Stap 3 J:-sync: {stap3}</li>
</ul>

<h2>Actiepunten</h2>
{actiepunten_html}
{j_melding}

<h2>Records per laag</h2>
<p style="color:#555;font-size:13px">
  Totaal: <strong>{totaal_huidig:,}</strong> records
  ({delta_prefix}{totaal_delta:,} t.o.v. vorige run)
</p>
<table>
<tr>
  <th>Laag</th>
  <th style="text-align:right">Huidig</th>
  <th style="text-align:right">Delta</th>
  <th>Datum%</th>
  <th>Recentste datum</th>
</tr>
{laag_rijen}
</table>

<p style="margin-top:40px;font-size:11px;color:#999">
  Logbestand: {logbestand}<br>
  Gegenereerd door pipeline_rapport.py — {run_ts}
</p>
</body>
</html>"""


# ─────────────────────────────────────────────
# NOTIFICATIES
# ─────────────────────────────────────────────

def stuur_toast(titel: str, bericht: str, type_: str = "info"):
    """Windows toast-notificatie via PowerShell (werkt alleen als gebruiker is ingelogd)."""
    ps = (
        f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null;"
        f"$template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02;"
        f"$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template);"
        f"$xml.GetElementsByTagName('text')[0].AppendChild($xml.CreateTextNode('{titel}')) | Out-Null;"
        f"$xml.GetElementsByTagName('text')[1].AppendChild($xml.CreateTextNode('{bericht}')) | Out-Null;"
        f"$toast = [Windows.UI.Notifications.ToastNotification]::new($xml);"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Ewaarnemingen Pipeline').Show($toast);"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=10)
    except Exception as e:
        print(f"Toast mislukt: {e}")


def stuur_email(onderwerp: str, html_body: str):
    """Stuur e-mailrapport via SMTP als SMTP_HOST geconfigureerd is."""
    if not SMTP_HOST or not EMAIL_NAAR:
        return
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = onderwerp
        msg["From"]    = EMAIL_VAN or SMTP_USER
        msg["To"]      = EMAIL_NAAR
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            if SMTP_USER and SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(msg["From"], EMAIL_NAAR.split(","), msg.as_string())
        print(f"E-mail verzonden naar {EMAIL_NAAR}")
    except Exception as e:
        print(f"E-mail mislukt: {e}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agol-exit",     type=int, default=0)
    parser.add_argument("--gpkg-exit",     type=int, default=0)
    parser.add_argument("--postgis-exit",  type=int, default=0,
                        help="Exit code van duckdb_naar_postgis.py (0 = OK).")
    parser.add_argument("--snapshot-exit", type=int, default=0,
                        help="Exit code van snapshot.py (0 = OK).")
    parser.add_argument("--j-beschikbaar", type=int, default=1)
    parser.add_argument("--logbestand",    type=str, default="")
    args = parser.parse_args()

    run_ts      = datetime.now().strftime("%Y-%m-%d %H:%M")
    run_date    = datetime.now().date()
    j_ok        = bool(args.j_beschikbaar)
    pipeline_ok = args.agol_exit == 0

    print(f"\n=== Rapport genereren: {run_ts} ===")

    # Stats altijd vanuit DuckDB ophalen, ongeacht agol_exit
    stats      = haal_statistieken()
    vorige     = laad_vorige_status()
    laagstatus = parse_log_laagstatus(args.logbestand)

    # Actiepunten detecteren
    actiepunten = detecteer_actiepunten(
        stats, vorige, run_date,
        args.agol_exit, args.gpkg_exit,
        laagstatus,
    )

    # PostGIS- en snapshot-fouten als extra actiepunten (backward-compatible).
    # Op exit-code-niveau ipv log-parsing → robuust tegen output-formaat-wijzigingen.
    if args.postgis_exit != 0:
        actiepunten.append({
            "ernst": "KRITIEK", "tag": "POSTGIS",
            "laag": "duckdb_naar_postgis",
            "toelichting": f"Export naar PostGIS faalde (exit {args.postgis_exit}). "
                           f"QGIS-gebruikers zien verouderde data.",
        })
    if args.snapshot_exit != 0:
        actiepunten.append({
            "ernst": "KRITIEK", "tag": "SNAPSHOT",
            "laag": "snapshot",
            "toelichting": f"Snapshot-stap faalde (exit {args.snapshot_exit}). "
                           f"Backup van vandaag ontbreekt — onderzoek logs.",
        })

    n_kritiek = sum(1 for a in actiepunten if a["ernst"] == "KRITIEK")
    n_actie   = len(actiepunten)

    # HTML genereren
    html = genereer_html(
        run_ts, stats, vorige, actiepunten,
        args.agol_exit, args.gpkg_exit, j_ok,
        args.logbestand, laagstatus, run_date,
    )

    # Lokaal opslaan
    RAPPORT_LOKAAL.parent.mkdir(parents=True, exist_ok=True)
    RAPPORT_LOKAAL.write_text(html, encoding="utf-8")
    print(f"Rapport opgeslagen: {RAPPORT_LOKAAL}")

    # Op J: opslaan (als bereikbaar)
    if j_ok:
        try:
            RAPPORT_J.parent.mkdir(parents=True, exist_ok=True)
            RAPPORT_J.write_text(html, encoding="utf-8")
            print(f"Rapport opgeslagen: {RAPPORT_J}")
        except Exception as e:
            print(f"Rapport op J: mislukt: {e}")

    # Actiepunten afdrukken
    if actiepunten:
        print(f"\nGevonden: {n_kritiek} kritiek, {n_actie - n_kritiek} waarschuwingen")
        for a in actiepunten:
            print(f"  [{a['ernst']}] {a['laag']} — {a['toelichting']}")

    # Status opslaan voor volgende run
    if stats:
        sla_status_op(run_ts, stats, pipeline_ok)

    # Toast notificatie
    totaal_nieuw = sum(
        v["records"] - vorige.get("tabellen", {}).get(t, {}).get("records", 0)
        for t, v in stats.items()
        if t not in EXCLUDE_FROM_REPORT
    ) if stats else 0

    if n_kritiek:
        stuur_toast(
            "Ewaarnemingen Pipeline: FOUT",
            f"{n_kritiek} kritieke fout(en). Controleer het rapport.",
            "fout",
        )
        onderwerp = f"[FOUT] Ewaarnemingen Pipeline {run_ts[:10]}"
    elif n_actie:
        stuur_toast(
            "Ewaarnemingen Pipeline: Aandacht vereist",
            f"{n_actie} actiepunt(en). +{totaal_nieuw:,} nieuwe records.",
            "waarschuwing",
        )
        onderwerp = f"[AANDACHT] Ewaarnemingen Pipeline {run_ts[:10]}"
    else:
        stuur_toast(
            "Ewaarnemingen Pipeline: Geslaagd",
            f"+{totaal_nieuw:,} nieuwe records. Rapport beschikbaar op J:.",
            "info",
        )
        onderwerp = f"[OK] Ewaarnemingen Pipeline {run_ts[:10]}"

    stuur_email(onderwerp, html)

    if n_kritiek:
        status_label = "FOUTEN"
    elif n_actie or not j_ok:
        status_label = "GEDEELTELIJK"
    else:
        status_label = "OK"
    print(f"\nRapport klaar. Status: {status_label}")


if __name__ == "__main__":
    main()
