# MEMORIA PERSISTENTE DI PROGETTO: GESTIONALE VITOCAL 111-S & BTICINO SMARTHER

> **ATTENZIONE PER QUALSIASI AGENTE AI (NUOVE CHAT E SUB-AGENTI):**
> Questo file è la memoria centrale del progetto. Quando inizi una nuova conversazione, leggi questo documento prima di fare qualsiasi modifica. **Regola fondamentale:** ogni volta che implementi nuove funzioni o risolvi problemi, AGGIORNA sempre questo file e `PROJECT_STATUS.md`.

---

## 1. CONTESTO DELL'IMPIANTO FISICO (Abitazione di Montagna - Zona Climatica E)
L'abitazione è una seconda casa di montagna non presidiata nei giorni feriali (abitata tipicamente nelle festività principali), soggetta a rigide temperature invernali e rischio gelo per radiante e tubazioni.
- **Disposizione edificio & involucro**: IDU e Puffer 200 L si trovano nel box al piano terra; sopra il box insistono due appartamenti intermedi e al 3° livello (ultimo piano mansardato) si trova l'appartamento gestito (~120 m², privo di cappotto termico, pareti perimetrali e tetto esposti all'esterno).
- **Unità Esterna (ODU)**: posizionata su terrapieno dietro al box, rialzata rispetto all'IDU di circa $\Delta H \approx 7\text{ m} \pm 2.5\text{ m}$.
L'impianto è idraulicamente disaccoppiato in due sottosistemi tramite un **Puffer parallelo da 200 litri**:

1. **Circuito Primario (PdC <-> Puffer)**:
   * **Pompa di Calore**: Viessmann Vitocal 111-S split (AWBT-E-AC 111.A16, 11 kW nominali, refrigerante R410A) con bollitore ACS integrato e resistenza elettrica di backup integrata (`heatingRod` a 2 stadi).
   * **Centralina**: Vitotronic 200 tipo WO1C collegata a Vitoconnect Optolink ViCare.
   * **Dispositivo reale nel cloud Viessmann**: `CU401B_S_64` (Device tipo `heating`, 193 features hardware).
   * **Regolazione**: Curva climatica con Inclinazione (Slope) = 0.6, Livello (Shift) = 0, mandata max 40 °C. Setpoint Normale/Ridotta = 12 °C (o 10 °C baseline).
2. **Circuito Secondario (Puffer <-> Pavimento)**:
   * **Rilancio**: Circolatore Grundfos (modello esatto da confermare a vista, tipo UPM3/ALPHA1 L, attualmente su curva Radiante) che pesca dal puffer 200 L e alimenta direttamente l'intero pavimento radiante (~120 m², **unica zona aperta senza testine né valvole di zona**).
   * **Termostato Ambiente**: BTicino Smarther (modello `BNS`, firmware 40) installato in "Corridoio".
   * **Comando**: Il consenso ON/OFF del termostato comanda direttamente il circolatore di rilancio.
3. **Criticità Termodinamica & Regola di Rigore**:
   * Se la Grundfos è spenta, la PdC da 11 kW satura rapidamente i soli 200 L di puffer e lavora a cicli brevi ad alto consumo.
   * Il sistema software orchestra cicli sincronizzati lunghi nelle ore calde ad alto COP + scarico finale del puffer.
   * **Regola ferrea (Zero Supposizioni)**: non trattare come certezze grandezze idrauliche non misurate (es. rapporto esatto di portata secondario/primario o curva esatta pompa non ancora letta da etichetta). Prima di ogni tuning strategico eseguire `python scripts/audit_strategy.py`.

---

## 2. REGOLE ARCHITETTURALI E PITFALLS DA EVITARE ASSOLUTAMENTE

### A. Pitfall Viessmann ViCare API:
1. **Selezione Dispositivo Hardware**:
   * Quando chiami `vicare.devices`, l'indice 0 è il gateway `Heatbox3` (tipo `vitoconnect`).
   * `dev.asHeatPump()` NON lancia eccezioni neanche sui gateway! **Non fidarsi di `dev.asHeatPump()` da solo**.
   * Bisogna **sempre** cercare il dispositivo con `dev.getDeviceType() == 'heating'` o ruolo `'type:heatpump'` / `'interface:circuit;heating'` (che è `CU401B_S_64`).
2. **Metodi Feature Dump**:
   * La chiamata `dev.service.fetch_all_features()` richiede obbligatoriamente `dev.accessor` come argomento: `dev.service.fetch_all_features(dev.accessor)`.
3. **Sensori e Modulazione Compressore**:
   * Inverter Hz e RPM ventola NON sono esposti via Cloud ViCare (sono confinati nel bus interno WO1C).
   * **La percentuale di modulazione reale (0-100%)** è esposta in: `heating.compressors.0.sensors.power`.
   * Le statistiche delle classi di modulazione (ore a carico 1..5) sono in: `heating.compressors.0.statistics.load`.
   * Pressione gas caldo (bar): `heating.sensors.pressure.hotGas`.
   * Temperature circuito frigo: `heating.sensors.temperature.hotGas`, `liquidGas`, `suctionGas`.
   * COP live calcolato dalla macchina: `heating.cop.heating`, `heating.cop.dhw`, `heating.cop.total`.
4. **Caching PyViCare e Verifica Read-Back Scrittura**:
   * `ViCareCachedService` mantiene una cache in memoria di 60 secondi per tutte le letture.
   * Quando si invia un comando di scrittura (`setNormalTemperature`, `setReducedTemperature`, `setHeatingCurve`), chiamare sempre `device_config.service.clear_cache()` prima del read-back per evitare falsi mismatch con il valore vecchio memorizzato nella cache.
5. **Ordine Parametri `setHeatingCurve` in PyViCare**:
   * **ATTENZIONE CRITICA**: In PyViCare la firma del metodo è `circuit.setHeatingCurve(shift, slope)` (Shift PRIMA, Slope SECONDO!).
   * Passare sempre argomenti espliciti con keyword: `circuit.setHeatingCurve(shift=int(shift), slope=round(float(slope), 1))` per evitare che lo slope venga convertito a zero.
