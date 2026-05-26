"""
AGOL domeinen → QGIS ValueMaps + QField-project
=================================================
Leest domains_snapshot.json en past codedValue-domeinen toe als QGIS ValueMap-widgets
op alle GeoPackages. Slaat styles OP in de GPKG (portabel voor QField offline sync).
Maakt daarna een compleet QGIS-project aan met alle 16 lagen.

GEBRUIK — plak in QGIS Python Console:
    exec(open(r'C:/GIS_Projecten/ArcGIS_online/scripts/agol_domeinen_naar_qgis.py').read())

Of via Terminal (QGIS headless):
    python agol_domeinen_naar_qgis.py

Vereisten: QGIS 3.x (qgis.core beschikbaar)
"""

import json
import os
from pathlib import Path

# ── Paden ─────────────────────────────────────────────────────────────────────
_SCRIPT_DIR  = Path(__file__).parent if '__file__' in dir() else Path(r'C:\GIS_Projecten\ArcGIS_online\scripts')
_PROJECT_DIR = _SCRIPT_DIR.parent

DOMAINS_PAD  = _PROJECT_DIR / 'Databeheer' / '00_kern'      / 'domains_snapshot.json'
GPKG_MAP     = _PROJECT_DIR / 'Databeheer' / '02_geopackage' / 'qgis'
PROJECT_PAD  = r'C:\GIS_Projecten\qgis_mcp\Q_cloud\projecttemplates\Ecologie\Ewaarnemingen_QField.qgz'

# Mapping: laagnaam in domains_snapshot → bestandsnaam gpkg
LAAG_MAP = {
    'vogels':         'vogels.gpkg',
    'vleermuizen':    'vleermuizen.gpkg',
    'zoogdieren':     'zoogdieren.gpkg',
    'flora':          'flora.gpkg',
    'reptielen':      'reptielen.gpkg',
    'vissen':         'vissen.gpkg',
    'ongewervelden':  'ongewervelden.gpkg',
    'amfibieen':      'amfibieën.gpkg',
    'exoten':         'exoten.gpkg',
    'faunakasten':    'faunakasten.gpkg',
    'veldbezoeken':   'veldbezoeken.gpkg',
    'veldmateriaal':  'veldmateriaal.gpkg',
    'projectgebieden':'projectgebieden.gpkg',
    'owaarnemingen':  'owaarnemingen.gpkg',
    'vliegroutes':    'vliegroutes.gpkg',
}

# Velden die NIET bewerkt mogen worden in QField
READONLY_VELDEN = {
    'object_id', 'global_id', 'creation_date', 'creator',
    'edit_date', 'editor', '_bron_laag', '_bron_type',
    'soortgroep', 'datum_beste', 'datum_bron', 'geometry',
}

# Velden die verborgen worden in QField-formulier
VERBORGEN_VELDEN = {
    '_bron_laag', '_bron_type', 'soortgroep',
    'datum_beste', 'datum_bron',
}


# ── Domeinen laden ─────────────────────────────────────────────────────────────

def laad_domeinen():
    with open(DOMAINS_PAD, encoding='utf-8') as f:
        snap = json.load(f)

    domeinen = {}  # {laagnaam: {veldnaam_lower: {label: waarde, ...}}}
    for laagnaam, laagdata in snap.get('lagen', {}).items():
        velden = {}
        for veld in laagdata.get('schema', {}).get('velden', []):
            if veld.get('domein_type') == 'codedValue' and veld.get('domein_waarden'):
                veld_lower = veld['naam'].lower()
                velden[veld_lower] = veld['domein_waarden']
        if velden:
            domeinen[laagnaam.lower()] = velden

    print(f'  Domeinen geladen: {len(domeinen)} lagen met domains')
    for laag, vd in domeinen.items():
        print(f'    {laag}: {list(vd.keys())}')
    return domeinen


# ── ValueMap instellen op een laag ────────────────────────────────────────────

def pas_valuemaps_toe(layer, domein_velden):
    """Past ValueMap-widgets toe op alle overeenkomende velden."""
    from qgis.core import QgsEditorWidgetSetup

    gewijzigd = 0
    veld_namen = {f.name().lower(): f.name() for f in layer.fields()}

    for veld_lower, domein_waarden in domein_velden.items():
        if veld_lower not in veld_namen:
            continue

        echte_naam = veld_namen[veld_lower]
        idx = layer.fields().indexOf(echte_naam)
        if idx < 0:
            continue

        # ValueMap-formaat voor QGIS: [{"label": "waarde"}, ...]
        # QGIS verwacht een lijst van dicts met één key (label) -> waarde
        waarde_map = [{label: waarde} for label, waarde in domein_waarden.items()]

        setup = QgsEditorWidgetSetup('ValueMap', {'map': waarde_map})
        layer.setEditorWidgetSetup(idx, setup)
        gewijzigd += 1
        print(f'      ValueMap "{echte_naam}": {len(domein_waarden)} opties')

    return gewijzigd


def stel_readonly_in(layer):
    """Zet readonly/verborgen configuratie voor systeemvelden."""
    from qgis.core import QgsEditorWidgetSetup

    veld_namen = {f.name().lower(): f.name() for f in layer.fields()}
    config = layer.editFormConfig()

    for veld_lower, echte_naam in veld_namen.items():
        idx = layer.fields().indexOf(echte_naam)
        if idx < 0:
            continue

        if veld_lower in VERBORGEN_VELDEN:
            config.setLabelOnTop(idx, False)
            layer.setFieldAlias(idx, '')
            setup = QgsEditorWidgetSetup('Hidden', {})
            layer.setEditorWidgetSetup(idx, setup)

    layer.setEditFormConfig(config)


