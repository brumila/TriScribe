@echo off
REM Doppio click su questo file per installare TriScribe.
REM Aggira la ExecutionPolicy senza modificarla in modo permanente.

cd /d "%~dp0"

echo.
echo  Installazione TriScribe (locale, senza permessi admin)
echo  ------------------------------------------------------
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-TriScribe.ps1"

echo.
echo  Premi un tasto per chiudere.
pause >nul
