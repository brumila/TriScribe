"""
I tre motori di TriScribe.

Tutti girano sul PC e nessun documento esce dalla macchina. Le uniche
connessioni sono verso Ollama su questo stesso PC (127.0.0.1, senza proxy) e,
solo se mancano, il download dei modelli PaddleOCR.

  digital()         MarkItDown        file con livello testo (PDF, Word, Excel...),
                    pdfplumber per le tabelle con i bordi dei PDF
  handwriting()     PaddleOCR-VL 1.6  scansioni e foto scritte a mano
  complex_layout()  GLM-OCR + Ollama  tabelle, formule, impaginazioni articolate
"""

from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Iterator

# All'import PaddleX prova a raggiungere i server dei modelli per scegliere da
# dove scaricarli. Con i modelli già in cache non serve: così l'app non apre
# connessioni. Se un modello manca, il download parte comunque.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

# progress(pagina_corrente, pagine_totali, nota)
Progress = Callable[[int, int, str], None]


class EngineError(RuntimeError):
    """Errore da mostrare all'utente così com'è."""


def log(msg: str) -> None:
    """Riga nel terminale di AVVIA.bat: tempi di ogni passaggio, per capire dove si ferma."""
    print(f"  [TriScribe] {msg}", flush=True)


# --------------------------------------------------------------------------
# Pagine: PDF e immagini → immagini PIL RGB, una alla volta
# --------------------------------------------------------------------------
def iter_pages(data: bytes, ext: str, scale: float) -> Iterator[tuple[int, int, object]]:
    """Restituisce (indice, totale, immagine) senza tenere in memoria tutto il PDF."""
    if ext == ".pdf":
        import pypdfium2 as pdfium

        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as exc:
            raise EngineError(f"PDF non leggibile: {exc}") from exc
        try:
            total = len(pdf)
            for i in range(total):
                page = pdf[i]
                try:
                    yield i, total, page.render(scale=scale).to_pil().convert("RGB")
                finally:
                    page.close()
        finally:
            pdf.close()
        return

    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(data))
    except UnidentifiedImageError as exc:
        raise EngineError("Immagine non leggibile.") from exc
    with img:
        total = getattr(img, "n_frames", 1)          # TIFF multipagina
        for i in range(total):
            img.seek(i)
            # exif_transpose: le foto da telefono arrivano già dritte
            yield i, total, ImageOps.exif_transpose(img).convert("RGB")


def to_bgr(img) -> object:
    """PaddleX legge gli array numpy come BGR (convenzione OpenCV)."""
    import numpy as np

    return np.ascontiguousarray(np.asarray(img)[:, :, ::-1])


def paddle_status() -> tuple[bool, str]:
    missing = [m for m in ("paddle", "paddleocr") if importlib.util.find_spec(m) is None]
    if missing:
        return False, "PaddleOCR non è installato: esegui INSTALLA.bat"
    return True, "PaddleOCR-VL 1.6 · in locale"


# Paddle non è thread-safe e ogni modello occupa GB di RAM: un lavoro alla volta.
_paddle_lock = threading.Lock()


def _load_model(factory: Callable[[], object], what: str) -> object:
    """Crea un modello Paddle; se manca e non si scarica, lo dice in italiano."""
    try:
        return factory()
    except Exception as exc:
        raise EngineError(
            f"Non riesco a caricare {what}. Se è il primo uso, i modelli non sono ancora "
            f"scaricati: rilancia INSTALLA.bat con la connessione attiva. Dettaglio: {exc}"
        ) from exc


# --------------------------------------------------------------------------
# 1. Documento digitale — MarkItDown
# --------------------------------------------------------------------------
_markitdown = None


def pdf_has_text(data: bytes, min_chars: int = 20) -> bool:
    """True se ogni pagina del PDF ha già il testo selezionabile: l'OCR non serve."""
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError:
        return False
    try:
        if len(pdf) == 0:
            return False
        for i in range(len(pdf)):
            page = pdf[i]
            try:
                textpage = page.get_textpage()
                try:
                    if len(textpage.get_text_range().strip()) < min_chars:
                        return False
                finally:
                    textpage.close()
            finally:
                page.close()
        return True
    finally:
        pdf.close()


def _md_cell(text: str | None) -> str:
    return " ".join((text or "").split()).replace("|", "\\|")


