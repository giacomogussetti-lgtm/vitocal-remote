"""
BANCHETTO PROVA INTERATTIVO — Vitocal 111-S & Termostato BTicino
Consente di testare lettura e scrittura in tempo reale sui due sistemi,
verificare i comandi con read-back e avviare il data logging.
"""
import sys
import time
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import Config
from api.viessmann import ViessmannConnector
from api.bticino import BTicinoConnector
from storage.database import DatabaseManager
from models.telemetry import TelemetrySample


def print_header():
    print("\n" + "=" * 70)
    print("      BANCHETTO PROVA — GESTIONALE VITOCAL 111-S & BTICINO")
    print("=" * 70)


def action_read_telemetry(v_conn: ViessmannConnector, b_conn: Optional[BTicinoConnector], db: DatabaseManager):
    print("\n[*] Lettura telemetria da Viessmann e BTicino in corso...")
    v_data = {}
    b_data = {}

    try:
        v_data = v_conn.get_telemetry()
    except Exception as e:
        print(f"[-] Errore lettura Viessmann: {e}")

    if b_conn and b_conn.is_connected:
        try:
            b_data = b_conn.get_status()
        except Exception as e:
            print(f"[-] Errore lettura BTicino: {e}")

    # Build TelemetrySample
    sample = TelemetrySample(
        external_temp_c=v_data.get("outside_temp_c"),
        indoor_temp_bticino_c=b_data.get("indoor_temp_c"),
        indoor_setpoint_bticino_c=b_data.get("setpoint_c"),
        grundfos_pump_active=b_data.get("grundfos_pump_active"),
        pdc_supply_temp_c=v_data.get("supply_temp_c"),
        pdc_return_temp_c=v_data.get("return_temp_c"),
        buffer_temp_c=v_data.get("buffer_temp_c"),
        dhw_storage_temp_c=v_data.get("dhw_storage_temp_c"),
        compressor_active=1 if v_data.get("compressor_active") else 0,
        compressor_hours=v_data.get("compressor_hours"),
        compressor_starts=v_data.get("compressor_starts"),
        heating_curve_slope=v_data.get("heating_curve_slope"),
        heating_curve_shift=v_data.get("heating_curve_shift"),
        active_mode=v_data.get("active_mode"),
        active_program=v_data.get("active_program"),
        heating_elec_kwh_total=v_data.get("power_consumption_heating_today_kwh"),
        dhw_elec_kwh_total=v_data.get("power_consumption_dhw_today_kwh"),
        dhw_thermal_kwh_total=v_data.get("heat_production_dhw_today_kwh"),
        active_preset="test_bench",
    )

    # Save to SQLite
    sample_id = db.insert_sample(sample)

    print("\n" + "-" * 70)
    print("  QUADRO ATTUALE IMPIANTO (Campione ID: %d salvato su DB)" % sample_id)
    print("-" * 70)
    print("  [TEMPERATURE]")
    print(f"    - Esterna (Sonda PdC)      : {sample.external_temp_c} °C")
    print(f"    - Interna (Termostato BT)  : {sample.indoor_temp_bticino_c} °C  (Setpoint: {sample.indoor_setpoint_bticino_c} °C)")
    print(f"    - Mandata PdC              : {sample.pdc_supply_temp_c} °C")
    print(f"    - Ritorno PdC              : {sample.pdc_return_temp_c} °C")
    print(f"    - Accumulo Inerziale Puffer: {sample.buffer_temp_c} °C")
    print(f"    - Bollitore ACS            : {sample.dhw_storage_temp_c} °C")

    print("\n  [STATO COMPONENTI]")
    pump_str = "ACCESA (Circolazione radiante in corso)" if sample.grundfos_pump_active == 1 else "SPENTA (Massetto isolato)"
    comp_str = "ATTIVO" if sample.compressor_active == 1 else "FERMO"
    print(f"    - Pompa Rilancio Grundfos  : {pump_str}")
    print(f"    - Compressore PdC (11 kW)  : {comp_str} (Ore: {sample.compressor_hours}, Avvii: {sample.compressor_starts})")

    print("\n  [REGOLAZIONE PDC]")
    print(f"    - Curva Climatica          : Inclinazione={sample.heating_curve_slope} | Livello={sample.heating_curve_shift}")
    print(f"    - Modalità / Programma     : Modalità='{sample.active_mode}' | Programma='{sample.active_program}'")
    print(f"    - Consumo Elettrico Oggi   : {sample.heating_elec_kwh_total} kWh riscaldamento")
    print("-" * 70)


def action_set_heating_curve(v_conn: ViessmannConnector):
    print("\n" + "-" * 70)
    print("  MODIFICA CURVA CLIMATICA PDC (Inclinazione / Livello)")
    print("-" * 70)
    try:
        curr_slope = v_conn.circuit.getHeatingCurveSlope() if v_conn.circuit else None
        curr_shift = v_conn.circuit.getHeatingCurveShift() if v_conn.circuit else None
        print(f"  Valori attuali: Inclinazione = {curr_slope}, Livello = {curr_shift}")

        slope_str = input("  Nuova Inclinazione (es. 0.6) [Invio per mantenere]: ").strip()
        shift_str = input("  Nuovo Livello/Shift (es. 0 o -6) [Invio per mantenere]: ").strip()

        new_slope = float(slope_str) if slope_str else curr_slope
        new_shift = float(shift_str) if shift_str else curr_shift

        print(f"\n[*] Invio comando: Inclinazione={new_slope}, Livello={new_shift}...")
        ok, msg = v_conn.set_heating_curve(new_slope, new_shift)
        if ok:
            print(f"[+] SUCCESSO! {msg}")
        else:
            print(f"[-] ERRORE: {msg}")
    except Exception as e:
        print(f"[-] Errore: {e}")


