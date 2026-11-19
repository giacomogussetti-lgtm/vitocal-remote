"""
Vitocal Remote - Mobile Web Server & API Bridge
Runs a lightweight Flask server on local port 8080, serving the PWA
and providing live direct API endpoints for instant sampling.
"""
import os
import sys
import json
import time
import socket
import logging
from pathlib import Path
import requests
from flask import Flask, send_from_directory, jsonify, request

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from config import Config
from storage.database import DatabaseManager
from storage.analytics import analyze_telemetry_period
from scripts.cloud_logger import log_sample

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("web_server")

app = Flask(__name__, static_folder="web", static_url_path="")
db = DatabaseManager()


def get_local_ips() -> list[str]:
    """Find all valid local LAN IPv4 addresses, prioritizing physical Wi-Fi/Ethernet over VPN tunnels."""
    try:
        hostname = socket.gethostname()
        addrs = socket.getaddrinfo(hostname, None)
        valid = set()
        for a in addrs:
            if a[0] == socket.AF_INET:
                ip = a[4][0]
                if not ip.startswith("127.") and not ip.startswith("169.254."):
                    valid.add(ip)
        # Prioritize 192.168.x.x, de-prioritize VPN ranges like 10.14.x.x
        sorted_ips = sorted(
            list(valid),
            key=lambda x: (not x.startswith("192.168."), x.startswith("10.14."), x)
        )
        return sorted_ips if sorted_ips else ["127.0.0.1"]
    except Exception:
        return ["127.0.0.1"]


# -------------------------------------------------------------
# STATIC ROUTES (PWA & DATA)
# -------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory("web", "index.html")


@app.route("/data/<path:filename>")
def serve_data(filename):
    return send_from_directory("data", filename)


# -------------------------------------------------------------
# REST API ENDPOINTS
# -------------------------------------------------------------
@app.route("/api/status", methods=["GET"])
def api_status():
    latest = db.get_latest_sample()
    return jsonify({
        "status": "online",
        "service": "Vitocal Remote Mobile Backend",
        "has_latest_sample": latest is not None,
        "latest_timestamp": latest.get("timestamp_utc") if latest else None,
    })


@app.route("/api/history", methods=["GET"])
def api_history():
    limit = request.args.get("limit", 200, type=int)
    samples = db.get_samples(limit=limit)
    # Return samples chronologically
    samples_list = list(reversed(samples))
    return jsonify({"count": len(samples_list), "samples": samples_list})


@app.route("/api/analytics", methods=["GET"])
def api_analytics():
    hours = request.args.get("hours", 24.0, type=float)
    cost_kwh = request.args.get("cost_kwh", 0.25, type=float)
    samples = db.get_samples(limit=1000)
    samples_list = list(reversed(samples))
    result = analyze_telemetry_period(samples_list, hours_requested=hours, cost_per_kwh=cost_kwh)
    return jsonify(result)