def _table_md(rows: list[list[str | None]]) -> str:
    rows = [[_md_cell(c) for c in r] for r in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return ""
    ncol = max(len(r) for r in rows)
    if ncol == 1:
        # riquadro con titolo: nei moduli è un'etichetta, non una tabella
        title, *body = [r[0] for r in rows]
        return "\n\n".join([f"**{title}**", *body])
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * ncol]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def pdf_tables_markdown(data: bytes) -> str | None:
    """Markdown di un PDF digitale con le tabelle a bordi ricostruite.

    MarkItDown riconosce i moduli senza bordi ma appiattisce le tabelle con
    le righe disegnate: ogni cella finisce su una riga a sé. pdfplumber le
    legge dai bordi. None se il PDF non ha tabelle con almeno due colonne:
    in quel caso resta MarkItDown.
    """
    import pdfplumber

    blocks: list[list] = []          # ["text", righe] oppure ["table", celle], in ordine
    grid_found = False
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            width, height = page.width, page.height
            # le cornici di pagina sembrano tabelle ma escono dai bordi
            tables = [
                t for t in page.find_tables()
                if t.bbox[0] >= -1 and t.bbox[1] >= -1 and t.bbox[2] <= width + 1 and t.bbox[3] <= height + 1
            ]
            items = []                       # (top, x0, tipo, contenuto)
            rest = page
            for t in tables:
                rows = t.extract()
                if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                    grid_found = True
                items.append((t.bbox[1], t.bbox[0], "table", rows))
                rest = rest.outside_bbox(t.bbox, strict=False)
            for line in rest.extract_text_lines(return_chars=False):
                items.append((line["top"], line["x0"], "text", line["text"]))
            items.sort(key=lambda b: (b[0], b[1]))

            for n, (_, _, kind, content) in enumerate(items):
                prev = blocks[-1] if blocks else None
                if kind == "text":
                    if prev and prev[0] == "text":
                        prev[1].append(content)
                    else:
                        blocks.append(["text", [content]])
                elif (n == 0 and prev and prev[0] == "table"
                      and max(map(len, prev[1]), default=0) == max(map(len, content), default=0) > 1):
                    # tabella che prosegue dalla pagina prima: stesse colonne, niente in mezzo
                    prev[1].extend(content)
                else:
                    blocks.append(["table", content])
            page.close()

    if not grid_found:
        return None
    parts = [_table_md(c) if kind == "table" else "\n".join(c) for kind, c in blocks]
    return "\n\n".join(p for p in parts if p).strip()


def digital(data: bytes, ext: str, filename: str) -> str:
    global _markitdown
    from markitdown import MarkItDown, StreamInfo

    if ext == ".pdf":
        try:
            md = pdf_tables_markdown(data)
        except Exception as exc:              # pdfplumber in difficoltà: resta MarkItDown
            log(f"tabelle PDF non lette ({type(exc).__name__}: {exc}), uso MarkItDown")
            md = None
        if md:
            log("PDF con tabelle a bordi: ricostruite con pdfplumber")
            return md

    if _markitdown is None:
        # enable_plugins=False e nessun llm_client/docintel_endpoint:
        # nessun converter può contattare la rete.
        _markitdown = MarkItDown(enable_plugins=False)
    # convert_stream: nessun I/O di rete, nessun file temporaneo sul disco.
    with io.BytesIO(data) as buf:
        result = _markitdown.convert_stream(
            buf, stream_info=StreamInfo(extension=ext, filename=filename)
        )
    return getattr(result, "markdown", None) or getattr(result, "text_content", "") or ""


# --------------------------------------------------------------------------
# 2. Scritto a mano — PaddleOCR-VL 1.6
# --------------------------------------------------------------------------
HANDWRITING_SCALE = 2.0      # il default di PaddleX per rendere i PDF

# Blocchi che non finiscono nel Markdown: il default di PaddleOCR-VL 1.6, più
# image e chart. TriScribe non salva le immagini, e i loro riferimenti
# resterebbero link rotti nel vault.
VL_IGNORE_LABELS = [
    "number", "footnote", "header", "header_image",
    "footer", "footer_image", "aside_text", "image", "chart", "seal",
]

_vl = None


def _plain_markdown(res) -> dict:
    """Markdown senza l'HTML di centratura che PaddleOCR-VL aggiunge di default."""
    try:
        return res._to_markdown(pretty=False)
    except (AttributeError, TypeError):      # API privata: se cambia, ripiego
        return res.markdown


