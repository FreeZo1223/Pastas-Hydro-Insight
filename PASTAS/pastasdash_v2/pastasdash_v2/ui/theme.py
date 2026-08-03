"""Visuele taal van het dashboard.

Uitgangspunt: dit is een *meetinstrument*, geen marketingpagina. De vormtaal
komt daarom uit het vak zelf:

* **Peil als ordenend principe.** Grondwaterwerk leest altijd tegen een
  referentie (NAP, maaiveld). Een dunne horizontale lijn — de peillijn —
  scheidt de zones in de interface, in plaats van kaders en schaduwen.
* **Kleur draagt betekenis, geen versiering.** Blauw is hoog water (GHG),
  oker is laag water (GLG). Die twee kleuren betekenen overal hetzelfde,
  dus een grafiek is leesbaar zonder legenda.
* **Cijfers zijn meetwaarden.** Alle getallen staan in een tabulair
  monospace-font zodat decimalen onder elkaar uitlijnen en reeksen
  vergelijkbaar zijn, net als op een instrumentafleesvenster.

De fonts zijn bewust Windows-systeemfonts: collega's draaien dit lokaal,
vaak zonder internet, en een webfont die niet laadt ziet er slechter uit
dan een systeemfont dat wél klopt.
"""

from __future__ import annotations

import math

from nicegui import ui

# ── Kleuren ────────────────────────────────────────────────────────────────
INK = "#0F1C24"        # bijna zwart met blauwgroene inslag — diep water
SLATE = "#5A6B75"      # secundaire tekst
LINE = "#DCE3E7"       # haarlijnen; de peillijn
PAPER = "#F6F8F9"      # paginavlak, koel (bewust niet warm/crème)
SURFACE = "#FFFFFF"    # kaartvlak
BRAND = "#006F92"      # Eelerwoude-blauw, herkenbaar uit de bestaande huisstijl
HIGH = "#1F7FA8"       # hoog water (GHG)
LOW = "#C2703D"        # laag water (GLG) — warm tegenover het koele blauw
WARN = "#B3541E"

FONT_UI = '"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif'
FONT_NUM = '"Cascadia Mono", "Cascadia Code", Consolas, ui-monospace, monospace'

CSS = f"""
:root {{
  --peil-ink: {INK};
  --peil-slate: {SLATE};
  --peil-line: {LINE};
  --peil-paper: {PAPER};
  --peil-surface: {SURFACE};
  --peil-brand: {BRAND};
  --peil-high: {HIGH};
  --peil-low: {LOW};
}}

body, .q-page, .nicegui-content {{
  background: var(--peil-paper);
  color: var(--peil-ink);
  font-family: {FONT_UI};
  font-size: 14px;
}}

/* De peillijn: onze enige scheidingsvorm. Geen schaduwen, geen dikke randen. */
.peil-rule {{ border-bottom: 1px solid var(--peil-line); }}

/* Instrumentlabel: klein, gespatieerd, rustig — zoals opschriften op een paneel. */
.peil-label {{
  font-size: 10.5px;
  letter-spacing: .09em;
  text-transform: uppercase;
  color: var(--peil-slate);
  font-weight: 600;
}}

/* Meetwaarden lijnen digit-voor-digit uit. */
.peil-num {{
  font-family: {FONT_NUM};
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
}}
.peil-num-lg {{ font-size: 22px; letter-spacing: -.01em; }}

.peil-high {{ color: var(--peil-high); }}
.peil-low  {{ color: var(--peil-low); }}

/* Kaartvlak: vlak, met haarlijn in plaats van schaduw. */
.peil-card {{
  background: var(--peil-surface);
  border: 1px solid var(--peil-line);
  border-radius: 3px;
}}

/* Zijbalk-rij: de selectie is de hoofdhandeling, dus die krijgt het accent. */
.peil-row {{
  border-bottom: 1px solid var(--peil-line);
  cursor: pointer;
  transition: background-color .12s ease;
}}
.peil-row:hover {{ background: #EEF3F5; }}
.peil-row[data-selected="true"] {{
  background: #E7F0F4;
  box-shadow: inset 3px 0 0 var(--peil-brand);
}}

/* Tijdspanne-balkje: laat zien welke reeksen elkaar in tijd overlappen. */
.peil-span-track {{
  position: relative; height: 3px; background: var(--peil-line); border-radius: 2px;
}}
.peil-span-fill {{
  position: absolute; top: 0; height: 3px;
  background: var(--peil-brand); border-radius: 2px; opacity: .75;
}}

/* Weergavekiezer boven het werkvlak. */
.peil-tab {{
  padding: 9px 2px; color: var(--peil-slate); font-weight: 500;
  border-bottom: 2px solid transparent; text-decoration: none;
}}
.peil-tab:hover {{ color: var(--peil-ink); }}
.peil-tab[data-active="true"] {{
  color: var(--peil-ink); border-bottom-color: var(--peil-brand); font-weight: 600;
}}

/* Toetsenbordfocus moet zichtbaar blijven — dit is een werkinstrument. */
a:focus-visible, button:focus-visible, .peil-row:focus-visible {{
  outline: 2px solid var(--peil-brand);
  outline-offset: 2px;
}}

@media (prefers-reduced-motion: reduce) {{
  * {{ transition: none !important; animation: none !important; }}
}}
"""


def apply_theme() -> None:
    """Injecteer stylesheet en Quasar-kleuren. Aanroepen binnen een page."""
    ui.add_css(CSS)
    ui.colors(primary=BRAND, secondary=SLATE, accent=LOW, dark=INK)


def fmt(waarde: float | None, decimalen: int = 2, leeg: str = "—") -> str:
    """Meetwaarde als tekst; ontbrekende waarden krijgen een duidelijke streep.

    Een leeg veld is dubbelzinnig (nul? niet berekend?), een streep niet.
    """
    if waarde is None:
        return leeg
    try:
        getal = float(waarde)
    except (TypeError, ValueError):
        return leeg
    if math.isnan(getal):
        return leeg
    return f"{getal:.{decimalen}f}"
