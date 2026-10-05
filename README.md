# TriScribe

TriScribe trasforma i tuoi documenti in Markdown senza farli uscire dal PC. Una sola schermata: carichi il file, scegli cosa vuoi fare e ottieni un `.md` pronto per Obsidian o per qualsiasi editor.

> 🚧 **In costruzione.** Il codice arriva con il primo rilascio.

## Cosa fa

- **Converte i documenti digitali.** PDF con testo selezionabile, Word, Excel, PowerPoint, HTML e CSV diventano Markdown in pochi istanti. Il motore è MarkItDown.
- **Legge lo scritto a mano.** Appunti, quaderni e moduli compilati a penna, da scansione o da foto. Il motore è PaddleOCR. Il corsivo resta il caso più difficile per qualsiasi OCR: rileggi sempre il risultato.
- **Ricostruisce i layout complessi.** Tabelle, formule, schede tecniche, timbri e pagine a più colonne. Il motore è GLM-OCR.
- **Salva nel tuo vault.** Agganci la cartella di Obsidian e TriScribe ti propone le sue sottocartelle come destinazione.

### Quale modalità scegliere

1. **Riesci a selezionare il testo del PDF con il mouse?** → 📄 Documento digitale. È la più veloce e la più fedele.
2. **Il contenuto è scritto a mano?** → ✍️ Scritto a mano.
3. **È una scansione o una foto con tabelle, formule o impaginazione articolata?** → 🧩 Layout complesso.

## Cosa serve

- Un **PC Windows**. Non serve una scheda video dedicata: TriScribe è pensato per un portatile con processore Intel Core i5 di 13ª generazione e 16 GB di RAM.
- Una **connessione a internet solo la prima volta**, per scaricare i modelli OCR.

Senza scheda video la modalità digitale è quasi istantanea; le due modalità OCR usano modelli neurali e richiedono più tempo per pagina.

## Installazione e avvio

Le istruzioni complete arrivano con il primo rilascio. L'avvio funziona così:

1. Doppio clic su **Avvia**.
2. Si apre il terminale; dopo qualche istante si apre la pagina nel browser.
3. L'app resta attiva finché il terminale è aperto. Per chiuderla, chiudi il terminale.

## Privacy

- **Tutta l'elaborazione avviene sul tuo PC.** Nessuna API cloud, nessuna chiave da inserire, nessun account.
- **Il browser è solo la finestra.** La pagina è servita dal tuo stesso PC: i documenti non passano da internet.
- **Internet serve una volta sola**, per scaricare i modelli. Dopo, TriScribe è pensato per lavorare offline.
- GLM-OCR offre anche un'API cloud: TriScribe **non la usa**, il modello gira sulla tua macchina.

## Crediti

TriScribe nasce da tre progetti open source, uno per modalità:

- [MarkItDown](https://github.com/microsoft/markitdown) di Microsoft, per i documenti digitali.
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) di PaddlePaddle, per lo scritto a mano.
- [GLM-OCR](https://github.com/zai-org/GLM-OCR) di Z.ai, per i layout complessi.

Li ho riuniti in una sola schermata che gira tutta in locale, con la scelta della modalità in base al documento e il salvataggio del Markdown nelle cartelle del tuo vault.