def handwriting(data: bytes, ext: str, progress: Progress) -> str:
    global _vl
    with _paddle_lock:
        if _vl is None:
            progress(0, 0, "Carico PaddleOCR-VL: la prima volta scarica i modelli")
            from paddleocr import PaddleOCRVL

            _vl = _load_model(lambda: PaddleOCRVL(pipeline_version="v1.6"), "PaddleOCR-VL")

        pages = []
        for i, total, img in iter_pages(data, ext, HANDWRITING_SCALE):
            progress(i + 1, total, "")
            started = time.perf_counter()
            for res in _vl.predict(to_bgr(img), markdown_ignore_labels=VL_IGNORE_LABELS):
                pages.append(_plain_markdown(res))
            log(f"PaddleOCR-VL pagina {i + 1}/{total}: {time.perf_counter() - started:.0f} s")
        return _vl.concatenate_markdown_pages(pages).strip()


# --------------------------------------------------------------------------
# 3. Layout complesso — GLM-OCR via Ollama
# --------------------------------------------------------------------------
# Stesso schema della pipeline ufficiale di GLM-OCR: PP-DocLayoutV3 trova le
# regioni della pagina, GLM-OCR legge ognuna con il prompt del suo tipo.
# Non usa l'SDK glmocr: di default manda i documenti all'API cloud di Zhipu.
# Prompt, parametri e regole di impaginazione vengono da GLM-OCR (Apache 2.0):
# vedi NOTICE.
COMPLEX_SCALE = 200 / 72     # 200 dpi, il pdf_dpi di GLM-OCR

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_GLM_MODEL = "glm-ocr"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}

# Da glmocr/config.yaml: task_prompt_mapping e label_task_mapping.
GLM_PROMPTS = {
    "text": "Text Recognition:",
    "table": "Table Recognition:",
    "formula": "Formula Recognition:",
}
GLM_TABLE_LABELS = {"table"}
GLM_FORMULA_LABELS = {"display_formula", "inline_formula"}
GLM_DROP_LABELS = {          # skip + abandon: niente testo da riconoscere
    "chart", "image", "header", "footer", "number", "footnote",
    "aside_text", "reference", "footer_image", "header_image",
}
# Parametri di generazione di GLM-OCR (page_loader). num_ctx alzato perché
# una pagina intera a 200 dpi supera il contesto di default di Ollama.
GLM_OPTIONS = {
    "temperature": 0,
    "top_p": 0.00001,
    "top_k": 1,
    "repeat_penalty": 1.1,
    "num_ctx": 16384,
}
# Token massimi per risposta. GLM-OCR ne prevede 8192 ovunque, ma senza GPU
# una risposta che si ripete in loop fino a 8192 blocca la pagina per decine
# di minuti. Questi tetti stanno larghi sui contenuti reali.
GLM_MAX_TOKENS = {"text": 2048, "table": 4096, "formula": 1024, "page": 4096}
OLLAMA_TIMEOUT = 900         # secondi per regione: senza GPU può essere lento

# Opener senza proxy: la richiesta va dritta a 127.0.0.1 anche se il PC
# ha un proxy aziendale configurato.
_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ollama_base(url: str | None) -> str | None:
    """L'URL di Ollama, solo se punta a questo PC. Altrimenti None."""
    raw = (url or DEFAULT_OLLAMA_URL).strip().rstrip("/")
    try:
        host = urllib.parse.urlsplit(raw).hostname
    except ValueError:
        return None
    return raw if host in LOOPBACK else None


def _ollama(base: str, path: str, payload: dict | None = None, timeout: float = 10) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        base + path, data=body, headers={"Content-Type": "application/json"}
    )
    with _direct.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def glm_status(url: str | None, model: str) -> tuple[bool, str]:
    base = ollama_base(url)
    if base is None:
        return False, "ollama_url in config.json deve puntare a questo PC (127.0.0.1)"
    try:
        tags = _ollama(base, "/api/tags", timeout=2)
    except (urllib.error.URLError, OSError, ValueError):
        return False, "Ollama non è avviato: aprilo e premi ↻"
    names = {m.get("name", "") for m in tags.get("models", [])}
    if not any(n == model or n.split(":")[0] == model for n in names):
        return False, f"Modello non scaricato: esegui «ollama pull {model}»"
    layout = "con analisi del layout" if layout_available() else "senza analisi del layout"
    return True, f"GLM-OCR via Ollama · {layout}"