6. **Curva Climatica, Riferimento Temperatura Normale ($T_{\text{normale}}$) e Sensore di Regolazione Puffer**:
   * La curva climatica Viessmann è ancorata alla Temperatura Ambiente Desiderata (Normale/Ridotta):
     $LWT = T_{\text{normale}} + \text{Shift} + \text{Slope} \cdot 1.83 \cdot (T_{\text{normale}} - OAT)^{0.8}$
   * **Logica reale di regolazione WO1C su questo impianto (Verificata su 175 campioni stazionari 21/11 + 4 picchi 21/11 & 24/11 + manuale WO1C `7200/7203/7209`)**:
     - **Regime stazionario & Riaccensione (`7200 = 1`, `7203 ≈ 5.0 K`)**: la Vitotronic WO1C regola sulla **sonda superiore Puffer (`T_buffer_top`)** rispetto al target della curva (con `OAT` smorzata interna ~2–3h). A regime piatto (21/11 `13:00–15:55`, 175 campioni): `BUF − Target = +0.45 K`, `LWT − Target = +1.46 K`, `EWT − Target = −1.37 K`. La riaccensione avviene esattamente quando `BUF` scende a `Target − 4.9..5.0 K` (parametro `7203` di fabbrica = `5.0 K`; provato alle `14:25:39` del 24/11 con `BUF = 19.5 °C` vs `Target = 24.4 °C`, mentre `EWT` era `20.9 °C` e `LWT` `21.5 °C`).
     - **Ritardo di modulazione (~10–12 min)**: sui transitori da freddo o post-defrost, il regolatore PI WO1C accumula integral wind-up (`81–88%`) e inizia a frenare solo `~10–12 min` dopo il superamento del target (~`-2%/min`).
     - **Stacco di carica completa (`7209`, verificato su tutti i 4 picchi)**: il compressore NON stacca sul solo overshoot temporaneo di `BUF_top` finché il ritorno `EWT` (fondo puffer) resta sotto target (21/11 `11:55` `BUF +3.1 K / EWT −0.4 K` → resta ON; 24/11 `13:27` `BUF +2.9 K / EWT −0.2 K` → resta ON; 24/11 `15:17` `BUF +2.2 K / EWT +0.1 K` → resta ON). Stacca in pausa termostatica (`heating → pause → off`, 24/11 `14:11`) quando l'intero puffer è saturo testa-fondo (**`BUF ≥ Target + 2.7 K` E `EWT ≥ Target`** con `OAT` smorzata stabilizzata). Per questo la guardia anti-stacco di `autopilot.py` verifica sia `BUF <= candidate + 1.0 K` sia `EWT <= candidate - 0.8 K`.
   * **Contatore guasti e logbook WO1C**: `device.messages.errors.counter.d6` conta gli errori attivi (`0` = nessun guasto). `device.messages.logbook` usa nomi di errore/stato rimappati dal cloud ViCare con etichette fuorvianti (`Inverter_CPU_error`, `Inverter_Under_voltage`) anche su normali transizioni di fine defrost o fine fascia oraria (`KAELTEKR_UMKEHR`, `VERDICHTER1`, `SEK_PUMPE1`); fare sempre fede all'attore + `status` e a `d6`.
   * **Pressione gas caldo**: `heating.sensors.pressure.hotGas` è **pressione assoluta ($\text{bar}_a$)** (verificata a riposo contro la curva di saturazione NIST R410A).
   * Il widget `ui/heating_curve_widget.py` visualizza esplicitamente la linea di riferimento violetta per $T_{\text{normale}}$, il badge informativo e calcola i punti coerentemente con il setpoint reale impostato sulla macchina.

### B. Pitfall BTicino / Netatmo Energy API:
1. **OAuth2 Scopes per BTicino Smarther**:
   * `read_thermostat` e `write_thermostat` funzionano SOLO sui termostati bianchi a marchio Netatmo!
   * Per il **BTicino Smarther** (tipo modulo `BNS`, MAC `00:03:50:...`) i soli scope validi sono:
     `read_smarther` e `write_smarther`.
   * Se usi gli scope errati, `/homesdata` restituisce la stanza "Corridoio" ma con `modules: []` vuoto e temperature `None`.
