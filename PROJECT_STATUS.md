# REGISTRO STATO DI PROGETTO E CHANGELOG
**Progetto**: Gestionale Unificato Viessmann Vitocal 111-S + BTicino Smarther (Abitazione Climatica Montana - Zona E)  
**Ultimo aggiornamento**: 26 Novembre 2026  
**Autore / Assistente**: Antigravity AI & Giacomo  

---

## 1. OBIETTIVI RAGGIUNTI (FASE 1 — BANOMETRO & DESKTOP GUI)

- [x] **Integrazione Git CLI & Automazione Deploy GitHub al 100% (Addio Drag-and-Drop)**:
  - Installato e configurato Git per Windows con eccezione TinyWall su `C:\Program Files\Git\ucrt64\libexec\git-core\git-remote-https.exe`.
  - Inizializzato repository Git locale collegato a `origin/main` (`giacomogussetti-lgtm/vitocal-remote`).
  - Eseguito primo push e allineamento con successo: rimossi i vecchi file di cache `__pycache__` remoti, protetti tutti i dati sensibili locali (`.env`, `token.save`, database) via `.gitignore`.
  - L'assistente AI ora opera in piena autonomia con commit e push diretti da terminale senza richiedere nessun intervento manuale dell'utente su GitHub Web.
- [x] **Gestione Ritenzione Dati Cloud & Rotazione Automatica (Campionamento 5 Minuti - Finestra 6 Mesi)**:
  - Progettata e implementata l'architettura **"Hot Buffer + Cold Storage"** in `scripts/cloud_logger.py`:
    - **Hot Window**: `data/cloud_telemetry.jsonl` mantiene una finestra scorrevole degli **ultimi 6 mesi (180 giorni)** di campionamento continuo a 5 minuti (`MAX_HOT_SAMPLES = 51840`, soglia `ROTATION_THRESHOLD = 52500`, `MIN_BYTES_BEFORE_CHECK = 32_000_000`). Pesa circa 34.7 MB uncompressed / solo ~3.8 MB trasferiti su 4G grazie alla compressione gzip nativa di GitHub.
    - **Cold Archive**: al superamento della soglia dei 6 mesi, i campioni più vecchi vengono archiviati mensilmente in formato compresso `data/archive/telemetry_YYYY-MM.jsonl.gz`.
    - **Filtri Web Aggiornati**: aggiunti selettori a 30gg, 3 Mesi e 6 Mesi (Tutti) nell'interfaccia PWA.
    - **Compatibilità Desktop & SQLite**: `DatabaseManager.import_file()` supporta nativamente sia file `.jsonl` sia archivi `.jsonl.gz`, permettendo all'applicazione desktop di conservare a vita l'intero storico su SQLite locale (`vitocal_telemetry.db`).
- [x] **Correzione Asse Temporale Continuo nei Grafici Mobile PWA**:
  - Risolto il problema dei campioni visualizzati a intervalli orizzontali equidistanti:
    * Impositata esplicitamente la modalità `distribution: 'linear'` e `bounds: 'ticks'` sulla scala X (`type: 'time'`).
    * Implementato l'ancoraggio proporzionale esatto calcolando dinamicamente `min` e `max` sulle ore attive (`latestMs - hours`), garantendo che intervalli di durata diversa (es. 5 min vs 2 ore) mostrino distanze grafiche rigorosamente proporzionali alla fisica temporale.
    * Aggiornata la versione cache Service Worker (`vitocal-remote-v3`) per forzare l'aggiornamento automatico e istantaneo su tutti gli smartphone senza residui di vecchie cache.
- [x] **Disaccoppiamento Cron GitHub Actions & Integrazione cron-job.org**:
  - Risolto il ritardo tipico dei cron GitHub su runner gratuiti integrando trigger esterno HTTPS via `cron-job.org` (`POST .../dispatches`).
  - Ottenuto campionamento puntuale al secondo esatto, funzionante 24/7 a computer spento.
  - Semplificato `telemetry_logger.yml` rimuovendo lo scheduler interno ridondante e lasciando `workflow_dispatch` gestito con gruppo di concorrenza `concurrency: telemetry-logger`.
- [x] **Configurazione e Sicurezza (.env)**:
  - Client ID e account Viessmann Developer configurati e operativi.
  - Client ID, Client Secret e `read_smarther`/`write_smarther` Refresh Token BTicino/Netatmo configurati.
  - File `.gitignore` impostato per proteggere token, dump e database da commit accidentali.
- [x] **Connettore Viessmann Cloud (`api/viessmann.py`)**:
  - Autenticazione OAuth2 automatica con cache in `token.save`.
  - Risolto bug di targeting: agganciato correttamente il generatore termico `CU401B_S_64` anziché il gateway `Heatbox3`.
  - Scaricato dump integrale di **193 parametri hardware reali** in `data/dumps/viessmann_features.json`.
  - Mappati sensori termodinamici: mandata, ritorno, puffer 200L, ACS, pressione gas caldo (10 bar), temperature gas circuito frigo, modulazione compressore % e COP calcolati.
  - Implementati metodi di scrittura sicura con *read-back check*: curva climatica (slope/shift), temperature setpoint (normale/ridotta) e modalità.
- [x] **Connettore BTicino Smarther (`api/bticino.py`)**:
  - Risolto problema degli scope: abilitati `read_smarther` e `write_smarther`.
  - Rilevata con successo l'abitazione, stanza `Corridoio`, e termostato modulo Smarther `BNS` (firmware 40).
  - Lettura in tempo reale: temperatura ambiente (**7.8 °C**), setpoint (**7.0 °C**), umidità (**61%**), stato relè/pompa Grundfos (0/1).
  - **Risolto Bug di Scrittura Setpoint (Errore 403 Code 13)**:
    - Identificato che per moduli Smarther (`BNS`), l'endpoint Netatmo Energy `/setroomthermpoint` è bloccato da API (`Operation is forbidden`).
    - Migrato all'endpoint Home + Control `POST /api/setstate` con schema specifico per room `therm_setpoint_mode` e `therm_setpoint_temperature`.
    - Testato e verificato con successo su hardware reale: impostazione setpoint manuale, ripristino programma `home`, e modalità antigelo `hg`.
    - Aggiunta gestione trasparente del token scaduto con re-autenticazione automatica.
    - Aggiunta gestione errore transitorio 6 (`device_unreachable`) per preservare i grafici continui senza drop a zero o `None`.
