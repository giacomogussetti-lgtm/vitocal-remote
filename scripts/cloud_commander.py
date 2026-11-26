"""
Cloud Command Executor for Vitocal 111-S & BTicino Smarther.
Executes validated bidirectional write commands (from GitHub Actions workflow_dispatch
or local Flask web_server), logs an updated telemetry snapshot, and writes a receipt
to data/last_command.json for PWA confirmation.
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config import Config
from api.viessmann import ViessmannConnector
from api.bticino import BTicinoConnector
from scripts.cloud_logger import log_sample

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("cloud_commander")

VALID_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _validate_hhmm(val: str, label: str) -> str:
    if not isinstance(val, str):
        raise ValueError(f"Orario {label} non valido.")
    parts = val.strip().split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError(f"Formato orario {label} non valido: {val}")
    hh, mm = int(parts[0]), int(parts[1])
    if not (0 <= hh <= 23 and 0 <= mm <= 59 and mm % 10 == 0):
        raise ValueError(f"Orario {label} deve essere multiplo di 10 min (es. 11:30): {val}")
    return f"{hh:02d}:{mm:02d}"


def _validate_schedule_params(params: dict[str, Any]) -> dict[str, Any]:
    raw_days = params.get("days", list(VALID_DAYS))
    if not isinstance(raw_days, list):
        raise ValueError("days deve essere una lista.")
    days = [str(d).strip().lower() for d in raw_days if str(d).strip().lower() in VALID_DAYS]
    if not days:
        raise ValueError("Selezionare almeno un giorno valido (mon..sun).")
    clear = bool(params.get("clear", False))
    if clear:
        return {"days": days, "clear": True}
    start = _validate_hhmm(str(params.get("start", "11:00")), "inizio")
    end = _validate_hhmm(str(params.get("end", "16:00")), "fine")
    if start >= end:
        raise ValueError(f"L'ora di fine ({end}) deve seguire l'inizio ({start}).")
    mode = str(params.get("mode", "reduced")).strip()
    if mode not in ("reduced", "normal", "fixed"):
        raise ValueError(f"Modo fascia non valido: {mode}")
    return {"days": days, "start": start, "end": end, "mode": mode, "clear": False}


def _validate_command(command: str, params: dict[str, Any]) -> dict[str, Any]:
    """Validates command name and strictly clamps/checks parameter ranges."""
    if not isinstance(params, dict):
        raise ValueError("I parametri devono essere un oggetto JSON.")

    if command == "viessmann_curve":
        slope = round(float(params["slope"]), 1)
        shift = int(round(float(params["shift"])))
        if not (0.0 <= slope <= 3.5):
            raise ValueError("Slope fuori range (0.0 – 3.5).")
        if not (-15 <= shift <= 40):
            raise ValueError("Shift fuori range (-15 – +40).")
        return {"slope": slope, "shift": shift}

    if command == "viessmann_temps":
        clean: dict[str, Any] = {}
        if params.get("normal") is not None:
            t_norm = int(round(float(params["normal"])))
            if not (10 <= t_norm <= 30):
                raise ValueError("Temperatura Normale fuori range (10 – 30 °C).")
            clean["normal"] = t_norm
        if params.get("reduced") is not None:
            t_red = int(round(float(params["reduced"])))
            if not (10 <= t_red <= 30):
                raise ValueError("Temperatura Ridotta fuori range (10 – 30 °C).")
            clean["reduced"] = t_red
        if params.get("dhw") is not None:
            t_dhw = int(round(float(params["dhw"])))
            if not (10 <= t_dhw <= 60):
                raise ValueError("Temperatura ACS fuori range (10 – 60 °C).")
            clean["dhw"] = t_dhw
        if not clean:
            raise ValueError("Specificare almeno una temperatura (normal, reduced o dhw).")
        return clean

    if command == "viessmann_mode":
        mode = str(params.get("mode", "")).strip()
        if mode not in ("standby", "dhw", "dhwAndHeating"):
            raise ValueError(f"Modalità PdC non valida: '{mode}'.")
        return {"mode": mode}

    if command == "viessmann_schedule":
        return _validate_schedule_params(params)

    if command == "viessmann_dhw_boost":
        return {"active": bool(params.get("active", True))}

    if command == "bticino_setpoint":
        mode = str(params.get("mode", "manual")).strip().lower()
        if mode not in ("manual", "home", "away", "hg"):
            raise ValueError(f"Modalità BTicino non valida: '{mode}'.")
        if mode == "manual":
            temp = round(float(params.get("temp", 12.0)) * 2) / 2.0
            if not (5.0 <= temp <= 30.0):
                raise ValueError("Setpoint BTicino fuori range (5.0 – 30.0 °C).")
            dur = int(params.get("duration_minutes", 180))
            if not (0 <= dur <= 1440):
                raise ValueError("Durata manuale fuori range (0 – 1440 min).")
            return {"mode": "manual", "temp": temp, "duration_minutes": dur}
        return {"mode": mode}

    if command == "bticino_switch_schedule":
        sid = str(params.get("schedule_id", "") or "").strip() or None
        sname = str(params.get("schedule_name", "") or "").strip() or None
        if not sid and not sname:
            raise ValueError("Specificare schedule_id o schedule_name per BTicino.")
        return {"schedule_id": sid, "schedule_name": sname}

    if command == "preset_stop_all":
        return {}

    if command == "preset_sync_pulse":
        temp = round(float(params.get("temp", 15.0)) * 2) / 2.0
        if not (7.0 <= temp <= 26.0):
            raise ValueError("Setpoint casa per ciclo sincronizzato fuori range (7.0 – 26.0 °C).")
        dur = int(params.get("duration_minutes", 180))
        if not (15 <= dur <= 720):
            raise ValueError("Durata ciclo sincronizzato fuori range (15 – 720 min).")
        clean: dict[str, Any] = {"temp": temp, "duration_minutes": dur}
        if params.get("pdc_reduced") is not None:
            pr = int(round(float(params["pdc_reduced"])))
            if not (10 <= pr <= 30):
                raise ValueError("Temperatura Ridotta PdC fuori range (10 – 30 °C).")
            clean["pdc_reduced"] = pr
        if params.get("pdc_normal") is not None:
            pn = int(round(float(params["pdc_normal"])))
            if not (10 <= pn <= 30):
                raise ValueError("Temperatura Normale PdC fuori range (10 – 30 °C).")
            clean["pdc_normal"] = pn
        return clean

    if command == "apply_full_profile":
        clean: dict[str, Any] = {}
        if params.get("profile_name") is not None:
            clean["profile_name"] = str(params["profile_name"]).strip()[:60]
        if params.get("autopilot_enabled") is not None:
            clean["autopilot_enabled"] = bool(params["autopilot_enabled"])
        if params.get("pdc_mode") is not None:
            mode = str(params["pdc_mode"]).strip()
            if mode not in ("standby", "dhw", "dhwAndHeating"):
                raise ValueError(f"Modalità PdC non valida: '{mode}'.")
            clean["pdc_mode"] = mode
        if params.get("pdc_normal") is not None:
            pn = int(round(float(params["pdc_normal"])))
            if not (10 <= pn <= 30):
                raise ValueError("Temperatura Normale PdC fuori range (10 – 30 °C).")
            clean["pdc_normal"] = pn
        if params.get("pdc_reduced") is not None:
            pr = int(round(float(params["pdc_reduced"])))
            if not (10 <= pr <= 30):
                raise ValueError("Temperatura Ridotta PdC fuori range (10 – 30 °C).")
            clean["pdc_reduced"] = pr
        if params.get("pdc_dhw") is not None:
            pd = int(round(float(params["pdc_dhw"])))
            if not (10 <= pd <= 60):
                raise ValueError("Temperatura ACS fuori range (10 – 60 °C).")
            clean["pdc_dhw"] = pd
        if params.get("curve_slope") is not None and params.get("curve_shift") is not None:
            slp = round(float(params["curve_slope"]), 1)
            shf = int(round(float(params["curve_shift"])))
            if not (0.0 <= slp <= 3.5) or not (-15 <= shf <= 40):
                raise ValueError("Curva climatica fuori range.")
            clean["curve_slope"] = slp
            clean["curve_shift"] = shf
        if isinstance(params.get("pdc_schedule"), dict):
            clean["pdc_schedule"] = _validate_schedule_params(params["pdc_schedule"])
        if params.get("bticino_mode") is not None:
            bm = str(params["bticino_mode"]).strip().lower()
            if bm not in ("manual", "home", "away", "hg"):
                raise ValueError(f"Modalità BTicino non valida: '{bm}'.")
            clean["bticino_mode"] = bm
            if bm == "manual":
                bt = round(float(params.get("bticino_temp", 18.0)) * 2) / 2.0
                if not (5.0 <= bt <= 30.0):
                    raise ValueError("Setpoint BTicino fuori range (5.0 – 30.0 °C).")
                bd = int(params.get("bticino_duration_minutes", 180))
                if not (0 <= bd <= 1440):
                    raise ValueError("Durata manuale BTicino fuori range (0 – 1440 min).")
                clean["bticino_temp"] = bt
                clean["bticino_duration_minutes"] = bd
        if params.get("bticino_schedule_name"):
            clean["bticino_schedule_name"] = str(params["bticino_schedule_name"]).strip()[:80]
        if not clean:
            raise ValueError("Il profilo non contiene impostazioni valide.")
        return clean

    if command in ("autopilot_configure", "autopilot_activate_away"):
        return _validate_autopilot_params(params, force_enable=(command == "autopilot_activate_away"))

    if command == "cronjob_test":
        return {"roundtrip_2m": bool(params.get("roundtrip_2m", False))}

    raise ValueError(f"Comando sconosciuto: '{command}'")


def _validate_autopilot_params(params: dict[str, Any], force_enable: bool = False) -> dict[str, Any]:
    """Validates tunable Full-Auto Mountain Custody parameters."""
    clean: dict[str, Any] = {}
    if force_enable:
        clean["enabled"] = True
        clean["mode"] = "away_antifrost"
    elif "enabled" in params:
        clean["enabled"] = bool(params["enabled"])

    bounds = {
        "t_min_c": (5.0, 15.0, float),
        "t_max_c": (6.0, 18.0, float),
        "t_emergency_c": (4.5, 12.0, float),
        "target_lwt_delta_k": (10.0, 25.0, float),
        "min_target_lwt_c": (19.0, 32.0, float),
        "max_target_lwt_c": (22.0, 36.0, float),
        "max_cycle_minutes": (30, 360, int),
        "puffer_drain_minutes": (0, 60, int),
        "puffer_drain_stop_temp_c": (10.0, 20.0, float),
        "cron_idle_minutes": (1, 60, int),
        "cron_armed_minutes": (1, 30, int),
        "cron_active_minutes": (1, 15, int),
        "soft_start_step_minutes": (10, 60, int),
        "soft_start_min_lwt_c": (18.0, 27.0, float),
        "defrost_trim_threshold_count": (1, 5, int),
        "defrost_guard_oat_max_c": (0.0, 10.0, float),
        "defrost_min_safe_lwt_c": (18.0, 28.0, float),
        "defrost_min_delta_k": (10.0, 18.0, float),
        "inverter_min_mod_pct": (20, 55, int),
        "soft_curve_max_shift_delta_k": (1, 4, int),
        "soft_curve_cooldown_minutes": (15, 180, int),
        "anti_seize_days": (0, 30, int),
        "weather_window_hours": (2, 9, int),
        "weather_refresh_hours": (1, 12, int),
        "weather_min_cop_gain": (0.0, 1.0, float),
        "min_cycle_minutes": (45, 240, int),
        "max_window_extension_minutes": (0, 240, int),
        "prearm_max_above_tmin_c": (0.1, 2.0, float),
        "prearm_emergency_margin_c": (0.1, 1.5, float),
        "weather_arbitrage_cop_delta": (0.05, 1.5, float),
        "window_lock_before_start_minutes": (15, 240, int),
        "min_cycle_end_temp_c": (0.0, 15.0, float),
    }
    for key, (lo, hi, caster) in bounds.items():
        if params.get(key) is not None:
            val = caster(params[key])
            if not (lo <= val <= hi):
                raise ValueError(f"{key} fuori range ({lo} – {hi}).")
            clean[key] = round(val, 2) if key in ("weather_min_cop_gain", "weather_arbitrage_cop_delta") else (round(val, 1) if caster is float else val)

    for bool_key in (
        "dynamic_cron_enabled",
        "soft_start_enabled",
        "defrost_guard_enabled",
        "soft_curve_tuning_enabled",
        "adaptive_model_enabled",
        "adaptive_model_apply_targets",
        "weather_planner_enabled",
        "weather_dynamic_window_enabled",
        "anti_short_cycle_enabled",
        "predictive_prearm_enabled",
        "weather_defer_enabled",
    ):
        if bool_key in params:
            clean[bool_key] = bool(params[bool_key])

    for tkey in ("cop_window_start", "cop_window_end", "weather_search_start", "weather_search_end"):
        if params.get(tkey) is not None:
            clean[tkey] = _validate_hhmm(str(params[tkey]), tkey)

    if "weather_search_start" in clean and "weather_search_end" in clean:
        if clean["weather_search_end"] <= clean["weather_search_start"]:
            raise ValueError("weather_search_end deve essere successivo a weather_search_start.")

    return clean


def _write_receipt(receipt: dict[str, Any]) -> None:
    receipt_file = Config.DATA_DIR / "last_command.json"
    receipt_file.parent.mkdir(parents=True, exist_ok=True)
    with open(receipt_file, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, ensure_ascii=False)


def execute_command(
    command: str,
    params: dict[str, Any] | None = None,
    dry_run: bool = False,
    write_receipt_file: bool = True,
) -> dict[str, Any]:
    """Validates and executes a hardware write command, returning structured receipt."""
    ts = datetime.now(timezone.utc).isoformat()
    raw_params = params or {}

    try:
        clean_params = _validate_command(command, raw_params)
    except Exception as ve:
        receipt = {
            "timestamp_utc": ts,
            "command": command,
            "params": raw_params,
            "success": False,
            "message": f"Validazione fallita: {ve}",
            "sample_logged": False,
        }
        if write_receipt_file and not dry_run:
            _write_receipt(receipt)
        return receipt

    if dry_run:
        return {
            "timestamp_utc": ts,
            "command": command,
            "params": clean_params,
            "success": True,
            "message": f"[DRY-RUN] Comando '{command}' validato correttamente.",
            "sample_logged": False,
        }

    success = False
    messages: list[str] = []
    v_reads = 0
    v_writes = 0
    b_reads = 0
    b_writes = 0
    cron_patches = 0
    state_already_recorded = False
    is_gha = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"

    try:
        needs_v = command.startswith("viessmann_") or command.startswith("preset_") or command == "autopilot_activate_away" or (
            command == "apply_full_profile" and any(k in clean_params for k in ("pdc_mode", "pdc_normal", "pdc_reduced", "pdc_dhw", "curve_slope", "pdc_schedule"))
        )
        needs_b = command.startswith("bticino_") or command.startswith("preset_") or command == "autopilot_activate_away" or (
            command == "apply_full_profile" and any(k in clean_params for k in ("bticino_mode", "bticino_schedule_name"))
        )

        if needs_v:
            v_conn = ViessmannConnector()
            v_conn.connect()
            v_reads += 1

        if needs_b:
            b_conn = BTicinoConnector()

        if command == "viessmann_curve":
            ok, msg = v_conn.set_heating_curve(clean_params["slope"], clean_params["shift"])
            v_writes += 1
            v_reads += 1
            success = ok
            messages.append(msg)

        elif command == "viessmann_temps":
            all_ok = True
            if "normal" in clean_params:
                ok, msg = v_conn.set_normal_temperature(clean_params["normal"])
                v_writes += 1
                v_reads += 1
                all_ok = all_ok and ok
                messages.append(msg)
            if "reduced" in clean_params:
                ok, msg = v_conn.set_reduced_temperature(clean_params["reduced"])
                v_writes += 1
                v_reads += 1
                all_ok = all_ok and ok
                messages.append(msg)
            if "dhw" in clean_params:
                ok, msg = v_conn.set_dhw_temperature(clean_params["dhw"])
                v_writes += 1
                v_reads += 1
                all_ok = all_ok and ok
                messages.append(msg)
            success = all_ok

        elif command == "viessmann_mode":
            ok, msg = v_conn.set_mode(clean_params["mode"])
            v_writes += 1
            v_reads += 1
            success = ok
            messages.append(msg)

        elif command == "viessmann_schedule":
            ok, msg = v_conn.set_heating_schedule_simple(
                days=clean_params["days"],
                start=clean_params.get("start", "11:00"),
                end=clean_params.get("end", "16:00"),
                mode=clean_params.get("mode", "reduced"),
                clear=clean_params["clear"],
            )
            v_writes += 1
            v_reads += 2
            success = ok
            messages.append(msg)

        elif command == "viessmann_dhw_boost":
            ok, msg = v_conn.set_dhw_onetime_charge(clean_params["active"])
            v_writes += 1
            success = ok
            messages.append(msg)

        elif command == "bticino_setpoint":
            if clean_params["mode"] == "manual":
                ok, msg = b_conn.set_thermostat_setpoint(
                    temp=clean_params["temp"],
                    mode="manual",
                    duration_minutes=clean_params["duration_minutes"],
                )
            else:
                ok, msg = b_conn.set_thermostat_mode(clean_params["mode"])
            b_reads += 1
            b_writes += 1
            success = ok
            messages.append(msg)

        elif command == "bticino_switch_schedule":
            ok, msg = b_conn.switch_schedule(
                schedule_id=clean_params.get("schedule_id"),
                schedule_name=clean_params.get("schedule_name"),
            )
            b_reads += 1
            b_writes += 1
            success = ok
            messages.append(msg)

        elif command == "preset_stop_all":
            ok_v, msg_v = v_conn.set_mode("standby")
            ok_b, msg_b = b_conn.set_thermostat_mode("hg")
            v_writes += 1
            v_reads += 1
            b_reads += 1
            b_writes += 1
            success = ok_v and ok_b
            messages.extend([msg_v, msg_b])

        elif command == "preset_sync_pulse":
            all_ok = True
            if "pdc_normal" in clean_params:
                ok_n, msg_n = v_conn.set_normal_temperature(clean_params["pdc_normal"])
                v_writes += 1
                v_reads += 1
                all_ok = all_ok and ok_n
                messages.append(msg_n)
            if "pdc_reduced" in clean_params:
                ok_r, msg_r = v_conn.set_reduced_temperature(clean_params["pdc_reduced"])
                v_writes += 1
                v_reads += 1
                all_ok = all_ok and ok_r
                messages.append(msg_r)
            ok_v, msg_v = v_conn.set_mode("dhwAndHeating")
            ok_b, msg_b = b_conn.set_thermostat_setpoint(
                temp=clean_params["temp"],
                mode="manual",
                duration_minutes=clean_params["duration_minutes"],
            )
            v_writes += 1
            v_reads += 1
            b_reads += 1
            b_writes += 1
            success = all_ok and ok_v and ok_b
            messages.extend([msg_v, msg_b])

        elif command == "apply_full_profile":
            all_ok = True
            prof_name = clean_params.get("profile_name") or "Profilo Personalizzato"
            if clean_params.get("autopilot_enabled") is False:
                from scripts.autopilot import load_config, save_config, load_state, save_state
                cfg = load_config()
                if cfg.get("enabled"):
                    cfg["enabled"] = False
                    save_config(cfg)
                    st = load_state()
                    st["state"] = "DISABLED"
                    st["below_threshold_since_utc"] = None
                    st["last_action_utc"] = datetime.now(timezone.utc).isoformat()
                    st["last_action_reason"] = f"Autopilota messo in pausa da profilo '{prof_name}'."
                    save_state(st)
                    messages.append("Autopilota disattivato")

            if "curve_slope" in clean_params and "curve_shift" in clean_params:
                ok_c, msg_c = v_conn.set_heating_curve(clean_params["curve_slope"], clean_params["curve_shift"])
                v_writes += 1
                v_reads += 1
                all_ok = all_ok and ok_c
                messages.append(msg_c)
            if "pdc_normal" in clean_params:
                ok_n, msg_n = v_conn.set_normal_temperature(clean_params["pdc_normal"])
                v_writes += 1
                v_reads += 1
                all_ok = all_ok and ok_n
                messages.append(msg_n)
            if "pdc_reduced" in clean_params:
                ok_r, msg_r = v_conn.set_reduced_temperature(clean_params["pdc_reduced"])
                v_writes += 1
                v_reads += 1
                all_ok = all_ok and ok_r
                messages.append(msg_r)
            if "pdc_dhw" in clean_params:
                ok_d, msg_d = v_conn.set_dhw_temperature(clean_params["pdc_dhw"])
                v_writes += 1
                v_reads += 1
                all_ok = all_ok and ok_d
                messages.append(msg_d)
            if "pdc_schedule" in clean_params:
                sc = clean_params["pdc_schedule"]
                ok_s, msg_s = v_conn.set_heating_schedule_simple(
                    days=sc["days"],
                    start=sc.get("start", "11:00"),
                    end=sc.get("end", "16:00"),
                    mode=sc.get("mode", "reduced"),
                    clear=sc["clear"],
                )
                v_writes += 1
                v_reads += 2
                all_ok = all_ok and ok_s
                messages.append(msg_s)
            if "pdc_mode" in clean_params:
                ok_m, msg_m = v_conn.set_mode(clean_params["pdc_mode"])
                v_writes += 1
                v_reads += 1
                all_ok = all_ok and ok_m
                messages.append(msg_m)

            if clean_params.get("bticino_schedule_name"):
                ok_bs, msg_bs = b_conn.switch_schedule(schedule_name=clean_params["bticino_schedule_name"])
                b_reads += 1
                b_writes += 1
                all_ok = all_ok and ok_bs
                messages.append(msg_bs)
            if "bticino_mode" in clean_params:
                bm = clean_params["bticino_mode"]
                if bm == "manual":
                    ok_b, msg_b = b_conn.set_thermostat_setpoint(
                        temp=clean_params["bticino_temp"],
                        mode="manual",
                        duration_minutes=clean_params["bticino_duration_minutes"],
                    )
                else:
                    ok_b, msg_b = b_conn.set_thermostat_mode(bm)
                b_reads += 1
                b_writes += 1
                all_ok = all_ok and ok_b
                messages.append(msg_b)

            success = all_ok
            messages.insert(0, f"Profilo '{prof_name}' applicato")

        elif command == "autopilot_configure":
            from scripts.autopilot import (
                load_config,
                save_config,
                load_state,
                save_state,
                update_cronjob_frequency,
                record_api_usage,
            )
            cfg = load_config()
            cfg.update(clean_params)
            if float(cfg["t_max_c"]) <= float(cfg["t_min_c"]):
                raise ValueError("t_max_c deve essere maggiore di t_min_c.")
            saved_cfg = save_config(cfg)
            st = load_state()
            if not saved_cfg.get("enabled"):
                st["state"] = "DISABLED"
                st["below_threshold_since_utc"] = None
                st["last_action_utc"] = datetime.now(timezone.utc).isoformat()
                st["last_action_reason"] = "Autopilota disattivato manualmente dalla PWA."
                desired_cron = int(saved_cfg.get("cron_armed_minutes") or 5)
            else:
                if st.get("state") == "DISABLED":
                    st["state"] = "IDLE"
                    st["state_since_utc"] = datetime.now(timezone.utc).isoformat()
                cur_st = st.get("state")
                if cur_st in ("HEATING_SYNC", "PUFFER_DRAIN"):
                    desired_cron = int(saved_cfg["cron_active_minutes"])
                elif cur_st == "ARMED":
                    desired_cron = int(saved_cfg["cron_armed_minutes"])
                else:
                    desired_cron = int(saved_cfg["cron_idle_minutes"])
                st["last_action_utc"] = datetime.now(timezone.utc).isoformat()
                st["last_action_reason"] = (
                    f"Parametri autopilota aggiornati (T_min={saved_cfg['t_min_c']}°C, "
                    f"T_max={saved_cfg['t_max_c']}°C, poll={saved_cfg['cron_idle_minutes']}/"
                    f"{saved_cfg['cron_armed_minutes']}/{saved_cfg['cron_active_minutes']}m)."
                )

            if saved_cfg.get("dynamic_cron_enabled"):
                ok_c, msg_c = update_cronjob_frequency(desired_cron)
                cron_patches += 1
                if ok_c:
                    st["current_cron_interval_min"] = desired_cron
                messages.append(msg_c)

            record_api_usage(
                cron_patches=cron_patches,
                gh_runs=1 if is_gha else 0,
                event_label="cmd:autopilot_configure",
                state_dict=st,
            )
            state_already_recorded = True
            save_state(st)
            success = True
            messages.append(st["last_action_reason"])

        elif command == "cronjob_test":
            from scripts.autopilot import test_cronjob_secrets
            is_rt = bool(clean_params.get("roundtrip_2m", False))
            ok_c, msg_c = test_cronjob_secrets(verify_2m_roundtrip=is_rt)
            cron_patches += 2 if is_rt else 1
            success = ok_c
            messages.append(msg_c)

        elif command == "autopilot_activate_away":
            from scripts.autopilot import (
                load_config,
                save_config,
                load_state,
                save_state,
                update_cronjob_frequency,
                record_api_usage,
            )
            cfg = load_config()
            cfg.update(clean_params)
            if float(cfg["t_max_c"]) <= float(cfg["t_min_c"]):
                raise ValueError("t_max_c deve essere maggiore di t_min_c.")
            saved_cfg = save_config(cfg)

            # Configure hardware fail-safes immediately on both devices
            ok_s, msg_s = v_conn.set_heating_schedule_simple(
                days=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                start=str(saved_cfg["cop_window_start"]),
                end=str(saved_cfg["cop_window_end"]),
                mode="reduced",
                clear=False,
            )
            ok_d, msg_d = v_conn.set_dhw_temperature(10)
            ok_v, msg_v = v_conn.set_mode("standby")
            ok_b, msg_b = b_conn.set_thermostat_mode("hg")
            v_writes += 3
            v_reads += 4
            b_reads += 1
            b_writes += 1

            now_iso = datetime.now(timezone.utc).isoformat()
            st = load_state()
            st["state"] = "IDLE"
            st["state_since_utc"] = now_iso
            st["below_threshold_since_utc"] = None
            st["cycle_started_utc"] = None
            st["drain_started_utc"] = None
            st["cycle_is_emergency"] = False
            st["soft_curve_trim_k"] = 0
            st["soft_curve_last_trim_utc"] = None
            st["last_action_utc"] = now_iso
            st["last_action_reason"] = f"Assenza Montagna Full-Auto ATTIVATA (T_min={saved_cfg['t_min_c']}°C, Standby+Antigelo)."
            if saved_cfg.get("dynamic_cron_enabled"):
                ok_c, _ = update_cronjob_frequency(int(saved_cfg["cron_idle_minutes"]))
                cron_patches += 1
                if ok_c:
                    st["current_cron_interval_min"] = int(saved_cfg["cron_idle_minutes"])
            record_api_usage(
                v_reads=v_reads,
                v_writes=v_writes,
                b_reads=b_reads,
                b_writes=b_writes,
                cron_patches=cron_patches,
                gh_runs=1 if is_gha else 0,
                event_label="cmd:autopilot_activate_away",
                state_dict=st,
            )
            state_already_recorded = True
            save_state(st)
            success = ok_s and ok_d and ok_v and ok_b
            messages.extend([msg_s, msg_d, msg_v, msg_b, st["last_action_reason"]])

    except Exception as exc:
        logger.error("Errore esecuzione comando '%s': %s", command, exc)
        success = False
        messages.append(str(exc))

    if not state_already_recorded and any((v_reads, v_writes, b_reads, b_writes, cron_patches, is_gha)):
        try:
            from scripts.autopilot import record_api_usage
            record_api_usage(
                v_reads=v_reads,
                v_writes=v_writes,
                b_reads=b_reads,
                b_writes=b_writes,
                cron_patches=cron_patches,
                gh_runs=1 if is_gha else 0,
                event_label=f"cmd:{command}",
            )
        except Exception as usage_err:
            logger.debug("Errore conteggio API comando: %s", usage_err)

    # Wait briefly for cloud state propagation, then refresh telemetry log
    sample_logged = False
    if success and command != "cronjob_test":
        try:
            time.sleep(2.0)
            sample_logged = bool(log_sample(run_autopilot=(command == "autopilot_activate_away")))
        except Exception as log_exc:
            logger.warning("Log post-comando fallito: %s", log_exc)

    receipt = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "params": clean_params,
        "success": bool(success),
        "message": " | ".join(m for m in messages if m) or ("Comando eseguito" if success else "Errore comando"),
        "sample_logged": sample_logged,
        "api_calls": {
            "v_reads": v_reads,
            "v_writes": v_writes,
            "b_reads": b_reads,
            "b_writes": b_writes,
            "cron_patches": cron_patches,
        },
    }
    if write_receipt_file:
        _write_receipt(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Vitocal Remote Cloud Command Executor")
    parser.add_argument("--command", default=os.environ.get("CMD_ACTION", ""), help="Command name")
    parser.add_argument("--params", default=os.environ.get("CMD_PAYLOAD_JSON", "{}"), help="JSON params string")
    parser.add_argument("--dry-run", action="store_true", help="Validate only without calling cloud APIs")
    args = parser.parse_args()

    if not args.command:
        logger.error("Nessun comando specificato (--command o CMD_ACTION).")
        return 1

    try:
        params = json.loads(args.params or "{}")
    except json.JSONDecodeError as je:
        receipt = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "command": args.command,
            "params": {},
            "success": False,
            "message": f"Payload JSON non valido: {je}",
            "sample_logged": False,
        }
        if not args.dry_run:
            _write_receipt(receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 1

    receipt = execute_command(args.command, params, dry_run=args.dry_run)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
