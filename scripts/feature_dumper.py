"""
Diagnostic Script: feature_dumper.py
Connects to Viessmann ViCare API and Netatmo/BTicino API,
dumps the full raw JSON feature map from the hardware,
and prints a complete diagnostic summary of all readable parameters.
"""
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from api.viessmann import ViessmannConnector
from api.bticino import BTicinoConnector


def dump_viessmann():
    print("=" * 70)
    print("  DIAGNOSTICA & FEATURE DUMPER — VIESSMANN VITOCAL 111-S")
    print("=" * 70)

    valid, msg = Config.validate_viessmann()
    if not valid:
        print(f"\n[!] Configurazione Viessmann incompleta: {msg}")
        print("    Apri il file '.env' e inserisci la tua email e password ViCare.")
        return

    connector = ViessmannConnector()
    try:
        print("\n[*] Tentativo di autenticazione OAuth2 su Viessmann Cloud...")
        connector.connect()
        print("[+] Connessione riuscita!")
    except Exception as e:
        print(f"\n[-] Errore durante la connessione Viessmann: {e}")
        return

    # 1. Raw Feature Dump to file
    dump_file = connector.dump_all_features()
    print(f"[+] Dump completo di tutti i features salvato in: {dump_file}")

    # 2. Extract and display telemetry summary
    print("\n" + "-" * 70)
    print("  LETTURA TELEMETRIA LIVE")
    print("-" * 70)
    try:
        telemetry = connector.get_telemetry()
        for k, v in telemetry.items():
            print(f"  {k:<35}: {v}")
    except Exception as e:
        print(f"[-] Errore lettura telemetria: {e}")

    # 3. Analyze raw features
    try:
        with open(dump_file, "r", encoding="utf-8") as f:
            features_data = json.load(f)

        features = features_data.get("data", [])
        print("\n" + "-" * 70)
        print(f"  MAPPA FEATURES RILEVATI ({len(features)} proprieta totali)")
        print("-" * 70)

        categories: dict[str, list[str]] = {}
        for feat in features:
            name = feat.get("feature", "unknown")
            cat = name.split(".")[0] if "." in name else "general"
            categories.setdefault(cat, []).append(name)

        for cat, items in sorted(categories.items()):
            print(f"\n  [Categoria: {cat.upper()}] ({len(items)} features)")
            for item in sorted(items):
                print(f"    - {item}")

    except Exception as e:
        print(f"[-] Errore analisi feature dump: {e}")


def dump_bticino():
    print("\n" + "=" * 70)
    print("  DIAGNOSTICA TERMOSTATO BTICINO (LEGRAND / NETATMO)")
    print("=" * 70)

    valid, msg = Config.validate_netatmo()
    if not valid:
        print(f"\n[*] Configurazione Netatmo/BTicino non presente o parziale: {msg}")
        print("    (Puoi configurarla in '.env' quando avrai creato l'app su dev.netatmo.com)")
        return

    connector = BTicinoConnector()
    try:
        print("\n[*] Tentativo di autenticazione Netatmo...")
        connector.authenticate()
        print("[+] Autenticazione Netatmo riuscita!")

        home_id, room_id = connector.discover_home_and_room()
        print(f"[+] Casa: {home_id} | Stanza: {room_id}")

        status = connector.get_status()
        print("\n  STATO TERMOSTATO BTICINO:")
        for k, v in status.items():
            print(f"  {k:<25}: {v}")

    except Exception as e:
        print(f"[-] Errore connessione BTicino: {e}")


def main():
    dump_viessmann()
    dump_bticino()
    print("\n" + "=" * 70)
    print("  DIAGNOSTICA COMPLETATA")
    print("=" * 70)


if __name__ == "__main__":
    main()