@app.route("/api/sync-github", methods=["POST", "GET"])
def api_sync_github():
    """Server-side sync from GitHub repository to update local files and SQLite."""
    try:
        raw_url = f"https://raw.githubusercontent.com/{Config.GITHUB_REPO}/main/data/cloud_telemetry.jsonl?t={int(time.time())}"
        headers = {}
        if Config.GITHUB_TOKEN:
            headers["Authorization"] = f"token {Config.GITHUB_TOKEN}"

        resp = requests.get(raw_url, headers=headers, timeout=12)
        if resp.status_code != 200:
            return jsonify({"success": False, "error": f"HTTP {resp.status_code} da GitHub"}), 400

        cloud_file = Config.DATA_DIR / "cloud_telemetry.jsonl"
        with open(cloud_file, "w", encoding="utf-8") as f:
            f.write(resp.text)

        # Parse and insert new samples into SQLite
        lines = [l.strip() for l in resp.text.split("\n") if l.strip()]
        imported = db.import_file(cloud_file)

        samples = db.get_samples(limit=200)
        samples_list = list(reversed(samples))
        return jsonify({
            "success": True,
            "imported": imported,
            "total_lines": len(lines),
            "samples": samples_list
        })
    except Exception as e:
        logger.error("Errore server-side sync GitHub: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


def _read_latest_cloud_sample_and_store() -> dict | None:
    """Reads last record from cloud_telemetry.jsonl and stores it in SQLite if present."""
    cloud_file = Config.DATA_DIR / "cloud_telemetry.jsonl"
    latest_record = None
    if cloud_file.exists():
        with open(cloud_file, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
            if lines:
                latest_record = json.loads(lines[-1])

    if latest_record:
        from models.telemetry import TelemetrySample
        try:
            db.insert_sample(TelemetrySample(**latest_record))
        except Exception as dbe:
            logger.debug("Insert SQLite: %s", dbe)
    return latest_record


@app.route("/api/refresh-direct", methods=["POST"])
def api_refresh_direct():
    """Triggers an immediate live reading from Viessmann and BTicino APIs."""
    logger.info("Richiesta campionamento live diretto ricevuta da app mobile...")
    try:
        success = log_sample()
        if not success:
            return jsonify({"success": False, "error": "Errore lettura connettori API"}), 500

        latest_record = _read_latest_cloud_sample_and_store()
        return jsonify({
            "success": True,
            "message": "Campionamento diretto completato con successo",
            "sample": latest_record,
        })
    except Exception as e:
        logger.error("Errore campionamento diretto: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/command", methods=["POST"])
def api_command():
    """Executes a validated bidirectional write command directly via local connectors."""
    body = request.get_json(silent=True) or {}
    command = str(body.get("command", "")).strip()
    params = body.get("params") or {}
    if not command:
        return jsonify({"success": False, "message": "Parametro 'command' mancante."}), 400

    logger.info("Comando bidirezionale ricevuto da PWA locale: %s %s", command, params)
    try:
        from scripts.cloud_commander import execute_command
        receipt = execute_command(command, params)
        latest_record = _read_latest_cloud_sample_and_store() if receipt.get("sample_logged") else None
        status_code = 200 if receipt.get("success") else 400
        return jsonify({**receipt, "sample": latest_record}), status_code
    except Exception as e:
        logger.error("Errore esecuzione /api/command: %s", e)
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/schedules", methods=["GET"])
def api_schedules():
    """Returns configured BTicino and Viessmann weekly schedules."""
    try:
        from api.bticino import BTicinoConnector
        from api.viessmann import ViessmannConnector
        bticino_schedules = BTicinoConnector().get_schedules()
        viessmann_schedule = ViessmannConnector().get_heating_schedule()
        return jsonify({
            "success": True,
            "bticino_schedules": bticino_schedules,
            "viessmann_schedule": viessmann_schedule,
        })
    except Exception as e:
        logger.error("Errore lettura programmazioni: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


def main():
    port = 8080
    ips = get_local_ips()
    primary_lan_ip = ips[0] if ips else "127.0.0.1"

    print("=" * 70)
    print("   📱 VITOCAL REMOTE - SERVER APP MOBILE ANDROID (PWA) 📱")
    print("=" * 70)
    print(f"\n   [PC / Desktop]:          http://localhost:{port}")
    print(f"   [Smartphone su Wi-Fi]:   http://{primary_lan_ip}:{port}  <-- USA QUESTO!")
    
    if len(ips) > 1:
        print("\n   Altri indirizzi rilevati (schede virtuali o VPN):")
        for extra_ip in ips[1:]:
            tag = " (Tunnel VPN)" if extra_ip.startswith("10.14.") else ""
            print(f"   • http://{extra_ip}:{port}{tag}")

    print("\n   ISTRUZIONI RAPIDE PER IL TUO SMARTPHONE:")
    print(f"   1. Assicurati che lo smartphone sia connesso alla Wi-Fi di casa.")
    print(f"   2. Apri Chrome o Brave su Android e vai su: http://{primary_lan_ip}:{port}")
    print("   3. Tocca i tre puntini ⋮ e scegli 'Installa app' o 'Aggiungi a schermata Home'.")
    print("   4. L'app si aprirà a schermo intero indipendente dal browser!\n")
    print("=" * 70)
    print("   Premi CTRL+C per arrestare il server.\n")

    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
