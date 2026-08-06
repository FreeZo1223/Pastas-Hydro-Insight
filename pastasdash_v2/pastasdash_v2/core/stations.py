"""KNMI grondstation-lijst (subset met dagelijkse RH + EV24)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnmiStation:
    code: int
    name: str
    lat: float
    lon: float


STATIONS: list[KnmiStation] = [
    KnmiStation(210, "Valkenburg", 52.17, 4.43),
    KnmiStation(235, "De Kooy", 52.92, 4.78),
    KnmiStation(240, "Schiphol", 52.31, 4.79),
    KnmiStation(249, "Berkhout", 52.64, 4.98),
    KnmiStation(251, "Hoorn (Terschelling)", 53.39, 5.35),
    KnmiStation(257, "Wijk aan Zee", 52.50, 4.60),
    KnmiStation(260, "De Bilt", 52.10, 5.18),
    KnmiStation(269, "Lelystad", 52.46, 5.52),
    KnmiStation(270, "Leeuwarden", 53.22, 5.76),
    KnmiStation(273, "Marknesse", 52.70, 5.89),
    KnmiStation(275, "Deelen", 52.06, 5.87),
    KnmiStation(277, "Lauwersoog", 53.41, 6.20),
    KnmiStation(279, "Hoogeveen", 52.73, 6.57),
    KnmiStation(280, "Eelde", 53.13, 6.59),
    KnmiStation(283, "Hupsel", 52.07, 6.66),
    KnmiStation(286, "Nieuw Beerta", 53.20, 7.15),
    KnmiStation(290, "Twenthe", 52.27, 6.90),
    KnmiStation(310, "Vlissingen", 51.44, 3.60),
    KnmiStation(319, "Westdorpe", 51.23, 3.86),
    KnmiStation(323, "Wilhelminadorp", 51.53, 3.88),
    KnmiStation(330, "Hoek van Holland", 51.99, 4.12),
    KnmiStation(340, "Woensdrecht", 51.45, 4.34),
    KnmiStation(344, "Rotterdam", 51.96, 4.45),
    KnmiStation(348, "Cabauw", 51.97, 4.93),
    KnmiStation(356, "Herwijnen", 51.86, 5.14),
    KnmiStation(370, "Eindhoven", 51.45, 5.42),
    KnmiStation(375, "Volkel", 51.65, 5.71),
    KnmiStation(377, "Ell", 51.20, 5.76),
    KnmiStation(380, "Maastricht", 50.91, 5.76),
    KnmiStation(391, "Arcen", 51.50, 6.20),
]

STATIONS_BY_CODE: dict[int, KnmiStation] = {s.code: s for s in STATIONS}
DEFAULT_STATION_CODE = 260


def station_label_map() -> dict[int, str]:
    """Code -> label voor NiceGUI select."""
    return {s.code: f"{s.code} — {s.name}" for s in sorted(STATIONS, key=lambda x: x.name)}
