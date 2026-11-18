# REGISTRO STATO DI PROGETTO E CHANGELOG
**Progetto**: Gestionale Unificato Viessmann Vitocal 111-S + BTicino Smarther (Abitazione Climatica Montana - Zona E)  
**Ultimo aggiornamento**: 19 Novembre 2026  
**Autore / Assistente**: Antigravity AI & Giacomo  

---

## 1. OBIETTIVI RAGGIUNTI (FASE 1 — BANOMETRO & DESKTOP GUI)

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
2. **Modulo Analytics Avanzato**:
   - Calcolo automatico COP medio per singolo ciclo di carica.
   - Algoritmo di stima della dispersione termica passiva (°C/ora) dell'abitazione in assenza di riscaldamento.
   - Allarme gelo se la temperatura interna scende sotto 6.5 °C.
3. **Fase 2 (Mobile / Micro-Backend)**:
   - Esportazione del core in un micro-servizio FastAPI.
   - Sviluppo App Android in Jetpack Compose per comandi rapidi da smartphone.