def action_set_temperature_setpoints(v_conn: ViessmannConnector):
    print("\n" + "-" * 70)
    print("  MODIFICA TEMPERATURE TARGET PDC (Normale / Ridotta)")
    print("-" * 70)
    try:
        curr_norm = v_conn.circuit.getNormalTemperature() if v_conn.circuit else None
        curr_red = v_conn.circuit.getReducedTemperature() if v_conn.circuit else None
        print(f"  Valori attuali: Normale = {curr_norm} °C, Ridotta = {curr_red} °C")

        norm_str = input("  Nuova Temperatura Normale (°C) [Invio per mantenere]: ").strip()
        if norm_str:
            ok, msg = v_conn.set_normal_temperature(float(norm_str))
            print(f"  [{'+' if ok else '-'}] {msg}")

        red_str = input("  Nuova Temperatura Ridotta (°C) [Invio per mantenere]: ").strip()
        if red_str:
            ok, msg = v_conn.set_reduced_temperature(float(red_str))
            print(f"  [{'+' if ok else '-'}] {msg}")

    except Exception as e:
        print(f"[-] Errore: {e}")


def action_set_bticino_setpoint(b_conn: BTicinoConnector):
    if not b_conn or not b_conn.is_connected:
        print("\n[-] BTicino non collegato o non configurato in .env!")
        return

    print("\n" + "-" * 70)
    print("  MODIFICA SETPOINT TERMOSTATO BTICINO")
    print("-" * 70)
    try:
        curr = b_conn.get_status()
        print(f"  Temperatura interna attuale : {curr.get('indoor_temp_c')} °C")
        print(f"  Setpoint attuale            : {curr.get('setpoint_c')} °C (Modo: {curr.get('mode')})")

        temp_str = input("\n  Nuovo setpoint desiderato (°C, es. 8.0 per antigelo o 20.0 per comfort): ").strip()
        if not temp_str:
            return

        target_temp = float(temp_str)
        ok, msg = b_conn.set_thermostat_setpoint(target_temp, mode="manual", duration_minutes=180)
        if ok:
            print(f"[+] SUCCESSO! {msg}")
        else:
            print(f"[-] ERRORE: {msg}")
    except Exception as e:
        print(f"[-] Errore: {e}")


def action_run_logger_loop(v_conn: ViessmannConnector, b_conn: Optional[BTicinoConnector], db: DatabaseManager):
    print("\n" + "-" * 70)
    print("  AVVIO LOGGER PERIODICO AUTOMATICO")
    print("  Premi Ctrl+C per interrompere in qualsiasi momento.")
    print("-" * 70)
    interval_sec = Config.POLL_INTERVAL_MINUTES * 60
    print(f"[*] Intervallo di campionamento: ogni {Config.POLL_INTERVAL_MINUTES} minuti ({interval_sec} sec)")

    try:
        while True:
            action_read_telemetry(v_conn, b_conn, db)
            print(f"[*] Prossima lettura tra {Config.POLL_INTERVAL_MINUTES} minuti...")
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("\n[!] Logger interrotto dall'utente.")


def main():
    print_header()

    # Initialize Database
    db = DatabaseManager()

    # Initialize Viessmann
    print("[*] Inizializzazione connettore Viessmann...")
    v_conn = ViessmannConnector()
    valid_v, msg_v = Config.validate_viessmann()
    if not valid_v:
        print(f"[!] NOTA: {msg_v}")
        print("    Per effettuare chiamate reali, apri il file .env e inserisci email e password.")
    else:
        try:
            v_conn.connect()
        except Exception as e:
            print(f"[-] Connessione a Viessmann non riuscita: {e}")

    # Initialize BTicino if credentials available
    b_conn = None
    valid_b, _ = Config.validate_netatmo()
    if valid_b:
        print("[*] Inizializzazione connettore BTicino...")
        try:
            b_conn = BTicinoConnector()
            b_conn.authenticate()
            b_conn.discover_home_and_room()
        except Exception as e:
            print(f"[-] Connessione a BTicino non riuscita: {e}")

    # Interactive Loop
    while True:
        print("\nSCEGLI UN'AZIONE:")
        print("  [1] Lettura telemetria completa (Viessmann + BTicino) e salvataggio DB")
        print("  [2] Modifica Curva Climatica PdC (Inclinazione / Livello) con verifica")
        print("  [3] Modifica Setpoint Temperature PdC (Normale / Ridotta)")
        print("  [4] Modifica Setpoint Termostato BTicino")
        print("  [5] Esegui Dump completo features Viessmann (file JSON)")
        print("  [6] Avvia Logger continuo (campionamento periodico ogni X min)")
        print("  [0] Esci")

        choice = input("\nSeleziona opzione [0-6]: ").strip()

        if choice == "1":
            action_read_telemetry(v_conn, b_conn, db)
        elif choice == "2":
            action_set_heating_curve(v_conn)
        elif choice == "3":
            action_set_temperature_setpoints(v_conn)
        elif choice == "4":
            action_set_bticino_setpoint(b_conn)
        elif choice == "5":
            if v_conn.is_connected:
                path = v_conn.dump_all_features()
                print(f"[+] Dump salvato in: {path}")
            else:
                print("[-] Viessmann non connesso. Verifica le credenziali in .env")
        elif choice == "6":
            action_run_logger_loop(v_conn, b_conn, db)
        elif choice == "0":
            print("\nChiusura banchetto prova. A presto!")
            break
        else:
            print("[!] Opzione non valida.")


if __name__ == "__main__":
    main()
