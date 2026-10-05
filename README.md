# TriScribe

TriScribe trasforma i tuoi documenti in Markdown senza farli uscire dal PC. Una sola schermata: scegli cosa vuoi fare, trascini il file e ottieni un `.md` pronto per Obsidian o per qualsiasi editor.

> **Prima versione.** I tre motori sono integrati. La qualità del riconoscimento va ancora misurata su documenti reali, a partire dal corsivo italiano.

## Cosa fa

- **Converte i documenti digitali.** PDF con testo selezionabile, Word, Excel e PowerPoint diventano Markdown in pochi istanti. Il motore è MarkItDown.
- **Legge lo scritto a mano.** Appunti, quaderni e moduli compilati a penna, da scansione o da foto. Il motore è PaddleOCR-VL. Il corsivo resta il caso più difficile per qualsiasi OCR: rileggi sempre il risultato.
- **Ricostruisce i layout complessi.** Tabelle, formule, schede tecniche e pagine a più colonne. Il motore è GLM-OCR: un modello trova le regioni della pagina, GLM-OCR legge ognuna con il prompt adatto (testo, tabella o formula).
- **Ti dice a che punto è.** Con l'OCR ogni pagina richiede tempo: vedi la pagina in corso e il tempo trascorso.
- **Salva nel tuo vault.** Agganci una cartella, per esempio il tuo vault Obsidian, e TriScribe ti propone le sue sottocartelle come destinazione. Agganci un'altra cartella e vedi la sua struttura. In cima al file aggiunge un front-matter con titolo, fonte, data e motore usato.

### Quale modalità scegliere

1. **Riesci a selezionare il testo del PDF con il mouse?** → 📄 Documento digitale. È la più veloce e la più fedele.
2. **Il contenuto è scritto a mano?** → ✍️ Scritto a mano.
3. **È una scansione o una foto con tabelle, formule o impaginazione articolata?** → 🧩 Layout complesso.

Se scegli Documento digitale su una scansione, TriScribe se ne accorge e ti indica le altre due.

## Cosa serve

- Un **PC Windows** con **Python tra 3.10 e 3.13**. Non serve una scheda video dedicata: TriScribe è pensato per un portatile con processore Intel Core i5 di 13ª generazione e 16 GB di RAM.
- **[Ollama](https://ollama.com/download)**, solo per Layout complesso. Si installa senza permessi di amministratore.
- Qualche GB libero su disco per pacchetti e modelli (circa 2 GB per PaddleOCR, 2,2 GB per GLM-OCR).
- Una **connessione a internet solo durante l'installazione**.

Senza scheda video la modalità digitale è quasi istantanea; le due modalità OCR usano modelli neurali e richiedono più tempo per pagina.

## Installazione

1. Scarica il repository: **Code › Download ZIP**, oppure clonalo con GitHub Desktop.
2. Doppio clic su **`INSTALLA.bat`**. Crea un ambiente Python isolato in `%LOCALAPPDATA%\TriScribe`, installa i pacchetti e scarica i modelli di PaddleOCR. Non servono permessi di amministratore e il Python di sistema non viene toccato.
3. Per Layout complesso installa Ollama e, una volta sola, lancia `ollama pull glm-ocr`. Se Ollama è già installato quando lanci `INSTALLA.bat`, il modello lo scarica lui.

Su un PC aziendale l'installer rileva il proxy e, se pip si blocca per i certificati, riprova con `--trusted-host`.

## Avvio

1. Doppio clic su **`AVVIA.bat`**.
2. Si apre il terminale; dopo qualche istante si apre la pagina nel browser su `http://127.0.0.1:8766`.
3. L'app resta attiva finché il terminale è aperto. Per chiuderla, chiudi il terminale.

Al primo avvio clicca sul percorso in alto a destra e incolla la cartella dove vuoi salvare. Se una modalità non è pronta, la sua scheda ti dice perché (Ollama spento, modello mancante). Risolto il problema, premi **↻**.

## Privacy

- **Tutta l'elaborazione avviene sul tuo PC.** Nessuna API cloud, nessuna chiave da inserire, nessun account.
- **Il server ascolta solo su `127.0.0.1`**: dalla rete non è raggiungibile.
- **GLM-OCR gira dentro Ollama, sul tuo PC.** TriScribe accetta per Ollama solo un indirizzo locale e lo chiama senza passare dal proxy.
- **TriScribe non usa l'SDK `glmocr`**: nella sua configurazione di default manda i documenti all'API cloud di Zhipu.
- **MarkItDown gira senza plugin** e senza i servizi Azure e OpenAI che potrebbe usare.
- **Internet serve solo all'installazione.** Una volta scaricati i modelli, PaddleOCR non contatta più i loro server.
- **Nessun file temporaneo**: i documenti restano in memoria finché non li salvi tu.

## Impostazioni

`config.json`, accanto ad `app.py`, si crea al primo salvataggio del percorso. Resta sul tuo PC e non finisce su GitHub.

| Chiave | A cosa serve | Default |
|---|---|---|
| `vault_path` | Cartella in cui salvare. Si cambia dall'interfaccia | vuoto |
| `ollama_url` | Indirizzo di Ollama. Solo indirizzi locali | `http://127.0.0.1:11434` |
| `glm_model` | Nome del modello GLM-OCR in Ollama | `glm-ocr` |

## Limiti

- Il corsivo resta difficile per qualsiasi OCR: rileggi sempre il risultato prima di usarlo.
- Le immagini dentro i documenti non vengono salvate: TriScribe estrae il testo.
- Fogli Excel con celle unite o grafici perdono parte della struttura; le tabelle piatte vengono bene.
- Una conversione alla volta: i modelli OCR occupano qualche GB di RAM.

## Crediti

TriScribe nasce da tre progetti open source, uno per modalità:

- [MarkItDown](https://github.com/microsoft/markitdown) di Microsoft, per i documenti digitali.
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) di PaddlePaddle, per lo scritto a mano.
- [GLM-OCR](https://github.com/zai-org/GLM-OCR) di Z.ai, per i layout complessi.

Li ho riuniti in una sola schermata che gira tutta in locale, con la scelta della modalità in base al documento e il salvataggio del Markdown nelle cartelle del tuo vault.