# ── GPKG verwerken ────────────────────────────────────────────────────────────

def verwerk_gpkg(gpkg_pad, laagnaam, domein_velden):
    from qgis.core import QgsVectorLayer

    gpkg_str = str(gpkg_pad)
    # GPKG kan meerdere lagen bevatten; eerste laag gebruiken
    layer = QgsVectorLayer(f'{gpkg_str}|layerindex=0', laagnaam, 'ogr')

    if not layer.isValid():
        print(f'  ❌ Kon niet laden: {gpkg_str}')
        return None

    print(f'\n  📦 {laagnaam} ({layer.featureCount():,} features, {layer.fields().count()} velden)')

    layer.startEditing()
    n = pas_valuemaps_toe(layer, domein_velden)
    stel_readonly_in(layer)
    layer.commitChanges()

    # Sla stijl op IN de GeoPackage (portabel voor QField)
    err, ok = layer.saveStyleToDatabase(
        name=f'{laagnaam}_qfield_stijl',
        description=f'ValueMaps + QField config voor {laagnaam}',
        useAsDefault=True,
        uiFileContent='',
    )
    if ok:
        print(f'    ✅ Stijl opgeslagen in GPKG ({n} ValueMaps)')
    else:
        print(f'    ⚠️  Stijl niet opgeslagen in GPKG: {err}')

    return layer


# ── QGIS-project aanmaken ─────────────────────────────────────────────────────

def maak_qfield_project(lagen):
    from qgis.core import QgsProject, QgsLayerTreeGroup

    project = QgsProject.instance()
    project.clear()
    project.setTitle('Ewaarnemingen — QField')
    project.setCrs(project.crs())  # EPSG:28992 via lagen

    # Stel CRS in op RD New
    from qgis.core import QgsCoordinateReferenceSystem
    crs = QgsCoordinateReferenceSystem('EPSG:28992')
    project.setCrs(crs)

    # Groepering voor QField overzicht
    groepen = {
        'Waarnemingen':    ['vogels', 'vleermuizen', 'zoogdieren', 'flora', 'reptielen',
                            'vissen', 'ongewervelden', 'amfibieen', 'exoten'],
        'Infrastructuur':  ['faunakasten', 'vliegroutes', 'veldmateriaal'],
        'Beheer':          ['veldbezoeken', 'projectgebieden', 'owaarnemingen'],
    }

    root = project.layerTreeRoot()
    naam_naar_laag = {l.name().lower(): l for l in lagen}

    for groep_naam, laagnamen in groepen.items():
        groep = root.addGroup(groep_naam)
        for ln in laagnamen:
            laag = naam_naar_laag.get(ln)
            if laag:
                project.addMapLayer(laag, False)
                groep.addLayer(laag)

    # Lagen zonder groep
    for laag in lagen:
        if laag not in [l for g in groepen.values() for l in g]:
            project.addMapLayer(laag)

    project.write(PROJECT_PAD)
    print(f'\n  ✅ QGIS-project opgeslagen: {PROJECT_PAD}')


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print('=' * 60)
    print('  AGOL DOMEINEN → QGIS VALUEMAPS + QFIELD PROJECT')
    print('=' * 60)

    # Controleer of QGIS beschikbaar is
    try:
        from qgis.core import QgsApplication, QgsVectorLayer, QgsProject
    except ImportError:
        print('\n❌ QGIS niet beschikbaar.')
        print('   Plak dit script in de QGIS Python Console:')
        print(f'   exec(open(r"{__file__}").read())')
        return

    domeinen = laad_domeinen()

    lagen = []
    for laagnaam, gpkg_bestand in LAAG_MAP.items():
        gpkg_pad = GPKG_MAP / gpkg_bestand

        if not gpkg_pad.exists():
            print(f'  ⚠️  GPKG niet gevonden: {gpkg_bestand}')
            continue

        domein_velden = domeinen.get(laagnaam, {})
        if not domein_velden:
            print(f'\n  📦 {laagnaam} — geen domeinen, wordt wel toegevoegd aan project')

        layer = verwerk_gpkg(gpkg_pad, laagnaam, domein_velden)
        if layer:
            lagen.append(layer)

    print(f'\n  {len(lagen)} lagen verwerkt')
    maak_qfield_project(lagen)

    print('\n' + '=' * 60)
    print('  VOLGENDE STAP: QField klaarmaken')
    print('=' * 60)
    print("""
  OPTIE A — USB/lokaal (offline volledig):
    1. Open Ewaarnemingen_QField.qgz in QGIS
    2. Plugins → QField Sync → Package for QField
    3. Kies exportmap → kopieer naar tablet via USB

  OPTIE B — QField Cloud (online sync):
    1. Maak account op qfield.cloud
    2. QGIS → QField Cloud plugin → Push project
    3. Op tablet: QField → Cloud → sync

  OPTIE C — PostGIS direct (online, geen export nodig):
    Host: localhost (of IP van deze machine)
    DB:   ewaarnemingen  schema: ewaarnemingen
    User: ew_collega  Pass: EelerWoude_lees2026!
    → Vereist netwerktoegang tot deze machine
""")


if __name__ == '__main__':
    main()
else:
    # Aangeroepen vanuit QGIS Python Console
    main()
