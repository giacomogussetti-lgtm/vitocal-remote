/**
 * Tap-to-explain Contextual Help System (`data-help-key`) for Vitocal Remote PWA.
 * Explains every Autopilot parameter, hardware command, and diagnostic chart feature
 * in clear Italian via a non-intrusive bottom/center modal sheet.
 */

const HELP_CATALOG = {
  ap_away_hero: {
    title: "🛡️ Custodia Automatica Montagna (Full-Auto)",
    what: "Attiva la gestione completamente autonoma quando la casa è vuota: mette la PdC in Standby (fascia sicurezza diurna), il bollitore ACS a 10 °C e il BTicino in Antigelo (7.0 °C).",
    impact: "Finché casa resta sopra T_min il compressore sta spento (consumo quasi zero). Quando serve calore aspetta le ore più calde, calcola il Target LWT ideale, accende PdC + Grundfos insieme e infine svuota il puffer.",
    tip: "Usa un solo tocco per attivare prima di partire. Quando torni, premi 'Disattiva (Manuale)' per riprendere i comandi liberi."
  },
  ap_t_min: {
    title: "🌡️ Soglia Avvio T_min (°C)",
    what: "Temperatura aria interna (letta dal BTicino in Corridoio) sotto la quale l'Autopilota inizia a prenotare un ciclo di riscaldamento.",
    impact: "Deve restare ≤ T_min per almeno 20 minuti consecutivi (anti-rimbalzo) prima di passare in stato ARMED. Abbassandola si risparmia energia; alzandola si tiene la casa più tiepida.",
    tip: "Per casa vuota invernale, 7.0–7.5 °C offre ottimo margine sopra al gelo con pochissime accensioni."
  },
  ap_t_max: {
    title: "🏁 Soglia Stacco T_max (°C)",
    what: "Temperatura aria interna alla quale il ciclo attivo spegne il compressore (PdC in Standby) ed entra nella fase di scarico puffer.",
    impact: "La banda (T_max − T_min, es. 7.5 → 8.8 °C) definisce l'isteresi lunga che evita brevi ON/OFF e permette al compressore inverter di fare una tirata lunga continua.",
    tip: "Ricorda che grazie all'inerzia del massetto la casa continua a salire leggermente anche dopo lo stacco."
  },
  ap_t_emergency: {
    title: "🚨 Emergenza Notte (°C)",
    what: "Soglia minima assoluta di sicurezza antigelo, valida 24 ore su 24.",
    impact: "Se T casa scende ≤ Emergenza (o se scende rapidamente ≤ -0.18 °C/h con proiezione a 6h sotto questa soglia), l'Autopilota ignora la finestra COP diurna e parte subito anche di notte.",
    tip: "Tienila almeno 1.5–2 °C sopra la soglia critica dei tubi (6.5–6.8 °C è un paracadute molto sicuro)."
  },
  ap_delta_lwt: {
    title: "🎯 Salto Acqua ΔT (K) su Puffer",
    what: "Differenza aggiunta alla temperatura casa per calcolare l'obiettivo acqua sulla Sonda Puffer 200L (su cui regola la WO1C): Target Acqua = clamp(T_in + ΔT, Min, Max).",
    impact: "Sui log reali (k_radiante ≈ 0.34 kW/K), +15.5 K porta il puffer a ~22.5–23.5 °C (mandata ~24 °C): il pavimento assorbe ~4.8 kWₜ continui facendo modulare la 11 kW dolce al 35–55% con pochissimi defrost.",
    tip: "15.0–16.0 K è lo sweet spot: più basso rischierebbe di avvicinare la potenza minima (~3.5 kWₜ); oltre 18 K alza la modulazione e moltiplica la brina a OAT 2–5 °C."
  },
  ap_lwt_bounds: {
    title: "🌡️ Limiti Min / Max Target Acqua (°C)",
    what: "Pavimento e soffitto di sicurezza per il Target Acqua (Puffer) calcolato dall'Autopilota.",
    impact: "Min = 22.0 °C garantisce sempre un salto sufficiente sul radiante per evitare cicli ON/OFF brevi; Max = 26.5 °C evita sovratemperature inutili a basso COP.",
    tip: "Mantieni 22.0–26.5 °C in custodia invernale; alza solo se vuoi riscaldare casa rapidamente prima di un arrivo."
  },
  ap_soft_start: {
    title: "🚀 Rampa Soft-Start Anti-Overshoot",
    what: "All'avvio a freddo (puffer a ~11 °C), parte 1–2 °C sotto il setpoint finale e sale di +1 °C ogni N minuti (o quando il puffer raggiunge il gradino).",
    impact: "Evita che la WO1C veda un errore iniziale di +14 K saturando l'integrale PI all'88% (causa dell'overshoot a 28.8 °C del 21/11 e della brina precoce al minuto 7 del 24/11).",
    tip: "Con passo 25 min, l'avvio resta dolce al 45–60% e raggiunge il regime senza picchi."
  },
  ap_defrost_guard: {
    title: "❄️ Defrost Guard Anti-Brina",
    what: "Monitora gli episodi di sbrinamento del ciclo attivo e la depressione evaporatore (OAT − T_aspirazione) quando l'aria esterna è nella fascia umida ≤ 5.5 °C.",
    impact: "Se rileva troppi defrost (≥ soglia) o evaporatore ghiacciato ad alta modulazione, riduce il setpoint PdC di −1 °C (solo quando Puffer ≤ nuovo target + 1 K, così da non provocare stacchi isteretici WO1C!).",
    tip: "Spezza il circolo vizioso 88% ↔ Defrost ogni 48 minuti, risparmiando fino al 20–25% di elettricità nelle giornate nebbiose."
  },
  ap_anti_seize: {
    title: "💧 Anti-Grippaggio Smart Grundfos (Giorni)",
    what: "Poiché in Full-Auto la modalità 'hg' del BTicino sovrascrive la programmazione giornaliera dell'app Home + Control, questo timer avvia la sola Grundfos per 15 min alle 12:00 se resta ferma per più di N giorni consecutivi.",
    impact: "Protegge il rotore bagnato della pompa nelle mezze stagioni miti senza sprecare cicli ogni singola mattina in inverno (quando già gira per ore nei cicli di riscaldamento).",
    tip: "4 giorni (0 = disattivo) è il compromesso ideale tra protezione meccanica e zero sprechi."
  },
  ap_bphe_floors: {
    title: "🛡️ Pavimenti Sicurezza BPHE, Soft-Start & Anti-ON/OFF",
    what: "Soglie minime fisiche configurabili (mai hardcoded): Pavimento BPHE Defrost (22.0 °C) protegge lo scambiatore durante l'inversione di sbrinamento; Pavimento Soft-Start (21.8 °C) limita il gradino d'avvio a freddo; ΔT Min Anti-ON/OFF (+13.5 K) impedisce al Target di scendere sotto la capacità minima di assorbimento del pavimento.",
    impact: "Sui dati reali del 24/11 ogni sbrinamento fa scendere LWT di 8–10 K: mantenere il puffer ≥ 22.0 °C garantisce LWT ≥ 13–14 °C in defrost (zero errori antigelo BPHE, zero resistenza elettrica S1/S2) e mantiene il compressore sopra il suo pavimento continuo (38%).",
    tip: "Lascia 22.0 °C / 21.8 °C / 13.5 K come base sicura; il Modello Fisico li affinerà man mano che raccogliamo cicli più freddi."
  },
  ap_inverter_floor: {
    title: "⚙️ Floor Inverter Rilevato (%)",
    what: "Percentuale minima reale di modulazione continua osservata sul compressore Vitocal 111-S (38% su 556 campioni attivi).",
    impact: "Serve al Modello Matematico e alle diagnostiche per non chiedere mai al radiante meno calore di quanto la macchina riesca a erogare al minimo (evitando stacchi secchi per isteresi).",
    tip: "Se in giornate miti osservi la macchina modulare stabilmente più in basso, il modello aggiornerà automaticamente questo valore."
  },
  ap_adaptive_model: {
    title: "🧠 Modello Matematico Auto-Convergente",
    what: "Identifica dai log reali 4 parametri fisici dell'impianto con convergenza Bayesiana (k_rad del pavimento, floor inverter, caduta termica BPHE in defrost e dispersione UA dell'edificio) eliminando i setpoint fissi hardcoded.",
    impact: "In 'Osservazione' si ricalibra a fine ciclo e mostra la stima di target e autonomia; abilitando 'Usa Target dal Modello', guida direttamente il Target Acqua (sempre entro i limiti Min/Max scelti da te) adattandosi automaticamente all'arrivo del gelo invernale.",
    tip: "Consigliato in Osservazione sui primi 3–4 cicli per verificare la convergenza, poi attivabile in pieno controllo."
  },
  ap_max_cycle: {
    title: "⏱️ Durata Max Ciclo (min)",
    what: "Durata massima di funzionamento continuo del compressore in un singolo ciclo di riscaldamento.",
    impact: "Anche se T_max non è stata ancora raggiunta, allo scadere di questo limite la PdC si ferma e avvia lo scarico puffer, evitando funzionamenti infiniti o fuori fascia calda.",
    tip: "Con finestra 11:00–16:00, impostare 300 min (5 ore) sfrutta l'intera fascia solare diurna."
  },
  ap_drain_min: {
    title: "💧 Scarico Puffer (min)",
    what: "Minuti in cui la pompa secondaria Grundfos resta accesa da sola dopo aver spento il compressore Viessmann.",
    impact: "Recupera tutta l'energia rimasta calda nei 200 litri del puffer cedendola al pavimento radiante anziché lasciarla raffreddare inutilmente nel box (termina prima se Puffer ≤ 13.8 °C).",
    tip: "20–30 minuti bastano in genere per svuotare completamente il puffer da 200 L."
  },
  ap_cop_window: {
    title: "☀️ Finestra COP (Inizio / Fine)",
    what: "Fascia oraria diurna (ora italiana) in cui è consentito l'avvio ordinario dei cicli dell'Autopilota e della fascia hardware sulla centralina Viessmann.",
    impact: "Concentra i cicli nelle ore con aria esterna più mite e minore umidità: COP molto più alto e meno sbrinamenti (defrost) sull'evaporatore esterno.",
    tip: "11:00–16:00 centra il picco termico pomeridiano in montagna."
  },
  ap_dynamic_cron: {
    title: "⚡ Frequenza Dinamica cron-job.org (Editabile)",
    what: "Adatta automaticamente ogni quanti minuti il logger interroga PdC e BTicino tramite cron-job.org in base allo stato dell'Autopilota (IDLE, Armato, Ciclo Attivo).",
    impact: "Puoi personalizzare ogni intervallo fino a un minimo di 1 minuto. Intervalli più fitti migliorano il dettaglio dei grafici ma consumano più chiamate Viessmann (limite 1.450/24h).",
    tip: "Valori equilibrati: 15 min in IDLE (192 chiamate/24h), 5 min in Armato, 1–2 min durante i cicli attivi per catturare ogni variazione."
  },
  ap_soft_curve: {
    title: "🎛️ Self-Tuning Soft Curva (Anti-Overshoot)",
    what: "Quando abilitato, invece di lasciare che il termostato tagli di colpo la pompa Grundfos quando casa sale troppo velocemente, riduce dolcemente di −1 K il riferimento PdC (fino a max −2 K, ogni 60 min).",
    impact: "Mantiene il circolatore secondario sempre aperto e costringe l'inverter Vitocal a modulare verso il basso, allungando il ciclo ed evitando stacchi secchi sul puffer.",
    tip: "Ideale in presenza o in giornate miti quando la casa tende a scaldarsi prima della fine finestra COP."
  },
  ap_weather_planner: {
    title: "🌦️ Pianificatore Meteo & Self-Tuning OAT",
    what: "Interroga Open-Meteo (modello alpino ICON-D2 / Best Match, senza salvare coordinate nel repository) e combina Temperatura esterna prevista, Umidità Relativa (RH%), precipitazioni e soleggiamento per stimare il COP netto orario e il rischio brina.",
    impact: "Calcola la finestra migliore della giornata e proietta T_casa fino a domani con un margine di sicurezza conservativo (UA × 1.15). Si auto-calibra confrontando la OAT prevista con la sonda reale Viessmann.",
    tip: "Espandi il cassetto 'Previsioni Meteo & Ragionamento' per vedere ogni numero, ogni assunzione e perché l'Autopilota ha deciso di partire, aspettare o estendere."
  },
  ap_weather_search_band: {
    title: "🕒 Fascia Ricerca Finestra Dinamica",
    what: "Intervallo orario entro cui l'algoritmo cerca il blocco continuo migliore di N ore (es. 5h tra le 09:00 e le 18:00), spostando la finestra statica 11:00–16:00 solo se il guadagno supera la soglia di stabilità (default +0.08 COP).",
    impact: "In giornate fredde al mattino e miti nel pomeriggio può centrare ad esempio 12:00–17:00; prima di una perturbazione nevosa pomeridiana può anticipare a 09:00–14:00. La fascia hardware WO1C viene allineata in automatico.",
    tip: "Se i Secrets meteo non sono configurati o Open-Meteo è offline, torna in sicurezza alla finestra statica senza errori."
  },
  ap_anti_short_cycle: {
    title: "🛡️ Protezione Anti-Micro-Ciclo (Fine Finestra)",
    what: "Impedisce alla PdC di avviarsi quando restano meno di N minuti (default 120 min) prima della chiusura della finestra COP.",
    impact: "Simula T_casa fino alla finestra di domani: se la notte resta sicura (≥ Emergenza + Margine), rinvia evitando uno short-cycle inutile da 20 minuti; se invece la notte rischierebbe il gelo, parte subito estendendo la chiusura per garantire almeno il ciclo minimo.",
    tip: "120 minuti garantiscono sempre il superamento della rampa fredda e un accumulo reale nel massetto radiante."
  },
  ap_predictive_prearm: {
    title: "⚡ Pre-Armamento Predittivo Notturno",
    what: "Se siamo dentro la finestra calda di oggi e T_casa è ancora leggermente sopra T_min (es. 7.8 °C vs 7.5 °C), verifica se stanotte scenderebbe sotto il pavimento di sicurezza prima della finestra di domani.",
    impact: "Evita il caso limite del trigger alle 16:30 seguito da un'emergenza notturna alle 04:00 a −5 °C: anticipa la carica alle ore miti di oggi, spendendo meno elettricità.",
    tip: "Può anche anticipare quando oggi c'è sole/COP alto e domani peggiora molto, se T_casa è già vicina a T_min."
  },
  ap_weather_defer: {
    title: "🌤️ Arbitraggio Meteo (Rinvio a Domani)",
    what: "Se l'impianto è ARMED dentro una giornata molto sfavorevole da brina/gelo ma domani è previsto un netto miglioramento (ΔCOP ≥ soglia, default +0.25), valuta se rimandare il ciclo a domani.",
    impact: "Rinvia SOLO se la simulazione conservativa (UA × 1.15) garantisce che la notte resti sopra il pavimento di sicurezza e MAI per due giorni di fila (anti-starvation). La soglia Emergenza 6.8 °C resta sempre prioritaria.",
    tip: "Puoi disattivare il solo rinvio mantenendo comunque attiva la finestra dinamica e l'anti-micro-ciclo."
  },
  ap_selftuning_audit: {
    title: "📈 Registro Self-Tuning & Convergenza Bayesiana",
    what: "Mostra in totale trasparenza come il modello fisico (k_rad, floor inverter, caduta defrost, dispersione UA) e il correttore meteo (Bias OAT) si aggiornano man mano che arrivano cicli reali.",
    impact: "Ogni parametro NON oscilla sugli ultimi campioni: calcola la mediana robusta su tutto lo storico con Bayesian shrinkage w = n / (n + k). All'aumentare dei cicli osservati (n), il valore converge asintoticamente verso il comportamento reale dell'impianto.",
    tip: "La tabella Open-Meteo vs Sonda OAT ti permette di verificare ora per ora quanto 'sgarra' la previsione rispetto al sensore fisico esterno della tua Vitocal."
  },
  ap_min_end_temp: {
    title: "🌡️ T Minima Fine Ciclo (°C)",
    what: "Temperatura minima che casa deve aver raggiunto prima di spegnere il ciclo alla chiusura della finestra COP o al raggiungimento dei 300 minuti.",
    impact: "Se si parte da molto freddo (es. emergenza a 6.8 °C), in 300 minuti la casa arriva solo a ~7.9–8.0 °C riducendo l'autonomia prima del riavvio. Se T_casa è sotto questa soglia (default 8.2 °C), il ciclo viene esteso una volta fino a +60 min (max 18:30) per completare la carica del massetto.",
    tip: "8.0–8.3 °C assicura abbastanza isteresi fino al giorno successivo senza tirare troppo tardi la sera."
  },
  ap_window_lock: {
    title: "🔒 Blocco Finestra Pre-Avvio (min)",
    what: "Impedisce alla finestra dinamica di continuare a slittare in avanti man mano che arrivano nuovi aggiornamenti meteo orari.",
    impact: "Entro N minuti prima dell'orario previsto di avvio (default 90 min), la finestra di oggi viene congelata. Inoltre, anche prima di quel limite, l'algoritmo non posticipa mai oltre il punto in cui T_casa toccherebbe l'Emergenza.",
    tip: "90 minuti è l'equilibrio ideale tra adattamento meteo mattutino e certezza dell'accensione."
  },
  cmd_profiles_smart: {
    title: "🎯 Scenari & Profili Coordinati (PdC + Consenso Pompa)",
    what: "Combina in un solo tocco i parametri Vitocal (modo, curva, temperature, fascia oraria) e il consenso relè del BTicino Smarther.",
    impact: "Poiché nel tuo impianto il BTicino funge da interruttore ON/OFF della Grundfos, coordinare entrambi evita che la PdC scaldi i soli 200L del puffer a pompa ferma.",
    tip: "Puoi usare i 4 profili pronti oppure salvare le impostazioni attuali con '➕ Salva Attuale'."
  },
  api_quota_monitor: {
    title: "📊 Monitor Quote & Token API (Letture + Scritture)",
    what: "Somma in tempo reale le letture telemetriche periodiche e le scritture di comando verso Viessmann ViCare (1.450/24h, burst 120/10m), BTicino/Netatmo (500/1h), cron-job.org e GitHub.",
    impact: "Ti permette di vedere subito quanto margine resta prima dei rate-limit, soprattutto se abbassi la frequenza di polling dinamico a 1–2 minuti.",
    tip: "In verde (<50%) sei in piena sicurezza; se superi l'80% in giallo/rosso, aumenta l'intervallo IDLE."
  },
  cmd_sync_pulse: {
    title: "⚡ Ciclo Sincronizzato (PdC + Grundfos)",
    what: "Accende contemporaneamente la Vitocal (Riscaldamento + ACS) e forza la pompa secondaria Grundfos impostando il BTicino in manuale a tempo.",
    impact: "Evita che la Vitocal scaldi i soli 200 litri del puffer a circolatore spento, prevenendo accensioni e spegnimenti ravvicinati (ON/OFF).",
    tip: "Usa questa funzione per fare un test rapido o dare una spinta controllata a scadenza automatica."
  },
  cmd_pdc_mode: {
    title: "🔥 Modalità Operativa Vitocal",
    what: "Imposta lo stato principale della centralina Viessmann WO1C: Standby (solo antigelo hardware), Solo ACS (solo acqua calda sanitaria), Riscaldamento + ACS.",
    impact: "In Standby la pompa di calore non riscalda il puffer salvo protezione gelo automatica della macchina; in Riscaldamento + ACS segue la fascia oraria e la curva climatica.",
    tip: "A casa vuota fuori dall'Autopilota, lascia Standby per azzerare gli ON/OFF accidentali."
  },
  cmd_slope: {
    title: "📈 Inclinazione Curva (Slope)",
    what: "Determina di quanto sale la temperatura di mandata dell'acqua (LWT) ogni grado in meno di aria esterna.",
    impact: "Con radiante a pavimento in genere 0.4–0.7 è ideale. Una Slope troppo alta manda acqua troppo calda presto, causando stacchi anticipati per raggiungimento setpoint (ON/OFF).",
    tip: "La preview viola sotto ti mostra subito la LWT target alla temperatura esterna attuale."
  },
  cmd_shift: {
    title: "↕️ Livello Curva (Shift K)",
    what: "Alza o abbassa in parallelo tutta la retta della curva climatica di N gradi Kelvin rispetto al riferimento standard.",
    impact: "Ogni +1 K di Shift sposta l'intera mandata target su di +1 °C a qualsiasi temperatura esterna.",
    tip: "Usalo per piccoli aggiustamenti stagionali senza cambiare la pendenza (Slope)."
  },
  cmd_pdc_temps: {
    title: "🌡️ Setpoint PdC & Bollitore ACS",
    what: "T Normale e T Ridotta sono i riferimenti ambientali interni su cui la WO1C ancora la curva climatica (LWT); T ACS è il target del bollitore sanitario.",
    impact: "Nel programma attivo (Ridotta/Normale), alzare questo numero sposta verso l'alto la mandata obiettivo calcolata dalla macchina (e viceversa). T ACS = 10 °C tiene spento il bollitore a casa vuota.",
    tip: "L'Autopilota calcola automaticamente il setpoint intero migliore per centrare la Target LWT desiderata."
  },
  cmd_pdc_schedule: {
    title: "🗓️ Fascia Oraria Hardware PdC",
    what: "Scrive direttamente nella centralina Viessmann la fascia oraria di funzionamento in modalità Ridotta o Normale (fuori fascia resta Standby).",
    impact: "Funge da fail-safe hardware autonomo: anche senza connessione internet, la PdC non si accende fuori dalla finestra impostata (es. 11:00–16:00).",
    tip: "'Svuota (Standby)' cancella gli slot del gruppo giorni selezionato lasciando tutto fermo."
  },
  cmd_bticino_manual: {
    title: "🏠 Setpoint Manuale BTicino (Grundfos)",
    what: "Imposta una temperatura manuale temporanea sul BTicino Smarther in Corridoio. Quando il setpoint supera la T casa, il relè chiude il contatto e avvia il circolatore Grundfos.",
    impact: "Ha sempre una durata massima a scadenza automatica (1–12 ore) come sicurezza: allo scadere torna al programma o antigelo evitando pompe dimenticate accese.",
    tip: "Per forzare sicuramente la Grundfos accesa anche a casa fredda/tiepida, usa almeno T casa + 2 °C (es. 15–18 °C)."
  },
  cmd_bticino_modes: {
    title: "🎛️ Modalità Rapide BTicino",
    what: "Programma segue gli orari settimanali Smarther; Antigelo (HG) fissa il termostato a 7.0 °C spegnendo la Grundfos finché casa è sopra 7 °C; Assente usa la modalità Away Netatmo.",
    impact: "Impostare Antigelo (HG) garantisce che la pompa di rilancio non parta mai fuori controllo quando la casa è chiusa.",
    tip: "Premi Antigelo per forzare la chiusura sicura del circolatore secondario."
  },
  cmd_bticino_schedule: {
    title: "📋 Cambio Programmazione Oraria BTicino",
    what: "Cambia la programmazione settimanale attiva salvata nel tuo account Legrand Home + Control / BTicino Smarther.",
    impact: "Passa istantaneamente tra i profili orari preconfigurati (es. Antigelo prolungato, Riscaldamento attivo, ECO).",
    tip: "Usa 🔄 Rileggi (in Wi-Fi locale) se hai creato nuove programmazioni dall'app ufficiale Home + Control."
  },
  chart_bands: {
    title: "🎨 Bande Verticali, Durate ON & Resa Termica",
    what: "Le fasce colorate sullo sfondo evidenziano quando sta lavorando la sola PdC (Ambra), la sola Grundfos (Ciano) o entrambe insieme in sincronia (Verde).",
    impact: "Espandendo o zoomando il grafico, la pillola mostra la durata e la resa termica stimata (kWhₜ e kWₜ medi, calcolati da modulazione e COP). Tocca le pillole in alto per filtrare i colori.",
    tip: "L'obiettivo di efficienza è avere bande Verdi lunghe e continue, riducendo al minimo le bande Ambra isolate."
  },
  chart_setpoint_stop: {
    title: "🎯 Marker Stop Setpoint (Mancata Modulazione)",
    what: "Evidenzia con un indicatore rosso/ambra (▼ e linea tratteggiata) il punto in cui il compressore si è spento subito dopo che la Mandata PdC (o Puffer) ha raggiunto/superato la Target LWT calcolata dalla curva.",
    impact: "Indica un probabile stacco per saturazione termica/mancata modulazione minima (ciclo ON/OFF breve), distinto invece da uno spegnimento voluto per cambio programma o defrost.",
    tip: "Confronta il punto con la modulazione % e con la Grundfos: se stacca mentre la Grundfos è OFF, il puffer si è saturato subito."
  },
  chart_axes_zoom: {
    title: "🔍 Gesti Touch Smart (Stile TradingView)",
    what: "Su smartphone: trascina con 1 dito per spostare nel tempo, tocca o tieni premuto (180 ms) per agganciare il mirino magnetico con barra HUD fissa (senza coprire le curve!), fai doppio-tap per Zoom 2× / Reset e usa 2 dita per pinch zoom X.",
    impact: "Gli assi Y restano bloccati durante zoom/pan in X e l'asse destro si nasconde automaticamente se non usato (più spazio alle curve). Tocca direttamente i numeri sugli assi o le pillole °C / % per fissare la scala.",
    tip: "Usa ◀ Ciclo ▶ in alto per saltare rapidamente tra tutti i cicli del compressore (es. 24/11 ↔ 21/11)!"
  },
  analytics_score: {
    title: "🎯 Qualità Modulazione & Sicurezza Gelo",
    what: "Analizza sulla finestra temporale selezionata il numero di avviamenti, la durata media dei cicli, il carico % dell'inverter e il margine sopra i 5.0 °C.",
    impact: "Punteggi alti indicano cicli lunghi con compressore al 20–50% di modulazione; punteggi bassi segnalano troppi cicli brevi ON/OFF (< 30 min).",
    tip: "Controlla i consumi elettrici stimati e lo storico reale dopo aver attivato l'Autopilota per verificare il risparmio."
  },
  sonde_rod: {
    title: "🔧 Diagnostica Defrost, Antigelo & Resistenza",
    what: "Mostra le sonde frigorifere Viessmann (gas caldo, liquido, aspirazione), la fase compressore (incluso sbrinamento 'defrost'), lo stato antigelo WO1C e le ore cumulative dei 2 stadi di resistenza elettrica.",
    impact: "Un aumento delle ore della resistenza (S1/S2) segnala uso del backup elettrico ad alto consumo (sotto i 0 °C o durante emergenze/sbrinamenti).",
    tip: "Se noti cicli con S1/S2 in crescita, controlla i dettagli nella scheda Grafici ed esegui un audit dei log."
  },
  sync_pat: {
    title: "🔑 GitHub Personal Access Token (PAT)",
    what: "Token personale memorizzato solo nel browser/telefono (mai nel codice pubblico) che autorizza la PWA a lanciare i workflow GitHub Actions via 4G/5G.",
    impact: "Permette di inviare comandi a PdC, BTicino e Autopilota ovunque nel mondo senza esporre mai le password Viessmann o Netatmo sullo smartphone.",
    tip: "In sola lettura (grafici e sinottico su repo pubblico) l'app funziona anche senza PAT."
  }
};

