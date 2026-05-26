#!/usr/bin/env python3
"""
QGIS PostGIS Value Relation Setup
==================================
Voeg alle waarnemingen_* lagen van PostGIS toe aan het project met:
- Value Relation widgets per domein-veld (uit postgis_domeinen_aanmaken.py output)
- Read-only systeemvelden (object_id, global_id, creation_date, creator)
- Verborgen interne velden (_bron_laag, _bron_type, soortgroep, datum_beste, datum_bron)

GEBRUIK IN QGIS PYTHON CONSOLE:
    exec(open(r'C:/GIS_Projecten/ArcGIS_online/scripts/qgis_postgis_valurelation_setup.py').read())
"""

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsEditorWidgetSetup,
    QgsLayerTreeGroup, QgsCoordinateReferenceSystem
)

# ── Configuratie per laag uit qfield_migratie_plan.md ────────────────────────

VALUE_RELATIONS = {
    'waarnemingen_vogels': {
        'soort':      'domein_vogelsoort',
        'gedrag':     'domein_vogelgedrag',
        'telmethode': 'domein_telmethode',
        'richting':   'domein_richting',
        'geslacht':   'domein_geslacht',
        'kleed':      'domein_vogelkleed',
        'stadium':    'domein_stadiumvogels',
    },
    'waarnemingen_vleermuizen': {
        'soort':             'domein_soortvleermuis',
        'gedrag':            'domein_gedragvleermuis',
        'type_verblijfplaats': 'domein_typeverblijfplaats',
        'telmethode':        'domein_telmethode',
        'richting':          'domein_richting',
        'geslacht':          'domein_geslacht',
        'stadium':           'domein_stadiumvleermuizen',
    },
    'waarnemingen_zoogdieren': {
        'soort':      'domein_soortzoogdier',
        'gedrag':     'domein_gedragzoogdier',
        'richting':   'domein_richting',
        'geslacht':   'domein_geslacht',
        'telmethode': 'domein_telmethode',
        'kleed':      'domein_kleedzoogdier',
        'methode':    'domein_methodezoogdier',
    },
    'waarnemingen_flora': {
        'nederlandse_naam': 'domein_nednaam',
        'activiteit':       'domein_gedragplant',
        'levensstadium':    'domein_kleedflora',
        'telmethode':       'domein_telmethode',
        'geslacht':         'domein_geslacht',
    },
    'waarnemingen_reptielen': {
        'soort':         'domein_soortreptiel',
        'gedrag':        'domein_gedragamfibie',
        'levensstadium': 'domein_stadiumamfibie',
        'geslacht':      'domein_geslacht',
        'telmethode':    'domein_telmethode',
        'methode':       'domein_methode',
    },
    'waarnemingen_vissen': {
        'soort':         'domein_soortvis',
        'gedrag':        'domein_gedragamfibie',
        'levensstadium': 'domein_stadiumamfibie',
        'geslacht':      'domein_geslacht',
        'telmethode':    'domein_telmethode',
        'methode':       'domein_methode',
        'lengte':        'domein_lengtevis',
    },
    'waarnemingen_ongewervelden': {
        'soort':      'domein_ongewervelden_soort',  # SLANG: te groot voor keuze-menu
        'gedrag':     'domein_gedraginsect',
        'richting':   'domein_richting',
        'geslacht':   'domein_geslacht',
        'telmethode': 'domein_telmethode',
    },
    'waarnemingen_amfibieen': {
        'soort':         'domein_soortamfibie',
        'gedrag':        'domein_gedragamfibie',
        'levensstadium': 'domein_stadiumamfibie',
        'geslacht':      'domein_geslacht',
        'telmethode':    'domein_telmethode',
        'methode':       'domein_methode',
    },
    'waarnemingen_exoten': {
        'soort':   'domein_exoot',
        'stadium': 'domein_gedragplant',
    },
    'waarnemingen_faunakasten': {
        'soort':              'domein_soort',
        'voorzieningstype':   'domein_voorzieningstype',
        'voorzieningsduur':   'domein_voorzieningsduur',
        'locatie':            'domein_locatie',
        'materiaal':          'domein_materiaal',
        'conditie':           'domein_conditie',
    },
    'waarnemingen_veldbezoeken': {
        'type_bezoek':        'domein_soortbezoek',
        'begintemperatuur':   'domein_temperatuur',
        'eindtemperatuur':    'domein_temperatuur',
        'windkracht':         'domein_windkracht',
        'neerslag':           'domein_neerslag',
        'weersomstandigheden': 'domein_bewolking',
    },
    'waarnemingen_vliegroutes': {
        'soort1':        'domein_soortvleermuis',
        'soort2':        'domein_soortvleermuis',
        'soort3':        'domein_soortvleermuis',
        'type_vliegroute': 'domein_typevliegroute',
    },
    'waarnemingen_owaarnemingen': {
        'soortgroep': 'domein_soortgroep',
        'materiaal':  'domein_materiaal',
    },
}

READONLY_VELDEN = {
    'object_id', 'global_id', 'creation_date', 'creator',
    'edit_date', 'editor'
}

VERBORGEN_VELDEN = {
    '_bron_laag', '_bron_type', 'soortgroep',
    'datum_beste', 'datum_bron'
}

# ── Verbindingsdetails ────────────────────────────────────────────────────────

PG_HOST   = 'localhost'
PG_PORT   = '5432'
PG_DB     = 'ewaarnemingen'
PG_SCHEMA = 'ewaarnemingen'
PG_USER   = 'ew_beheer'  # Gebruik beheerder voor configuratie

# ── Implementatie ─────────────────────────────────────────────────────────────

