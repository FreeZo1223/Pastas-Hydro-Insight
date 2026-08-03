"""Vaste omlijsting: kop, peilbuizenlijst links, werkvlak rechts.

Overgenomen uit Menyanthes: de peilbuizenlijst is *altijd* zichtbaar en de
selectie blijft staan als je van weergave wisselt. In de oude opzet was elke
tab een eigen pagina met een eigen selectie, waardoor je bij elke stap opnieuw
moest kiezen. Wie van Menyanthes komt verwacht één lijst waar je in werkt —
en het scheelt ook gewoon klikken.

De selectie leeft in ``UIState`` (SQLite) en overleeft dus ook een herstart.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import pandas as pd
from nicegui import ui

from pastasdash_v2.core.store import STORE
from pastasdash_v2.core.timeseries import timeseries_stats
from pastasdash_v2.ui.tasks import REGISTRY
from pastasdash_v2.ui.theme import apply_theme

log = logging.getLogger(__name__)

# Boven dit aantal peilbuizen slaan we de tijdspanne-balkjes over: die vereisen
# per reeks een (gecachete) uitlezing, en bij een groot meetnet is de eerste
# render dan onaangenaam traag.
MAX_REEKSEN_MET_DETAIL = 150

WEERGAVEN: list[tuple[str, str, str]] = [
    ("overview", "Reeksen", "/overview"),
    ("model", "Model", "/model"),
    ("compare", "Vergelijken", "/compare"),
    ("statistics", "Statistiek", "/statistics"),
    ("maps", "Kaart", "/maps"),
    ("droogte", "Droogte", "/droogte"),
]

SELECTIE_SLEUTEL = "selectie.peilbuizen"


def geselecteerd() -> list[str]:
    """Huidige peilbuisselectie, gedeeld door alle weergaven."""
    if not STORE.is_loaded:
        return []
    namen = STORE.ui_state.get(SELECTIE_SLEUTEL, []) or []
    bestaande = set(STORE.oseries_names())
    return [n for n in namen if n in bestaande]


def zet_selectie(namen: list[str]) -> None:
    if STORE.is_loaded:
        STORE.ui_state.set(SELECTIE_SLEUTEL, namen)


@contextmanager
def pagina(actief: str) -> Iterator[None]:
    """Omhul een weergave met kop, peilbuizenlijst en werkvlak."""
    apply_theme()
    _kop()
    with ui.row().classes("w-full no-wrap gap-0 items-stretch"):
        _zijbalk()
        with ui.column().classes("flex-1 min-w-0 p-0 gap-0"):
            _weergavekiezer(actief)
            with ui.column().classes("w-full p-5 gap-5"):
                yield


# ── Kop ────────────────────────────────────────────────────────────────────
def _kop() -> None:
    with ui.header().classes("peil-rule").style(
        "background: var(--peil-surface); padding: 0 20px; height: 52px;"
    ):
        with ui.row().classes("items-center justify-between w-full no-wrap h-full"):
            with ui.row().classes("items-center gap-3 no-wrap"):
                ui.html(
                    '<div style="width:3px;height:20px;background:var(--peil-brand);'
                    'border-radius:1px"></div>'
                )
                ui.label("PastasDash").classes("text-base font-semibold").style(
                    "color: var(--peil-ink)"
                )
                bron = ui.label().style("color: var(--peil-slate)").classes("text-sm")

                def _ververs_bron() -> None:
                    if STORE.is_loaded:
                        aantal = len(STORE.oseries_names())
                        bron.text = f"{STORE.display_name} · {aantal} peilbuizen"
                    else:
                        bron.text = "geen dataset geladen"

                _ververs_bron()
                STORE.on_change(_ververs_bron)

            with ui.row().classes("items-center gap-4 no-wrap"):
                _takenmelder()
                ui.link("Dataset kiezen", "/").classes("text-sm no-underline").style(
                    "color: var(--peil-brand)"
                )


def _takenmelder() -> None:
    """Toont wat er op de achtergrond rekent, zodat stilte niet op vastlopen lijkt."""
    houder = ui.row().classes("items-center gap-2 no-wrap")

    def _ververs() -> None:
        houder.clear()
        with houder:
            if len(REGISTRY) == 0:
                return
            ui.spinner(size="xs", color="primary")
            labels = REGISTRY.labels()
            extra = f" +{len(labels) - 1}" if len(labels) > 1 else ""
            ui.label(f"{labels[0]}{extra}").classes("text-xs").style(
                "color: var(--peil-slate)"
            )

    _ververs()
    REGISTRY.on_change(lambda: ui.timer(0.01, _ververs, once=True))
    ui.timer(1.0, _ververs)


# ── Weergavekiezer ─────────────────────────────────────────────────────────
def _weergavekiezer(actief: str) -> None:
    with ui.row().classes("w-full peil-rule items-center gap-6 no-wrap px-5").style(
        "background: var(--peil-surface); min-height: 42px;"
    ):
        for sleutel, label, doel in WEERGAVEN:
            link = ui.link(label, doel).classes("peil-tab text-sm no-underline")
            if sleutel == actief:
                link.props('data-active=true')


# ── Zijbalk ────────────────────────────────────────────────────────────────
def _zijbalk() -> None:
    with ui.column().classes("gap-0 no-wrap").style(
        "width: 272px; min-width: 272px; background: var(--peil-surface);"
        "border-right: 1px solid var(--peil-line); min-height: calc(100vh - 52px);"
    ):
        if not STORE.is_loaded:
            with ui.column().classes("p-5 gap-2"):
                ui.label("Peilbuizen").classes("peil-label")
                ui.label("Laad eerst een dataset.").classes("text-sm").style(
                    "color: var(--peil-slate)"
                )
                ui.link("Dataset kiezen", "/").classes("text-sm").style(
                    "color: var(--peil-brand)"
                )
            return

        namen = STORE.oseries_names()
        toon_detail = len(namen) <= MAX_REEKSEN_MET_DETAIL
        spans = _tijdspannes(namen) if toon_detail else {}

        with ui.row().classes(
            "items-center justify-between w-full px-4 pt-4 pb-2 no-wrap"
        ):
            ui.label("Peilbuizen").classes("peil-label")
            teller = ui.label().classes("peil-label peil-num")

        zoek = ui.input(placeholder="Filter op naam").props(
            "dense outlined clearable"
        ).classes("mx-4 mb-3").style("font-size: 13px")

        lijst = ui.column().classes("w-full gap-0 overflow-auto").style(
            "max-height: calc(100vh - 210px)"
        )

        def _teken() -> None:
            huidige = geselecteerd()
            teller.text = f"{len(huidige)}/{len(namen)}"
            filter_tekst = (zoek.value or "").strip().lower()
            zichtbaar = [n for n in namen if filter_tekst in n.lower()]
            lijst.clear()
            with lijst:
                if not zichtbaar:
                    ui.label("Niets gevonden.").classes("text-sm p-4").style(
                        "color: var(--peil-slate)"
                    )
                    return
                for naam in zichtbaar:
                    _rij(naam, naam in huidige, spans.get(naam), _wissel)

        def _wissel(naam: str) -> None:
            huidige = geselecteerd()
            if naam in huidige:
                huidige.remove(naam)
            else:
                huidige.append(naam)
            zet_selectie(huidige)
            _teken()
            ui.navigate.reload()

        zoek.on_value_change(lambda _: _teken())
        _teken()

        with ui.row().classes("items-center gap-4 px-4 py-3 peil-rule no-wrap").style(
            "border-top: 1px solid var(--peil-line); border-bottom: none;"
        ):
            def _alles() -> None:
                zet_selectie(list(namen))
                ui.navigate.reload()

            def _geen() -> None:
                zet_selectie([])
                ui.navigate.reload()

            ui.button("Alles", on_click=_alles).props("flat dense no-caps size=sm")
            ui.button("Wissen", on_click=_geen).props("flat dense no-caps size=sm")


def _rij(naam: str, actief: bool, span: tuple[float, float, str] | None,
         bij_klik) -> None:
    """Eén peilbuis in de lijst."""
    with ui.column().classes("peil-row w-full px-4 py-2 gap-1").props(
        f'data-selected={"true" if actief else "false"} tabindex=0'
    ) as rij:
        rij.on("click", lambda: bij_klik(naam))
        rij.on("keydown.enter", lambda: bij_klik(naam))
        ui.label(naam).classes("text-sm font-medium truncate w-full")
        if span is None:
            return
        start, breedte, bijschrift = span
        ui.html(
            '<div class="peil-span-track">'
            f'<div class="peil-span-fill" style="left:{start:.1f}%;'
            f'width:{max(breedte, 1.5):.1f}%"></div></div>'
        ).classes("w-full")
        ui.label(bijschrift).classes("text-xs peil-num").style(
            "color: var(--peil-slate)"
        )


def _tijdspannes(namen: list[str]) -> dict[str, tuple[float, float, str]]:
    """Meetperiode per peilbuis, geschaald op een gedeelde tijdas.

    Zo zie je in één oogopslag welke reeksen elkaar overlappen — precies wat
    je wilt weten voordat je ze met elkaar vergelijkt.
    """
    ruw: dict[str, tuple[pd.Timestamp, pd.Timestamp, int]] = {}
    for naam in namen:
        try:
            stats = timeseries_stats(STORE.store_key, naam)
        except Exception as exc:  # noqa: BLE001
            log.debug("Stats voor %s niet beschikbaar: %s", naam, exc)
            continue
        if not stats.get("tmin") or not stats.get("tmax"):
            continue
        ruw[naam] = (
            pd.Timestamp(stats["tmin"]),
            pd.Timestamp(stats["tmax"]),
            int(stats.get("n_observations") or 0),
        )
    if not ruw:
        return {}

    vroegste = min(v[0] for v in ruw.values())
    laatste = max(v[1] for v in ruw.values())
    totaal = (laatste - vroegste).total_seconds() or 1.0

    resultaat: dict[str, tuple[float, float, str]] = {}
    for naam, (start, eind, n) in ruw.items():
        links = (start - vroegste).total_seconds() / totaal * 100
        breedte = (eind - start).total_seconds() / totaal * 100
        bijschrift = f"{start:%Y}–{eind:%Y} · {n} metingen"
        resultaat[naam] = (links, breedte, bijschrift)
    return resultaat