- [x] **Persistenza Dati SQLite (`storage/database.py`)**:
  - Tabella `telemetry_samples` versionata e indicizzata per storicizzazione serie temporali.
- [x] **Diagnostica & Script CLI**:
  - `scripts/feature_dumper.py`: report diagnostico hardware e albero categorie.
  - `test_bench.py`: console interattiva per testare letture e comandi di scrittura senza GUI.
- [x] **Applicazione Desktop PyQt6 (`ui/main_window.py` & `app.py`)**:
  - **Risolto Contrasto Finestre di Dialogo & Popup**:
    - Abilitato motore di rendering cross-platform `Fusion` in `app.py`.
    - Applicato stile scuro ad alto contrasto per tutti i `QMessageBox`, `QDialog` e `QInputDialog`: sfondo ardesia scuro (`#1e222b`), testo bianco brillante ad alta leggibilità (`#f8fafc`) e pulsanti blu cobalto.
  - **Risolto Falso Mismatch su Scrittura Setpoint Viessmann (`api/viessmann.py`)**:
    - Risolto bug della cache interna PyViCare (60s): introdotta invalidazione forzata `clear_cache()` e gestione della sincronizzazione asincrona del cloud per evitare falsi errori di verifica su temperatura normale e ridotta.
  - **Nuovo Sinottico Impianto & Mappatura Sonde (`ui/synoptic_widget.py`)**:
    - Scheda dedicata ad alta risoluzione in stile SCADA industriale:
    - **Risolto Spaziamento e Sovrapposizioni**: allargato il canvas a 1280x600 px con QScrollArea responsive. Spaziate le sezioni idrauliche per garantire zero sovrapposizioni tra tubazioni, etichette e box.
    - I tag di misura su mandata e ritorno primario sono ora flottanti al centro delle campate con indicatori a trattino, senza collidere con i riquadri della PdC e del Puffer.
    - **Integrazione Telemetria Completa Viessmann (14+ parametri)**:
      * Circuito Frigo: Compressore (Stato/Modulazione %), Pressione Gas Caldo (bar), T Gas Caldo, T Gas Liquido, T Gas Aspirazione.
      * Idraulica & Circolatori: Sonda Esterna OAT, Bollitore ACS 220L, Circolatore Primario PdC (%), COP Riscaldamento, COP Totale, COP ACS.
      * Diagnostica: Ore di funzionamento compressore, numero di avvii totali, Curva Climatica (Slope/Shift), Programma e Modo.
    - Puffer inerziale 200L con sfumatura di stratificazione termica e sonda di accumulo.
    - Pompa di rilancio secondaria Grundfos con simbolo SCADA illuminato verde quando attiva.
    - Abitazione con serpentina massetto radiante (200 m²), scheda termostato BTicino Smarther (Corridoio) con temperatura ambiente, setpoint, umidità e stato consenso relè.
    - **Precaricamento Istantaneo all'Avvio**: la finestra principale precarica l'ultimo campione da SQLite all'apertura, popolando subito il sinottico senza attendere il primo polling cloud.
  - **Nuovo Grafico Interattivo Curva Climatica LWT vs OAT (`ui/heating_curve_widget.py`)**:
    - Visualizzazione grafica della temperatura di mandata calcolata in funzione della temperatura esterna (-20 °C a +20 °C).
    - **Riferimento Curva alla Temperatura Normale ($T_{\text{normale}}$)**: chiarito e implementato il legame fisico Viessmann per cui la curva è pivotata sulla Temperatura Normale desiderata.
    - Aggiunta linea tratteggiata verticale violetta sull'asse X al valore di $T_{\text{normale}}$ reale (es. 12.0 °C) e badge informativo sul grafico che riporta parametri e temperatura di riferimento.
    - Sincronizzazione dinamica bidirezionale: variando la Temperatura Normale nei comandi o ricevendo nuova telemetria, l'intera curva trasla parallelamente in tempo reale.
    - Punto di lavoro reale in tempo reale evidenziato con marker dorato (es. a 5.9 °C ➔ mandata calcolata).
    - Fascia verde di sicurezza pavimento radiante (20-38 °C) e linea di warning rossa a 40 °C (limite massetto).
  - **Risolto Errore Salvataggio Curva Climatica (`api/viessmann.py`)**:
    - Risolto errore `name 'time' is not defined` aggiungendo l'import del modulo `time`.
    - Risolto bug critico dell'ordine degli argomenti in PyViCare: la libreria richiede `setHeatingCurve(shift, slope)`. L'invio ora utilizza parametri espliciti a parola chiave `setHeatingCurve(shift=..., slope=...)` garantendo il corretto salvataggio di Inclinazione e Livello su Viessmann Cloud IoT con esito verificato (`Slope: 0.6, Shift: 0`).
  - **Spazio Predisposto per Preset Multi-Dispositivo**:
    - Rimossi i vecchi pulsanti hardcoded provvisori.
    - Introdotto pulsante fittizio `[ ➕ Crea Nuovo Preset Personalizzato ]` per futura configurazione.
    - Aggiunta scheda promemoria dettagliata con spiegazione dell'orchestrazione congiunta Viessmann + BTicino e dell'obiettivo termodinamico di accumulo termico nel massetto nelle ore a massimo COP.
  - **Doppio Clic sugli Assi del Grafico & Range Personalizzato (Auto vs Fixed)**:
    - Implementata classe `ScalableAxisItem`: doppio clic sugli estremi di un asse apre la finestra di dialogo `AxisRangeDialog` per digitare inizio e fondo scala.
    - Possibilità di fissare la scala a valori custom (es. Asse Sx 0-45 °C, Asse Dx 0-100%) o mantenere Auto-Range.
    - Pulsanti di stato dedicati nella barra del grafico (`📐 Scala Sx: AUTO / FIXED`, `📐 Scala Dx: AUTO / FIXED`).
  - **Continuità e Interpolazione Grafici (`connect="finite"`)**:
    - Abilitato `connect="finite"` su tutte le tracce `PlotCurveItem`: i grafici rimangono continui anche in presenza di campioni isolati senza spezzare le linee o lasciare punti isolati.
    - Aggiunto fallback automatico su SQLite in `FetchDataWorker`: se una chiamata al cloud va temporaneamente in timeout, il logger riutilizza l'ultima misura valida nota anziché inserire buchi `NULL`.
    - Bonificate le righe storiche 10-12 nel database locale riallineando la temperatura a 7.8 °C e il setpoint a 7.0 °C.
  - **Dashboard Live**: visualizzazione grafica moderna delle temperature dei due circuiti, stato compressore, modulazione e consenso Grundfos.
  - **Banchetto Comandi & Preset**: slider/box per curva climatica e setpoint con conferma visiva + 4 preset one-click (*Assenza Diurna*, *Solo Antigelo*, *Pre-Riscaldamento*, *Weekend Comfort*).
  - **JSON Feature Inspector**: ricerca e ispezione interattiva formattata di tutti i 193 parametri hardware.