2. **Grant Type Password Bloccato da WAF**:
   * Le chiamate OAuth direct password su `api.netatmo.com` sono bloccate con 403 da Cloudflare.
   * Si DEVE usare `NETATMO_REFRESH_TOKEN` generato dalla sezione "Token generator" del portale [dev.netatmo.com/apps](https://dev.netatmo.com/apps).
3. **Cache Token Invalidation**:
   * Il connettore `api/bticino.py` usa una cache su file in `data/netatmo_token.json`. Se l'utente aggiorna il refresh token in `.env`, eliminare la cache per forzare la rigenerazione dell'access token con i nuovi permessi.
4. **Rilevamento Pompa Grundfos**:
   * Il consenso Grundfos corrisponde a `heating_power_request > 0` o `boiler_status == True` nel JSON del modulo/stanza.
5. **Endpoint di Scrittura Setpoint / Modalità (Risolto Errore 403 Code 13)**:
   * **NON** usare `POST /api/setroomthermpoint`! Netatmo Energy API restituisce errore `403 Forbidden: {"code": 13, "message": "Operation is forbidden"}` perché tale endpoint è riservato ai dispositivi Energy puri (`NATherm1`, `NRV`).
   * Per il **BTicino Smarther (`BNS`)** si DEVE usare l'endpoint Legrand Home + Control:
     `POST https://api.netatmo.com/api/setstate`
     con payload:
     `{"home": {"id": "<home_id>", "rooms": [{"id": "<room_id>", "therm_setpoint_mode": "manual", "therm_setpoint_temperature": 7.0, "therm_setpoint_end_time": <ts>}]}}`
     oppure `"therm_setpoint_mode": "home"` (per tornare al programma) / `"hg"` (antigelo).
6. **Gestione Error Code 6 (`device_unreachable`) in `/homestatus`**:
   * Se il termostato cade momentaneamente dal Wi-Fi o è in sleep radio, la risposta JSON contiene `"errors": [{"code": 6}]` e `rooms: []` è vuoto.
   * `api/bticino.py` usa una cache `last_status` per evitare che la telemetria inserisca valori `None` o salti a zero nei grafici temporali.
7. **Continuità Tracce e Prevenzione Gap nei Grafici**:
   * In `ui/main_window.py`, `FetchDataWorker` esegue un fallback sull'ultimo record valido presente in SQLite nel caso in cui un campionamento non riceva risposta, impedendo l'inserimento di righe `NULL`.
   * Le tracce `pyqtgraph` utilizzano `connect="finite"` per interpolare e congiungere i punti validi con linee continue.
8. **Rilevamento Pompa Grundfos e Regola Termodinamica $T_{setpoint} \le T_{ambient}$**:
   * Quando il setpoint viene abbassato sotto la temperatura ambiente (es. da 12.0 °C a 7.0 °C con stanza a 7.8 °C), i server Netatmo impiegano 60-120 secondi a sincronizzare lo spegnimento del relè fisico dal modulo Smarther.
   * `api/bticino.py` applica un controllo di coerenza fisica: se $T_{setpoint} \le T_{indoor}$, `grundfos_pump_active` è impostato a 0, evitando falsi positivi da ritardo cloud.
   * In `ui/main_window.py`, le bande verticali gialle di delimitazione delle regioni `LinearRegionItem` sono azzerate con `pen=null_pen` e `hoverPen=null_pen`, lasciando solo la campitura colorata pulita (verde per Grundfos, ambra per compressore) che si chiude esattamente sull'ultimo istante in cui il dispositivo era attivo.
9. **Snap Magnetico del Cursore su Asse X (`_on_chart_mouse_moved`)**:
   * Per evitare letture su valori interpolati astratti tra un prelievo e l'altro, il cursore verticale `crosshair_v` aggancia via `bisect` la coordinata temporale esatta del campione reale più vicino.
   * L'HUD superiore visualizza il codice `📍 Campione #id` e i valori effettivi registrati a database in quell'istante.
10. **Evidenziazione Dinamica Tracce & Badge Fluttuante (`_apply_curve_highlight`)**:
   * Quando il puntatore si trova entro 28 px da una curva, la traccia si ispessisce a 4.5 px con `zValue=100` e punti ingranditi, mentre le altre curve si attenuano leggermente in trasparenza.
   * Un badge `pg.TextItem` con marker `pg.ScatterPlotItem` compare sopra il punto per visualizzare il nome della traccia e il valore esatto registrato.

### C. Ergonomia UI, Stepper, Reset e Finestre di Conferma:
1. **Hitbox Spinbox Qt**:
   * Quando si applica padding a `QSpinBox` / `QDoubleSpinBox`, definire sempre esplicitamente `::up-button` e `::down-button` con larghezza (es. 24px) e `subcontrol-origin: border` per evitare click a vuoto o freccette offsettate.
   * Affiancare sempre pulsanti stepper fisici `[-]` e `[+]` (`.btn-step`) a ogni controllo numerico.
2. **Pulsanti Reset `↺` & LED di Stato**:
   * Ogni parametro (Slope, Shift, Temp Normale, Temp Ridotta, Setpoint BTicino) dispone di un tasto di reset `↺` per ripristinare il valore attualmente salvato sulla macchina.
   * I LED (`🟢 Sincronizzato` / `🟠 Modifica in sospeso`) tracciano in tempo reale se il valore a video differisce da quello confermato dall'hardware.
3. **Conferma Modale Obbligatoria prima dell'Invio**:
   * Nessun comando di scrittura verso Viessmann o BTicino deve partire senza un `QMessageBox.question` di riepilogo con pulsante di default su `No`.

### D. Architettura Cloud Logging GitHub Actions & cron-job.org (24/7 Headless):
1. **Orchestrazione Ibrida e Bypass Limitazioni Cron**:
   * Repository GitHub collegato: `giacomogussetti-lgtm/vitocal-remote`.
   * Per evitare i ritardi imprevedibili (20-45 min) dello scheduler `cron` interno dei runner gratuiti di GitHub, il campionamento è pilotato via HTTPS da `cron-job.org` tramite `POST .../dispatches` con token PAT (`workflow_dispatch`).
   * Esegue `scripts/cloud_logger.py`, che interroga Viessmann e BTicino (1 sola chiamata ciascuno) e fa append a `data/cloud_telemetry.jsonl`.
   * Il workflow gestisce la concorrenza con `concurrency: group: telemetry-logger`, impedendo sovrapposizioni.
   * Consumo API: a 10-15 minuti di intervallo, consumo Viessmann 96-144 chiamate/giorno su 1.440 (~7-10%). Precisione al secondo.
2. **Sincronizzazione Cloud -> SQLite**:
   * L'applicazione desktop dispone del pulsante `☁️ Sync Cloud (GitHub)` nella barra superiore, che importa i campioni da `cloud_telemetry.jsonl` nel database SQLite locale scartando i duplicati basandosi sull'indice `timestamp_utc`.
   * **Bypass Cache CDN Fastly GitHub (300s)**: `raw.githubusercontent.com` applica una cache CDN di 5 minuti. L'URL include `?t={int(time.time())}` con intestazioni `Cache-Control: no-cache` e `Pragma: no-cache` per garantire che ogni clic scarichi sempre l'ultimo commit in tempo reale senza attendere il refresh della CDN.
3. **Politica di Ritenzione Dati & Rotazione Hot/Cold (Campionamento 5 Minuti - Finestra 6 Mesi)**:
   * Con campionamento ogni 5 minuti (288 campioni/giorno = 8.640 campioni/mese), un log continuo non segmentato raggiungerebbe 72 MB/anno, eccedendo i limiti di commit Git e saturando la memoria.
   * `scripts/cloud_logger.py` adotta una **sliding window estesa di 6 mesi / 180 giorni** (`MAX_HOT_SAMPLES = 51840`, soglia isteresi `ROTATION_THRESHOLD = 52500`, `MIN_BYTES_BEFORE_CHECK = 32_000_000`).
   * `cloud_telemetry.jsonl` conserva sempre gli ultimi 6 mesi completi (~34.7 MB raw, ma solo ~3.8 MB scaricati effettivamente via 4G/Wi-Fi grazie alla compressione automatica gzip di GitHub).
   * I campioni che superano i 6 mesi vengono automaticamente compressi e archiviati per mese in `data/archive/telemetry_YYYY-MM.jsonl.gz`.
   * `DatabaseManager.import_file()` su desktop supporta in modo trasparente sia `.jsonl` che `.jsonl.gz`, archiviando a lungo termine tutto lo storico su SQLite (`vitocal_telemetry.db`).

### E. Regole Mandatorie di Sicurezza, Privacy e Controllo Pre-Commit:
1. **Anonimizzazione Geografica e Dati Personali (Anti-Intrusione)**:
   * Nei file pubblici, esportati o versionati non devono MAI comparire toponimi di comuni/paesi specifici né indirizzi email personali o MAC address fisici.
   * **Motivo di sicurezza fisica**: trattandosi di una seconda casa non presidiata nei feriali, associare la località con le letture di temperatura o setpoint (es. 7.0 °C fissa) rivelerebbe che la casa è disabitata.
   * Usare sempre definizioni tecniche generiche: *"Abitazione di Montagna (Zona Climatica E)"*, *"Circuito Secondario"*.
2. **Scanner di Sicurezza Automatico**:
   * Prima di caricare file su GitHub o modificare `github_ready/`, eseguire sempre:
     `python scripts/prepare_github_export.py`
     oppure:
     `python scripts/security_check.py`
   * Lo script blocca l'operazione con codice di errore se rileva password, token, email personali o toponimi geografici.

### F. Gestione Precaricamento SQLite & Sincronizzazione Cloud:
1. **Estrazione Sicura Dizionario da SQLite**:
   * La funzione `_load_latest_db_sample` usa `row_dict = dict(row)` con `.get()` per evitare `IndexError`/`KeyError` in caso di variazioni schema tra migrazioni.
   * Il campo umidità nel database è `humidity_percent`.
2. **Refresh Grafico su Sincronizzazione**:
   * Nel metodo `_on_sync_cloud_clicked`, il richiamo di `_load_latest_db_sample()` e `_update_charts()` è eseguito sia quando vengono aggiunti nuovi record (`imported_count > 0`), sia nel ramo `else` (quando i dati scaricati sono già archiviati), garantendo il ricaricamento istantaneo del sinottico e dei grafici.

### I. Gestione Automatica dei Workflow YAML & CI/CD:
1. **Responsabilità Esclusiva dell'Agente AI**:
   - L'utente non deve mai comporre o correggere a mano file YAML o workflow di GitHub Actions.
   - L'agente genera, modifica e valida direttamente tutti i file `.github/workflows/*.yml` nel workspace.
   - Ogni modifica viene replicata in `github_ready/` ed esportata tramite `python scripts/prepare_github_export.py`.

### J. Architettura Comandi Remoti da Mobile (Scrittura Setpoint & Curva Climatica):
1. **Stesse API Cloud del Desktop (Zero Duplicazione Credenziali)**:
   - Le credenziali API Viessmann e BTicino/Netatmo appartengono all'impianto (alla caldaia e al termostato), NON ai singoli smartphone.
   - Non serve rigenerare token diversi per ogni dispositivo o per ogni smartphone: tutti fanno riferimento allo stesso impianto.
2. **Esecuzione Comandi via Cloud Executor (GitHub Actions)**:
   - I browser mobili su GitHub Pages non possono fare chiamate dirette a PyViCare a causa del CORS e per ragioni di sicurezza (mai esporre password Viessmann nel frontend web).
   - Soluzione: l'app mobile invia un `workflow_dispatch` con parametri (es. `action: set_temperature`, `target: bticino`, `value: 12.0`) a un workflow dedicato (`apply_command.yml`).
   - Il runner GitHub esegue lo script Python in ambiente isolato usando i **GitHub Secrets** già memorizzati (`VIESSMANN_USER`, `NETATMO_REFRESH_TOKEN`), verifica il read-back e conferma il risultato all'app mobile.
   - In questo modo sul cellulare serve SOLO il Personal Access Token di GitHub (PAT), garantendo massima sicurezza e funzionamento 24/7 in 4G/5G ovunque nel mondo.

### K. Grafici Web / PWA Mobile (Chart.js Continuous Time vs Category Scale):
1. **Pitfall Scala a Categorie in Chart.js**:
   - Se a Chart.js vengono passati `labels: [...]` e un array ordinario di valori `data: [y1, y2, ...]`, la libreria usa di default una **Category Scale**.
   - Nella scala a categorie, ogni campione è distanziato a intervalli orizzontali identici indipendentemente dall'orario reale (un salto di 1 ora occuperebbe lo stesso spazio a video di un intervallo di 1 minuto, falsando visivamente la pendenza termica).
   - Per una telemetria termodinamica coerente, si DEVE usare una scala temporale continua: `type: 'time'` con date adapter (`chartjs-adapter-date-fns`).
   - I punti nei dataset devono avere coordinate `{ x: timestamp_ms, y: value }`. In questo modo la coordinata orizzontale riflette i minuti effettivi, le tacche orarie vengono calcolate ad intervalli uniformi (es. 01:00, 01:30, 02:00) e l'interazione touch (`mode: 'nearest', axis: 'x'`) aggancia la fetta temporale corretta con tooltip completo.
   - Le librerie (`chart.min.js` e `chartjs-adapter-date-fns.bundle.min.js`) sono salvate in `web/js/` e gestite dal Service Worker (`sw.js`) in modalità offline-first, funzionando senza necessità di connessione a CDN esterne.
2. **Prevenzione Campioni Equidistanti (`distribution: 'linear'`, `bounds: 'ticks'`)**:
   - Per impedire che i campioni vengano disegnati a distanze orizzontali identiche nonostante intervalli temporali diversi (es. un buco di 1 ora o campioni a 5 min), la scala temporale adotta esplicitamente `distribution: 'linear'` e `bounds: 'ticks'`.
   - In `web/js/charts.js`, le funzioni `buildChart` e `updateChartData` calcolano dinamicamente `min = latestMs - hours` e `max = latestMs` ancorando l'asse X all'esatto intervallo temporale selezionato.
   - La cache PWA in `web/sw.js` è versionata (`vitocal-remote-v16`, con query cache-buster `?v=16` sugli asset in `web/index.html`) per forzare il refresh immediato su tutti i dispositivi mobili.
3. **Grafici Pro Mobile Edge-to-Edge, Touch Stile TradingView, Resa Termica & Cerca Canali (`web/js/charts.js`, `web/js/help.js`, `web/css/styles.css`)**:
   - **Layout Mobile Edge-to-Edge & Zero Chrome Sprecato**: su smartphone `< 640px` la card grafica è a tutta larghezza, i controlli sopra sono compattati in 2 righe scorrevoli (Timeframe + navigatore `◀ Ciclo ▶` + Preset/Scale/Bande) e `#chartWindowStats` scorre su 1 riga fissa; gli assi Y nascondono i titoli ruotati e l'asse destro `yOther` sparisce automaticamente quando nessun canale lo usa (+70–100 px orizzontali e +100 px verticali!).
   - **Gesti Touch Stile TradingView & HUD Fissa (`#chartScrubHud`)**: su smartphone 1 dito trascina fluidamente l'asse X (`✋ Pan`), Tap o Long-Press 180 ms (con micro-vibrazione) aggancia il mirino magnetico con barra HUD fissa sopra il canvas (zero occlusione delle curve sotto al dito!) + valori aggiornati in tempo reale nei chip della legenda (`tabular-nums`, con filtro rapido `🎯 Solo attivi`), Doppio-Tap fa Zoom 2.2× / Reset, e 2 dita eseguono pinch zoom + drag su asse X. Su smartphone orizzontale (`orientation: landscape` + `max-height: 540px`) `header` e `nav.bottom-nav` spariscono lasciando solo il pulsante flottante `☰`.
   - **Asse Y Bloccato & Modale Tappabile**: durante zoom/pan in X gli assi Y restano congelati (`yAutoFrozen`, con `grace: '14%'` in auto su `yTemp` per lasciare spazio a bande e badge); toccando l'asse o le pillole `°C` / `%` si fissa il range in `localStorage`. Quando si aggiunge/rimuove un canale da zoomato, `updateChartData` ricalcola il riferimento Y sulla finestra del timeframe prima di ricongelare l'asse.
   - **Bande Verticali, Durate ON, Anti-Glitch Cloud & Resa Calibrata (`activityBandsPlugin`)**: mostra fasce + nastro 6px per `Solo PdC`, `Solo Grundfos`, `PdC + Grundfos` con filtro anti-glitch sui poll Viessmann vuoti (evita falsi `Stop SP`) e sui singoli drop `code 6` BTicino (`GF=0` con `BT_SP >= T_in + 2°C`). Calcolo energetico a integrazione trapezoidale con COP dinamico (curva Carnot) e penalità defrost (`-3.5 kWₜ`, `+1.35 kWₑ`), conteggio episodi defrost distinti (`❄️ Defrost: N (Xm)`) e COP netto reale in `#chartWindowStats`.
   - **Nuove Tracce Core & Cerca Canali Espandibile (`🔍 + Canali`)**: esposte tra le tracce core `ΔT Primario (LWT−EWT)` (`_delta_lwt_ewt`) e `Circolatore Primario P1` (`primary_pump_rotation_percent`, incluse nel preset `Inverter`), più `#channelSearchDrawer` posizionato subito sotto `.chart-header` per aggiungere on-demand 24 canali extra inclusi canali diagnostici R410A (`_t_cond_c`, `_subcooling_k`, `_evap_depression_k`, `_discharge_superheat_k`, `_delta_buf_target`, `primary_supply_temp_c`).
   - **Preset Rapidi, Legenda ad Alto Contrasto & Stop Setpoint (`telemetryAnnotationsPlugin`)**: preset (`Termo`, `Inverter`, `Casa`, `Tutto`), legenda raggruppata Grafana-style con valori live/scrubbed + doppio-tap *Solo*, salto rapido `⏭️ Ciclo`, e marker `🎯 Stop SP` (`detectSetpointCutoffEvents`).
   - **Guida Contestuale `(i)` Ovunque (`web/js/help.js`)**: ogni parametro dell'Autopilota, profilo, comando PdC/BTicino, grafico e monitor quote espone un pulsante `i` con scheda esplicativa modale (*Cos'è / Effetto / Consiglio*).
