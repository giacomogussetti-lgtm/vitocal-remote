"""
Full-Auto Mountain Custody Autopilot & Dynamic cron-job.org Scheduler.
Evaluates indoor temperature feedback, rate-of-change (derivative), optimal COP windows,
synchronized PdC + Grundfos cycles, puffer residual heat drain, and adaptive telemetry polling.
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config import Config
from api.viessmann import (
    ViessmannConnector,
    compute_inverse_setpoint_for_target_lwt,
    compute_wo1c_lwt,
)
from api.bticino import BTicinoConnector

logger = logging.getLogger("autopilot")

CONFIG_FILE = Config.DATA_DIR / "autopilot_config.json"
STATE_FILE = Config.DATA_DIR / "autopilot_state.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "mode": "away_antifrost",
    "t_min_c": 7.5,
    "t_max_c": 8.8,
    "t_emergency_c": 6.8,
    "rapid_drop_slope_c_per_h": -0.18,
    "debounce_minutes": 20,
    "cop_window_start": "11:00",
    "cop_window_end": "16:00",
    "target_lwt_delta_k": 18.0,
    "min_target_lwt_c": 25.0,
    "max_target_lwt_c": 28.5,
    "max_cycle_minutes": 300,
    "puffer_drain_minutes": 25,
    "puffer_drain_stop_temp_c": 13.8,
    "bticino_force_on_temp_c": 18.0,
    "bticino_idle_temp_c": 7.0,
    "antifrost_pdc_assist_buffer_c": 22.0,
    "dynamic_cron_enabled": True,
    "cron_idle_minutes": 15,
    "cron_armed_minutes": 5,
    "cron_active_minutes": 2,
}

DEFAULT_STATE: dict[str, Any] = {
    "state": "DISABLED",
    "state_since_utc": None,
    "below_threshold_since_utc": None,
    "cycle_started_utc": None,
    "cycle_is_emergency": False,
    "drain_started_utc": None,
    "last_eval_utc": None,
    "last_action_utc": None,
    "last_action_reason": "In attesa di attivazione dalla PWA",
    "indoor_slope_c_per_h": 0.0,
    "calculated_target_lwt_c": 25.5,
    "calculated_pdc_setpoint_c": 15,
    "current_cron_interval_min": 5,
    "defrost_detected_today": 0,
    "heating_rod_delta_s": 0,
}


def _get_rome_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Rome")
    except Exception:
        return timezone(timedelta(hours=1))


def load_config() -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg.update(loaded)
        except Exception as e:
            logger.warning("Errore lettura autopilot_config.json: %s", e)
    return cfg


def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return merged


def load_state() -> dict[str, Any]:
    st = dict(DEFAULT_STATE)
    if STATE_FILE.exists():
        try:
            loaded = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                st.update(loaded)
        except Exception as e:
            logger.warning("Errore lettura autopilot_state.json: %s", e)
    return st


def save_state(st: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_STATE)
    merged.update(st)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return merged


def _parse_iso(ts_str: Optional[str]) -> Optional[datetime]:
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _load_recent_samples(limit: int = 80) -> list[dict[str, Any]]:
    cloud_file = Config.DATA_DIR / "cloud_telemetry.jsonl"
    if not cloud_file.exists():
        return []
    try:
        lines = [ln.strip() for ln in cloud_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        out = []
        for ln in lines[-limit:]:
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
        return out
    except Exception:
        return []


def compute_indoor_derivative(samples: list[dict[str, Any]], window_hours: float = 3.0) -> float:
    """Computes least-squares linear slope (degC/h) of indoor temperature over the last window_hours."""
    pts: list[tuple[float, float]] = []
    now_ref: Optional[datetime] = None
    parsed = []
    for s in samples:
        dt = _parse_iso(s.get("timestamp_utc"))
        t_in = s.get("indoor_temp_bticino_c")
        if dt is not None and t_in is not None:
            parsed.append((dt, float(t_in)))

    if len(parsed) < 2:
        return 0.0

    parsed.sort(key=lambda x: x[0])
    now_ref = parsed[-1][0]
    cutoff = now_ref - timedelta(hours=window_hours)
    window_pts = [(dt, val) for dt, val in parsed if dt >= cutoff]
    if len(window_pts) < 2:
        window_pts = parsed[-2:]

    t0 = window_pts[0][0]
    xs = [(dt - t0).total_seconds() / 3600.0 for dt, _ in window_pts]
    ys = [val for _, val in window_pts]
    if xs[-1] - xs[0] < 0.25:
        return 0.0

    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom <= 1e-9:
        return 0.0
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
    return round(slope, 3)


def _compute_daily_diagnostics(samples: list[dict[str, Any]], rome_tz) -> tuple[int, int]:
    """Counts defrost phase samples and backup heatingRod delta seconds for the current local day."""
    if not samples:
        return 0, 0
    today_local = datetime.now(rome_tz).date()
    defrost_count = 0
    rod_vals: list[int] = []
    for s in samples:
        dt = _parse_iso(s.get("timestamp_utc"))
        if not dt or dt.astimezone(rome_tz).date() != today_local:
            continue
        phase = str(s.get("compressor_phase") or "").lower()
        if "defrost" in phase:
            defrost_count += 1
        r1 = s.get("heating_rod_level1_s")
        r2 = s.get("heating_rod_level2_s")
        if r1 is not None or r2 is not None:
            rod_vals.append(int(r1 or 0) + int(r2 or 0))
    rod_delta = max(0, rod_vals[-1] - rod_vals[0]) if len(rod_vals) >= 2 else 0
    return defrost_count, rod_delta


def _hhmm_to_minutes(hhmm: str) -> int:
    parts = hhmm.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _is_in_cop_window(local_dt: datetime, cfg: dict[str, Any]) -> bool:
    cur_min = local_dt.hour * 60 + local_dt.minute
    start_min = _hhmm_to_minutes(str(cfg.get("cop_window_start", "11:30")))
    end_min = _hhmm_to_minutes(str(cfg.get("cop_window_end", "15:30")))
    return start_min <= cur_min <= end_min


def _is_past_cop_window_end(local_dt: datetime, cfg: dict[str, Any]) -> bool:
    cur_min = local_dt.hour * 60 + local_dt.minute
    end_min = _hhmm_to_minutes(str(cfg.get("cop_window_end", "15:30")))
    return cur_min >= end_min


def update_cronjob_frequency(interval_min: int) -> tuple[bool, str]:
    """Updates cron-job.org polling interval dynamically via REST PATCH API."""
    api_key = os.environ.get("CRONJOB_API_KEY", "").strip()
    job_id = os.environ.get("CRONJOB_ID", "").strip()
    if not api_key or not job_id:
        return False, "CRONJOB_API_KEY o CRONJOB_ID non configurati nei secrets."

    step = max(1, min(30, int(interval_min)))
    minutes = [-1] if step == 1 else list(range(0, 60, step))
    url = f"https://api.cron-job.org/jobs/{job_id}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "job": {
            "schedule": {
                "timezone": "Europe/Rome",
                "expiresAt": 0,
                "hours": [-1],
                "minutes": minutes,
                "mdays": [-1],
                "months": [-1],
                "wdays": [-1],
            }
        }
    }
    try:
        resp = requests.patch(url, headers=headers, json=payload, timeout=15)
        if resp.status_code == 200:
            logger.info("Frequenza cron-job.org aggiornata dinamicamente a ogni %d minuti.", step)
            return True, f"cron-job.org aggiornato a ogni {step} min"
        return False, f"cron-job.org HTTP {resp.status_code}: {resp.text}"
    except Exception as exc:
        return False, str(exc)


def _weekday_code(local_dt: datetime) -> str:
    return ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[local_dt.weekday()]


def _apply_start_heating(
    cfg: dict[str, Any],
    pdc_setpoint: int,
    local_dt: datetime,
    is_emergency: bool,
) -> tuple[bool, str]:
    """Starts synchronized BTicino Grundfos + Viessmann PdC heating cycle with hardware fail-safes."""
    b_conn = BTicinoConnector()
    total_dur = int(cfg["max_cycle_minutes"]) + int(cfg["puffer_drain_minutes"])
    ok_b, msg_b = b_conn.set_thermostat_setpoint(
        temp=float(cfg["bticino_force_on_temp_c"]),
        mode="manual",
        duration_minutes=total_dur,
    )
    if not ok_b:
        return False, f"Errore avvio BTicino: {msg_b}"

    v_conn = ViessmannConnector()
    v_conn.connect()
    ok_r, msg_r = v_conn.set_reduced_temperature(float(pdc_setpoint))
    ok_n, msg_n = v_conn.set_normal_temperature(float(pdc_setpoint))

    # If emergency cycle outside COP window, temporarily open today's hardware schedule
    if is_emergency:
        today_code = _weekday_code(local_dt)
        v_conn.set_heating_schedule_simple(
            days=[today_code],
            start="00:00",
            end="23:50",
            mode="reduced",
            clear=False,
        )

    ok_m, msg_m = v_conn.set_mode("dhwAndHeating")
    return (ok_r and ok_n and ok_m), f"{msg_b} | {msg_r} | {msg_m}"


def _apply_stop_pdc_keep_drain(cfg: dict[str, Any]) -> tuple[bool, str]:
    """Stops Viessmann compressor (standby) while keeping Grundfos running to drain buffer."""
    v_conn = ViessmannConnector()
    v_conn.connect()
    ok_m, msg_m = v_conn.set_mode("standby")

    b_conn = BTicinoConnector()
    ok_b, msg_b = b_conn.set_thermostat_setpoint(
        temp=float(cfg["bticino_force_on_temp_c"]),
        mode="manual",
        duration_minutes=int(cfg["puffer_drain_minutes"]) + 5,
    )
    return (ok_m and ok_b), f"{msg_m} | {msg_b}"


def _apply_full_idle_shutdown(cfg: dict[str, Any]) -> tuple[bool, str]:
    """Returns BTicino to frost-guard (hg) and restores Viessmann standby + fail-safe schedule."""
    b_conn = BTicinoConnector()
    ok_b, msg_b = b_conn.set_thermostat_mode("hg")

    v_conn = ViessmannConnector()
    v_conn.connect()
    ok_m, msg_m = v_conn.set_mode("standby")
    v_conn.set_reduced_temperature(12.0)
    v_conn.set_normal_temperature(12.0)
    v_conn.set_heating_schedule_simple(
        days=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        start=str(cfg["cop_window_start"]),
        end=str(cfg["cop_window_end"]),
        mode="reduced",
        clear=False,
    )
    return (ok_b and ok_m), f"{msg_b} | {msg_m}"


def _apply_antifrost_assist_grundfos(cfg: dict[str, Any]) -> tuple[bool, str]:
    """Opens Grundfos for 30 min if hardware frost protection overheated the 200L buffer."""
    b_conn = BTicinoConnector()
    return b_conn.set_thermostat_setpoint(
        temp=float(cfg["bticino_force_on_temp_c"]),
        mode="manual",
        duration_minutes=30,
    )


def _clamp_target_lwt(t_in: float, cfg: dict[str, Any]) -> float:
    raw = float(t_in) + float(cfg["target_lwt_delta_k"])
    return round(max(float(cfg["min_target_lwt_c"]), min(float(cfg["max_target_lwt_c"]), raw)), 1)


def run_autopilot_tick(latest_sample: dict[str, Any] | Any, dry_run: bool = False) -> dict[str, Any]:
    """
    Executes one evaluation tick of the Full-Auto Mountain Custody state machine.
    Updates data/autopilot_state.json and optionally adjusts cron-job.org polling rate.
    """
    if hasattr(latest_sample, "model_dump"):
        sample = latest_sample.model_dump()
    else:
        sample = dict(latest_sample or {})

    cfg = load_config()
    st = load_state()
    rome_tz = _get_rome_tz()
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(rome_tz)
    now_iso = now_utc.isoformat()

    recent = _load_recent_samples(limit=100)
    if sample and (not recent or recent[-1].get("timestamp_utc") != sample.get("timestamp_utc")):
        recent.append(sample)

    slope_c_h = compute_indoor_derivative(recent, window_hours=3.0)
    defrost_cnt, rod_delta_s = _compute_daily_diagnostics(recent, rome_tz)

    t_in = sample.get("indoor_temp_bticino_c")
    oat = sample.get("external_temp_c") if sample.get("external_temp_c") is not None else 5.0
    curve_slope = sample.get("heating_curve_slope") if sample.get("heating_curve_slope") is not None else 0.6
    curve_shift = sample.get("heating_curve_shift") if sample.get("heating_curve_shift") is not None else 0.0
    buf_temp = sample.get("buffer_temp_c")
    gf_active = sample.get("grundfos_pump_active")
    comp_active = sample.get("compressor_active")
    frost_status = str(sample.get("frost_protection_status") or "").lower()

    st["last_eval_utc"] = now_iso
    st["indoor_slope_c_per_h"] = slope_c_h
    st["defrost_detected_today"] = defrost_cnt
    st["heating_rod_delta_s"] = rod_delta_s

    ref_tin = float(t_in) if t_in is not None else float(cfg["t_min_c"])
    if (
        cfg.get("enabled")
        and st.get("state") in ("HEATING_SYNC", "PUFFER_DRAIN")
        and st.get("calculated_target_lwt_c") is not None
        and st.get("calculated_pdc_setpoint_c") is not None
    ):
        # Lock Target LWT & Setpoint PdC once the cycle starts so Viessmann WO1C modulates undisturbed
        target_lwt = float(st["calculated_target_lwt_c"])
        pdc_setpoint = int(st["calculated_pdc_setpoint_c"])
    else:
        target_lwt = _clamp_target_lwt(ref_tin, cfg)
        pdc_setpoint = compute_inverse_setpoint_for_target_lwt(
            target_lwt_c=target_lwt,
            oat_c=float(oat),
            slope=float(curve_slope),
            shift=float(curve_shift),
        )
        st["calculated_target_lwt_c"] = target_lwt
        st["calculated_pdc_setpoint_c"] = pdc_setpoint

    if not cfg.get("enabled"):
        st["state"] = "DISABLED"
        st["below_threshold_since_utc"] = None
        return save_state(st)

    if st.get("state") == "DISABLED":
        st["state"] = "IDLE"
        st["state_since_utc"] = now_iso
        st["last_action_reason"] = "Autopilota attivato: monitoraggio standby in corso."

    if t_in is None:
        st["last_action_reason"] = "Temperatura BTicino non disponibile; nessuna transizione."
        return save_state(st)

    t_in_f = float(t_in)
    cur_state = st["state"]

    # ---------------- STATE MACHINE ----------------
    if cur_state == "IDLE":
        # Edge case: autonomous PdC frost protection heating puffer above threshold
        if (frost_status == "on" or comp_active == 1) and buf_temp is not None and float(buf_temp) >= float(cfg["antifrost_pdc_assist_buffer_c"]) and gf_active == 0:
            if not dry_run:
                ok, msg = _apply_antifrost_assist_grundfos(cfg)
                st["last_action_utc"] = now_iso
                st["last_action_reason"] = f"Assist antigelo PdC (Puffer {buf_temp}°C): Grundfos aperta 30 min ({msg})"
            else:
                st["last_action_reason"] = "[DRY-RUN] Assist antigelo PdC -> Grundfos 30 min"

        if t_in_f <= float(cfg["t_min_c"]):
            below_dt = _parse_iso(st.get("below_threshold_since_utc"))
            if below_dt is None:
                st["below_threshold_since_utc"] = now_iso
                st["last_action_reason"] = f"T interna {t_in_f:.1f}°C <= {cfg['t_min_c']}°C: inizio conferma ({cfg['debounce_minutes']} min)."
            else:
                held_min = (now_utc - below_dt).total_seconds() / 60.0
                if held_min >= float(cfg["debounce_minutes"]):
                    st["state"] = "ARMED"
                    st["state_since_utc"] = now_iso
                    st["last_action_reason"] = f"Richiesta calore confermata da {held_min:.0f} min (T={t_in_f:.1f}°C). Attesa finestra COP / emergenza."
        else:
            st["below_threshold_since_utc"] = None
            st["last_action_reason"] = f"Standby OK: T={t_in_f:.1f}°C > {cfg['t_min_c']}°C (pendenza {slope_c_h:+.2f}°C/h)."

    elif cur_state == "ARMED":
        if t_in_f >= float(cfg["t_min_c"]) + 0.3:
            st["state"] = "IDLE"
            st["state_since_utc"] = now_iso
            st["below_threshold_since_utc"] = None
            st["last_action_reason"] = f"Rientro termico spontaneo (T={t_in_f:.1f}°C): ritorno in IDLE."
        else:
            in_cop = _is_in_cop_window(now_local, cfg)
            is_emergency = t_in_f <= float(cfg["t_emergency_c"])
            projected_6h = t_in_f + (slope_c_h * 6.0)
            is_steep_drop = (
                t_in_f <= float(cfg["t_min_c"]) - 0.2
                and slope_c_h <= float(cfg["rapid_drop_slope_c_per_h"])
                and projected_6h < float(cfg["t_emergency_c"])
            )
            if in_cop or is_emergency or is_steep_drop:
                trigger_why = "Emergenza Gelo" if is_emergency else ("Crollo Rapido Notturno" if is_steep_drop else "Finestra Alto COP")
                if not dry_run:
                    ok, msg = _apply_start_heating(cfg, pdc_setpoint, now_local, is_emergency=(is_emergency or is_steep_drop))
                    if ok:
                        st["state"] = "HEATING_SYNC"
                        st["state_since_utc"] = now_iso
                        st["cycle_started_utc"] = now_iso
                        st["cycle_is_emergency"] = bool(is_emergency or is_steep_drop)
                        st["last_action_utc"] = now_iso
                        st["last_action_reason"] = f"Avvio ciclo ({trigger_why}): Target LWT {target_lwt}°C (T_set={pdc_setpoint}°C). {msg}"
                    else:
                        st["last_action_reason"] = f"Errore avvio ciclo ({trigger_why}): {msg}"
                else:
                    st["state"] = "HEATING_SYNC"
                    st["state_since_utc"] = now_iso
                    st["cycle_started_utc"] = now_iso
                    st["cycle_is_emergency"] = bool(is_emergency or is_steep_drop)
                    st["last_action_reason"] = f"[DRY-RUN] Avvio ({trigger_why}) LWT={target_lwt}°C"

    elif cur_state == "HEATING_SYNC":
        cycle_dt = _parse_iso(st.get("cycle_started_utc")) or now_utc
        elapsed_min = (now_utc - cycle_dt).total_seconds() / 60.0
        is_emerg_cycle = bool(st.get("cycle_is_emergency"))

        # Re-assert Grundfos ON if manual timer/cloud dropped prematurely
        if gf_active == 0 and elapsed_min >= 5 and not dry_run:
            b_conn = BTicinoConnector()
            rem_min = max(30, int(cfg["max_cycle_minutes"] - elapsed_min) + int(cfg["puffer_drain_minutes"]))
            b_conn.set_thermostat_setpoint(float(cfg["bticino_force_on_temp_c"]), mode="manual", duration_minutes=rem_min)

        stop_target = t_in_f >= float(cfg["t_max_c"])
        stop_max_dur = elapsed_min >= float(cfg["max_cycle_minutes"])
        stop_window = (not is_emerg_cycle) and _is_past_cop_window_end(now_local, cfg)

        if stop_target or stop_max_dur or stop_window:
            why = "Target raggiunto" if stop_target else ("Durata max raggiunta" if stop_max_dur else "Fine finestra COP")
            if not dry_run:
                ok, msg = _apply_stop_pdc_keep_drain(cfg)
                st["last_action_utc"] = now_iso
                st["last_action_reason"] = f"Stop PdC ({why}), avvio scarico puffer {cfg['puffer_drain_minutes']} min. {msg}"
            else:
                st["last_action_reason"] = f"[DRY-RUN] Stop PdC ({why}) -> PUFFER_DRAIN"
            st["state"] = "PUFFER_DRAIN"
            st["state_since_utc"] = now_iso
            st["drain_started_utc"] = now_iso

    elif cur_state == "PUFFER_DRAIN":
        drain_dt = _parse_iso(st.get("drain_started_utc")) or now_utc
        drain_min = (now_utc - drain_dt).total_seconds() / 60.0
        buf_cold = buf_temp is not None and float(buf_temp) <= float(cfg["puffer_drain_stop_temp_c"])
        if drain_min >= float(cfg["puffer_drain_minutes"]) or buf_cold:
            why = f"Puffer scarico ({buf_temp}°C)" if buf_cold else f"Timeout scarico ({drain_min:.0f} min)"
            if not dry_run:
                ok, msg = _apply_full_idle_shutdown(cfg)
                st["last_action_utc"] = now_iso
                st["last_action_reason"] = f"Ciclo completato ({why}) -> ritorno in IDLE. {msg}"
            else:
                st["last_action_reason"] = f"[DRY-RUN] Fine ciclo ({why}) -> IDLE"
            st["state"] = "IDLE"
            st["state_since_utc"] = now_iso
            st["below_threshold_since_utc"] = None
            st["cycle_started_utc"] = None
            st["drain_started_utc"] = None
            st["cycle_is_emergency"] = False

    # ---------------- DYNAMIC CRON FREQUENCY ----------------
    next_state = st["state"]
    if next_state in ("HEATING_SYNC", "PUFFER_DRAIN"):
        desired_cron = int(cfg["cron_active_minutes"])
    elif next_state == "ARMED":
        desired_cron = int(cfg["cron_armed_minutes"])
    else:
        desired_cron = int(cfg["cron_idle_minutes"])

    if cfg.get("dynamic_cron_enabled") and st.get("current_cron_interval_min") != desired_cron:
        if not dry_run:
            ok_cron, msg_cron = update_cronjob_frequency(desired_cron)
            if ok_cron:
                st["current_cron_interval_min"] = desired_cron
            logger.info("Adattamento frequenza cron (%s): %s", next_state, msg_cron)
        else:
            st["current_cron_interval_min"] = desired_cron

    return save_state(st)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    recent = _load_recent_samples(limit=10)
    if recent:
        res = run_autopilot_tick(recent[-1], dry_run=True)
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print("Nessun campione locale trovato per test.")