def add_postgis_layer(laag_naam):
    """Voeg PostGIS-laag toe aan project."""
    uri = f'postgres://host={PG_HOST} port={PG_PORT} dbname={PG_DB} ' \
          f'user={PG_USER} schema={PG_SCHEMA} table={laag_naam} (geometry) '
    layer = QgsVectorLayer(uri, laag_naam, 'postgres')

    if not layer.isValid():
        print(f'  ❌ Kon laag niet laden: {laag_naam}')
        return None

    return layer


def pas_value_relations_toe(layer, domein_config):
    """Pas Value Relation widgets toe per domein-veld."""
    velden = {f.name().lower(): f for f in layer.fields()}
    gewijzigd = 0

    for veld_lower, domein_tabel in domein_config.items():
        if veld_lower not in velden:
            continue

        veld = velden[veld_lower]
        idx = layer.fields().indexOf(veld.name())

        # Value Relation: verwijst naar domein_* tabel in dezelfde PostGIS
        setup = QgsEditorWidgetSetup('ValueRelation', {
            'AllowMulti':   False,
            'AllowNull':    True,
            'FilterExpression': '',
            'Key':          'code',
            'Layer':        domein_tabel,  # Tabel naam
            'OrderByValue': False,
            'Value':        'label',
            'UseCompleter': False
        })
        layer.setEditorWidgetSetup(idx, setup)
        gewijzigd += 1

    return gewijzigd


def stel_readonly_en_verborgen_in(layer):
    """Zet read-only en verborgen configuratie."""
    config = layer.editFormConfig()
    velden = {f.name().lower(): f for f in layer.fields()}

    for veld_lower, veld in velden.items():
        idx = layer.fields().indexOf(veld.name())

        if veld_lower in VERBORGEN_VELDEN:
            # Verborgen veld
            setup = QgsEditorWidgetSetup('Hidden', {})
            layer.setEditorWidgetSetup(idx, setup)
            config.setLabelOnTop(idx, False)

        elif veld_lower in READONLY_VELDEN:
            # Read-only veld (TextEdit zonder bewerking)
            setup = QgsEditorWidgetSetup('TextEdit', {
                'IsMultiline': False,
                'UseHtml':     False
            })
            layer.setEditorWidgetSetup(idx, setup)
            # QGIS doesn't have direct "ReadOnly" widget, dus TextEdit laten met voorzichtige opmerkingen

    layer.setEditFormConfig(config)


def main():
    print('=' * 70)
    print('  QGIS POSTGIS VALUE RELATION SETUP')
    print('=' * 70)

    project = QgsProject.instance()
    project.clear()
    project.setTitle('Ewaarnemingen — QField (PostGIS)')

    # Zet CRS op RD New (EPSG:28992)
    crs = QgsCoordinateReferenceSystem('EPSG:28992')
    project.setCrs(crs)

    # Groepering
    root = project.layerTreeRoot()

    groepen_def = {
        'Waarnemingen': [
            'waarnemingen_vogels',
            'waarnemingen_vleermuizen',
            'waarnemingen_zoogdieren',
            'waarnemingen_flora',
            'waarnemingen_reptielen',
            'waarnemingen_vissen',
            'waarnemingen_ongewervelden',
            'waarnemingen_amfibieen',
            'waarnemingen_exoten',
        ],
        'Veldwerk': [
            'waarnemingen_veldbezoeken',
            'waarnemingen_veldmateriaal',
        ],
        'Infrastructuur': [
            'waarnemingen_faunakasten',
            'waarnemingen_vliegroutes',
            'waarnemingen_projectgebieden',
        ],
        'Overig': [
            'waarnemingen_owaarnemingen',
        ]
    }

    all_lagen = []
    for groep_naam, laagnamen in groepen_def.items():
        groep = root.addGroup(groep_naam)

        for laag_naam in laagnamen:
            if laag_naam not in VALUE_RELATIONS:
                print(f'  ⚠️  {laag_naam}: geen Value Relation config (slaat over)')
                continue

            layer = add_postgis_layer(laag_naam)
            if not layer:
                continue

            # Value Relations toepassen
            domein_config = VALUE_RELATIONS[laag_naam]
            n_vr = pas_value_relations_toe(layer, domein_config)

            # Read-only/verborgen instellen
            stel_readonly_en_verborgen_in(layer)

            # Aan project toevoegen
            project.addMapLayer(layer, False)
            groep.addLayer(layer)

            all_lagen.append(laag_naam)
            print(f'  ✅ {laag_naam:35s} ({n_vr} Value Relations)')

    # Domein-tabellen als aparte groep (alleen voor referentie, niet bewerkbaar)
    domein_groep = root.addGroup('Domeinen (referentie)')
    # Hier kunnen we evt. ook domein_* tabellen toevoegen als read-only

    # Sla project op
    project_pad = r'C:\GIS_Projecten\qgis_mcp\Q_cloud\projecttemplates\Ecologie\Ewaarnemingen_QField_PostGIS.qgz'
    project.write(project_pad)

    print(f'\n' + '=' * 70)
    print(f'  ✅ PROJECT OPGESLAGEN: {project_pad}')
    print(f'  {len(all_lagen)} lagen geladen + geconfigureerd')
    print('=' * 70)
    print(f"""
  Volgende stappen:
  1. Test velden: open waarnemingen_vogels → attributes
     → soort, gedrag, etc. moeten dropdown-keuzes tonen (Value Relation)
  2. Voeg veldwerk_invoer toe voor nieuwe waarnemingen
  3. QField-sync via QField Cloud of USB
    """)


if __name__ == '__main__':
    main()