4. **Sinottico SCADA PWA/Desktop Responsive, Target Reali & Resistenza Backup (`web/js/synoptic.js`, `ui/synoptic_widget.py`)**:
   - Rilevamento automatico viewport/orientamento (`detectSynopticMode` + listener `resize`/`orientationchange`) tra **Verticale Portrait** (`viewBox 0 0 420 850`, zero scroll orizzontale) e **Orizzontale Landscape** (`viewBox 0 0 1260 560`).
   - **Target Acqua & Target Casa Reali al posto del Setpoint Dummy BTicino**: nel sinottico SVG (Portrait/Landscape), nelle 6 card rapide (`#synopticKpiDrawer`) e nel sinottico Desktop PyQt6, il setpoint fittizio BTicino (`6.5 °C` / `18.0 °C`) è sostituito da **Target Acqua (Puffer)** e **Target Casa Reale** (es. `7.5–8.8 °C` in Full-Auto).
   - Mini-badge compatto **`RESIST. S1/S2`** (`svgBackupHeaterBlock`, allineato sotto `ΔT PRIM.`) che distingue attivazione/minuti odierni (`OFF · 0m` / `OGGI Xm` / `⚡ ON`) rispetto ai contatori storici cumulativi in scheda Sonde (`480.774s` S1 / `475.751s` S2).
   - Schematizzati: circolatore primario PdC `P1` con girante rotante e %, circolatore Grundfos secondario, ventilatore evaporatore, mini bollitore ACS 220L, puffer con gradiente termico dinamico e casetta con tetto a falde che contrappone aria esterna (`T Esterna OAT`) ad aria interna (`BTicino Smarther`) e serpentina radiante collegata alle tubazioni.
