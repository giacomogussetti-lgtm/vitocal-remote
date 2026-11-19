# REGISTRO STATO DI PROGETTO E CHANGELOG
**Progetto**: Gestionale Unificato Viessmann Vitocal 111-S + BTicino Smarther (Abitazione Climatica Montana - Zona E)  
**Ultimo aggiornamento**: 19 Novembre 2026  
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
  - **App Mobile PWA Bidirezionale (`tab-commands`, `web/js/commands.js`, `scripts/cloud_commander.py`, `.github/workflows/apply_command.yml`, `web_server.py`)**:
    - **Controllo Remoto Completo (4G/5G + LAN)**: nuova scheda `🎛️ Comandi` con conferma modale obbligatoria, LED `🟢 Sincronizzato / 🟠 Da inviare`, stepper e preview Target LWT dal vivo.
    - **Comandi Viessmann Vitocal**: cambio modalità (`standby`/`dhw`/`dhwAndHeating`), curva climatica (`slope`/`shift`), temperature (`Normale`/`Ridotta`/`ACS`), carica rapida ACS e programmazione fasce orarie settimanali (`setHeatingSchedule`).
    - **Comandi BTicino Smarther & Preset Sincronizzati**: setpoint manuale con durata, cambio modalità (`home`/`hg`/`away`), cambio programmazione oraria (`POST /api/switchhomeschedule`), e pulsanti rapidi sincronizzati PdC + Grundfos (`Avvia Ciclo Sincronizzato` / `Tutto Standby`).
    - **Sicurezza & Ricevuta Cloud**: in LAN invio diretto tramite `POST /api/command`; da remoto in 4G/5G `workflow_dispatch` su `apply_command.yml` usando i GitHub Secrets, verifica read-back, aggiornamento telemetria e ricevuta in `data/last_command.json`.
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

---

## 3. WORK IN PROGRESS & ROADMAP (FASE 2)

### A. Strategia Adattiva Anti-ON/OFF & Regolazione Dinamica (Prossimo Step)
- Analisi approfondita dei primi log 24/7 e definizione strategia basata su feedback reale della temperatura ambiente per minimizzare i cicli brevi su puffer 200L e massimizzare il COP sincronizzando Vitocal e Grundfos.

### B. Decimazione Dati Adattiva nei Grafici Web (LTTB - Largest Triangle Three Buckets)
- Inserimento di un algoritmo di decimazione client-side leggero per visualizzare grafici plurimensili (fino a 6 mesi / 50.000 campioni) a 60 fps fluidi su qualsiasi smartphone senza rallentamenti grafici.
