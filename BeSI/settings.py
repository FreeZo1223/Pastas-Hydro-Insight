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
VRT_PATH = Path(r"C:\GIS_Projecten\Data\BESI_Master.vrt")

# Map met individuele COG GeoTIFF-bestanden per soort
LAYERS_DIR = Path(r"C:\GIS_Projecten\Data\NDFF_layers")

# Basismap voor alle output (per run wordt een submap aangemaakt)
OUTPUT_BASE_DIR = Path(r"C:\GIS_Projecten\Output")

# Locatie van de species metadata CSV
METADATA_PATH = Path(__file__).parent / "species_metadata.csv"

# ------------------------------------------------------------
# ANALYSE PARAMETERS
# ------------------------------------------------------------

# Aantal prioriteitsklassen in de geclassificeerde kaarten
N_KLASSEN = 5

# Minimale kansscore om een soort als 'aanwezig' te beschouwen
# als er geen soortspecifieke cutoff beschikbaar is in metadata
DEFAULT_CUTOFF = 0.3

# Celoppervlakte in m² (25x25 meter)
CEL_OPPERVLAKTE_M2 = 625
CEL_OPPERVLAKTE_HA = CEL_OPPERVLAKTE_M2 / 10_000  # = 0.0625 ha

# Drempelwaarde voor 'hoge prioriteit' (als percentage van max soortenrijkdom)
# Cellen boven deze drempel worden als hoge prioriteit beschouwd
HOGE_PRIORITEIT_DREMPEL = 0.75

# Maximum geheugengebruik per chunk (in MB) — pas aan op basis van je RAM
MAX_CHUNK_MB = 512

# ------------------------------------------------------------
# GEWICHTEN PER BESCHERMINGSSTATUS (voor versie 2)
# ------------------------------------------------------------
# Hogere waarde = zwaarder gewicht in de gewogen rijkdomsanalyse
# Pas aan naar ecologisch oordeel

STATUS_WEIGHTS = {
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
    "HR_II":   2,  # Bijlage II (gebiedsbescherming)
    "HR_IV":   3,  # Bijlage IV (strikte soortbescherming)
    "HR_II_IV": 4, # Beide bijlagen
}

# Brede soortengroepindeling voor geaggregeerde rapportage
BROAD_GROUP_MAPPING = {
    "Vogels":             "Fauna",
    "Zoogdieren":         "Fauna",
    "Reptielen":          "Fauna",
    "Amfibieën":          "Fauna",
    "Vissen":             "Fauna",
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
COLORMAP_RICHNESS   = "YlOrRd"   # geel → rood (laag → hoog)
COLORMAP_WEIGHTED   = "YlGn"     # geel → groen
COLORMAP_PRIORITY   = "RdYlGn_r" # groen → rood (laag → hoog prioriteit)

# DPI voor PNG-export
PNG_DPI = 150

# ------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------
LOG_LEVEL = "INFO"   # "DEBUG" voor meer detail tijdens ontwikkeling
LOG_TO_FILE = True   # Sla logbestand op in output-map