5. **PWA Bidirezionale, Scenari Coordinati, Timeline Oraria 24h & Monitor Quote (`api/bticino.py`, `scripts/cloud_commander.py`, `web/js/commands.js`, `.github/workflows/apply_command.yml`)**:
   - **Fix Soglia `setpoint == indoor_temp` in `api/bticino.py`**: il sanity check anti-lag cloud usa `setpoint < (temp - 0.3)` anziché `setpoint <= temp`, evitando di mascherare a `0` le reali attivazioni PID/isteresi di Smarther quando il setpoint coincide con la temperatura stanza (es. `8.5 °C == 8.5 °C`).
   - **UX Tab Comandi Ridisegnata**: scenari rapidi preconfigurati e salvabili (`apply_full_profile`) che coordinano PdC + consenso pompa BTicino; **Pianificatore Orario Grafico 24h** (`#pdcScheduleTimeline`) con chip giorni e preset salvabili; controlli diretti con conferma modale obbligatoria, LED di sincronizzazione, stepper, preview curva LWT e Monitor Quote API (`renderApiQuotaMonitor`) su letture + scritture.

### M. Autopilota Custodia Montagna Full-Auto v2, Soft-Start, Defrost Guard, Anti-Grippaggio & Quote API (`scripts/autopilot.py`, `scripts/audit_strategy.py`):
1. **Sensori Diagnostici Esposti (`api/viessmann.py`, `scripts/cloud_logger.py`)**:
   - `compressor_phase` (`heating.compressors.0.phase`), `frost_protection_status`, `heating_rod_level1_s` / `heating_rod_level2_s`, `primary_supply_temp_c` (aria ingresso ODU), `error_counter_d6` (`device.messages.errors.counter.d6`), `load_class_1_h..5_h` (`heating.compressors.0.statistics.load`) e logbook WO1C decodificato in `autopilot_state.json`.
   - **Resilienza Logger (`api/bticino.py`, `scripts/cloud_logger.py`)**: su `code 6` Netatmo stateless `grundfos_pump_active` torna `None` (non `0`) e viene ripristinato dall'ultimo campione valido; su timeout/fallimento Viessmann `cloud_logger.py` esegue fallback completo senza mai registrare falsi `compressor_active = 0`.