function openHelpModal(helpKey) {
  const entry = HELP_CATALOG[helpKey];
  const modal = document.getElementById("helpInfoModal");
  if (!entry || !modal) return;

  const titleEl = document.getElementById("helpModalTitle");
  const whatEl = document.getElementById("helpModalWhat");
  const impactEl = document.getElementById("helpModalImpact");
  const tipEl = document.getElementById("helpModalTip");

  if (titleEl) titleEl.textContent = entry.title;
  if (whatEl) whatEl.textContent = entry.what;
  if (impactEl) impactEl.textContent = entry.impact;
  if (tipEl) tipEl.textContent = entry.tip;

  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
}

function closeHelpModal() {
  const modal = document.getElementById("helpInfoModal");
  if (!modal) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}

function initHelpSystem() {
  const modal = document.getElementById("helpInfoModal");
  if (modal && modal.dataset.bound !== "1") {
    modal.dataset.bound = "1";
    const closeBtn = document.getElementById("btnCloseHelpModal");
    const okBtn = document.getElementById("btnOkHelpModal");
    if (closeBtn) closeBtn.addEventListener("click", closeHelpModal);
    if (okBtn) okBtn.addEventListener("click", closeHelpModal);
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeHelpModal();
    });
  }

  if (document.body && document.body.dataset.helpBound !== "1") {
    document.body.dataset.helpBound = "1";
    document.addEventListener("click", (e) => {
      const btn = e.target && e.target.closest ? e.target.closest("[data-help-key]") : null;
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      const key = btn.getAttribute("data-help-key");
      if (key) openHelpModal(key);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeHelpModal();
    });
  }
}

window.HELP_CATALOG = HELP_CATALOG;
window.openHelpModal = openHelpModal;
window.closeHelpModal = closeHelpModal;
window.initHelpSystem = initHelpSystem;
