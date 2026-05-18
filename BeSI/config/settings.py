# config/settings.py
# ============================================================
# CENTRALE CONFIGURATIE — pas hier paden en parameters aan
# Nooit paden hardcoden in andere bestanden
# ============================================================

from pathlib import Path

# ------------------------------------------------------------
# PADEN — pas aan naar jouw systeem
# ------------------------------------------------------------

# Locatie van de Master VRT met alle 235 BeSI-lagen
# Let op: de VRT gebruikt relatieve paden naar BESI_COGs\*_cog.tif
# (relatief t.o.v. de VRT-locatie). Zorg dat de COG-bestanden op die
# locatie beschikbaar zijn, of gebruik een junction/symlink:
#   mklink /J "C:\GIS_Projecten\BeSI\BESI_COGs" "C:\GIS_Projecten\Data\BESI_COGs"
VRT_PATH = Path(r"C:\GIS_Projecten\BeSI\BESI_Master.vrt")

# Map met individuele COG GeoTIFF-bestanden per soort
LAYERS_DIR = Path(r"C:\GIS_Projecten\Data\BESI_COGs")

# Basismap voor alle output (per run wordt een submap aangemaakt)
OUTPUT_BASE_DIR = Path(r"C:\GIS_Projecten\Output")

# Locatie van de species metadata CSV
METADATA_PATH = Path(__file__).parent / "species_metadata.csv"

# ------------------------------------------------------------
# SCHAALFACTOR VAN DE RASTERWAARDEN
# ------------------------------------------------------------
# De COG-bestanden slaan kanswaardes op als Byte (0–255).
# Om de kans op voorkomen (0–1) te verkrijgen: waarde / DATA_SCALE_FACTOR
# Standaard: 255 (volledige Byte-schaal → 0–1 range)
# Pas aan naar 100 als de waarden als 0–100 percentages zijn opgeslagen.
DATA_SCALE_FACTOR: float = 255.0

# ------------------------------------------------------------
# ANALYSE PARAMETERS
# ------------------------------------------------------------

# Aantal prioriteitsklassen in de geclassificeerde kaarten
N_KLASSEN: int = 5

# Minimale kansscore om een soort als 'aanwezig' te beschouwen
# als er geen soortspecifieke cutoff beschikbaar is in metadata
DEFAULT_CUTOFF: float = 0.3

# Celoppervlakte in m² (25x25 meter)
CEL_OPPERVLAKTE_M2: float = 625.0
CEL_OPPERVLAKTE_HA: float = CEL_OPPERVLAKTE_M2 / 10_000  # = 0.0625 ha

# Drempelwaarde voor 'hoge prioriteit' (als percentage van max soortenrijkdom)
# Cellen boven deze drempel worden als hoge prioriteit beschouwd
HOGE_PRIORITEIT_DREMPEL: float = 0.75

# Maximum geheugengebruik per chunk (in MB) — pas aan op basis van je RAM
MAX_CHUNK_MB: int = 512

# Gebiedsgrootte (in ha) waarboven chunk-gewijze verwerking wordt gebruikt
CHUNK_THRESHOLD_HA: float = 1000.0

# ------------------------------------------------------------
# GEWICHTEN PER BESCHERMINGSSTATUS (voor versie 2)
# ------------------------------------------------------------
# Hogere waarde = zwaarder gewicht in de gewogen rijkdomsanalyse

STATUS_WEIGHTS: dict[str, int] = {
    # Rode Lijst categorieën
    "EX":   0,    # Uitgestorven in Nederland
    "RE":   0,    # Regionaal uitgestorven
    "CR":   5,    # Ernstig bedreigd
    "EN":   4,    # Bedreigd
    "VU":   3,    # Kwetsbaar
    "NT":   2,    # Gevoelig
    "LC":   1,    # Niet bedreigd
    "DD":   1,    # Onvoldoende data
    "NE":   1,    # Niet geëvalueerd (default)

    # Habitatrichtlijn (HR) — cumulatief bovenop Rode Lijst gewicht
    "HR_I":    2,  # Bijlage I Vogelrichtlijn
    "HR_II":   2,  # Bijlage II (gebiedsbescherming)
    "HR_IV":   3,  # Bijlage IV (strikte soortbescherming)
    "HR_II_IV": 4, # Beide bijlagen
    "HR_V":    1,  # Bijlage V
}

# Brede soortengroepindeling voor geaggregeerde rapportage
BROAD_GROUP_MAPPING: dict[str, str] = {
    "Vogels":             "Fauna",
    "Zoogdieren":         "Fauna",
    "Reptielen":          "Fauna",
    "Amfibieën":          "Fauna",
    "Vissen":             "Fauna",
    "Vleermuizen":        "Fauna",
    "Dagvlinders":        "Insecten",
    "Libellen":           "Insecten",
    "Kevers":             "Insecten",
    "Bijen en wespen":    "Insecten",
    "Sprinkhanen":        "Insecten",
    "Nachtvlinders":      "Insecten",
    "Overige insecten":   "Insecten",
    "Vaatplanten":        "Flora",
    "Mossen":             "Flora",
    "Paddenstoelen":      "Flora",
    "Weekdieren":         "Overig",
    "Kreeften":           "Overig",
    "Onbekend":           "Onbekend",
}

# ------------------------------------------------------------
# VISUALISATIE
# ------------------------------------------------------------

# Colormap voor soortenrijkdom en prioriteitskaarten
COLORMAP_RICHNESS:  str = "YlOrRd"   # geel → rood (laag → hoog)
COLORMAP_WEIGHTED:  str = "YlGn"     # geel → groen
COLORMAP_PRIORITY:  str = "RdYlGn_r" # groen → rood (laag → hoog prioriteit)

# DPI voor PNG-export
PNG_DPI: int = 150

# ------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------
LOG_LEVEL: str = "INFO"   # "DEBUG" voor meer detail tijdens ontwikkeling
LOG_TO_FILE: bool = True  # Sla logbestand op in output-map