2. **Macchina a Stati Autopilota Full-Auto v2/v3 (`scripts/autopilot.py`)**:
   - Configurazione calibrata su dati reali 21/11, 24/11 e 26/11 in `data/autopilot_config.json`: `target_lwt_delta_k = 15.5`, `min_target_lwt_c = 23.5`, `max_target_lwt_c = 26.5`, `defrost_min_safe_lwt_c = 23.0`, `soft_start_min_lwt_c = 22.8`, `cron_active_minutes = 1` (massima risoluzione 1 min durante marcia PdC; jitter reale misurato 26/11: med `60s`, p95 `86s`, max `114s`, 0 gap > 120s).
   - **Fix Audit, Contro-Audit & Upgrade SCADA `7209` (`vitocal-remote-v22` / `v23`)**: (1) `compute_optimal_sp_and_shift_for_target_lwt(..., min_lwt_floor_c)` combina `SP` intero e `Shift ∈ [-1, 0, +1]` mantenendo `Slope = 0.6` come fail-safe autonomo offline (risoluzione fine `~0.3–0.5 °C` senza mai scendere sotto `min_target_lwt_c = 23.5 °C`, reset a `Shift = 0` in `IDLE`; `Slope = 0.0` mandata fissa scartato perché insicuro se cade internet col gelo); (2) Soft-Start disattivato automaticamente in condizioni di brina `MEDIO/ALTO` a `regime_sp ≤ 14` (dai log 21–26/11 non riduce la rampa 0–20m ma ridurrebbe la riserva BPHE prima del 1° defrost); (3) `ap_min_end_ext` pre-estende fascia WO1C (+10m margine anti-drift orologio WO1C ~+3.5m) con **15 min di anticipo** e salva `base_window_end_local` per non perdere l'uscita anticipata a `8.2 °C`; (4) `thermal_model.py` stima anche **`k_rad_end_kw_per_k`** (`t ≥ 90m`, decadimento `-15%..-35%` dello scambio a massetto caldo) per il pavimento anti-ON/OFF, mentre il bilancio chiuso misura **`H_tot ≈ 210 W/K`** (`189 W/K` soleggiato – `231 W/K` coperto; curva comfort `21.0 °C` di riferimento: `T_norm=21 °C, Slope=0.6, Shift=-5 K`, o `-6 K` con vicini sotto accesi); (5) **Tachimetro SCADA Anti-Stacco WO1C (`7209` / `7203` / BPHE Defrost, `v23`)** integrato dentro il Puffer 200L nel Sinottico SVG (Portrait + Landscape), nel Sinottico Desktop PyQt6 (`ui/synoptic_widget.py`), nel Cockpit interattivo `#wo1cCutoffMarginCard` (con memoria dell'ultimo picco anche in Standby), nel canale grafico `_wo1c_sat_pct` (`charts.js`) e nella sezione obbligatoria `AUDIT INDICATORE ANTI-STACCO WO1C` di `scripts/audit_strategy.py`.
   - **Nota Limite Hardware Cloud ViCare & Checklist Prove Future (`P1..P6` in `vitocal-thermodynamic-tuning/SKILL.md`)**: il *Funzionamento silenzioso* locale WO1C non è controllabile da remoto via API ViCare ed è escluso per scelta progettuale; restano attive le verifiche `P1..P6` (fix ciclo umido `P1`, audit indicatore `7209` `P2`, curva Grundfos `P3`, clock WO1C `P4`, gelo sotto zero `P5`, taratura contatore elettrico `P6`).
   - **Soft-Start Anti-Overshoot (`soft_start_enabled = True`, `soft_start_step_minutes = 25`)**: parte 1–2 °C sotto il target di regime a puffer freddo (pavimento `≥ 21.8 °C` per garantire riserva termica BPHE anche su defrost precoci) e sale dolcemente a gradini di +1 °C per evitare picchi 88% e stacchi di isteresi.
   - **Defrost Guard Anti-Brina (`defrost_guard_enabled = True`, `defrost_trim_threshold_count = 2`, `defrost_guard_oat_max_c = 5.5`)**: se rileva ≥2 episodi defrost nel ciclo o forte depressione evaporatore (`OAT - T_suc >= 13 K` a `Mod >= 75%` con `OAT <= 5.5 °C`), abbassa dolcemente il target di `-1 °C` (fino al pavimento di sicurezza BPHE/inverter `max(22.0, T_in + 13.5)` — mai sotto `22.0 °C` per garantire `LWT_min >= 13-14 °C` in sbrinamento e restare sopra il floor inverter reale `38%`), **protetto da guardia isteresi (`buf_temp <= candidate_lwt + 1.0 K`)** per non innescare mai uno stacco immediato del compressore.
   - **Anti-Grippaggio Grundfos Nativo (`anti_seize_days = 4`)**: sostituisce la fascia BTicino 08:00–08:15 (che Full-Auto sovrascrive con modalità `hg` fissa) facendo girare la sola Grundfos 15 min tra le 12:00 e le 12:45 se l'impianto resta fermo ≥4 giorni in `IDLE`.
   - **Zero Soglie Hardcoded & Modello Matematico Auto-Convergente (`scripts/thermal_model.py`, `data/thermal_model.json`)**: tutte le soglie di sicurezza (`defrost_min_safe_lwt_c`, `defrost_min_delta_k`, `soft_start_min_lwt_c`, `defrost_guard_oat_max_c`, `inverter_min_mod_pct`, `adaptive_model_enabled`, `adaptive_model_apply_targets`) sono configurabili dalla PWA e validate da `cloud_commander.py`. A ogni ciclo completato (`PUFFER_DRAIN -> IDLE`), `thermal_model.py` aggiorna con Bayesian shrinkage `k_rad`, floor inverter, caduta BPHE in defrost e dispersione UA dell'edificio, permettendo al sistema di convergere su target matematici data-driven.
   - **Pianificatore Meteo Dinamico, Anti-Short-Cycle & Pre-Armamento Predittivo (`scripts/weather_planner.py`, `data/weather_forecast.json`, `vitocal-remote-v19`)**:
     * Interroga Open-Meteo (`best_match` / ICON-D2 con correzione altimetrica) leggendo `WEATHER_LAT`, `WEATHER_LON`, `WEATHER_ELEVATION_M` **esclusivamente** da GitHub Secrets / `.env` locale e sanitizzando la cache (zero coordinate e zero toponimi nei file versionati).
     * **Modelli Unificati EN 14511 & Letteratura (`thermal_model.py`, `storage/analytics.py`, `charts.js`, `weather_planner.py`)**: curva COP calibrata su Vitocal `111.A16` (A7/W35 `4.37–4.50`, A2/W35 `3.32`, A-7/W35 `2.72`), modello brina continuo senza gradini binari (`T_evap = OAT - 6.5 K`, envelope brina + pioggia/neve proporzionale) e fattore vento su dispersione `UA`.
     * **Gestione Casi Limite & Anti-Slittamento**: (1) *Blocco Finestra Pre-Avvio* (`window_lock_before_start_minutes = 90`) + *Guardia Emergenza* (non posticipa mai oltre il punto in cui `T_in ≤ T_emerg + 0.2 °C`) + *Posticipo Asimmetrico* (max 1/giorno su guadagno COP forte); (2) *T Min Fine Ciclo* (`min_cycle_end_temp_c = 8.2`: estende fino a `+60 min`, max `18:30`, se partito da freddo intenso non ha ancora accumulato isteresi sufficiente); (3) *Anti-Micro-Ciclo* (`min_cycle_minutes = 120`); (4) *Pre-Armamento Predittivo* e *Arbitraggio Rinvio Meteo* anti-starvation.
     * **Trasparenza Glass-Box, Sinottico & Audit Self-Tuning in PWA (`vitocal-remote-v19`)**: cassetto espandibile `☀️ Finestra Target` direttamente nella tab **Sinottico** + cassetti `🌦️ Previsioni Meteo` e `📈 Registro Self-Tuning, Convergenza & Verifica Meteo` in **Comandi** con diagnostica Bayesiana, storico `thermal_model.json["history"]` e tabella oraria `Open-Meteo vs Sonda Reale OAT`.
     * **Fix `scripts/git_safe_push.py`**: in modalità `telemetry` ora committa anche `data/thermal_model.json` e `data/weather_forecast.json`.
   - **Self-Tuning Soft Curva (`soft_curve_tuning_enabled = True`, cooldown `45 min`)**: anch'esso protetto dalla guardia isteresi sul puffer.
   - **Doppio Fail-Safe Hardware & Push Race-Free (`scripts/git_safe_push.py`)**: manuale BTicino sempre con scadenza automatica + fascia hardware `heating.schedule` Vitocal; merge deduplicato senza conflitti tra `telemetry_logger.yml` e `apply_command.yml`.