- [x] **Grafici Multi-Asse Avanzati & Ispezione Dinamica (`pyqtgraph`)**:
  - **Mirino Interattivo a Croce (Crosshair Cursor) & HUD Inspector con Snap Magnetico in X**:
    - **Snap Magnetico sull'Asse X sui Punti Acquisiti Reali**: il cursore verticale (`crosshair_v`) non fluttua più nel vuoto sui segmenti interpolati, ma si ancora magneticamente (tramite ricerca binaria $O(\log N)$) alla coordinata temporale esatta del campione reale più vicino.
    - La linea verticale passa esattamente al centro dei marker (`o`) dei campioni misurati.
    - Barra HUD informativa superiore dinamica (`lbl_chart_hover_info`): riporta il numero del campione reale `📍 Campione #id`, data/ora esatta del prelievo e i valori acquisiti sul campo di tutti i canali attivi con codice colore dedicato, indicando chiaramente che non si tratta di valori interpolati.
  - **Evidenziazione Dinamica delle Tracce (Trace Hover Highlight) & Tooltip Fluttuante Interattivo**:
    - **Highlight Curva al Passaggio del Mouse**: quando il puntatore si avvicina a una linea (soglia di prossimità 28 px), la traccia interessata si **ispessisce a 4.5 px**, ingrandisce i marker di campionamento e viene portata in primo piano (`z-order: 100`), mentre le altre tracce sullo sfondo vengono delicatamente attenuate in trasparenza (`alpha 150`).
    - **Badge Fluttuante Dinamico (Tool Dinamico)**: sopra il punto di campionamento esatto agganciato compare un badge semitrasparente scuro con bordo del colore della traccia, riportante il **Nome della Grandezza** e il **Valore Esatto Misurato** (es. *T Accumulo Puffer 200L: 19.8 °C*), affiancato da un punto marker circolare evidenziato in bianco lucido. All'allontanarsi del mouse, le tracce e i marker ripristinano istantaneamente l'aspetto standard senza alcun lag.
  - **Asse Temporale Assoluto (`AbsoluteTimeAxisItem`)**: formattazione intelligente della data e ora locale (`GG/MM HH:MM` o `HH:MM:SS` in base allo zoom).
  - Etichetta chiara sull'asse X: `Tempo Assoluto (Data & Ora Locale)`.
  - Punti di campionamento evidenziati con simboli a cerchietto colorati (`o`).
  - Doppio asse Y sincronizzato: Asse Sinistro per le Temperature (°C), Asse Destro per Modulazione %, Pressione bar, COP e rotazione pompa.
  - **Evidenziazione Eventi ON/OFF**: fasce temporali colorate in background (Ambra traslucida quando il compressore è ON/modulante, Verde traslucido quando la pompa Grundfos è ON).
    - Rimosse le linee verticali di bordo gialle dai `LinearRegionItem` (`pen` e `hoverPen` trasparenti a larghezza 0) per un'estetica minimale ed elegante a sola campitura morbida.
    - Corretta la delimitazione temporale del ciclo: l'area evidenziata si chiude esattamente sull'ultimo istante in cui il dispositivo era attivo anziché estendersi sul campione spento successivo.
    - Aggiunto controllo di coerenza termodinamica in `api/bticino.py` ($T_{setpoint} \le T_{interna} \rightarrow \text{pompa}=0$) per annullare la latenza di sincronizzazione radio/cloud di Netatmo (~60-120 s).
    - Bonificati nel database i campioni 25 e 26.
  - **Gestore Canali con Ricerca Fuzzy (`RapidFuzz`)**: filtro istantaneo tollerante a errori di battitura per selezionare/deselezionare qualsiasi canale con legenda colorata.
  - Pulsante "Auto-Adatta Assi" (Reset Zoom) e supporto pan/zoom mouse indipendente.
- [x] **Ergonomia Comandi Diretti, Steppers, Pulsanti Reset e LED di Sincronizzazione**:
  - **Risolto Bug Hitbox Frecce Spinbox**: rimosso l'offset delle freccette Qt ridefinendo esplicitamente le dimensioni dei subcontrolli (`::up-button`, `::down-button` a 24x15 px con `subcontrol-origin: border`).
  - **Pulsanti Stepper Affiancati `[-]` e `[+]`**: aggiunti grandi bottoni fisici a ogni controllo numerico per incrementare/decrementare a colpo sicuro (0.1 su slope, 1 K su shift, 0.5 °C sui setpoint).
  - **Pulsante di Reset Singolo `↺`**: ogni parametro dispone di un tasto di ripristino istantaneo per rimettere il valore memorizzato/confermato dalla macchina qualora si cambi idea prima dell'invio.
  - **LED di Stato Sincronizzazione Hardware**:
    * 🟢 *Sincronizzato con Vitocal / BTicino*: parametro a video coincide con l'ultimo valore confermato dalla macchina.
    * 🟠 *Modifica in sospeso / Non inviata*: evidenzia visivamente che il valore è stato modificato a video ma non ancora inviato al cloud.
  - **Finestre di Conferma Modale su Tutti i Comandi**: nessun comando viene inviato alla PdC o a BTicino senza un esplicito clic su "Sì" nella finestra modale di riepilogo parametri, prevenendo invii accidentali.