def _recognize(base: str, model: str, img, task: str, limit: str = "") -> str:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    payload = {
        "model": model,
        "prompt": GLM_PROMPTS[task],
        "images": [base64.b64encode(buf.getvalue()).decode("ascii")],
        "stream": False,
        "options": {**GLM_OPTIONS, "num_predict": GLM_MAX_TOKENS[limit or task]},
    }
    try:
        out = _ollama(base, "/api/generate", payload, timeout=OLLAMA_TIMEOUT)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise EngineError(f"Ollama ha risposto {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise EngineError(f"Ollama non raggiungibile: {exc}") from exc
    if "error" in out:
        raise EngineError(f"Ollama: {out['error']}")
    return out.get("response") or ""


def _format_block(content: str, label: str, task: str) -> str:
    """Le regole di impaginazione di GLM-OCR (ResultFormatter._format_content)."""
    content = (content or "").strip()
    if not content:
        return ""
    if task == "formula":
        content = re.sub(r"^(\$\$|\\\[|\\\()\s*", "", content)
        content = re.sub(r"\s*(\$\$|\\\]|\\\))$", "", content)
        return "$$\n" + content + "\n$$"
    if task == "table":
        return content
    if label == "doc_title":
        return "# " + re.sub(r"^#+\s*", "", content)
    if label == "paragraph_title":
        content = re.sub(r"^[-*]\s+", "", content)
        return "## " + re.sub(r"^#+\s*", "", content)
    if content[0] in "·•" or content.startswith("* "):
        content = "- " + content[1:].lstrip()
    return content


_layout = None               # None: da caricare · False: non disponibile


def layout_available() -> bool:
    return _layout is not False and paddle_status()[0]


def _regions(img) -> list[dict]:
    """Regioni da leggere, in ordine di lettura. Vuota se il layout non è disponibile."""
    global _layout
    if not layout_available():
        return []
    if _layout is None:
        from paddleocr import LayoutDetection

        try:
            _layout = _load_model(lambda: LayoutDetection(model_name="PP-DocLayoutV3"), "l'analisi del layout")
        except EngineError as exc:
            # Ollama da solo basta: si ripiega sulla pagina intera, e lo si dice.
            print(f"  [!] {exc}\n      Layout complesso continua a pagina intera.", flush=True)
            _layout = False
            return []
    results = list(_layout.predict(to_bgr(img), threshold=0.3, layout_nms=True))
    boxes = list(results[0].get("boxes") or []) if results else []
    ordered = sorted(
        enumerate(boxes),
        key=lambda t: (t[1].get("order") is None, t[1].get("order") or 0, t[0]),
    )
    return [b for _, b in ordered if b.get("label", "text") not in GLM_DROP_LABELS]


def complex_layout(data: bytes, ext: str, url: str | None, model: str, progress: Progress) -> str:
    base = ollama_base(url)
    if base is None:
        raise EngineError("ollama_url in config.json deve puntare a questo PC (127.0.0.1).")

    with _paddle_lock:          # anche l'analisi del layout usa Paddle
        out_pages = []
        for i, total, img in iter_pages(data, ext, COMPLEX_SCALE):
            first_load = _layout is None and layout_available()
            progress(i + 1, total, "Carico l'analisi del layout" if first_load else "")
            started = time.perf_counter()
            regions = _regions(img)
            log(f"GLM-OCR pagina {i + 1}/{total}: {len(regions)} regioni trovate in {time.perf_counter() - started:.0f} s")
            blocks = []
            for n, box in enumerate(regions, 1):
                label = box.get("label", "text")
                task = (
                    "table" if label in GLM_TABLE_LABELS
                    else "formula" if label in GLM_FORMULA_LABELS
                    else "text"
                )
                x0, y0, x1, y1 = (int(v) for v in box["coordinate"])
                if x1 - x0 < 4 or y1 - y0 < 4:
                    continue
                progress(i + 1, total, f"Regione {n} di {len(regions)}")
                started = time.perf_counter()
                text = _recognize(base, model, img.crop((x0, y0, x1, y1)), task)
                log(f"  regione {n}/{len(regions)} {label} {x1 - x0}x{y1 - y0}px: "
                    f"{time.perf_counter() - started:.0f} s, {len(text)} caratteri")
                block = _format_block(text, label, task)
                if block:
                    blocks.append(block)
            if not regions:
                # Niente layout, o nessuna regione di testo trovata: pagina intera.
                progress(i + 1, total, "Pagina intera")
                started = time.perf_counter()
                text = _recognize(base, model, img, "text", limit="page")
                log(f"  pagina intera: {time.perf_counter() - started:.0f} s, {len(text)} caratteri")
                block = _format_block(text, "text", "text")
                blocks = [block] if block else []
            out_pages.append("\n\n".join(blocks))
        return "\n\n".join(p for p in out_pages if p).strip()