3. **Audit Strategia Obbligatorio (Regola #0 di Inizio Chat), Zero Bias & Rollback Data-Driven (`scripts/audit_strategy.py`, `scripts/thermal_model.py`, regola `.agents/rules/thermodynamic-rigor-and-telemetry-audit.md`)**:
   - **A ogni inizio conversazione** e prima di qualsiasi tuning su ON/OFF, defrost, meteo o soglie, eseguire `git pull --rebase origin main`, `python scripts/audit_strategy.py` e `python scripts/thermal_model.py` per verificare dati reali, modalità applicate, durata cicli, pendenze termiche, margine BPHE, contatori resistenza elettrica e **self-tuning meteo** (`oat_bias_c`, `oat_mae_c`, `tin_projection_mae_c`, `frost_penalty_scale`).
   - **Zero Bias & Marcia Indietro**: confrontare sempre i nuovi cicli con la baseline storica pre-modifica (21/11 e 24/11) senza difendere nuove logiche per pregiudizio; se dai dati emerge che l'impianto andava meglio prima, dichiararlo apertamente ed eseguire rollback mirato.
   - **Consumi Reali (`storage/analytics.py`, `web/js/analytics.js`)**: la Vitotronic 200 WO1C (`CU401B_S_64`) non espone nativamente `heating.power.consumption.*` né `heating.heat.production.*` via ViCare API; il gestionale usa un modello calibrato a integrazione trapezoidale + COP dinamico Carnot + penalità defrost + contatori resistenza backup + registro giornaliero (`dailyBreakdown`). Per misura fiscale ±1%, consigliato contatore esterno tipo Shelly EM / Pro 1PM sul magnetotermico PdC+Grundfos.

### L. Procedura di Deploy su GitHub (Automatizzata al 100% via Git CLI):
1. **Automazione Git Completa (Nessun Upload Manuale nel Browser)**:
   - È configurato Git per Windows con eccezione TinyWall su `C:\Program Files\Git\ucrt64\libexec\git-core\git-remote-https.exe`.
   - Il repository locale è collegato a `origin/main` (`giacomogussetti-lgtm/vitocal-remote`).
   - L'agente AI gestisce modifiche, commit e push direttamente via riga di comando (`git push origin main`).
   - Il caricamento manuale drag-and-drop su browser è superato: l'agente esegue lo scanner di sicurezza (`python scripts/security_check.py`), verifica `.gitignore` e invia le modifiche in autonomia senza rischi di esporre file nascosti o token.

---

## 3. STRUTTURA DEL REPOSITORY
```text
vitocal remote/
├── .agents/
│   ├── rules/
│   │   ├── security-and-privacy.md               # Regola permanente di audit pre-commit
│   │   └── thermodynamic-rigor-and-telemetry-audit.md # Rigore fisico & audit obbligatorio
│   └── skills/
│       ├── vitocal-remote-expert/                # Skill runbook, architettura e troubleshooting
│       ├── vitocal-build-deploy/                 # Skill checklist e release su GitHub
│       └── vitocal-thermodynamic-tuning/         # Procedura periodica di audit log & calibrazione
├── .github/
│   └── workflows/
│       ├── telemetry_logger.yml                  # Workflow GitHub Actions 24/7 (cron + autopilot)
│       ├── apply_command.yml                     # Executor comandi remoti PWA -> Vitocal/BTicino/Autopilota
│       ├── deploy_pwa.yml                        # Deploy automatico dell'app web PWA su GitHub Pages
│       └── build_apk.yml                         # Compilatore cloud APK nativo Android Capacitor
├── .env                                          # Credenziali e token (NON versionare)
├── .env.example                                  # Template credenziali anonimizzato
├── .gitignore                                    # Esclusioni git (token, cache, db, dumps)
├── requirements_cloud.txt                        # Dipendenze headless minime per GitHub Actions
├── config.py                                     # Validazione e caricamento impostazioni
├── app.py                                        # ENTRY POINT APPLICAZIONE DESKTOP PYQT6
├── web_server.py                                 # SERVER FLASK PER APP MOBILE ANDROID (PWA)
├── avvia_gestionale.bat                          # Launcher desktop Windows doppio-clic
├── avvia_app_mobile.bat                          # Launcher server mobile Android doppio-clic
├── test_bench.py                                 # Banchetto prova interattivo CLI
├── web/                                          # Frontend Web & PWA per Smartphone Android
│   ├── index.html                                # Layout mobile SCADA con 5 Tab (Sinottico, Comandi, Grafici, Analisi, Sonde/Sync)
│   ├── manifest.json                             # Manifest per installazione nativa Android
│   ├── sw.js                                     # Service Worker per caching e offline (`vitocal-remote-v9`)
│   ├── css/styles.css                            # Tema SCADA scuro industriale per schermi touch
│   ├── icons/                                    # Icone 192px e 512px per Android
│   └── js/
│       ├── synoptic.js                           # Motore SVG responsive del Sinottico animato
│       ├── charts.js                             # Grafici Pro (zoom X, Stop SP, durata bande, preset)
│       ├── commands.js                           # Logica controlli bidirezionali & pannello Autopilota
│       ├── help.js                               # Catalogo spiegazioni contestuali tap `(i)`
│       └── app.js                                # Controller PWA, sync GitHub, analytics & trigger
├── api/
│   ├── viessmann.py                              # Connettore Viessmann PyViCare (lettura/scrittura + diagnostica)
│   └── bticino.py                                # Connettore Netatmo/BTicino Smarther (read/write_smarther)
├── storage/
│   └── database.py                               # Manager SQLite (tabella telemetry_samples versionata)
├── models/
│   └── telemetry.py                              # Modelli Pydantic per telemetria
├── ui/
│   ├── main_window.py                            # Interfaccia grafica desktop PyQt6
│   ├── heating_curve_widget.py                   # Visualizzatore dinamico Curva Climatica LWT vs OAT
│   └── synoptic_widget.py                        # Sinottico SCADA vettoriale desktop
├── scripts/
│   ├── feature_dumper.py                         # Diagnostica completa e dump 193 features
│   ├── cloud_logger.py                           # Logger headless 24/7 + tick autopilota
│   ├── cloud_commander.py                        # Esecutore sicuro comandi remoti & ricevute
│   ├── git_safe_push.py                          # Helper push concorrente race-free per Actions
│   ├── autopilot.py                              # Macchina a stati Custodia Montagna & cron dinamico
│   ├── weather_planner.py                        # Pianificatore meteo Open-Meteo, finestra COP dinamica & look-ahead
│   ├── test_autopilot_weather.py                 # Test isolati casi limite autopilota & meteo
│   ├── audit_strategy.py                         # Report audit termodinamico su log reali
│   ├── security_check.py                         # Scanner preventivo di privacy e sicurezza pre-commit
│   └── prepare_github_export.py                  # Preparatore automatico cartella github_ready/
├── github_ready/                                 # Cartella pulita, verificata e anonimizzata per upload Git
├── data/
│   ├── vitocal_telemetry.db                      # Database SQLite locale
│   ├── cloud_telemetry.jsonl                     # Log telemetrico rolling live (6 mesi / 180 giorni)
│   ├── autopilot_config.json                     # Parametri tunabili Autopilota Full-Auto
│   ├── autopilot_state.json                      # Stato persistente macchina a stati Autopilota
│   ├── last_command.json                         # Ricevuta ultimo comando remoto eseguito
│   ├── archive/                                  # Archivi mensili compressi (telemetry_YYYY-MM.jsonl.gz)
│   └── dumps/                                    # Dump JSON reali delle API
├── AGENTS.md                                     # Questa memoria persistente per tutte le chat
├── PROJECT_STATUS.md                             # Registro avanzamento e changelog
└── README.md                                     # Istruzioni d'uso
```

---

## 4. PROCEDURA DI AVVIO E RIPRESA LAVORO (REGOLA OBBLIGATORIA NUOVO GIORNO)
Se l'utente apre una nuova chat (specialmente in un nuovo giorno) e chiede di continuare o analizzare l'impianto:
1. Leggi questo `AGENTS.md`, `PROJECT_STATUS.md`, `.agents/rules/thermodynamic-rigor-and-telemetry-audit.md` e `.agents/skills/vitocal-thermodynamic-tuning/SKILL.md`.
2. **PRIMA di proporre o commentare strategie**: esegui `git pull --rebase origin main`, `python scripts/audit_strategy.py --hours 168` e `python scripts/thermal_model.py --write`.
3. **Audit Obbligatorio del Modello LWT Intelligente (`adaptive_model_apply_targets = true`, attivo dal 26/11/2026) & Estensione Meteo-Aware (`min_cycle_end_temp_c = 8.2 °C`)**:
   - **Perché è stato introdotto**: simulazioni su parametri reali (`k_rad = 0.413`, `α = 0.0161`, `UA = 0.179`, EN 14511 `111.A16`) hanno dimostrato che lavorare `6–7h` dolci a `LWT 23.0 °C` consuma `-7%..-13%` in meno in bolletta rispetto a comprimere in `3.5–4h` a `26.5–28.5 °C`. Pertanto `recommend_operating_targets` mantiene LWT bassa (`22.5–23.5 °C`) a `OAT ≥ 0 °C`, scala verso `26.5 °C` solo su gelo reale (`OAT ≤ -2..-8 °C`), e calcola il pavimento anti-ON/OFF su `ref_tin_end = min(T_max, T_in + 0.8)` (`>= 1.15 * P_min(OAT) / k_rad`) per proteggere da stacchi alle `OAT` miti (es. `+8 °C` → `≥ 24.2 °C`). Inoltre, in `HEATING_SYNC` l'estensione `+60 min` (fino a 2 step, tetto `18:30` / `420 min`, uscita anticipata appena `T ≥ 8.2 °C`) è subordinata al meteo (estende se evita emergenza notturna o se COP ora extra è entro `0.25` da domani; altrimenti spegne pulito).
   - **Cosa verificare OGNI nuovo giorno sui log reali**: (a) esaminare sempre la sezione `AUDIT INDICATORE ANTI-STACCO WO1C (7209 / 7203)` di `audit_strategy.py` (`SatMax %`, `% tempo 🟢/🟡/🔴`, margini Testa/Fondo ed eventuali near-miss `≥ 82%`) confermando che la casa assorba la potenza minima dell'inverter (`38–42%`) senza stacchi `7209`; (b) che `LWT_min` in defrost resti `≥ 12.0 °C` con `heatingRod = +0s`; (c) che le estensioni meteo-aware migliorino `kWhₑ/°C` ed evitino emergenze. Se si osservano stacchi ON/OFF prematuri o peggioramento rispetto alla baseline 21/11 e 24/11, **dichiararlo apertamente e fare rollback immediato** (`adaptive_model_apply_targets = false` o rialzo `min_target_lwt_c`).
4. Verifica che i connettori `api/viessmann.py` e `api/bticino.py` siano integri e mantieni sempre sincronizzati codice, `AGENTS.md` e `PROJECT_STATUS.md`.
5. Se l'utente vuole avviare l'app desktop o mobile locale: `avvia_gestionale.bat` / `avvia_app_mobile.bat` (`python web_server.py`).
