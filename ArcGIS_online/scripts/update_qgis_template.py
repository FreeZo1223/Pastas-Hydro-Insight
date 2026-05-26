#!/usr/bin/env python3
import zipfile
import tempfile
import os
import shutil

template_path = r'C:\GIS_Projecten\qgis_mcp\Q_cloud\projecttemplates\Ecologie\Ewaarnemingen_template.qgz'

# Extract to temp dir
with tempfile.TemporaryDirectory() as tmpdir:
    with zipfile.ZipFile(template_path, 'r') as zf:
        zf.extractall(tmpdir)

    # Read and modify QGS
    qgs_file = os.path.join(tmpdir, 'Ewaarnemingen_template.qgs')
    with open(qgs_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Replace parquet paths with gpkg paths
    content = content.replace('J:/Databeheer', 'C:/GIS_Projecten/ArcGIS_online/Databeheer')
    content = content.replace('/01_parquet/', '/02_geopackage/qgis/')
    content = content.replace('.parquet', '.gpkg')

    with open(qgs_file, 'w', encoding='utf-8') as f:
        f.write(content)

    # Repackage
    backup_path = template_path + '.backup'
    shutil.copy2(template_path, backup_path)

    with zipfile.ZipFile(template_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for fname in os.listdir(tmpdir):
            fpath = os.path.join(tmpdir, fname)
            zf.write(fpath, arcname=fname)

    print('✓ Template updated ({:.1f} KB)'.format(os.path.getsize(template_path) / 1024))
    print('  Backup: {}'.format(backup_path))
