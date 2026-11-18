# Gestionale Unificato Viessmann Vitocal 111-S & Termostato BTicino Smarther
**Abitazione di Bratto (Castione della Presolana, BG)**

Piattaforma software per il controllo centralizzato, il data logging termodinamico e la gestione tramite preset multi-dispositivo dell'impianto di riscaldamento a pompa di calore e pavimento radiante.

---

## 🚀 Avvio Rapido

### Metodo 1: Doppio Clic (Windows)
Fai doppio clic sul file [**`avvia_gestionale.bat`**](./avvia_gestionale.bat) nella cartella di progetto.

### Metodo 2: Da Terminale
```powershell
python app.py
```

### Metodo 3: Banchetto Prova da Riga di Comando (CLI)
Se preferisci una console testuale senza interfaccia grafica:
```powershell
python test_bench.py
```

---

## 🛠️ Funzionalità dell'Applicazione Desktop (5 Schede Specializzate)

1. **📊 Dashboard Live**:
   * Quadro completo in tempo reale delle temperature della Vitocal 111-S (Esterna, Mandata, Ritorno, Puffer 200L, ACS).
   * Temperatura ambiente reale (**Corridoio**), setpoint e umidità dal termostato BTicino Smarther.
   * Rilevamento dello stato del circolatore Grundfos (rilancio pavimento radiante attivo vs puffer isolato).
   * Sensori termodinamici: pressione gas caldo (10 bar), modulazione compressore (0-100%), ore/avvii e COP macchina.

2. **🗺️ Sinottico Impianto & Sonde (SCADA)**:
   * Diagramma vettoriale idraulico ad alta risoluzione con disposizione fisica reale delle sonde:
   * Circuito primario (mandata calda rossa e ritorno freddo blu tra PdC Vitocal e serbatoio inerziale).
   * Puffer 200 Litri disaccoppiatore con sonda top di accumulo.
   * Pompa di rilancio secondaria Grundfos con animazione/indicatore di stato dinamico (verde se attiva, grigio a riposo).
   * Abitazione Bratto con serpentina massetto radiante (200 m²) e centralina termostato BTicino Smarther a parete.

3. **🎛️ Banchetto Comandi & Preset + Curva Climatica Grafica**:
   * **Visualizzatore Interattivo Curva Climatica LWT vs OAT**:
     * Visualizza la temperatura di mandata calcolata in funzione della temperatura esterna (-20 °C a +20 °C).
     * Marker dorato in tempo reale che indica esattamente il punto di lavoro attuale (es. a 5.9 °C ➔ 29.1 °C mandata).
     * Fascia verde di sicurezza pavimento radiante (20-38 °C) e soglia rossa a 40 °C (limite shock termico).
     * Sincronizzazione dinamica immediata con gli spinbox di Inclinazione (Slope) e Livello (Shift).
   * **Comandi Diretti con Verifica Read-Back**:
     * Modifica setpoint temperature Normale e Ridotta PdC con invalidazione forzata della cache PyViCare.
     * Regolazione setpoint termostato BTicino tramite Home + Control API (`POST /api/setstate`).
     * Pulsanti one-click: `📅 Ripristina Programma (Home)` e `❄️ Antigelo Fisso (HG)`.
   * **Preset Multi-Dispositivo**:
     * ⚡ *Assenza Impulso Diurno (Inverno)*: traslazione notturna Shift -6 e carica diurna del massetto.
     * ⚡ *Solo Antigelo / Standby*: PdC in standby, BTicino a 7.5 °C.
     * ⚡ *Pre-Riscaldamento Arrivo*: avvio 12-24h prima per vincere l'inerzia del massetto.
     * ⚡ *Weekend Comfort*: regime continuo 20.5 °C, curva nominale (0.6 / 0), ACS attiva.

4. **🔍 JSON Feature Inspector**:
   * Ispezione di tutti i **193 parametri hardware reali** esposti dal cloud Viessmann.
   * Ricerca istantanea con filtro testuale e visualizzatore JSON interattivo con formattazione e colori.

5. **📈 Grafici Multi-Asse, Cicli Compressore & Storico SQLite**:
   * **Asse X Temporale Assoluto**: data e ora locale formattata dinamicamente (`GG/MM HH:MM` o `HH:MM:SS`).
   * **Doppio Asse Y Sincronizzato**: Asse Sinistro per le Temperature (°C), Asse Destro per Modulazione %, Pressione bar e COP.
   * **Doppio Clic sugli Assi per Scala Personalizzata (Auto vs Fixed)**:
     * Facendo doppio clic direttamente sui numeri degli assi (o usando i pulsanti `📐 Scala Sx / Dx`) è possibile digitare Inizio e Fondo scala custom (es. 0 - 45 °C) oppure attivare l'Auto-Range.
     * Pulsante `Auto-Adatta Assi` per il ripristino istantaneo di entrambi gli assi.
   * **Evidenziazione Eventi ON/OFF**: fasce temporali colorate in background (Ambra quando il compressore è modulante, Verde quando la pompa Grundfos è attiva).
   * **Ricerca Canali Fuzzy (`RapidFuzz`)**: selezione rapida dei canali tollerante a errori di battitura.
   * **Auto-Logger Schedulato**: campionamento temporizzato regolabile (5-60 min) con timer e conto alla rovescia live.

---

## 📁 Struttura del Progetto

* `app.py`: Entry point dell'interfaccia grafica PyQt6.
* `avvia_gestionale.bat`: Script di lancio per Windows.
* `test_bench.py`: Console interattiva di collaudo.
* `api/`: Connettori OAuth2 per Viessmann Cloud (`PyViCare`) e BTicino (`Netatmo Connect API`).
* `ui/`: Interfaccia grafica PyQt6 disaccoppiata con thread asincroni per non bloccare la UI.
* `storage/`: Database SQLite locale (`data/vitocal_telemetry.db`).
* `scripts/feature_dumper.py`: Diagnostica completa e dump dei parametri hardware.
* `AGENTS.md`: Memoria persistente di progetto per gli agenti AI.
* `PROJECT_STATUS.md`: Registro avanzamento e changelog dettagliato.