- [x] **Raffinamento Grafico Curva Climatica (`ui/heating_curve_widget.py`)**:
  - Rimossa la linea verticale di riferimento sull'asse X (che generava confusione poiché l'asse X è la temperatura esterna $OAT$ e non la temperatura ambiente interna).
  - La temperatura target normale di riferimento (es. 12.0 °C) è indicata con chiarezza nel badge informativo in testa al grafico e nella tabella dei punti radianti.
  - Rilassato il clamp minimo a 18.0 °C per consentire la corretta visualizzazione delle rette anche con shift negativi.
- [x] **Architettura di Logging Cloud 24/7 (GitHub Actions)**:
  - Creato script headless `scripts/cloud_logger.py`: interroga le API cloud di Viessmann e BTicino senza bisogno di interfaccia grafica o PC acceso, con salvataggio append in formato JSON Lines `data/cloud_telemetry.jsonl`.
  - Creato workflow automatico `.github/workflows/telemetry_logger.yml`: gira ogni 5 minuti (288 run/giorno a minuti illimitati su repo pubblico), archiviando la telemetria continua dell'impianto con risoluzione ad alta densità per catturare ogni ciclo del compressore e della pompa Grundfos.
    - **Collaudato con successo sul repository reale** (`giacomogussetti-lgtm/vitocal-remote` run #3: **SUCCESS in 21s**, lettura e auto-commit verificati).
  - Aggiunto pulsante `☁️ Sync Cloud (GitHub)` nella barra superiore dell'app desktop: importa con un clic tutti i nuovi campioni registrati dal cloud direttamente nel database SQLite locale, ignorando i duplicati.
  - **Auto-Logger Integrato nella UI**:
    - Timer con conto alla rovescia in tempo reale nella barra superiore (`Prossimo: MM:SS`).
    - Intervallo regolabile (5-60 min) per storicizzare automaticamente su SQLite senza dover cliccare a mano.
  - Creato file launcher per Windows `avvia_gestionale.bat`.
- [x] **Sicurezza, Privacy e Controllo Preventivo Pre-Commit**:
  - Creato script di audit `scripts/security_check.py`: esegue scansione con regex su credenziali, token, email personali, MAC address e toponimi geografici.
  - Creato script di esportazione sicura `scripts/prepare_github_export.py`: genera la cartella pulita `github_ready/` escludendo file bytecode, database locali e segreti, eseguendo l'audit automatico prima di confermare.
  - Definita regola permanente Antigravity in `.agents/rules/security-and-privacy.md`: obbligo per tutti gli agenti di verificare l'assenza di dati sensibili prima di qualsiasi push su GitHub.
  - Anonimizzati i riferimenti geografici e personali nei file del codice, sinottico e documentazione.
- [x] **Bug Fix Sincronizzazione Cloud & Rete Mobile (`ui/main_window.py`, `web/js/app.js`, `web_server.py`)**:
  - **Risolto `NameError: name 'time' is not defined` in `ui/main_window.py`**:
    - Aggiunto `import time` mancante tra gli import standard, ripristinando il corretto funzionamento del pulsante `☁️ Sync Cloud (GitHub)` sia all'avvio che su richiesta.
  - **Risolto Blocco CORS Browser su `raw.githubusercontent.com` (`web/js/app.js`)**:
    - Rimosse le intestazioni personalizzate `Cache-Control` e `Pragma` che causavano l'invio di richieste `OPTIONS` preflight bloccate da GitHub con HTTP 403.
    - Il cache-busting è ora gestito in modo pulito e nativo tramite il parametro query URL `?t=${Date.now()}`.
  - **Aggiunto Endpoint Server-Side Proxy `/api/sync-github` (`web_server.py`)**:
    - Consente all'app mobile e web di sincronizzarsi da GitHub con download Python diretto, aggiornando sia il file `cloud_telemetry.jsonl` che il database SQLite.
  - **Risolto Rilevamento IP VPN (`web_server.py`)**:
    - Filtrati i tunnel VPN virtuali (es. Surfshark WireGuard `10.14.0.2`) e data priorità all'indirizzo fisico LAN/Wi-Fi `192.168.1.66` per la connessione da smartphone.
  - Risolto `IndexError` in `_load_latest_db_sample`: corretto il nome colonna `humidity_percent` (era erroneamente mappato su `humidity_corridoio_percent`), migrando a estrazione sicura con `dict(row)`.
  - Risolto mancato refresh UI al clic su `Sync Cloud`: aggiunto `_load_latest_db_sample()` e `_update_charts()` anche quando i dati cloud sono già allineati nel database locale, popolando istantaneamente tutte le 26 sonde del sinottico.
  - **Bypass Cache CDN GitHub Actions (300s Fastly)**: aggiunto parametro di cache-busting `?t={timestamp}` e header `Cache-Control: no-cache` per evitare che la CDN di GitHub serva risposte vecchie di 5 minuti quando viene aggiunto un nuovo campione.
- [x] **Memoria Persistente di Progetto**:
  - Creato e aggiornato `AGENTS.md` per consentire a qualsiasi nuovo agente in nuove chat di riprendere il lavoro immediatamente senza perdere il contesto.
  - Creata la Skill dedicata `.agents/skills/vitocal-remote-expert/SKILL.md`.

---

## 2. VALORI HARDWARE DI RIFERIMENTO RILEVATI SUL CAMPO

| Parametro Hardware | Valore Rilevato (18/11/2026) | Origine / Note |
| :--- | :--- | :--- |
| **Vitocal Modello** | `AWBT-E-AC 111.A16` (CU401B_S_64) | 11 kW split R410A, S/N 7733734301040129 |
| **Temp. Esterna** | 5.9 °C | Sonda esterna Viessmann |
| **Temp. Puffer Inerziale 200L** | 13.2 °C | Sonda superiore buffer top |
| **Temp. Mandata PdC** | 11.5 °C | Circuito secondario mandata |
| **Temp. Ritorno PdC** | 11.7 °C | Ritorno scambiatore |
| **Temp. Bollitore ACS** | 11.4 °C | Bollitore sanitario integrato |
| **Pressione Gas Caldo** | 10.0 bar | Sensore refrigerante alta pressione |
| **Compressore Stato** | Spento (0% modulazione) | 212 avvii, 153.3 ore totali |
| **Curva Climatica Attuale** | Inclinazione = 0.6 \| Livello = 0 | Setpoint target: 12 °C Normale / 12 °C Ridotta |
| **COP Calcolati da Macchina** | Riscaldamento: 3.1 \| ACS: 2.5 \| Totale: 3.0 | COP istantanei/cumulati |
| **Termostato BTicino** | Smarther Thermostat (`BNS`) | Modulo Smarther, FW 40 |
| **Temp. Interna Corridoio** | 7.8 °C | Misurata dal termostato BTicino |
| **Setpoint BTicino** | 7.0 °C (Modo: `home`) | Soglia di consenso |
| **Umidità Corridoio** | 61 % | Sonda igrometrica integrata |
| **Pompa Grundfos** | 0 (Spenta) | Relè aperto (nessuna circolazione radiante) |

---

## 3. PROSSIMI PASSI (ROADMAP FASE 1 & FASE 2)

1. **Logging Continuo Cloud 24/7 (Senza PC acceso a casa)**:
   - Configurazione workflow GitHub Actions con cron schedulato (es. ogni 10 min).
   - Connessione a database cloud SQLite gratuito (Turso libSQL) per salvare le letture nel cloud a costo zero.
- [x] **Modulo Analytics Avanzato & Statistiche X Ore (Desktop & Mobile PWA)**:
  - **Motore di Calcolo Termodinamico (`storage/analytics.py` & `web/js/analytics.js`)**:
    - **Finestra Temporale Dinamica e Personalizzabile**: selezione rapida (6h, 12h, 24h, 48h, 72h, 7 giorni, Tutto) o inserimento di qualsiasi valore $X$ in ore.
    - **Conteggio Avviamenti Reale**: riconciliazione tra delta contatore hardware Vitotronic WO1C (`compressor_starts`) e rilevamento transizioni di ciclo sui campioni densi.
    - **Durate dei Cicli**: calcolo esatto di durata media ($\bar{D}$ min), minima e massima, ore totali di marcia e Duty Cycle %.
    - **Diagnostica Qualità Modulazione ("Ha modulato bene?")**:
      * Valutazione del carico medio inverter durante il funzionamento e rilevamento *short-cycling* sui 200L di puffer.
      * Ripartizione del tempo per fasce di carico: Basso Carico (1-30%), Medio Carico (31-60%), Alto Carico (>60%).
      * Score di salute modulazione (0-100), verdetto sintetico e diagnosi termodinamica approfondita.
    - **Stima Consumo Elettrico (kWh) e Spesa in Bolletta (€)**:
      * Modello di potenza elettrica calibrato sulla Vitocal 111-S split 11 kW (standby 25W, assorbimento inverter proporzionale a modulazione %, pompa primaria interna).
      * Calcolo energia totale kWh, potenza media assorbita e spesa in euro con tariffa configurabile (default 0.25 €/kWh) e proiezione giornaliera.
    - **Verifica Sicurezza Antigelo ("Casa al Sicuro con Minima Spesa")**:
      * Monitoraggio temperatura interna minima registrata, temperatura minima del puffer e dell'aria esterna.
      * Margine di sicurezza in °C rispetto alla soglia di rischio gelo (5.0 °C) e consiglio operativo per non sprecare energia garantendo la protezione totale dell'immobile.
  - **Integrazione Desktop PyQt6 (`ui/main_window.py`)**:
    - Nuova Scheda dedicata `⏱️ Statistiche & Efficienza (X Ore)` con scroll area, controlli stepper, banner sicurezza gelo, 4 card KPI, box qualità modulazione e tabella dettagliata dei singoli cicli.
  - **Integrazione Mobile PWA (`web/`)**:
    - Nuova scheda `Analisi` nella barra inferiore mobile con motore JavaScript client-side istantaneo e visualizzazione responsive touch.
  - **Endpoint REST Flask (`web_server.py`)**:
    - Nuovo endpoint `GET /api/analytics?hours=X&cost_kwh=0.25` per interrogazioni programmatiche.
- [x] **Applicazione Mobile Android PWA & Micro-Server Flask (`web/`, `web_server.py`)**:
  - **Architettura PWA Standalone per Smartphone Android**:
    - Manifest web standard (`web/manifest.json`), icone responsive (192px e 512px) e Service Worker (`web/sw.js`) per caching offline.
    - Installabile direttamente con 1 tocco su Chrome/Brave Android ("Installa app" / "Aggiungi a Home") per avvio a schermo intero nativo senza barra degli indirizzi.
  - **Sinottico SCADA Mobile Vettoriale SVG Responsive (`web/js/synoptic.js`)**:
    - Layout adattivo automatico su dimensione schermo e orientamento: **Verticale Portrait** (`0 0 420 850`, a tutta larghezza senza scroll orizzontale, KPI compatti 3×2) e **Orizzontale Landscape** (`0 0 1260 560`, schema SCADA orizzontale esteso).
    - Schematizzati tutti gli organi principali: **Circolatore Primario PdC (`P1`)** con girante rotante e %, circolatore Grundfos secondario, ventola evaporatore, mini bollitore ACS 220L, Puffer 200L con stratificazione cromatica dinamica e **casetta con tetto a falde** che confronta visivamente **Aria Esterna (OAT)** e **Aria Interna (BTicino Smarther)** con serpentina radiante collegata al circuito secondario.
  - **Grafici Touch Mobile Avanzati (`web/js/charts.js`, Service Worker `vitocal-remote-v5`)**:
    - **Zoom/Pan Solo X a 2 Dita & Toggle Minimale**: pinch + drag con 2 dita esclusivamente su asse X mantenendo la lettura valori a 1 dito in `👆 Leggi`; toggle compatto in alto a destra per passare a `✋ Sposta` (pan a 1 dito) + pulsante `↺ Reset`.
    - **Asse Y Bloccato & Range Tappabile**: durante zoom/pan in X gli assi Y restano fissi; toccando l'asse Y sinistro/destro o le pillole `°C: Auto` / `%: Auto` si imposta e blocca `Y Min`/`Y Max` (con preset rapidi e salvataggio in `localStorage`).
    - **Area Grafico Verticale Amplificata**: barra filtri compatta su riga singola scorrevole e altezza dinamica `clamp(320px, 50dvh, 560px)`.
    - **Bande Verticali Stato Impianto Adiacenti & Disattivabili**: plugin Chart.js `beforeDatasetsDraw` con fasce traslucide e nastro superiore da 6px per `Solo PdC` (Ambra), `Solo Grundfos` (Ciano) e `PdC + Grundfos` (Verde), attivabili/disattivabili singolarmente da legenda e saldate senza buchi tra cambi di stato adiacenti.
    - **Traccia Target LWT Curva (PdC) & Fix Isteresi BTicino**: traccia calcolata `Target LWT Curva (PdC)` basata sulla formula ufficiale Viessmann WO1C `variant2` (attiva fuori da `standby`); `Setpoint BTicino` disattivato di default per evitare compressioni verticali da picchi anti-grippaggio (30 °C), con riepilogo casa/setpoint sempre nel tooltip. Risolto inoltre il bug `setpoint <= temp` in `api/bticino.py` (`setpoint < temp - 0.3`) che mascherava i cicli PID della Grundfos a soglia `8.5 == 8.5 °C`.
  - **App Mobile PWA Bidirezionale, Autopilota Full-Auto & Grafici Pro (`tab-commands`, `scripts/autopilot.py`, `scripts/git_safe_push.py`, `web/js/charts.js`, `web/js/help.js`, Service Worker `vitocal-remote-v9`)**:
    - **Push Race-Free GitHub Actions (`scripts/git_safe_push.py`)**: elimina i conflitti di push concorrente tra `telemetry_logger.yml` e `apply_command.yml` tramite merge cronologico deduplicato di `cloud_telemetry.jsonl` / `data/archive/` e precedenza comandi espliciti su `autopilot_config.json` / `autopilot_state.json`.
    - **Controllo Remoto Completo (4G/5G + LAN)**: nuova scheda `🎛️ Comandi` con conferma modale obbligatoria, LED `🟢 Sincronizzato / 🟠 Da inviare`, stepper, preview Target LWT e stato dinamico del pulsante Hero (`✅ ASSENZA ATTIVA` vs `🛡️ ATTIVA`).
    - **Pannello One-Click "Custodia Automatica Montagna" ("A Prova di Nonni")**: tasto singolo `🛡️ ATTIVA ASSENZA MONTAGNA` con cassetto parametri tunabili, pulsante verifica Secrets sola lettura + test roundtrip timer 2 min (`cronjob_test` con `roundtrip_2m: true`) e banner rapido sul Sinottico.
    - **Motore Autopilota a Macchina a Stati (`scripts/autopilot.py`)**: gestisce `IDLE` → `ARMED` (anti-rimbalzo 20 min) → `HEATING_SYNC` (finestra COP `11:00–16:00` o emergenza gelo/derivata notturna, max `300 min`, Target LWT calcolato e bloccato all'avvio ciclo con formula inversa WO1C) → `PUFFER_DRAIN` (25 min di scarico puffer a PdC spenta) con doppio fail-safe hardware e adattamento automatico della frequenza `cron-job.org` (15m / 5m / 2m).
    - **Grafici Pro, Modalità Smartphone Landscape Immersiva & Guida `(i)`**: header/barra inferiore nascosti su smartphone orizzontale (toggle `☰`), preset visualizzazione, legenda Grafana ad alto contrasto con valori live/scrubbed e doppio-tap Solo, marker `🎯 Stop SP` per stacchi su Target LWT, pillole durata ON zoom-aware nelle bande, KPI dinamici su finestra visibile, salto `⏭️ Ciclo` e modali informativi `(i)` su tutta l'app.
    - **Diagnostica Avanzata Defrost, Antigelo & Resistenza Elettrica (`api/viessmann.py`)**: mappati e storicizzati `compressor_phase`, `frost_protection_status`, `heating_rod_level1_s` e `heating_rod_level2_s` (secondi reali resistenza backup BPHE) + script di audit `scripts/audit_strategy.py` e regola/skill di rigore termodinamico.
    - **Comandi Viessmann Vitocal & BTicino Smarther**: cambio modalità, curva climatica, temperature, boost ACS, fasce orarie settimanali (`setHeatingSchedule`), setpoint manuale con durata, switch programmazione BTicino (`/api/switchhomeschedule`) e preset sincronizzati via `POST /api/command` (LAN) o `apply_command.yml` (4G/5G).
  - **Audit Forense & Termodinamico 21/11–24/11, Autopilota Full-Auto v2 (Soft-Start + Defrost Guard + Anti-Grippaggio), Sinottico Target Reali & Consumi Calibrati (`vitocal-remote-v13`)**:
    - **Fix Glitch Logger Cloud (`api/bticino.py`, `scripts/cloud_logger.py`)**: su `code 6` Netatmo stateless `grundfos_pump_active` restituisce `None` con fallback sull'ultimo valore valido (risolve i falsi buchi neri e le strisce `Solo PdC` del 21/11 e 24/11); aggiunto fallback completo Viessmann su poll vuoti (risolve il falso `Stop SP` del 21/11 13:41).
    - **Nuovi Sensori Diagnostici & Logbook WO1C (`api/viessmann.py`, `models/telemetry.py`, `storage/database.py`, `web/js/app.js`)**: esposti `primary_supply_temp_c` (aria ingresso ODU), `error_counter_d6` (`0` = zero guasti), classi carico inverter `C1..C5` (`heating.compressors.0.statistics.load`) e logbook WO1C decodificato (`KAELTEKR_UMKEHR`, `VERDICHTER1`, `SEK_PUMPE1`) nella scheda Sonde.
    - **Autopilota Full-Auto v2 Ottimizzato (`scripts/autopilot.py`, `scripts/cloud_commander.py`, `data/autopilot_config.json`)**:
      * Calibrazione su modello numerico reale (`k_rad ≈ 0.344 kW/K`, sensore di regolazione WO1C su `T_buffer_top`, pavimento reale inverter `38%`): `target_lwt_delta_k = 15.5`, `min_target_lwt_c = 22.5`, `max_target_lwt_c = 26.5`, `cron_active_minutes = 1` (alta risoluzione 1 min durante marcia PdC).
      * **Soft-Start Anti-Overshoot** (`soft_start_enabled`, pavimento configurabile `21.8 °C`, gradini `+1 °C` ogni `25 min`, anti PI wind-up WO1C), **Defrost Guard Anti-Brina** (`defrost_guard_enabled`, `-1 °C` fino al pavimento BPHE configurabile `22.0 °C` / `T_in + 13.5 K` con **doppia guardia anti-stacco `BUF ≤ cand + 1.0 K` E `EWT ≤ cand − 0.8 K`** basata sul comportamento reale WO1C `7203/7209`) e **Anti-Grippaggio Grundfos** (`anti_seize_days = 4`).
      * **Grafici Mobile Pro v4 Edge-to-Edge & Touch Stile TradingView (`vitocal-remote-v16`, `web/index.html`, `web/css/styles.css`, `web/js/charts.js`, `web/js/help.js`)**: layout a tutta larghezza su smartphone con +70–100 px orizzontali (nascosti titoli Y ruotati e asse destro `yOther` quando inutilizzato) e +100 px verticali (header su 2 righe scorrevoli + KPI ticker 1-riga), gesti touch naturali (1 dito Pan, Tap/Long-Press 180ms Mirino Magnetico con HUD fissa `#chartScrubHud` anti-occlusione + legenda `tabular-nums`, Doppio-Tap Zoom 2.2×/Reset, 2 dita Pinch X), navigatore multi-ciclo `◀ Ciclo ▶` e filtro legenda `🎯 Solo attivi`.
      * **Zero Soglie Hardcoded & Modello Matematico Auto-Convergente (`scripts/thermal_model.py`, `data/thermal_model.json`, `vitocal-remote-v15`)**: esposte in PWA (`web/index.html`, `commands.js`, `help.js`) e `cloud_commander.py` tutte le soglie fisiche (`defrost_min_safe_lwt_c`, `defrost_min_delta_k`, `soft_start_min_lwt_c`, `defrost_guard_oat_max_c`, `inverter_min_mod_pct`) + motore matematico Bayesiano che identifica `k_rad`, floor inverter, caduta BPHE defrost e dispersione UA edificio a ogni ciclo, con widget live in PWA e regola ferrea anti-hardcoding.
      * **Pianificatore Meteo Dinamico Open-Meteo, Anti-Short-Cycle, Pre-Armamento Predittivo & Glass-Box UI (`scripts/weather_planner.py`, `scripts/autopilot.py`, `scripts/test_autopilot_weather.py`, `vitocal-remote-v17`)**:
        - Finestra COP dinamica oraria basata su $\text{COP}_{\text{netto}}(T_{\text{ext}}, RH\%, \text{precip}, \text{radiazione})$ con coordinate lette solo da GitHub Secrets / `.env` (`WEATHER_LAT`, `WEATHER_LON`, `WEATHER_ELEVATION_M`) e cache sanitizzata `data/weather_forecast.json`.
        - Self-tuning automatico su telemetria reale (`oat_bias_c` con Bayesian shrinkage, `oat_mae_c`, `tin_projection_mae_c`, `frost_penalty_scale`).
        - Risolti i casi limite di fine finestra: **Anti-Micro-Ciclo** (`min_cycle_minutes = 120`, rinvio se notte sicura o estensione garantita fino a `max_window_extension_minutes` con allineamento fascia hardware WO1C), **Pre-Armamento Predittivo** in finestra calda contro gelate notturne, e **Arbitraggio Meteo** anti-starvation.
        - Cassetto Glass-Box `🌦️ Previsioni Meteo, Finestra Dinamica & Ragionamento` nella tab Comandi PWA con verdetto, trace passo-passo, card Oggi vs Domani, strip oraria 30h, assunzioni esplicite e controlli configurabili.
        - Fix `scripts/git_safe_push.py` (`telemetry` mode ora committa `data/thermal_model.json` e `data/weather_forecast.json`) + suite da 11 test isolati (`python scripts/test_autopilot_weather.py`).
        - Rafforzata la **Regola #0 di Inizio Conversazione** nelle rules e skill di progetto per eseguire sempre `audit_strategy.py` e `thermal_model.py` prima di ogni analisi.
      * **Protocollo Ferreo Post-Ciclo (7 punti)** codificato in `.agents/rules/thermodynamic-rigor-and-telemetry-audit.md`, `.agents/skills/vitocal-thermodynamic-tuning/SKILL.md` e `scripts/audit_strategy.py`.
    - **Sinottico PWA & Desktop con Target Reali (`web/js/synoptic.js`, `web/index.html`, `ui/synoptic_widget.py`)**: sostituito il setpoint dummy BTicino con **Target Acqua (Puffer)** e **Target Casa Reale** (`7.5–8.8 °C`).
    - **Grafici Pro v3 & Consumi Calibrati (`web/js/charts.js`, `web/js/analytics.js`, `storage/analytics.py`)**: filtro anti-glitch sulle bande di stato, 6 canali diagnostici R410A (condensazione NIST, sottoraffreddamento, depressione evaporatore, surriscaldamento scarico, ΔPuffer-Target, aria ODU), integrazione trapezoidale kWh elettrici/termici con penalità defrost e COP netto reale, più registro consumi giornalieri (`#dailyConsumptionLedger`).
  - **Grafici Pro v2 (Resa Termica, ΔT Primario, P1 & Cerca Canali), Sinottico Ottimizzato, UX Comandi & Monitor Quote API (`web/`, `scripts/autopilot.py`, `scripts/cloud_commander.py`, Service Worker `vitocal-remote-v12`)**:
    - **Resa Termica nelle Bande ON & KPI (`web/js/charts.js`)**: espandendo/zoomando il grafico, le pillole sulle bande mostrano progressivamente anche la resa termica stimata del ciclo (`~kWhₜ` e `kWₜ` medi da modulazione + COP) e il riepilogo totale entra nella barra KPI `#chartWindowStats` e nel tooltip.
    - **Nuove Tracce Core & Cerca Canali Espandibile (`🔍 + Canali`)**: aggiunte `ΔT Primario (LWT−EWT)` e `Circolatore Primario P1 (%)` tra i canali core (attive di default nel preset `Inverter`), più `#channelSearchDrawer` subito sotto `.chart-header` per aggiungere/rimuovere 18 canali extra con persistenza in `localStorage`. Fix v12: `✕` (`#btnClearChannelSearch`) ed `Esc` chiudono/puliscono la barra di ricerca ridimensionando il canvas, isolato `#btnToggleChannelSearch` da `.btn-preset-chip[data-preset]`, sbloccato X-pan continuo su tutto lo storico (`getPanLimits` + drag desktop in `Leggi`/`Sposta`, reset sicuro `suppressSingleTouchUntilRelease` e ricalcolo scala Y al toggle canali da zoomato).
    - **Sinottico Ottimizzato, Letture Rapide Collassabili & Mini-Badge Resistenza S1/S2 (`web/js/synoptic.js`, `web/index.html`)**: rimossa la riga testuale Grundfos; spostato lo stato Autopilota in cima alla tab Sinottico con le 6 card di lettura rapida racchiuse sotto in `<details id="synopticKpiDrawer">` chiuso di default; mini-badge compatto `RESIST. S1/S2` allineato sotto `ΔT PRIM.` (mostra stato/minuti di oggi `OFF · 0m`, mentre la scheda Sonde distingue `Oggi` vs totale storico di vita `133.5h / 132.2h`).
    - **UX Comandi Ridisegnata, Profili Smart & Timeline 24h (`web/js/commands.js`, `scripts/cloud_commander.py`)**: introdotti scenari preconfigurati e profili personalizzati salvabili (`apply_full_profile`) che coordinano PdC + consenso pompa BTicino, più il pianificatore grafico 24h (`#pdcScheduleTimeline`) con selezione rapida dei 7 giorni, template e preset orari salvabili.
    - **Frequenza Dinamica Editabile (`min 1 min`), Self-Tuning Soft & Monitor Quote API (`scripts/autopilot.py`, `scripts/cloud_logger.py`)**: rimossi i bottoni di test cron, sostituiti da intervalli editabili (`IDLE` 1–60m, `ARMED` 1–30m, `ATTIVO` 1–15m), opzione opzionale *Self-Tuning Soft Curva* (`−1 K` anti-overshoot senza tagliare Grundfos) e monitor quote live (letture + scritture) per Viessmann, BTicino/Netatmo, cron-job.org e GitHub.
  - **Grafici Touch Mobile Interattivi (`web/js/charts.js`)**:
    - **Risolto Bug di Spaziatura Temporale (Scala Continua su Asse X)**:
      * Sostituita la precedente scala a categorie (che posizionava i campioni in modo rigidamente equidistante, distorcendo i buchi temporali o le letture ravvicinate) con una scala temporale continua reale (`type: 'time'`).
      * Integrato l'adapter `chartjs-adapter-date-fns` con dataset a coordinate `{ x: timestamp_ms, y: val }`: ora 58 minuti di intervallo occupano esattamente 58 volte lo spazio di un campione a 1 minuto, preservando fedelmente le reali pendenze fisiche del raffreddamento termico.
      * Bundle delle librerie (`chart.min.js` e `chartjs-adapter-date-fns.bundle.min.js`) salvati localmente in `web/js/` e gestiti dal Service Worker v2 offline-first per funzionamento garantito senza internet né CDN.
      * Multi-asse Y per temperature (°C) e grandezze modulazione/bar/COP.
      * Selettori rapidi d'intervallo temporale (6h, 24h, 3 giorni, Tutti) e pillole per accendere/spegnere singoli canali con tooltip informativo esteso e formattazione italiana.
  - **Sincronizzazione Intelligente a 3 Vie (`web/js/app.js`)**:
    1. *Sync Automatico Cloud GitHub*: polling in background ogni 120s da `raw.githubusercontent.com` con cache-busting per leggere gli aggiornamenti generati ogni 5 minuti da GitHub Actions.
    2. *Trigger Campionamento On-Demand (GitHub Action)*: pulsante per avviare subito il workflow GitHub Actions (`workflow_dispatch`) con token.
    3. *Interrogazione Diretta API Live (Backend Locale)*: endpoint `/api/refresh-direct` per campionamento istantaneo senza passare dal cloud quando connessi in rete locale.
  - **Launcher Doppio-Clic & Micro-Server Python (`web_server.py`, `avvia_app_mobile.bat`)**:
    - Server Flask leggero su porta 8080 con rilevamento automatico dell'IP locale per connessione immediata da smartphone nella stessa rete Wi-Fi.
  - **Workflow Deploy Automatico su GitHub Pages (`.github/workflows/deploy_pwa.yml`)**:
    - Pubblicazione automatica dell'app web PWA su GitHub Pages per l'accesso 24/7 da smartphone in 4G/5G da qualsiasi parte del mondo a costo zero.
  - **Compilatore Automatico APK Android Nativo (`.github/workflows/build_apk.yml`)**:
    - Workflow cloud che ad ogni aggiornamento della cartella `web/` compila automaticamente l'app in pacchetto nativo `.apk` (via Capacitor), scaricabile direttamente da GitHub Actions Artifacts.
  - **Skill Dedicate per l'Assistente AI (`.agents/skills/`)**:
    - `vitocal-remote-expert`: manuale operativo di bordo, mappatura sensori, runbook e protezione termodinamica.
    - `vitocal-build-deploy`: guida per esportazione, audit di sicurezza pre-commit, gestione dei file nascosti (`.github/workflows/`) su GitHub Web e controllo della finestra di ritenzione.
    - `vitocal-thermodynamic-tuning`: workflow obbligatorio di audit telemetria (`scripts/audit_strategy.py`) prima di qualsiasi modifica a strategie o soglie, unito alla regola di rigore fisico (zero supposizioni non misurate).

---

## 3. WORK IN PROGRESS & ROADMAP (FASE 2)

### A. Tasto "Arrivo in Montagna (Pre-Riscaldamento Comfort)" & Verifica Portata Circolatore
- Implementazione del secondo tasto rapido one-click per pre-riscaldare gradualmente massetto, ambiente e bollitore ACS prima del soggiorno.
- Verifica a vista del modello esatto del circolatore secondario in centrale termica (UPM3 / ALPHA1 L) e test di portata/durata cicli con curva III costante vs Radiante.

### B. Decimazione Dati Adattiva nei Grafici Web (LTTB - Largest Triangle Three Buckets)
- Inserimento di un algoritmo di decimazione client-side leggero per visualizzare grafici plurimensili (fino a 6 mesi / 50.000 campioni) a 60 fps fluidi su qualsiasi smartphone senza rallentamenti grafici.
