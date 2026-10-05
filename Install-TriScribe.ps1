<#
    Install-TriScribe.ps1
    Installa TriScribe in modalita' 100% locale su Windows, senza permessi di amministratore.

    Crea un ambiente Python isolato e installa i tre motori:
      - MarkItDown            documenti digitali (PDF con testo, Word, Excel, PowerPoint)
      - PaddleOCR-VL          scritto a mano
      - GLM-OCR via Ollama    layout complessi (Ollama e' un programma a parte)

    Internet serve solo qui, per scaricare pacchetti e modelli. Dopo, TriScribe lavora offline.

    Uso:
      powershell -ExecutionPolicy Bypass -File .\Install-TriScribe.ps1
      powershell -ExecutionPolicy Bypass -File .\Install-TriScribe.ps1 -InstallDir "D:\Tools\TriScribe"
      powershell -ExecutionPolicy Bypass -File .\Install-TriScribe.ps1 -SkipModels
#>

[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\TriScribe",
    [switch]$SkipModels
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Write-Step { param($m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok   { param($m) Write-Host "    [OK] $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "    [!]  $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "    [X]  $m" -ForegroundColor Red }

# ---------------------------------------------------------------------------
# 1. Trova un interprete Python 3.10 - 3.13
#    (MarkItDown chiede almeno 3.10, PaddlePaddle non ha ancora pacchetti per 3.14)
# ---------------------------------------------------------------------------
function Test-PyVersion { param($ver) return ($ver -and ([version]$ver -ge [version]'3.10') -and ([version]$ver -lt [version]'3.14')) }

function Find-Python {
    # Le prove falliscono per scelta (es. "py -3.12" senza la 3.12 installata) e
    # scrivono su stderr: in PowerShell 5.1, con 'Stop', basterebbe a bloccare
    # lo script. Qui dentro gli errori dei comandi provati si ignorano.
    $ErrorActionPreference = 'Continue'

    # a) Python Launcher (py.exe) - il piu' affidabile su Windows
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($v in '3.12', '3.13', '3.11', '3.10') {
            $null = & $py.Source "-$v" -c "import sys" 2>$null
            if ($LASTEXITCODE -eq 0) {
                return [pscustomobject]@{ Exe = $py.Source; Pre = @("-$v"); Label = "py $v" }
            }
        }
    }

    # b) python.exe / python3.exe nel PATH (esclusi gli stub del Microsoft Store)
    foreach ($name in 'python.exe', 'python3.exe') {
        foreach ($c in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
            if ($c.Source -like '*\WindowsApps\*') { continue }   # stub dello Store
            $ver = & $c.Source -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and (Test-PyVersion $ver)) {
                return [pscustomobject]@{ Exe = $c.Source; Pre = @(); Label = "python $ver" }
            }
        }
    }

    # c) Installazioni note non nel PATH
    $roots = @(
        "$env:LOCALAPPDATA\Programs\Python",
        "$env:ProgramFiles\Python*",
        "C:\Python3*"
    )
    foreach ($r in $roots) {
        foreach ($d in @(Get-ChildItem -Path $r -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending)) {
            $exe = Join-Path $d.FullName 'python.exe'
            if (Test-Path $exe) {
                $ver = & $exe -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
                if ($LASTEXITCODE -eq 0 -and (Test-PyVersion $ver)) {
                    return [pscustomobject]@{ Exe = $exe; Pre = @(); Label = "python $ver ($($d.FullName))" }
                }
            }
        }
    }
    return $null
}

Write-Step "Cerco Python 3.10 - 3.13"
$python = Find-Python

if (-not $python) {
    Write-Err "Nessun Python tra 3.10 e 3.13 trovato su questa macchina."
    Write-Host @"

    OPZIONI:

    1) winget:
           winget install --id Python.Python.3.12 --scope user --source winget

    2) Installer ufficiale, modalita' "Just for me" (NON serve admin):
           https://www.python.org/downloads/windows/
       -> scarica "Windows installer (64-bit)" 3.12.x
       -> in fase di setup: SPUNTA "Add python.exe to PATH"

    3) Microsoft Store: cerca "Python 3.12"

    Poi rilancia questo script.
"@ -ForegroundColor Yellow
    exit 1
}
Write-Ok "Trovato: $($python.Label)  ->  $($python.Exe)"

