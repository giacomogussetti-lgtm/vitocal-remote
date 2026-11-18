"""
Cloud Telemetry Logger for Vitocal 111-S & BTicino Smarther.
Designed to run in headless environments (e.g., GitHub Actions cron jobs or VPS)
without any GUI dependencies. Fetches a single sample from Viessmann ViCare
and Netatmo Connect APIs and appends it to data/cloud_telemetry.jsonl.
"""
import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config import Config
from api.viessmann import ViessmannConnector
from api.bticino import BTicinoConnector
from models.telemetry import TelemetrySample

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("cloud_logger")


def log_sample() -> bool:
    logger.info("Avvio campionamento telemetria cloud (Vitocal 111-S & BTicino)...")

    # Validate configurations
    ok_v, msg_v = Config.validate_viessmann()
    if not ok_v:
        logger.error("Configurazione Viessmann non valida: %s", msg_v)
        return False

    ok_b, msg_b = Config.validate_netatmo()
    if not ok_b:
        logger.warning("Configurazione Netatmo / BTicino: %s", msg_b)

    # 1. Fetch Viessmann telemetry
    v_data = {}
    try:
        v_conn = ViessmannConnector()
        v_data = v_conn.get_telemetry()
        logger.info(
            "Viessmann OK: OAT=%.1f °C, LWT=%.1f °C, Puffer=%.1f °C, Modulazione=%.0f%%",
            v_data.get("outside_temp_c", 0.0) or 0.0,
            v_data.get("supply_temp_c", 0.0) or 0.0,
            v_data.get("buffer_temp_c", 0.0) or 0.0,
            v_data.get("compressor_modulation_percent", 0.0) or 0.0,
        )
    except Exception as e:
        logger.error("Errore lettura Viessmann: %s", e)

    # 2. Fetch BTicino telemetry
    b_data = {}
    try:
        b_conn = BTicinoConnector()
        b_data = b_conn.get_status()
        logger.info(
            "BTicino OK: Stanza=%s, T=%s °C, Setpoint=%s °C, Pompa Grundfos=%s",
            b_data.get("room_name", "Corridoio"),
            str(b_data.get("indoor_temp_c", "--")),
            str(b_data.get("setpoint_c", "--")),
            "ACCESA" if b_data.get("grundfos_pump_active") == 1 else "SPENTA",
        )
    except Exception as e:
        logger.error("Errore lettura BTicino: %s", e)

    # 2b. Fallback to previous valid telemetry if BTicino was momentarily in sleep/Wi-Fi retry
    cloud_file = Config.DATA_DIR / "cloud_telemetry.jsonl"
    if not b_data or b_data.get("indoor_temp_c") is None:
        try:
            if cloud_file.exists():
                with open(cloud_file, "r", encoding="utf-8") as f:
                    lines = [ln.strip() for ln in f if ln.strip()]
                for prev_ln in reversed(lines):
                    prev_rec = json.loads(prev_ln)
                    if prev_rec.get("indoor_temp_bticino_c") is not None:
                        if b_data.get("indoor_temp_c") is None:
                            b_data["indoor_temp_c"] = prev_rec.get("indoor_temp_bticino_c")
                        if b_data.get("setpoint_c") is None:
                            b_data["setpoint_c"] = prev_rec.get("indoor_setpoint_bticino_c")
                        if b_data.get("humidity_percent") is None:
                            b_data["humidity_percent"] = prev_rec.get("humidity_percent")
                        logger.info("Recuperati valori precedenti BTicino da cache cloud: T=%.1f °C", b_data["indoor_temp_c"])
                        break
        except Exception as fb_err:
            logger.debug("Fallback cloud cache: %s", fb_err)

    if not v_data and not b_data:
        logger.error("Nessun dato ottenuto da Viessmann o BTicino. Interruzione.")
        return False

    # 3. Assemble TelemetrySample
    sample = TelemetrySample(
        external_temp_c=v_data.get("outside_temp_c"),
        indoor_temp_bticino_c=b_data.get("indoor_temp_c"),
        indoor_setpoint_bticino_c=b_data.get("setpoint_c"),
        grundfos_pump_active=b_data.get("grundfos_pump_active"),
        pdc_supply_temp_c=v_data.get("supply_temp_c"),
        pdc_return_temp_c=v_data.get("return_temp_c"),
        buffer_temp_c=v_data.get("buffer_temp_c"),
        dhw_storage_temp_c=v_data.get("dhw_storage_temp_c"),
        compressor_active=1 if (v_data.get("compressor_active") or (v_data.get("compressor_modulation_percent", 0) or 0) > 0) else 0,
        compressor_hours=v_data.get("compressor_hours"),
        compressor_starts=v_data.get("compressor_starts"),
        heating_curve_slope=v_data.get("heating_curve_slope"),
        heating_curve_shift=v_data.get("heating_curve_shift"),
        active_mode=v_data.get("active_mode"),
        active_program=v_data.get("active_program"),
        heating_elec_kwh_total=v_data.get("power_consumption_heating_today_kwh"),
        dhw_elec_kwh_total=v_data.get("power_consumption_dhw_today_kwh"),
        dhw_thermal_kwh_total=v_data.get("heat_production_dhw_today_kwh"),
        hot_gas_pressure_bar=v_data.get("hot_gas_pressure_bar"),
        hot_gas_temp_c=v_data.get("hot_gas_temp_c"),
        liquid_gas_temp_c=v_data.get("liquid_gas_temp_c"),
        suction_gas_temp_c=v_data.get("suction_gas_temp_c"),
        compressor_modulation_percent=v_data.get("compressor_modulation_percent"),
        primary_pump_rotation_percent=v_data.get("primary_pump_rotation_percent"),
        cop_heating=v_data.get("cop_heating"),
        cop_dhw=v_data.get("cop_dhw"),
        cop_total=v_data.get("cop_total"),
        humidity_percent=b_data.get("humidity_percent"),
        active_preset="cloud_github_actions",
    )

    # 4. Append to data/cloud_telemetry.jsonl
    cloud_file = Config.DATA_DIR / "cloud_telemetry.jsonl"
    cloud_file.parent.mkdir(parents=True, exist_ok=True)

    record_json = json.dumps(sample.model_dump(), ensure_ascii=False)
    with open(cloud_file, "a", encoding="utf-8") as f:
        f.write(record_json + "\n")

    logger.info("Campione registrato con successo in: %s", cloud_file)
    return True


if __name__ == "__main__":
    success = log_sample()
    sys.exit(0 if success else 1)
