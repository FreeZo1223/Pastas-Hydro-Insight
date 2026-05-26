@echo off
setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..
set LOG_DIR=%PROJECT_DIR%\Databeheer\03_logs
set J_DATABEHEER=J:\Databeheer\Ewaarnemingen_databeheer

:: Betrouwbare timestamp via PowerShell (omzeilt Dutch date-format bug)
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmm"') do set TS=%%i
set BAT_LOG=%LOG_DIR%\pipeline_%TS%.log

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

:: Initialiseer alle exit-codes op 0 zodat rapport-stap nooit op ongedefinieerde
:: variabelen crasht als een tussenstap wordt overgeslagen.
set AGOL_CODE=0
set GPKG_CODE=0
set POSTGIS_CODE=0
set SNAPSHOT_CODE=0
set SYNC_CODE=0

echo ============================================================ >> "%BAT_LOG%"
echo  Ewaarnemingen Pipeline gestart: %TS%                        >> "%BAT_LOG%"
echo ============================================================ >> "%BAT_LOG%"

:: ─────────────────────────────────────────────────────────────
:: STAP 0: Wacht op J:-schijf (max 8x 15 min = 2 uur)
:: ─────────────────────────────────────────────────────────────
set J_BESCHIKBAAR=0
set /a POGING=0

:wacht_op_J
if exist "%J_DATABEHEER%\" (
    set J_BESCHIKBAAR=1
    echo [%TIME%] J:-schijf bereikbaar na poging %POGING%          >> "%BAT_LOG%"
    goto J_klaar
)
if %POGING% GEQ 8 (
    echo [%TIME%] J:-schijf NIET bereikbaar na 8 pogingen (2 uur)  >> "%BAT_LOG%"
    goto J_klaar
)
set /a POGING+=1
echo [%TIME%] J:-schijf niet bereikbaar, wacht 15 min (poging %POGING%/8)... >> "%BAT_LOG%"
timeout /t 900 /nobreak >nul
goto wacht_op_J

:J_klaar

set PYTHONIOENCODING=utf-8

:: ─────────────────────────────────────────────────────────────
:: STAP 1: AGOL -> DuckDB
:: ─────────────────────────────────────────────────────────────
echo [%TIME%] Stap 1: AGOL naar DuckDB gestart                     >> "%BAT_LOG%"
python "%SCRIPT_DIR%agol_naar_duckdb_v2.py" >> "%BAT_LOG%" 2>&1
set AGOL_CODE=%ERRORLEVEL%

if %AGOL_CODE% EQU 0 (
    echo [%TIME%] Stap 1: GESLAAGD                                 >> "%BAT_LOG%"
) else (
    echo [%TIME%] Stap 1: MISLUKT (exit %AGOL_CODE%)               >> "%BAT_LOG%"
    goto rapport
)

:: ─────────────────────────────────────────────────────────────
:: STAP 2: DuckDB -> GeoPackage + Parquet
:: ─────────────────────────────────────────────────────────────
echo [%TIME%] Stap 2: GeoPackage export gestart                     >> "%BAT_LOG%"
python "%SCRIPT_DIR%duckdb_naar_geopackage.py" >> "%BAT_LOG%" 2>&1
set GPKG_CODE=%ERRORLEVEL%

if %GPKG_CODE% EQU 0 (
    echo [%TIME%] Stap 2: GESLAAGD                                 >> "%BAT_LOG%"
) else (
    echo [%TIME%] Stap 2: MISLUKT (exit %GPKG_CODE%)               >> "%BAT_LOG%"
)

:: ─────────────────────────────────────────────────────────────
:: STAP 3: DuckDB -> PostGIS (cloudnative QGIS-leeslaag)
:: ─────────────────────────────────────────────────────────────
echo [%TIME%] Stap 3: PostGIS export gestart                        >> "%BAT_LOG%"
python "%SCRIPT_DIR%duckdb_naar_postgis.py" >> "%BAT_LOG%" 2>&1
set POSTGIS_CODE=%ERRORLEVEL%

if %POSTGIS_CODE% EQU 0 (
    echo [%TIME%] Stap 3: GESLAAGD                                 >> "%BAT_LOG%"
) else (
    echo [%TIME%] Stap 3: MISLUKT (exit %POSTGIS_CODE%)            >> "%BAT_LOG%"
)

:: ─────────────────────────────────────────────────────────────
:: STAP 4: Snapshots DuckDB + PostgreSQL (3-2-1 backup)
:: Lokaal — J:-sync gebeurt in stap 5
:: ─────────────────────────────────────────────────────────────
echo [%TIME%] Stap 4: Snapshots gestart                             >> "%BAT_LOG%"
python "%SCRIPT_DIR%snapshot.py" >> "%BAT_LOG%" 2>&1
set SNAPSHOT_CODE=%ERRORLEVEL%

if %SNAPSHOT_CODE% EQU 0 (
    echo [%TIME%] Stap 4: GESLAAGD                                 >> "%BAT_LOG%"
) else (
    echo [%TIME%] Stap 4: MISLUKT (exit %SNAPSHOT_CODE%)           >> "%BAT_LOG%"
)

:: ─────────────────────────────────────────────────────────────
:: STAP 5: Sync naar J:-schijf (alleen als J: beschikbaar)
:: Inclusief snapshots — geeft remote 3-2-1-redundantie.
:: ─────────────────────────────────────────────────────────────
if %J_BESCHIKBAAR% EQU 0 (
    echo [%TIME%] Stap 5: OVERGESLAGEN - J:-schijf niet bereikbaar >> "%BAT_LOG%"
    goto rapport
)

echo [%TIME%] Stap 5: Sync naar J:-schijf gestart                  >> "%BAT_LOG%"
robocopy "%PROJECT_DIR%\Databeheer" "%J_DATABEHEER%" /E /MIR /NP /R:3 /W:60 /LOG+:"%BAT_LOG%"
set SYNC_CODE=%ERRORLEVEL%

if %SYNC_CODE% LEQ 7 (
    echo [%TIME%] Stap 5: Sync GESLAAGD (exit %SYNC_CODE%)         >> "%BAT_LOG%"
) else (
    echo [%TIME%] Stap 5: Sync MISLUKT (exit %SYNC_CODE%)          >> "%BAT_LOG%"
)

:: ─────────────────────────────────────────────────────────────
:: STAP 6: Rapport + notificaties
:: ─────────────────────────────────────────────────────────────
:rapport
echo [%TIME%] Stap 6: Rapport genereren                            >> "%BAT_LOG%"
python "%SCRIPT_DIR%pipeline_rapport.py" ^
    --agol-exit %AGOL_CODE% ^
    --gpkg-exit %GPKG_CODE% ^
    --postgis-exit %POSTGIS_CODE% ^
    --snapshot-exit %SNAPSHOT_CODE% ^
    --j-beschikbaar %J_BESCHIKBAAR% ^
    --logbestand "%BAT_LOG%" >> "%BAT_LOG%" 2>&1

echo [%TIME%] Pipeline afgerond                                     >> "%BAT_LOG%"
echo ============================================================ >> "%BAT_LOG%"

exit /b %AGOL_CODE%