# ---------------------------------------------------------------------------
# 2. Rileva proxy aziendale
# ---------------------------------------------------------------------------
Write-Step "Rilevo configurazione proxy"
$proxyUrl = $env:HTTPS_PROXY
if (-not $proxyUrl) { $proxyUrl = $env:HTTP_PROXY }
if (-not $proxyUrl) {
    try {
        $ie = Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction Stop
        if ($ie.ProxyEnable -eq 1 -and $ie.ProxyServer) {
            $ps = ($ie.ProxyServer -split ';')[0]
            if ($ps -match '=') { $ps = ($ps -split '=')[1] }
            if ($ps -notmatch '^https?://') { $ps = "http://$ps" }
            $proxyUrl = $ps
        }
    } catch { }
}
if ($proxyUrl) {
    Write-Ok "Proxy: $proxyUrl"
    $env:HTTP_PROXY  = $proxyUrl
    $env:HTTPS_PROXY = $proxyUrl
    # Ollama gira su questo PC: le sue chiamate non devono passare dal proxy
    $env:NO_PROXY    = 'localhost,127.0.0.1,::1'
} else {
    Write-Ok "Nessun proxy configurato (connessione diretta)"
}

# ---------------------------------------------------------------------------
# 3. Crea il virtual environment
# ---------------------------------------------------------------------------
Write-Step "Creo l'ambiente virtuale in $InstallDir"
$VenvDir = Join-Path $InstallDir '.venv'

if (Test-Path $VenvDir) {
    Write-Warn "Ambiente gia' esistente: verra' riutilizzato/aggiornato"
} else {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    & $python.Exe @($python.Pre) -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Write-Err "Creazione venv fallita"; exit 1 }
}

$VenvPy = Join-Path $VenvDir 'Scripts\python.exe'
if (-not (Test-Path $VenvPy)) { Write-Err "python.exe non trovato nel venv"; exit 1 }
Write-Ok "Venv pronto: $VenvDir"

# ---------------------------------------------------------------------------
# 4. pip install con fallback progressivi (proxy / SSL interception)
# ---------------------------------------------------------------------------
$TrustedHosts = @(
    '--trusted-host', 'pypi.org',
    '--trusted-host', 'files.pythonhosted.org',
    '--trusted-host', 'pypi.python.org'
)

function Invoke-Pip {
    param([string[]]$PipArgs, [string]$What)

    $attempts = @(
        @{ Name = 'diretto';                         Extra = @() }
        @{ Name = 'con --trusted-host (SSL bypass)'; Extra = $TrustedHosts }
    )
    if ($proxyUrl) {
        $attempts += @{ Name = 'con --proxy + --trusted-host'; Extra = (@('--proxy', $proxyUrl) + $TrustedHosts) }
    }

    foreach ($a in $attempts) {
        Write-Host "    tentativo: $($a.Name)..." -ForegroundColor DarkGray
        # Out-Host: senza, l'output di pip finirebbe nel valore restituito dalla
        # funzione, che risulterebbe sempre "vero" anche quando pip fallisce.
        & $VenvPy -m pip @PipArgs @($a.Extra) --disable-pip-version-check | Out-Host
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "$What installato ($($a.Name))"
            return $true
        }
    }
    return $false
}

Write-Step "Aggiorno pip"
if (-not (Invoke-Pip -PipArgs @('install', '--upgrade', 'pip', 'setuptools', 'wheel') -What 'pip')) {
    Write-Warn "Aggiornamento pip fallito: proseguo comunque con la versione corrente"
}

# 4a. Base: interfaccia web + documenti digitali. Senza questa l'app non parte.
Write-Step "Installo l'interfaccia e MarkItDown (documenti digitali)"
$base = @('markitdown[pdf,docx,xlsx,xls,pptx]', 'fastapi', 'uvicorn', 'python-multipart', 'pypdfium2', 'pillow')
if (-not (Invoke-Pip -PipArgs (@('install', '--upgrade') + $base) -What 'MarkItDown')) {
    Write-Err "Installazione fallita su tutti i tentativi."
    Write-Host @"

    Cause tipiche su PC aziendale:

    A) SSL interception (errore CERTIFICATE_VERIFY_FAILED)
       Crea %APPDATA%\pip\pip.ini con:
           [global]
           trusted-host = pypi.org
                          files.pythonhosted.org
           cert = C:\percorso\root-aziendale.pem

    B) pypi.org bloccato dal firewall
       Chiedi lo sblocco di pypi.org e files.pythonhosted.org.
"@ -ForegroundColor Yellow
    exit 1
}

# 4b. OCR: PaddlePaddle (CPU) + PaddleOCR. Se fallisce, la modalita' digitale funziona comunque.
#     Versioni fissate: sono quelle con cui TriScribe e' stato scritto.
Write-Step "Installo PaddleOCR (scritto a mano e analisi del layout) - qualche minuto"
$ocr = @('paddlepaddle>=3.3,<3.4', 'paddleocr[doc-parser]>=3.7,<3.8')
$paddleOk = Invoke-Pip -PipArgs (@('install', '--upgrade') + $ocr) -What 'PaddleOCR'
if (-not $paddleOk) {
    Write-Warn "PaddleOCR non installato: 'Scritto a mano' non sara' disponibile, 'Layout complesso' lavorera' senza analisi del layout."
}

