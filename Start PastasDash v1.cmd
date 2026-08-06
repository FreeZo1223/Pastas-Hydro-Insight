@echo off
chcp 65001 >nul
setlocal EnableExtensions
title PastasDash v1 - oorspronkelijke versie

rem ===========================================================
rem  PastasDash v1 starten met een dubbelklik.
rem
rem  Dit bestand mag overal staan - bijvoorbeeld op de J-schijf.
rem  Het houdt zelf een kopie van de software bij in
rem  %LOCALAPPDATA%\PastasDash en werkt die elke start bij.
rem
rem  Staat dit bestand toevallig IN een kloon van de repo, dan
rem  gebruikt het die map in plaats van een eigen kopie.
rem
rem  v1 en v2 delen dezelfde kopie en draaien op verschillende
rem  poorten (8050 en 8051), dus ze kunnen tegelijk aan staan.
rem ===========================================================

set "REPO_URL=https://github.com/FreeZo1223/Pastas-Hydro-Insight.git"
set "SUBMAP=pastasdash"
set "MODULE=pastasdash"
set "POORT=8050"
set "NAAM=PastasDash v1"

echo.
echo   %NAAM%
echo   ----------------------------------------
echo.

rem --- Waar staat de code? -----------------------------------
if exist "%~dp0.git" (
    set "MAP=%~dp0"
) else (
    set "MAP=%LOCALAPPDATA%\PastasDash"
)

rem --- Is uv aanwezig? ---------------------------------------
where uv >nul 2>&1
if errorlevel 1 (
    echo   [!] Het programma "uv" is niet gevonden.
    echo.
    echo   uv regelt Python en alle pakketten. Installeer het eenmalig
    echo   door dit in PowerShell te plakken:
    echo.
    echo       winget install --id=astral-sh.uv -e
    echo.
    echo   Sluit daarna dit venster en probeer het opnieuw.
    echo.
    pause
    exit /b 1
)

rem --- Is git aanwezig? --------------------------------------
where git >nul 2>&1
if errorlevel 1 (
    echo   [!] Het programma "git" is niet gevonden.
    echo.
    echo   git haalt de nieuwste versie op. Installeer het eenmalig
    echo   door dit in PowerShell te plakken:
    echo.
    echo       winget install --id=Git.Git -e
    echo.
    echo   Sluit daarna dit venster en probeer het opnieuw.
    echo.
    pause
    exit /b 1
)

rem --- Ophalen of bijwerken ----------------------------------
if not exist "%MAP%\.git" (
    echo   Eerste keer: software ophalen naar
    echo   %MAP%
    echo.
    git clone "%REPO_URL%" "%MAP%"
    if errorlevel 1 goto :mislukt
) else (
    echo   Controleren op een nieuwere versie...
    pushd "%MAP%"
    git pull --ff-only
    if errorlevel 1 (
        echo.
        echo   [!] Bijwerken lukte niet. De vorige versie wordt gestart.
        echo.
    )
    popd
)

if not exist "%MAP%\%SUBMAP%" (
    echo   [!] Map "%SUBMAP%" niet gevonden in %MAP%
    goto :mislukt
)

rem --- Browser openen zodra de app antwoordt -----------------
start "" /min powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "$u='http://127.0.0.1:%POORT%'; for($i=0;$i -lt 200;$i++){ try{ $null = Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 2; Start-Process $u; break } catch { Start-Sleep -Seconds 2 } }"

echo.
echo   Starten... Alleen de eerste keer duurt dit een paar minuten,
echo   omdat Python en de pakketten opgehaald worden. Daarna is het
echo   een kwestie van seconden.
echo.
echo   De browser gaat vanzelf open op http://127.0.0.1:%POORT%
echo   Laat dit venster openstaan zolang je het dashboard gebruikt.
echo   Sluit het venster om te stoppen.
echo.

pushd "%MAP%\%SUBMAP%"
uv run python -m %MODULE% --port %POORT%
set "FOUT=%ERRORLEVEL%"
popd

if not "%FOUT%"=="0" goto :mislukt

echo.
echo   %NAAM% is gestopt.
echo.
pause
exit /b 0

:mislukt
echo.
echo   ===========================================================
echo   Er ging iets mis.
echo.
echo   Selecteer ALLE tekst in dit venster (rechtermuisknop -
echo   Alles selecteren), kopieer die met Enter, en plak het in
echo   een mail. Zonder die tekst is de fout meestal niet te
echo   vinden zonder eerst te raden.
echo   ===========================================================
echo.
pause
exit /b 1
