"""
TriScribe — da documento a Markdown, tutto in locale.

Backend FastAPI. Gira esclusivamente su 127.0.0.1: nessun dato lascia la macchina.
Tre modalità, una per motore (vedi engines.py):

  digitale     MarkItDown         PDF con testo, Word, Excel, PowerPoint
  manoscritto  PaddleOCR-VL       scansioni e foto scritte a mano
  complesso    GLM-OCR (Ollama)   tabelle, formule, impaginazioni articolate

Avvio:  python app.py
        python app.py --port 8888 --no-browser
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
import unicodedata
import webbrowser
from datetime import datetime
from pathlib import Path
from threading import Timer

# --------------------------------------------------------------------------
# Dipendenze
# --------------------------------------------------------------------------
try:
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import FileResponse, JSONResponse
    from pydantic import BaseModel, Field
    import uvicorn
except ImportError as exc:  # pragma: no cover
    sys.exit(
        f"Dipendenza mancante: {exc.name}\n"
        f"Installa con:\n  \"{sys.executable}\" -m pip install fastapi uvicorn python-multipart"
    )

try:
    import markitdown  # noqa: F401  la modalità digitale è il minimo indispensabile
except ImportError:  # pragma: no cover
    sys.exit(
        "MarkItDown non è installato in questo interprete.\n"
        f"Interprete corrente: {sys.executable}\n"
        "Esegui prima INSTALLA.bat"
    )

import engines

# --------------------------------------------------------------------------
# Costanti e configurazione
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

DEFAULT_CONFIG = {
    "vault_path": "",
    "ollama_url": engines.DEFAULT_OLLAMA_URL,
    "glm_model": engines.DEFAULT_GLM_MODEL,
}

# Formati con livello testo: li legge MarkItDown con converter 100% offline.
DIGITAL_EXT = {
    ".pdf": "PDF",
    ".docx": "Word",
    ".xlsx": "Excel",
    ".xls": "Excel (legacy)",
    ".pptx": "PowerPoint",
}
# Scansioni e foto: le leggono i due motori OCR.
SCAN_EXT = {
    ".pdf": "PDF",
    ".png": "Immagine",
    ".jpg": "Immagine",
    ".jpeg": "Immagine",
    ".tif": "Immagine",
    ".tiff": "Immagine",
    ".bmp": "Immagine",
    ".webp": "Immagine",
}

MODES = {
    "digitale": {"label": "Documento digitale", "tool": "MarkItDown", "ext": DIGITAL_EXT},
    "manoscritto": {"label": "Scritto a mano", "tool": "PaddleOCR-VL", "ext": SCAN_EXT},
    "complesso": {"label": "Layout complesso", "tool": "GLM-OCR", "ext": SCAN_EXT},
}

MAX_UPLOAD_BYTES = 150 * 1024 * 1024  # 150 MB

# Id del progetto "radice": salva direttamente nella cartella agganciata.
ROOT_ID = "."

IGNORED_DIRS = {".obsidian", ".trash", ".git", ".smart-env", "node_modules", "__pycache__"}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


CONFIG = load_config()


def engine_status(mode: str) -> tuple[bool, str]:
    if mode == "digitale":
        return True, "MarkItDown · in locale"
    if mode == "manoscritto":
        return engines.paddle_status()
    return engines.glm_status(CONFIG.get("ollama_url"), CONFIG.get("glm_model") or engines.DEFAULT_GLM_MODEL)


# Una conversione alla volta: i modelli OCR occupano GB di RAM.
_job_lock = threading.Lock()
PROGRESS = {"busy": False, "mode": "", "page": 0, "pages": 0, "note": ""}


def set_progress(**fields) -> None:
    PROGRESS.update(fields)


# --------------------------------------------------------------------------
# Utility
# --------------------------------------------------------------------------
WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename(name: str, fallback: str = "documento") -> str:
    """Rende un nome sicuro per il filesystem Windows, senza componenti di percorso."""
    name = unicodedata.normalize("NFC", name or "")
    name = name.replace("\\", "/").split("/")[-1]          # via ogni componente di path
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "-", name)        # caratteri vietati
    name = re.sub(r"\s+", " ", name).strip(" .")           # spazi e punti finali
    if not name:
        name = fallback
    # toglie un'estensione finale nota (.md o quella del sorgente) per non
    # generare doppioni tipo "manuale.pdf.md"
    stem = re.sub(
        r"\.(md|pdf|docx?|xlsx?|pptx?|png|jpe?g|tiff?|bmp|webp)$", "", name, flags=re.IGNORECASE
    ) or name
    if stem.upper().split(".")[0] in WIN_RESERVED:
        stem = f"_{stem}"
    stem = stem[:120].strip(" .") or fallback     # il taglio può lasciare spazi/punti finali
    return f"{stem}.md"


def yaml_escape(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_frontmatter(title: str, source: str, kind: str, tool: str) -> str:
    now = datetime.now()
    return (
        "---\n"
        f"titolo: {yaml_escape(title)}\n"
        f"fonte: {yaml_escape(source)}\n"
        f"tipo: {yaml_escape(kind)}\n"
        f"convertito: {now.strftime('%Y-%m-%d %H:%M')}\n"
        f"strumento: {tool}\n"
        "tags:\n"
        "  - da-convertire\n"
        "---\n\n"
    )


def vault_root() -> Path | None:
    raw = (CONFIG.get("vault_path") or "").strip()
    if not raw:
        return None
    try:
        root = Path(raw).expanduser().resolve()
    except (OSError, ValueError):
        return None
    return root if root.is_dir() else None


def scan_vault(root: Path) -> list[dict]:
    """Legge la struttura reale dal disco, senza nessun layout predefinito.

    Ogni sottocartella visibile della cartella agganciata è un progetto, con le
    sue sottocartelle fino al secondo livello: agganciando un'altra cartella si
    vede la sua struttura.
    """
    def subdirs(d: Path) -> list[Path]:
        """Sottocartelle visibili, tollerante a permessi negati e path troppo lunghi."""
        try:
            return sorted(
                (p for p in d.iterdir()
                 if p.is_dir() and p.name not in IGNORED_DIRS and not p.name.startswith(".")),
                key=lambda p: p.name.lower(),
            )
        except OSError:
            return []

    projects: list[dict] = []
    for pdir in subdirs(root):
        folders: list[str] = []
        for sub in subdirs(pdir):
            folders.append(sub.name)
            for nested in subdirs(sub):          # secondo livello (es. contenuti/articoli)
                folders.append(f"{sub.name}/{nested.name}")
        projects.append({"id": pdir.name, "label": pdir.name, "folders": folders})

    # Sempre in fondo: una cartella senza sottocartelle resta comunque usabile.
    projects.append({"id": ROOT_ID, "label": "(radice)", "folders": []})
    return projects


def resolve_target_dir(root: Path, project: str, folder: str) -> Path:
    """Risolve la cartella di destinazione garantendo che resti dentro il vault."""
    for part in (project, folder):
        if ".." in Path(part.replace("\\", "/")).parts or Path(part).is_absolute():
            raise HTTPException(400, "Percorso di destinazione non valido.")

    target = (root / project / folder) if folder else (root / project)
    try:
        target = target.resolve()
        target.relative_to(root)          # solleva ValueError se esce dal vault
    except (ValueError, OSError):
        raise HTTPException(400, "La destinazione è fuori dal vault.")
    return target


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------
app = FastAPI(title="TriScribe", docs_url=None, redoc_url=None)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(
        BASE_DIR / "index.html",
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/status")
def status() -> dict:
    root = vault_root()
    modes = {}
    for key, m in MODES.items():
        ok, detail = engine_status(key)
        modes[key] = {
            "label": m["label"],
            "tool": m["tool"],
            "allowed": sorted(m["ext"]),
            "ok": ok,
            "detail": detail,
        }
    return {
        "vault_path": CONFIG.get("vault_path", ""),
        "vault_ok": root is not None,
        "projects": scan_vault(root) if root else [],
        "modes": modes,
        "max_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
    }


@app.get("/api/progress")
def progress() -> dict:
    return dict(PROGRESS)


class VaultConfig(BaseModel):
    vault_path: str = Field(min_length=1, max_length=500)


@app.post("/api/config")
def set_config(payload: VaultConfig) -> dict:
    candidate = Path(payload.vault_path.strip().strip('"')).expanduser()
    if not candidate.is_dir():
        raise HTTPException(400, f"Cartella non trovata: {candidate}")
    CONFIG["vault_path"] = str(candidate.resolve())
    save_config(CONFIG)
    return status()


@app.post("/api/convert")
async def convert(file: UploadFile = File(...), mode: str = Form("digitale")) -> dict:
    if mode not in MODES:
        raise HTTPException(400, f"Modalità sconosciuta: {mode}")
    allowed = MODES[mode]["ext"]

    original = file.filename or "documento"
    ext = Path(original).suffix.lower()
    if ext not in allowed:
        raise HTTPException(
            415,
            f"Formato «{ext or 'sconosciuto'}» non supportato in «{MODES[mode]['label']}». "
            f"Accettati: {', '.join(sorted(allowed))}",
        )

    ok, detail = engine_status(mode)
    if not ok:
        raise HTTPException(503, detail)

    data = await file.read()
    if not data:
        raise HTTPException(400, "Il file è vuoto.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File troppo grande (max {MAX_UPLOAD_BYTES // 1024 // 1024} MB).")

    def report(page: int, pages: int, note: str) -> None:
        set_progress(page=page, pages=pages, note=note)

    def run() -> str:
        if mode == "digitale":
            return engines.digital(data, ext, Path(original).name)
        if mode == "manoscritto":
            return engines.handwriting(data, ext, report)
        return engines.complex_layout(
            data, ext, CONFIG.get("ollama_url"),
            CONFIG.get("glm_model") or engines.DEFAULT_GLM_MODEL, report,
        )

    if not _job_lock.acquire(blocking=False):
        raise HTTPException(409, "C'è già una conversione in corso: aspetta che finisca.")
    started = time.perf_counter()
    try:
        set_progress(busy=True, mode=mode, page=0, pages=0, note="")
        # In threadpool: un PDF lungo con l'OCR può durare minuti, e senza
        # questo l'event loop resterebbe fermo.
        markdown = await run_in_threadpool(run)
    except engines.EngineError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(422, f"Conversione fallita: {type(exc).__name__}: {exc}")
    finally:
        set_progress(busy=False)
        _job_lock.release()

    if not markdown.strip():
        raise HTTPException(
            422,
            "Il documento non contiene testo estraibile. "
            "Se è una scansione, usa «Scritto a mano» o «Layout complesso»."
            if mode == "digitale" else
            "Nessun testo riconosciuto nel documento.",
        )

    return {
        "markdown": markdown,
        "source": Path(original).name,
        "stem": Path(original).stem,
        "kind": allowed[ext],
        "tool": MODES[mode]["tool"],
        "ext": ext,
        "bytes": len(data),
        "chars": len(markdown),
        "words": len(markdown.split()),
        "ms": round((time.perf_counter() - started) * 1000),
    }


class SaveRequest(BaseModel):
    project: str = Field(min_length=1, max_length=120)
    folder: str = Field(default="", max_length=200)
    filename: str = Field(min_length=1, max_length=200)
    markdown: str
    frontmatter: bool = True
    overwrite: bool = False
    source: str = ""
    kind: str = ""
    tool: str = ""


@app.post("/api/save")
def save(req: SaveRequest) -> JSONResponse:
    root = vault_root()
    if root is None:
        raise HTTPException(400, "Vault non configurato o percorso inesistente.")

    target_dir = resolve_target_dir(root, req.project.strip(), req.folder.strip())
    filename = sanitize_filename(req.filename, fallback=Path(req.source).stem or "documento")
    target = target_dir / filename

    if target.exists() and not req.overwrite:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "exists",
                "filename": filename,
                "path": str(target),
                "suggestion": f"{target.stem}-{datetime.now():%Y%m%d-%H%M}.md",
            },
        )

    body = req.markdown
    if req.frontmatter:
        # strumento da una lista chiusa: finisce nel YAML senza virgolette
        tools = {m["tool"] for m in MODES.values()}
        tool = req.tool if req.tool in tools else "TriScribe"
        body = build_frontmatter(target.stem, req.source or filename, req.kind or "documento", tool) + body

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise HTTPException(500, f"Scrittura fallita: {exc}")

    return JSONResponse({
        "ok": True,
        "path": str(target),
        "relative": str(target.relative_to(root)),
        "bytes": len(body.encode("utf-8")),
    })


# --------------------------------------------------------------------------
# Avvio
# --------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="TriScribe — da documento a Markdown, in locale")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    # la console Windows può non avere alcuni simboli: meglio un "?" che un crash
    sys.stdout.reconfigure(errors="replace")

    url = f"http://127.0.0.1:{args.port}"
    print("\n  TriScribe")
    print(f"  {url}")
    print(f"  Vault: {CONFIG.get('vault_path') or '(da configurare)'} {'[ok]' if vault_root() else '[NON TROVATO]'}")
    for key, m in MODES.items():
        ok, detail = engine_status(key)
        print(f"  {m['label']:<20} {'[ok]' if ok else '[--]'} {detail}")
    print("  Ctrl+C per fermare\n")

    if not args.no_browser:
        Timer(1.2, lambda: webbrowser.open(url)).start()

    # host fisso su loopback: il server non è raggiungibile dalla rete aziendale.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