# ---------------------------------------------------------------------------
# 5. Verifica
# ---------------------------------------------------------------------------
Write-Step "Verifico i componenti"
$check = @'
import importlib, sys
mods = {
    "Web":       "fastapi",
    "PDF":       "pdfminer.high_level",
    "DOCX":      "mammoth",
    "XLSX":      "openpyxl",
    "XLS":       "xlrd",
    "PPTX":      "pptx",
    "Pagine":    "pypdfium2",
    "Paddle":    "paddle",
    "PaddleOCR": "paddleocr",
}
ko = []
for label, m in mods.items():
    try:
        importlib.import_module(m)
        print("    [OK] %-10s -> %s" % (label, m))
    except Exception as e:
        ko.append(label)
        print("    [--] %-10s -> %s (%s)" % (label, m, e))
sys.exit(1 if set(ko) - {"Paddle", "PaddleOCR"} else 0)
'@
$tmp = Join-Path $env:TEMP 'triscribe_check.py'
Set-Content -Path $tmp -Value $check -Encoding UTF8
& $VenvPy $tmp
$checkOk = ($LASTEXITCODE -eq 0)
Remove-Item $tmp -ErrorAction SilentlyContinue
if (-not $checkOk) { Write-Warn "Mancano componenti della modalita' digitale (vedi sopra)" }

# ---------------------------------------------------------------------------
# 6. Modelli PaddleOCR (una volta sola, circa 2 GB)
# ---------------------------------------------------------------------------
if ($paddleOk -and -not $SkipModels) {
    Write-Step "Scarico i modelli PaddleOCR (una volta sola, circa 2 GB)"
    $dl = @'
from paddleocr import LayoutDetection, PaddleOCRVL
LayoutDetection(model_name="PP-DocLayoutV3")
PaddleOCRVL(pipeline_version="v1.6")
print("    [OK] PP-DocLayoutV3 e PaddleOCR-VL 1.6 pronti")
'@
    $tmp = Join-Path $env:TEMP 'triscribe_models.py'
    Set-Content -Path $tmp -Value $dl -Encoding UTF8
    & $VenvPy $tmp
    $modelsOk = ($LASTEXITCODE -eq 0)
    Remove-Item $tmp -ErrorAction SilentlyContinue
    if (-not $modelsOk) {
        Write-Warn "Download dei modelli non riuscito: verra' ritentato al primo uso."
        Write-Host @"
    Se il proxy aziendale blocca huggingface.co, prova un'altra sorgente prima di rilanciare:
        setx PADDLE_PDX_MODEL_SOURCE modelscope
    (valori possibili: huggingface, modelscope, aistudio, bos)
"@ -ForegroundColor Yellow
    }
}

# ---------------------------------------------------------------------------
# 7. Ollama + GLM-OCR (layout complessi)
# ---------------------------------------------------------------------------
Write-Step "Controllo Ollama (serve per 'Layout complesso')"
$ollama = Get-Command ollama.exe -ErrorAction SilentlyContinue
if (-not $ollama) {
    $guess = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path $guess) { $ollama = Get-Item $guess }
}
if ($ollama) {
    $ollamaExe = if ($ollama.Source) { $ollama.Source } else { $ollama.FullName }
    Write-Ok "Trovato: $ollamaExe"
    Write-Host "    Scarico il modello glm-ocr (circa 2,2 GB, una volta sola)..." -ForegroundColor DarkGray
    & $ollamaExe pull glm-ocr
    if ($LASTEXITCODE -eq 0) { Write-Ok "Modello glm-ocr pronto" }
    else { Write-Warn "Download non riuscito: avvia Ollama e lancia a mano  ollama pull glm-ocr" }
} else {
    Write-Warn "Ollama non trovato. 'Layout complesso' sara' disponibile dopo averlo installato:"
    Write-Host @"
        1) Scarica e installa Ollama (non serve admin):  https://ollama.com/download
           oppure:  winget install --id Ollama.Ollama
        2) Poi, una volta sola:                          ollama pull glm-ocr
"@ -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
Write-Host "`n" -NoNewline
Write-Host "  INSTALLAZIONE COMPLETATA" -ForegroundColor Green
Write-Host @"

  Ambiente:  $VenvDir
  Avvio:     doppio click su AVVIA.bat

  Tutto gira in locale: nessun documento lascia la macchina.

"@ -ForegroundColor White
