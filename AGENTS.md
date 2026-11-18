# MEMORIA PERSISTENTE DI PROGETTO: GESTIONALE VITOCAL 111-S & BTICINO SMARTHER

> **ATTENZIONE PER QUALSIASI AGENTE AI (NUOVE CHAT E SUB-AGENTI):**
> Questo file è la memoria centrale del progetto. Quando inizi una nuova conversazione, leggi questo documento prima di fare qualsiasi modifica. **Regola fondamentale:** ogni volta che implementi nuove funzioni o risolvi problemi, AGGIORNA sempre questo file e `PROJECT_STATUS.md`.

---

## 1. CONTESTO DELL'IMPIANTO FISICO (Abitazione di Montagna - Zona Climatica E)
L'abitazione è una seconda casa di montagna non presidiata nei giorni feriali, soggetta a rigide temperature invernali e rischio gelo per radiante e tubazioni nei muri perimetrali.
L'impianto è idraulicamente disaccoppiato in due sottosistemi tramite un **Puffer parallelo da 200 litri**:

1. **Circuito Primario (PdC <-> Puffer)**:
   * **Pompa di Calore**: Viessmann Vitocal 111-S split (AWBT-E-AC 111.A16, 11 kW nominali, refrigerante R410A) con bollitore ACS integrato.
   * **Centralina**: Vitotronic 200 tipo WO1C collegata a Vitoconnect Optolink ViCare.
   * **Dispositivo reale nel cloud Viessmann**: `CU401B_S_64` (Device tipo `heating`, 193 features hardware).
   * **Regolazione**: Curva climatica con Inclinazione (Slope) = 0.6, Livello (Shift) = 0, mandata max 40 °C. Setpoint Normale/Ridotta = 12 °C (o 10 °C baseline).
2. **Circuito Secondario (Puffer <-> Pavimento)**:
   * **Rilancio**: Circolatore Grundfos a velocità fissa che pesca dal puffer 200 L e alimenta i collettori del riscaldamento a pavimento.
   * **Termostato Ambiente**: BTicino Smarther (modello `BNS`, firmware 40) installato in "Corridoio".
   * **Comando**: Il consenso ON/OFF del termostato comanda direttamente la pompa Grundfos.
3. **Criticità Termodinamica Risolta dal Software**:
   * Se la Grundfos è spenta, la PdC da 11 kW satura rapidamente i soli 200 L di puffer e lavora a cicli brevi ad alto consumo.
   * Il sistema software orchestra preset multi-dispositivo per sincronizzare la PdC nelle ore più calde ad alto COP con l'accensione forzata della Grundfos per accumulare calore nel massetto radiante.

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
6. **Curva Climatica e Riferimento Temperatura Normale ($T_{\text{normale}}$)**:
   * La curva climatica Viessmann è ancorata alla Temperatura Ambiente Desiderata (Normale/Ridotta):
     $LWT = T_{\text{normale}} + \text{Shift} + \text{Slope} \cdot 1.83 \cdot (T_{\text{normale}} - OAT)^{0.8}$
   * All'aumentare o diminuire della Temperatura Normale, l'intera retta di regolazione trasla in parallelo lungo l'asse della mandata.
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

### D. Architettura Cloud Logging GitHub Actions (24/7 Headless):
1. **Cron e Limiti API**:
   * Repository GitHub collegato: `giacomogussetti-lgtm/vitocal-remote` (collaudato con successo, run #3 `Success` in 21s).
   * Il workflow `.github/workflows/telemetry_logger.yml` gira su cron ogni 5 minuti (`*/5 * * * *`).
   * Esegue `scripts/cloud_logger.py`, che interroga Viessmann e BTicino (1 sola chiamata ciascuno) e fa append a `data/cloud_telemetry.jsonl`.
   * Consumo API: 288 chiamate/giorno su 1.440 consentite da Viessmann (~20%) e su oltre 4.000 consentite da Netatmo. Risoluzione temporale ottimale per catturare ogni ciclo del compressore e della pompa Grundfos.
2. **Sincronizzazione Cloud -> SQLite**:
   * L'applicazione desktop dispone del pulsante `☁️ Sync Cloud (GitHub)` nella barra superiore, che importa i campioni da `cloud_telemetry.jsonl` nel database SQLite locale scartando i duplicati basandosi sull'indice `timestamp_utc`.

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

---

## 3. STRUTTURA DEL REPOSITORY
```text
vitocal remote/
├── .agents/
│   ├── rules/
│   │   └── security-and-privacy.md # Regola permanente di audit pre-commit
│   └── skills/
│       └── vitocal-remote-expert/  # Skill runbook, architettura e troubleshooting
├── .github/
│   └── workflows/
│       └── telemetry_logger.yml    # Workflow GitHub Actions 24/7 (cron ogni 30 min)
├── .env                            # Credenziali e token (NON versionare)
├── .env.example                    # Template credenziali anonimizzato
├── .gitignore                      # Esclusioni git (token, cache, db, dumps)
├── requirements_cloud.txt          # Dipendenze headless minime per GitHub Actions
├── config.py                       # Validazione e caricamento impostazioni
├── app.py                          # ENTRY POINT APPLICAZIONE DESKTOP PYQT6
├── avvia_gestionale.bat            # Launcher doppio-clic per Windows
├── test_bench.py                   # Banchetto prova interattivo CLI
├── api/
│   ├── viessmann.py                # Connettore Viessmann PyViCare (lettura/scrittura verificata)
│   └── bticino.py                  # Connettore Netatmo/BTicino Smarther (read_smarther)
├── storage/
│   └── database.py                 # Manager SQLite (tabella telemetry_samples versionata)
├── models/
│   └── telemetry.py                # Modelli Pydantic per telemetria
├── ui/
│   ├── main_window.py              # Interfaccia grafica PyQt6 (5 Tab, steppers, crosshair, HUD)
│   ├── heating_curve_widget.py     # Visualizzatore dinamico interattivo Curva Climatica LWT vs OAT
│   └── synoptic_widget.py          # Sinottico SCADA vettoriale impianto idraulico e mappatura sonde
├── scripts/
│   ├── feature_dumper.py           # Diagnostica completa e dump 193 features
│   ├── cloud_logger.py             # Logger headless 24/7 per GitHub Actions
│   ├── security_check.py           # Scanner preventivo di privacy e sicurezza pre-commit
│   └── prepare_github_export.py    # Preparatore automatico cartella github_ready/
├── github_ready/                   # Cartella pulita, verificata e anonimizzata per upload Git
├── data/
│   ├── vitocal_telemetry.db        # Database SQLite locale
│   ├── cloud_telemetry.jsonl       # Log telemetrico continuo registrato dal cloud
│   └── dumps/                      # Dump JSON reali delle API
├── AGENTS.md                       # Questa memoria persistente per tutte le chat
├── PROJECT_STATUS.md               # Registro avanzamento e changelog
└── README.md                       # Istruzioni d'uso
```

---

## 4. PROCEDURA DI AVVIO E RIPRESA LAVORO
Se l'utente apre una nuova chat e chiede di continuare:
1. Leggi questo `AGENTS.md` e `PROJECT_STATUS.md`.
2. Verifica che i connettori `api/viessmann.py` e `api/bticino.py` siano integri.
3. Se l'utente vuole avviare l'app grafica: invitalo a cliccare su `avvia_gestionale.bat` o lancia `Start-Process python -ArgumentList "app.py"`.
4. Mantieni sempre la sincronizzazione tra modifiche al codice e documentazione.
