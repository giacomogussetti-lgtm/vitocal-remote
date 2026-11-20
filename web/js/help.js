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
    title: "🎯 Salto LWT ΔT (K)",
    what: "Differenza di temperatura aggiunta all'aria di casa per calcolare la mandata target della pompa di calore all'inizio del ciclo: Target LWT = clamp(T_in + ΔT, 25.0, 28.5 °C).",
    impact: "Più è alto il ΔT, più calda è l'acqua spinta nel pavimento (più kW resi, ma leggermente meno COP). Più è basso, più la PdC lavora in bassa temperatura ad altissimo rendimento.",
    tip: "+18 K con casa a 7.5 °C punta a ~25.5 °C di mandata: ideale per modulare dolce sul radiante senza saturare il puffer."
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
    title: "⚡ Frequenza Dinamica cron-job.org",
    what: "Adatta in automatico ogni quanto tempo il logger cloud interroga PdC e BTicino tramite l'API cron-job.org.",
    impact: "15 min a riposo (IDLE, risparmia API Viessmann), 5 min in attesa conferma (ARMED), 2 min ad alta risoluzione durante HEATING_SYNC e PUFFER_DRAIN per tracciare curve e consumi al dettaglio.",
    tip: "Richiede i GitHub Secrets CRONJOB_API_KEY e CRONJOB_ID configurati sul repository."
  },
  ap_test_cron: {
    title: "🧪 Verifica Secrets & Cambio Timer 2 min",
    what: "Usa GitHub Actions per interrogare cron-job.org: 'Solo Lettura' verifica chiavi e ID senza toccare nulla; 'Test Cambio Timer 2m' scrive davvero 2 min (30 slot/ora), rilegge per conferma e ripristina subito lo schedule iniziale.",
    impact: "Zero modifiche su PdC o termostato di casa; ti dà certezza matematica che l'Autopilota riuscirà a passare a 2 min quando partirà il riscaldamento.",
    tip: "Puoi eseguirlo ogni volta che cambi i Secrets su GitHub o modifichi il job su cron-job.org."
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
    title: "🎨 Bande Verticali & Durate ON",
    what: "Le fasce colorate sullo sfondo evidenziano quando sta lavorando la sola PdC (Ambra), la sola Grundfos (Ciano) o entrambe insieme in sincronia (Verde).",
    impact: "Quando fai zoom sufficiente su un blocco, sopra la banda compare la durata esatta dell'intervallo (es. 'PdC 24m'). Tocca ciascuna pillola in alto per mostrare o nascondere i singoli colori.",
    tip: "L'obiettivo di efficienza è avere bande Verdi lunghe e continue, riducendo al minimo le bande Ambra isolate."
  },
  chart_setpoint_stop: {
    title: "🎯 Marker Stop Setpoint (Mancata Modulazione)",
    what: "Evidenzia con un indicatore rosso/ambra (▼ e linea tratteggiata) il punto in cui il compressore si è spento subito dopo che la Mandata PdC (o Puffer) ha raggiunto/superato la Target LWT calcolata dalla curva.",
    impact: "Indica un probabile stacco per saturazione termica/mancata modulazione minima (ciclo ON/OFF breve), distinto invece da uno spegnimento voluto per cambio programma o defrost.",
    tip: "Confronta il punto con la modulazione % e con la Grundfos: se stacca mentre la Grundfos è OFF, il puffer si è saturato subito."
  },
  chart_axes_zoom: {
    title: "🔍 Gesti Touch, Zoom X & Scale Y Bloccate",
    what: "1 dito legge i valori istantanei (oppure sposta se premi '✋ Sposta'); 2 dita fanno pinch zoom e scorrimento esclusivamente lungo l'asse X del tempo.",
    impact: "Durante lo zoom orizzontale gli assi verticali restano congelati (niente salti fastidiosi). Tocca direttamente i numeri sull'asse sinistro/destro (o le pillole °C / %) per fissare min/max personalizzati.",
    tip: "Usa '⏭️ Ciclo' per centrare con un tap l'ultimo ciclo compressore registrato."
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
