@echo off
setlocal enabledelayedexpansion
title TriScribe

cd /d "%~dp0"

set "VENV=%LOCALAPPDATA%\TriScribe\.venv\Scripts\python.exe"
set "PORT=8766"
REM Ollama gira su questo PC: le chiamate a 127.0.0.1 non passano dal proxy
set "NO_PROXY=localhost,127.0.0.1,::1"

echo.
echo   TriScribe - da documento a Markdown, in locale
echo   ----------------------------------------------
echo.

REM --- 1. Interprete Python del venv TriScribe --------------------------------
if not exist "%VENV%" (
    echo   [X] Ambiente TriScribe non trovato in:
    echo       %VENV%
    echo.
    echo   Esegui prima INSTALLA.bat
    echo.
    pause
    exit /b 1
)

REM --- 2. Dipendenze web ------------------------------------------------------
"%VENV%" -c "import fastapi, uvicorn, importlib.util as u, sys; sys.exit(0 if (u.find_spec('multipart') or u.find_spec('python_multipart')) else 1)" >nul 2>&1
if errorlevel 1 (
    echo   Installo le dipendenze web...
    echo.
    "%VENV%" -m pip install --quiet --disable-pip-version-check fastapi uvicorn python-multipart
    if errorlevel 1 (
        echo   Riprovo con --trusted-host ^(proxy / SSL aziendale^)...
        "%VENV%" -m pip install --quiet --disable-pip-version-check fastapi uvicorn python-multipart ^
            --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org
    )
    "%VENV%" -c "import fastapi, uvicorn, importlib.util as u, sys; sys.exit(0 if (u.find_spec('multipart') or u.find_spec('python_multipart')) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo   [X] Installazione dipendenze fallita. Rilancia INSTALLA.bat
        echo.
        pause
        exit /b 1
    )
    echo   [OK] Dipendenze installate.
    echo.
)

REM --- 3. Avvio ---------------------------------------------------------------
echo   Server: http://127.0.0.1:%PORT%
echo   Chiudi questa finestra per fermarlo.
echo.

"%VENV%" "%~dp0app.py" --port %PORT%

echo.
echo   Server fermato.
pause
