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
    compute_optimal_sp_and_shift_for_target_lwt,
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
    "target_lwt_delta_k": 15.5,
    "min_target_lwt_c": 23.5,
    "max_target_lwt_c": 26.5,
    "max_cycle_minutes": 300,
    "puffer_drain_minutes": 25,
    "puffer_drain_stop_temp_c": 13.8,
    "bticino_force_on_temp_c": 18.0,
    "bticino_idle_temp_c": 7.0,
    "antifrost_pdc_assist_buffer_c": 22.0,
    "dynamic_cron_enabled": True,
    "cron_idle_minutes": 15,
    "cron_armed_minutes": 5,
    "cron_active_minutes": 1,
    "soft_start_enabled": True,
    "soft_start_step_minutes": 25,
    "soft_start_min_lwt_c": 22.8,
    "defrost_guard_enabled": True,
    "defrost_trim_threshold_count": 2,
    "defrost_guard_oat_max_c": 5.5,
    "defrost_min_safe_lwt_c": 23.0,
    "defrost_min_delta_k": 13.5,
    "inverter_min_mod_pct": 38,
    "soft_curve_tuning_enabled": True,
    "soft_curve_max_shift_delta_k": 2,
    "soft_curve_cooldown_minutes": 45,
    "anti_seize_days": 4,
    "adaptive_model_enabled": True,
    "adaptive_model_apply_targets": True,
    "weather_planner_enabled": True,
    "weather_dynamic_window_enabled": True,
    "weather_search_start": "09:00",
    "weather_search_end": "18:00",
    "weather_window_hours": 5,
    "weather_refresh_hours": 3,
    "weather_min_cop_gain": 0.08,
    "anti_short_cycle_enabled": True,
    "min_cycle_minutes": 120,
    "max_window_extension_minutes": 120,
    "predictive_prearm_enabled": True,
    "prearm_max_above_tmin_c": 0.6,
    "prearm_emergency_margin_c": 0.4,
    "weather_defer_enabled": True,
    "weather_arbitrage_cop_delta": 0.25,
    "window_lock_before_start_minutes": 90,
    "min_cycle_end_temp_c": 8.2,
    "fine_shift_tuning_enabled": True,
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
    "calculated_target_lwt_c": 23.5,
    "calculated_pdc_setpoint_c": 13,
    "target_pdc_setpoint_c": 13,
    "calculated_curve_shift": 0,
    "base_window_end_local": None,
    "soft_start_last_step_utc": None,
    "current_cron_interval_min": 5,
    "defrost_detected_today": 0,
    "cycle_defrost_episodes": 0,
    "prev_phase_was_defrost": False,
    "heating_rod_delta_s": 0,
    "soft_curve_trim_k": 0,
    "soft_curve_last_trim_utc": None,
    "last_grundfos_run_utc": None,
    "last_anti_seize_utc": None,
    "error_counter_d6": 0,
    "recent_wo1c_events": [],
    "active_window_start_local": None,
    "active_window_end_local": None,
    "weather_deferred_date": None,
    "armed_by_prearm": False,
    "committed_window_date": None,
    "committed_window_start": None,
    "committed_window_end": None,
    "window_postponed_date": None,
    "min_end_temp_extended": False,
    "min_end_ext_count": 0,
    "weather_plan": None,
    "api_usage": {
        "date_utc": None,
        "viessmann_reads": 0,
        "viessmann_writes": 0,
        "bticino_reads": 0,
        "bticino_writes": 0,
        "cronjob_patches": 0,
        "github_runs": 0,
        "recent_events": [],
    },
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


def _default_api_usage(today_str: Optional[str] = None) -> dict[str, Any]:
    return {
        "date_utc": today_str or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "viessmann_reads": 0,
        "viessmann_writes": 0,
        "bticino_reads": 0,
        "bticino_writes": 0,
        "cronjob_patches": 0,
        "github_runs": 0,
        "recent_events": [],
    }


def record_api_usage(
    v_reads: int = 0,
    v_writes: int = 0,
    b_reads: int = 0,
    b_writes: int = 0,
    cron_patches: int = 0,
    gh_runs: int = 0,
    event_label: Optional[str] = None,
    state_dict: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Tracks cumulative daily & rolling-24h API reads/writes across Viessmann,
    BTicino/Netatmo, cron-job.org and GitHub Actions inside autopilot_state.json.
    """
    own_state = state_dict is None
    st = state_dict if state_dict is not None else load_state()
    now_utc = datetime.now(timezone.utc)
    today_utc = now_utc.strftime("%Y-%m-%d")

    usage = st.get("api_usage")
    if not isinstance(usage, dict):
        usage = _default_api_usage(today_utc)
    elif usage.get("date_utc") != today_utc:
        prev_events = usage.get("recent_events") if isinstance(usage.get("recent_events"), list) else []
        usage = _default_api_usage(today_utc)
        usage["recent_events"] = prev_events

    usage["viessmann_reads"] = int(usage.get("viessmann_reads") or 0) + int(v_reads)
    usage["viessmann_writes"] = int(usage.get("viessmann_writes") or 0) + int(v_writes)
    usage["bticino_reads"] = int(usage.get("bticino_reads") or 0) + int(b_reads)
    usage["bticino_writes"] = int(usage.get("bticino_writes") or 0) + int(b_writes)
    usage["cronjob_patches"] = int(usage.get("cronjob_patches") or 0) + int(cron_patches)
    usage["github_runs"] = int(usage.get("github_runs") or 0) + int(gh_runs)

    cutoff_24h = now_utc - timedelta(hours=24)
    cleaned_events: list[dict[str, Any]] = []
    for ev in usage.get("recent_events") or []:
        if not isinstance(ev, dict):
            continue
        dt = _parse_iso(ev.get("ts"))
        if dt is not None and dt >= cutoff_24h:
            cleaned_events.append(ev)

    if any((v_reads, v_writes, b_reads, b_writes, cron_patches, gh_runs)):
        evt: dict[str, Any] = {"ts": now_utc.isoformat(), "lbl": event_label or "api"}
        if v_reads:
            evt["vr"] = int(v_reads)
        if v_writes:
            evt["vw"] = int(v_writes)
        if b_reads:
            evt["br"] = int(b_reads)
        if b_writes:
            evt["bw"] = int(b_writes)
        if cron_patches:
            evt["cp"] = int(cron_patches)
        if gh_runs:
            evt["gh"] = int(gh_runs)
        cleaned_events.append(evt)

    if len(cleaned_events) > 1600:
        cleaned_events = cleaned_events[-1600:]
    usage["recent_events"] = cleaned_events
    st["api_usage"] = usage

    if own_state:
        return save_state(st)
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
    """Counts distinct defrost episodes and backup heatingRod delta seconds for the current local day."""
    if not samples:
        return 0, 0
    today_local = datetime.now(rome_tz).date()
    defrost_episodes = 0
    prev_was_defrost = False
    rod_vals: list[int] = []
    for s in samples:
        dt = _parse_iso(s.get("timestamp_utc"))
        if not dt or dt.astimezone(rome_tz).date() != today_local:
            continue
        phase = str(s.get("compressor_phase") or "").lower()
        is_def = "defrost" in phase
        if is_def and not prev_was_defrost:
            defrost_episodes += 1
        prev_was_defrost = is_def
        r1 = s.get("heating_rod_level1_s")
        r2 = s.get("heating_rod_level2_s")
        if r1 is not None or r2 is not None:
            rod_vals.append(int(r1 or 0) + int(r2 or 0))
    rod_delta = max(0, rod_vals[-1] - rod_vals[0]) if len(rod_vals) >= 2 else 0
    return defrost_episodes, rod_delta


def _decode_wo1c_logbook(entries: Any) -> list[dict[str, Any]]:
    """
    Translates Vitotronic WO1C internal actor state transitions into readable labels.
    Note: ViCare cloud maps numeric internal actor transition IDs to misleading inverter enum strings
    even on normal shutdowns/defrosts; hardware faults are tracked via error_counter_d6.
    """
    if not isinstance(entries, list):
        return []
    actor_map = {
        "VERDICHTER1": "Compressore",
        "SEK_PUMPE1": "Circolatore P1",
        "KAELTEKR_UMKEHR": "Valvola 4-Vie Defrost",
        "HEIZSTAB1": "Resistenza S1",
        "HEIZSTAB2": "Resistenza S2",
    }
    out: list[dict[str, Any]] = []
    for item in entries[:6]:
        if not isinstance(item, dict):
            continue
        actor_raw = str(item.get("actor") or "")
        status_val = item.get("status")
        actor_label = actor_map.get(actor_raw, actor_raw or "WO1C")
        if actor_raw == "KAELTEKR_UMKEHR":
            desc = "Inversione Defrost ON" if status_val else "Fine Defrost -> Riscald."
        elif actor_raw == "SEK_PUMPE1":
            desc = f"Pompa P1 -> {status_val}%" if status_val is not None else "Cambio stato P1"
        elif actor_raw == "VERDICHTER1":
            desc = "Compressore ON" if status_val else "Arresto / Pausa Compressore"
        else:
            desc = f"Stato={status_val}"
        out.append({
            "ts": str(item.get("timestamp") or ""),
            "actor": actor_label,
            "desc": desc,
            "info_s": item.get("additionalInfo"),
        })
    return out


def _hhmm_to_minutes(hhmm: str) -> int:
    parts = hhmm.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _round_hhmm_10m(hhmm: str, round_up: bool = False) -> str:
    m = _hhmm_to_minutes(hhmm)
    m = ((m + 9) // 10) * 10 if round_up else (m // 10) * 10
    m = max(0, min(23 * 60 + 50, m))
    return f"{m // 60:02d}:{m % 60:02d}"


def _is_in_cop_window(
    local_dt: datetime,
    cfg: dict[str, Any],
    start_override: Optional[str] = None,
    end_override: Optional[str] = None,
) -> bool:
    cur_min = local_dt.hour * 60 + local_dt.minute
    start_min = _hhmm_to_minutes(str(start_override or cfg.get("cop_window_start", "11:00")))
    end_min = _hhmm_to_minutes(str(end_override or cfg.get("cop_window_end", "16:00")))
    return start_min <= cur_min <= end_min


def _is_past_cop_window_end(
    local_dt: datetime,
    cfg: dict[str, Any],
    end_override: Optional[str] = None,
) -> bool:
    cur_min = local_dt.hour * 60 + local_dt.minute
    end_min = _hhmm_to_minutes(str(end_override or cfg.get("cop_window_end", "16:00")))
    return cur_min >= end_min


def update_cronjob_frequency(interval_min: int) -> tuple[bool, str]:
    """Updates cron-job.org polling interval dynamically via REST PATCH API."""
    api_key = os.environ.get("CRONJOB_API_KEY", "").strip()
    job_id = os.environ.get("CRONJOB_ID", "").strip()
    if not api_key or not job_id:
        return False, "CRONJOB_API_KEY o CRONJOB_ID non configurati nei secrets."

    step = max(1, min(60, int(interval_min)))
    if step == 1:
        minutes = [-1]
    elif step >= 60:
        minutes = [0]
    else:
        minutes = list(range(0, 60, step))
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


def test_cronjob_secrets(verify_2m_roundtrip: bool = False) -> tuple[bool, str]:
    """
    Verifies CRONJOB_API_KEY and CRONJOB_ID against cron-job.org REST API.
    When verify_2m_roundtrip=True, writes 2-minute intervals ([0,2,4...58]),
    reads back to confirm all 30 slots, and ALWAYS restores the original
    schedule inside a finally block.
    """
    api_key = os.environ.get("CRONJOB_API_KEY", "").strip()
    job_id = os.environ.get("CRONJOB_ID", "").strip()
    if not api_key and not job_id:
        return False, "Mancano entrambi i GitHub Secrets: CRONJOB_API_KEY e CRONJOB_ID."
    if not api_key:
        return False, "Manca il GitHub Secret CRONJOB_API_KEY (o è vuoto)."
    if not job_id:
        return False, "Manca il GitHub Secret CRONJOB_ID (o è vuoto)."
    if not job_id.isdigit():
        return False, f"CRONJOB_ID non è numerico (lunghezza {len(job_id)}): inserire solo le cifre dell'ID job."

    url = f"https://api.cron-job.org/jobs/{job_id}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    def _extract_details(payload: dict[str, Any]) -> dict[str, Any]:
        det = payload.get("jobDetails", {}) if isinstance(payload, dict) else {}
        if isinstance(det, list):
            det = det[0] if det else {}
        return det if isinstance(det, dict) else {}

    def _fmt_mins(mins: list[Any]) -> str:
        return ",".join(str(m) for m in mins[:6]) + ("..." if len(mins) > 6 else "")

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 401:
            return False, "CRONJOB_API_KEY non valida (HTTP 401 Unauthorized)."
        if resp.status_code == 404:
            return False, f"CRONJOB_ID #{job_id} non trovato su questo account (HTTP 404)."
        if resp.status_code != 200:
            return False, f"Errore cron-job.org HTTP {resp.status_code}: {resp.text[:180]}"

        data = resp.json() if resp.text else {}
        details = _extract_details(data)
        enabled = details.get("enabled")
        orig_schedule = dict(details.get("schedule") or {})
        mins = list(orig_schedule.get("minutes") or [])
        mins_txt = _fmt_mins(mins)
        status_txt = "ATTIVO" if enabled else "DISABILITATO"

        if not verify_2m_roundtrip:
            return True, f"Secrets cron-job.org OK! Job #{job_id} ({status_txt}), minuti=[{mins_txt}]"

        restore_schedule = {
            "timezone": orig_schedule.get("timezone", "Europe/Rome"),
            "expiresAt": orig_schedule.get("expiresAt", 0),
            "hours": orig_schedule.get("hours", [-1]),
            "minutes": mins if mins else [0, 15, 30, 45],
            "mdays": orig_schedule.get("mdays", [-1]),
            "months": orig_schedule.get("months", [-1]),
            "wdays": orig_schedule.get("wdays", [-1]),
        }
        test_schedule = dict(restore_schedule)
        test_schedule["minutes"] = list(range(0, 60, 2))

        patched_ok = False
        readback_err: Optional[str] = None
        restore_ok = False
        try:
            p_resp = requests.patch(url, headers=headers, json={"job": {"schedule": test_schedule}}, timeout=15)
            if p_resp.status_code != 200:
                return False, f"Test 2m fallito su PATCH (HTTP {p_resp.status_code}): {p_resp.text[:160]}"
            patched_ok = True

            v_resp = requests.get(url, headers=headers, timeout=15)
            if v_resp.status_code != 200:
                readback_err = f"Read-back GET fallito (HTTP {v_resp.status_code})"
            else:
                v_data = v_resp.json() if v_resp.text else {}
                v_mins = list((_extract_details(v_data).get("schedule") or {}).get("minutes") or [])
                if len(v_mins) != 30 or v_mins[:4] != [0, 2, 4, 6]:
                    readback_err = f"Read-back 2m inatteso: len={len(v_mins)}, primi={v_mins[:6]}"
        finally:
            if patched_ok:
                try:
                    r_resp = requests.patch(url, headers=headers, json={"job": {"schedule": restore_schedule}}, timeout=15)
                    restore_ok = (r_resp.status_code == 200)
                except Exception as rest_exc:
                    logger.error("Errore ripristino schedule originale cron-job.org: %s", rest_exc)

        if readback_err:
            return False, f"{readback_err} (ripristino=[{mins_txt}] {'OK' if restore_ok else 'FALLITO'})"
        if not restore_ok:
            return False, "Scrittura/verifica 2m riuscita, ma ripristino schedule originale fallito!"
        return True, (
            f"Test cambio timer 2m OK! Scritto [0,2,4...58] (30 slot/h), "
            f"letto e verificato OK, ripristinato schedule originale ([{mins_txt}])."
        )
    except Exception as exc:
        return False, f"Errore connessione cron-job.org: {exc}"


def _weekday_code(local_dt: datetime) -> str:
    return ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[local_dt.weekday()]


def _apply_start_heating(
    cfg: dict[str, Any],
    pdc_setpoint: int,
    local_dt: datetime,
    is_emergency: bool,
    active_start_hhmm: Optional[str] = None,
    active_end_hhmm: Optional[str] = None,
    target_shift: Optional[int] = None,
    cur_slope: float = 0.6,
    cur_shift: float = 0.0,
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
    shift_msg = ""
    if target_shift is not None and int(target_shift) != int(round(float(cur_shift))):
        _, shift_msg = v_conn.set_heating_curve(slope=round(float(cur_slope), 1), shift=int(target_shift))
        shift_msg = f" | {shift_msg}"
    ok_r, msg_r = v_conn.set_reduced_temperature(float(pdc_setpoint))
    ok_n, msg_n = v_conn.set_normal_temperature(float(pdc_setpoint))

    # Align WO1C hardware schedule when emergency or dynamic/extended window differs from static window
    today_code = _weekday_code(local_dt)
    if is_emergency:
        v_conn.set_heating_schedule_simple(
            days=[today_code],
            start="00:00",
            end="23:50",
            mode="reduced",
            clear=False,
        )
    elif active_start_hhmm and active_end_hhmm and (
        active_start_hhmm != str(cfg.get("cop_window_start", "11:00"))
        or active_end_hhmm != str(cfg.get("cop_window_end", "16:00"))
    ):
        s10 = _round_hhmm_10m(active_start_hhmm, round_up=False)
        # Add +10 min buffer on WO1C hardware schedule end to absorb ~3-5 min WO1C internal clock drift
        # (Autopilot still issues explicit set_mode('standby') at exact end of cycle).
        end_buf_min = min(23 * 60 + 50, _hhmm_to_minutes(active_end_hhmm) + 10)
        e10 = _round_hhmm_10m(f"{end_buf_min // 60:02d}:{end_buf_min % 60:02d}", round_up=True)
        if e10 > s10:
            v_conn.set_heating_schedule_simple(
                days=[today_code],
                start=s10,
                end=e10,
                mode="reduced",
                clear=False,
            )

    ok_m, msg_m = v_conn.set_mode("dhwAndHeating")
    return (ok_r and ok_n and ok_m), f"{msg_b} | {msg_r}{shift_msg} | {msg_m}"


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


def _apply_full_idle_shutdown(cfg: dict[str, Any], cur_slope: float = 0.6, cur_shift: float = 0.0) -> tuple[bool, str]:
    """Returns BTicino to frost-guard (hg) and restores Viessmann standby + fail-safe schedule & shift=0."""
    b_conn = BTicinoConnector()
    ok_b, msg_b = b_conn.set_thermostat_mode("hg")

    v_conn = ViessmannConnector()
    v_conn.connect()
    ok_m, msg_m = v_conn.set_mode("standby")
    if int(round(float(cur_shift))) != 0:
        v_conn.set_heating_curve(slope=round(float(cur_slope), 1), shift=0)
    v_conn.set_reduced_temperature(12.0)
    v_conn.set_normal_temperature(12.0)
    # Add +10 min buffer on static fail-safe schedule end to absorb WO1C ~3.5m internal clock drift
    end_idle_min = min(23 * 60 + 50, _hhmm_to_minutes(str(cfg.get("cop_window_end") or "16:00")) + 10)
    end_idle_hhmm = _round_hhmm_10m(f"{end_idle_min // 60:02d}:{end_idle_min % 60:02d}", round_up=True)
    v_conn.set_heating_schedule_simple(
        days=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        start=str(cfg["cop_window_start"]),
        end=end_idle_hhmm,
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


def _apply_anti_seize_grundfos(cfg: dict[str, Any], duration_minutes: int = 15) -> tuple[bool, str]:
    """Briefly spins Grundfos pump alone (PdC stays in standby) to prevent rotor seizure during long idle spells."""
    b_conn = BTicinoConnector()
    return b_conn.set_thermostat_setpoint(
        temp=float(cfg["bticino_force_on_temp_c"]),
        mode="manual",
        duration_minutes=duration_minutes,
    )


def _clamp_target_lwt(t_in: float, cfg: dict[str, Any], oat: float = 4.0, model: Optional[dict[str, Any]] = None) -> float:
    """
    Computes target buffer LWT. When adaptive_model_apply_targets is enabled (and model is available),
    uses the self-converging physical model instead of a fixed hardcoded T_in + delta_k offset,
    always bounded by user [min_target_lwt_c, max_target_lwt_c].
    """
    if cfg.get("adaptive_model_apply_targets") and model:
        try:
            from scripts.thermal_model import recommend_operating_targets
            rec = recommend_operating_targets(model, float(t_in), float(oat), cfg)
            return float(rec["recommended_target_lwt_c"])
        except Exception:
            pass
    raw = float(t_in) + float(cfg["target_lwt_delta_k"])
    return round(max(float(cfg["min_target_lwt_c"]), min(float(cfg["max_target_lwt_c"]), raw)), 1)


def run_autopilot_tick(
    latest_sample: dict[str, Any] | Any,
    dry_run: bool = False,
    extra_diagnostics: Optional[dict[str, Any]] = None,
    now_utc_override: Optional[datetime] = None,
    weather_cache_file: Optional[Path] = None,
) -> dict[str, Any]:
    """
    Executes one evaluation tick of the Full-Auto Mountain Custody v2 state machine.
    Includes Weather-Aware dynamic COP window, Anti-Short-Cycle guard, Predictive Pre-Arming,
    Soft-Start anti-overshoot ramp, Defrost-Aware derating, smart Grundfos anti-seize,
    and adaptive telemetry polling.
    """
    if hasattr(latest_sample, "model_dump"):
        sample = latest_sample.model_dump()
    else:
        sample = dict(latest_sample or {})

    cfg = load_config()
    st = load_state()
    rome_tz = _get_rome_tz()
    now_utc = now_utc_override.astimezone(timezone.utc) if now_utc_override else datetime.now(timezone.utc)
    now_local = now_utc.astimezone(rome_tz)
    now_iso = now_utc.isoformat()

    recent = _load_recent_samples(limit=250)
    if sample and (not recent or recent[-1].get("timestamp_utc") != sample.get("timestamp_utc")):
        recent.append(sample)

    slope_c_h = compute_indoor_derivative(recent, window_hours=3.0)
    defrost_cnt, rod_delta_s = _compute_daily_diagnostics(recent, rome_tz)

    t_in = sample.get("indoor_temp_bticino_c")
    oat = sample.get("external_temp_c") if sample.get("external_temp_c") is not None else 5.0
    curve_slope = sample.get("heating_curve_slope") if sample.get("heating_curve_slope") is not None else 0.6
    curve_shift = sample.get("heating_curve_shift") if sample.get("heating_curve_shift") is not None else 0.0
    buf_temp = sample.get("buffer_temp_c")
    ewt_temp = sample.get("pdc_return_temp_c")
    gf_active = sample.get("grundfos_pump_active")
    comp_active = sample.get("compressor_active")
    comp_mod = sample.get("compressor_modulation_percent")
    suction_temp = sample.get("suction_gas_temp_c")
    comp_phase = str(sample.get("compressor_phase") or "").lower()
    frost_status = str(sample.get("frost_protection_status") or "").lower()

    st["last_eval_utc"] = now_iso
    st["indoor_slope_c_per_h"] = slope_c_h
    st["defrost_detected_today"] = defrost_cnt
    st["heating_rod_delta_s"] = rod_delta_s
    if gf_active == 1:
        st["last_grundfos_run_utc"] = now_iso
    if sample.get("error_counter_d6") is not None:
        st["error_counter_d6"] = int(sample.get("error_counter_d6") or 0)
    if isinstance(extra_diagnostics, dict) and extra_diagnostics.get("logbook_entries"):
        st["recent_wo1c_events"] = _decode_wo1c_logbook(extra_diagnostics.get("logbook_entries"))

    # Load (or hydrate) self-converging physical model summary for target calculation & UI visibility
    tm_model: Optional[dict[str, Any]] = None
    if cfg.get("adaptive_model_enabled", True):
        try:
            from scripts.thermal_model import load_thermal_model, recommend_operating_targets
            tm_model = load_thermal_model()
            rec_now = recommend_operating_targets(tm_model, float(t_in) if t_in is not None else float(cfg["t_min_c"]), float(oat), cfg)
            st["thermal_model"] = {
                "cycles_observed": tm_model.get("cycles_observed", 0),
                "confidence_pct": tm_model.get("confidence_pct", 15),
                "k_rad_kw_per_k": tm_model.get("k_rad_kw_per_k"),
                "inverter_min_mod_pct": tm_model.get("inverter_min_mod_pct"),
                "defrost_lwt_drop_p90_k": tm_model.get("defrost_lwt_drop_p90_k"),
                "ua_building_c_24h_per_k": tm_model.get("ua_building_c_24h_per_k"),
                "recommended_target_lwt_c": rec_now.get("recommended_target_lwt_c"),
                "pred_autonomy_hours": rec_now.get("pred_autonomy_hours"),
                "updated_utc": tm_model.get("updated_utc"),
            }
        except Exception:
            tm_model = None

    ref_tin = float(t_in) if t_in is not None else float(cfg["t_min_c"])
    if (
        cfg.get("enabled")
        and st.get("state") in ("HEATING_SYNC", "PUFFER_DRAIN")
        and st.get("calculated_target_lwt_c") is not None
        and st.get("calculated_pdc_setpoint_c") is not None
    ):
        # Keep active setpoint locked during HEATING_SYNC / PUFFER_DRAIN except controlled Soft-Start / Defrost Guard steps
        target_lwt = float(st["calculated_target_lwt_c"])
        pdc_setpoint = int(st["calculated_pdc_setpoint_c"])
        regime_sp = int(st.get("target_pdc_setpoint_c") or pdc_setpoint)
        target_shift = int(st.get("calculated_curve_shift") if st.get("calculated_curve_shift") is not None else round(float(curve_shift)))
    else:
        target_lwt = _clamp_target_lwt(ref_tin, cfg, oat=float(oat), model=tm_model)
        min_lwt_floor = float(cfg.get("min_target_lwt_c") or 23.5)
        if cfg.get("fine_shift_tuning_enabled", True):
            regime_sp, target_shift, actual_regime_lwt = compute_optimal_sp_and_shift_for_target_lwt(
                target_lwt_c=target_lwt,
                oat_c=float(oat),
                slope=float(curve_slope),
                base_shift=0,
                allowed_shifts=(-1, 0, 1),
                min_lwt_floor_c=min_lwt_floor,
            )
        else:
            target_shift = int(round(float(curve_shift)))
            regime_sp = compute_inverse_setpoint_for_target_lwt(
                target_lwt_c=target_lwt,
                oat_c=float(oat),
                slope=float(curve_slope),
                shift=float(target_shift),
                min_lwt_floor_c=min_lwt_floor,
            )
            actual_regime_lwt = compute_wo1c_lwt(float(oat), float(regime_sp), float(curve_slope), float(target_shift))
        target_lwt = round(actual_regime_lwt, 1)
        pdc_setpoint = regime_sp
        st["calculated_target_lwt_c"] = target_lwt
        st["calculated_pdc_setpoint_c"] = pdc_setpoint
        st["target_pdc_setpoint_c"] = regime_sp
        st["calculated_curve_shift"] = target_shift

    # Evaluate Weather-Aware Dynamic Window, Anti-Short-Cycle & Predictive Plan (fail-safe wrapped)
    weather_plan: dict[str, Any] = {
        "available": False,
        "effective_window_start": str(cfg.get("cop_window_start") or "11:00"),
        "effective_window_end": str(cfg.get("cop_window_end") or "16:00"),
        "in_window_now": _is_in_cop_window(now_local, cfg),
        "short_cycle_action": "normal",
        "prearm_recommended": False,
        "defer_recommended": False,
        "decision_summary": f"Finestra statica {cfg.get('cop_window_start', '11:00')}–{cfg.get('cop_window_end', '16:00')}",
        "decision_trace": [],
    }
    try:
        from scripts.weather_planner import evaluate_weather_plan
        eval_state = st.get("state") or "IDLE"
        weather_plan = evaluate_weather_plan(
            now_local=now_local,
            t_in_c=float(t_in) if t_in is not None else None,
            current_oat_c=float(oat),
            cur_state=eval_state,
            cfg=cfg,
            thermal_model=tm_model,
            recent_samples=recent,
            st=st,
            dry_run=dry_run,
            cache_file=weather_cache_file,
        )
        st["weather_plan"] = weather_plan
        today_str_loc = now_local.strftime("%Y-%m-%d")
        # Only latch daily committed_window from 05:00 onward (or during active heating) so 00:00-04:59
        # overnight forecasts never prematurely lock in a pessimistic early start for the entire day.
        if now_local.hour >= 5 or st.get("state") == "HEATING_SYNC":
            st["committed_window_date"] = today_str_loc
            st["committed_window_start"] = weather_plan.get("committed_window_start") or weather_plan.get("effective_window_start")
            st["committed_window_end"] = weather_plan.get("committed_window_end") or weather_plan.get("effective_window_end")
        if weather_plan.get("was_postponed_now"):
            st["window_postponed_date"] = today_str_loc
    except Exception as wp_err:
        logger.warning("Valutazione weather_planner fallita (fallback statico): %s", wp_err)

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
    eff_win_start = str(weather_plan.get("effective_window_start") or cfg.get("cop_window_start") or "11:00")
    eff_win_end = str(weather_plan.get("effective_window_end") or cfg.get("cop_window_end") or "16:00")

    # ---------------- STATE MACHINE ----------------
    if cur_state == "IDLE":
        # Edge case 1: autonomous PdC frost protection heating puffer above threshold
        if (frost_status == "on" or comp_active == 1) and buf_temp is not None and float(buf_temp) >= float(cfg["antifrost_pdc_assist_buffer_c"]) and gf_active == 0:
            if not dry_run:
                ok, msg = _apply_antifrost_assist_grundfos(cfg)
                record_api_usage(b_reads=1, b_writes=1, event_label="ap_antifrost_assist", state_dict=st)
                st["last_action_utc"] = now_iso
                st["last_action_reason"] = f"Assist antigelo PdC (Puffer {buf_temp}°C): Grundfos aperta 30 min ({msg})"
            else:
                st["last_action_reason"] = "[DRY-RUN] Assist antigelo PdC -> Grundfos 30 min"

        # Edge case 2: Smart Grundfos Anti-Seize during prolonged mild idle periods (replaces daily 08:00 BTicino schedule)
        anti_seize_days = int(cfg.get("anti_seize_days") or 0)
        if anti_seize_days > 0 and gf_active == 0 and 12 <= now_local.hour <= 12 and now_local.minute < 45:
            last_gf_dt = _parse_iso(st.get("last_grundfos_run_utc")) or _parse_iso(st.get("state_since_utc"))
            last_as_dt = _parse_iso(st.get("last_anti_seize_utc"))
            days_idle = ((now_utc - last_gf_dt).total_seconds() / 86400.0) if last_gf_dt else 0.0
            as_cooldown_ok = last_as_dt is None or ((now_utc - last_as_dt).total_seconds() / 3600.0) >= 24.0
            if days_idle >= anti_seize_days and as_cooldown_ok:
                if not dry_run:
                    ok_as, msg_as = _apply_anti_seize_grundfos(cfg, duration_minutes=15)
                    record_api_usage(b_reads=1, b_writes=1, event_label="ap_anti_seize", state_dict=st)
                    if ok_as:
                        st["last_anti_seize_utc"] = now_iso
                        st["last_grundfos_run_utc"] = now_iso
                        st["last_action_utc"] = now_iso
                        st["last_action_reason"] = f"Anti-grippaggio Grundfos (ferma da {days_idle:.1f} gg): avvio 15 min a PdC spenta."
                else:
                    st["last_action_reason"] = f"[DRY-RUN] Anti-grippaggio Grundfos ({days_idle:.1f} gg idle)"

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
                    st["armed_by_prearm"] = False
                    st["last_action_reason"] = f"Richiesta calore confermata da {held_min:.0f} min (T={t_in_f:.1f}°C). Attesa finestra COP ({eff_win_start}–{eff_win_end}) / emergenza."
        elif cfg.get("predictive_prearm_enabled", True) and weather_plan.get("prearm_recommended"):
            st["state"] = "ARMED"
            st["state_since_utc"] = now_iso
            st["below_threshold_since_utc"] = now_iso
            st["armed_by_prearm"] = True
            st["last_action_utc"] = now_iso
            st["last_action_reason"] = weather_plan.get("prearm_reason") or weather_plan.get("decision_summary")
        else:
            st["below_threshold_since_utc"] = None
            st["armed_by_prearm"] = False
            st["last_action_reason"] = f"Standby OK: T={t_in_f:.1f}°C > {cfg['t_min_c']}°C (pendenza {slope_c_h:+.2f}°C/h). {weather_plan.get('decision_summary', '')}".strip()

    elif cur_state == "ARMED":
        prearm_hold = bool(
            cfg.get("predictive_prearm_enabled", True)
            and (weather_plan.get("prearm_recommended") or st.get("armed_by_prearm"))
            and weather_plan.get("in_window_now")
            and t_in_f <= float(cfg["t_min_c"]) + float(cfg.get("prearm_max_above_tmin_c") or 0.6) + 0.15
        )
        if t_in_f >= float(cfg["t_min_c"]) + 0.3 and not prearm_hold:
            st["state"] = "IDLE"
            st["state_since_utc"] = now_iso
            st["below_threshold_since_utc"] = None
            st["armed_by_prearm"] = False
            st["last_action_reason"] = f"Rientro termico spontaneo (T={t_in_f:.1f}°C): ritorno in IDLE."
        else:
            in_cop = _is_in_cop_window(now_local, cfg, start_override=eff_win_start, end_override=eff_win_end)
            is_emergency = t_in_f <= float(cfg["t_emergency_c"])
            projected_6h = t_in_f + (slope_c_h * 6.0)
            is_steep_drop = (
                t_in_f <= float(cfg["t_min_c"]) - 0.2
                and slope_c_h <= float(cfg["rapid_drop_slope_c_per_h"])
                and projected_6h < float(cfg["t_emergency_c"])
            )

            short_cycle_action = str(weather_plan.get("short_cycle_action") or "normal")
            should_defer_sc = (not is_emergency and not is_steep_drop and in_cop and short_cycle_action == "defer_short_cycle")
            should_defer_wx = (not is_emergency and not is_steep_drop and in_cop and not should_defer_sc and bool(weather_plan.get("defer_recommended")))

            if should_defer_sc:
                st["last_action_reason"] = weather_plan.get("decision_summary") or "Rinvio anti-micro-ciclo a domani."
            elif should_defer_wx:
                st["weather_deferred_date"] = now_local.strftime("%Y-%m-%d")
                st["last_action_utc"] = now_iso
                st["last_action_reason"] = weather_plan.get("defer_reason") or weather_plan.get("decision_summary")
            elif in_cop or is_emergency or is_steep_drop:
                trigger_why = "Emergenza Gelo" if is_emergency else ("Crollo Rapido Notturno" if is_steep_drop else ("Pre-Armamento Predittivo" if st.get("armed_by_prearm") else "Finestra Alto COP"))
                run_win_start = eff_win_start
                run_win_end = eff_win_end
                if (not is_emergency and not is_steep_drop) and short_cycle_action == "extend_short_cycle" and weather_plan.get("extended_end_hhmm"):
                    run_win_end = str(weather_plan["extended_end_hhmm"])
                    trigger_why = f"{trigger_why} + Estensione Anti-Short-Cycle ({run_win_end})"

                # Soft-Start Anti-Overshoot:
                # Counter-audit verified on 21/11, 24/11 & 26/11 logs that lowering SP on cold starts does NOT
                # reduce the 0-20m PI ramp (always 81-88%), and in cold/humid frosting weather (frost_risk MEDIO/ALTO)
                # holding LWT lower before Defrost #1 (~min 35-40) reduces BPHE reserve. Therefore skip Soft-Start
                # down-step when frosting risk is MEDIO/ALTO and regime_sp <= 14.
                start_sp = regime_sp
                start_lwt = target_lwt
                today_frost_risk = str(((weather_plan.get("today_window") or {}).get("frost_risk")) or "").upper()
                oat_frost_lim = float(cfg.get("defrost_guard_oat_max_c") or 5.5)
                skip_ss_for_bphe = (float(oat) <= oat_frost_lim and today_frost_risk in ("MEDIO", "ALTO") and regime_sp <= 14)
                if (
                    cfg.get("soft_start_enabled", True)
                    and not skip_ss_for_bphe
                    and buf_temp is not None
                    and float(buf_temp) < target_lwt - 5.0
                ):
                    ss_floor = float(cfg.get("soft_start_min_lwt_c") or 22.8)
                    soft_lwt_cap = max(ss_floor, min(target_lwt, float(buf_temp) + 10.5))
                    soft_sp = compute_inverse_setpoint_for_target_lwt(
                        target_lwt_c=soft_lwt_cap,
                        oat_c=float(oat),
                        slope=float(curve_slope),
                        shift=float(target_shift),
                        min_lwt_floor_c=ss_floor,
                    )
                    max_drop = 1 if (regime_sp <= 13 and float(oat) <= oat_frost_lim) else 2
                    start_sp = max(soft_sp, max(regime_sp - max_drop, 12))
                    start_sp = min(regime_sp, start_sp)
                    start_lwt = compute_wo1c_lwt(float(oat), float(start_sp), float(curve_slope), float(target_shift))

                if not dry_run:
                    ok, msg = _apply_start_heating(
                        cfg,
                        start_sp,
                        now_local,
                        is_emergency=(is_emergency or is_steep_drop),
                        active_start_hhmm=run_win_start,
                        active_end_hhmm=run_win_end,
                        target_shift=target_shift,
                        cur_slope=float(curve_slope),
                        cur_shift=float(curve_shift),
                    )
                    emerg_flag = bool(is_emergency or is_steep_drop)
                    sched_changed = emerg_flag or (
                        run_win_start != str(cfg.get("cop_window_start", "11:00"))
                        or run_win_end != str(cfg.get("cop_window_end", "16:00"))
                    )
                    shift_changed = int(target_shift) != int(round(float(curve_shift)))
                    record_api_usage(
                        v_reads=(6 if sched_changed else 4) + (2 if shift_changed else 0),
                        v_writes=(4 if sched_changed else 3) + (1 if shift_changed else 0),
                        b_reads=1,
                        b_writes=1,
                        event_label="ap_start_heating",
                        state_dict=st,
                    )
                    if ok:
                        st["state"] = "HEATING_SYNC"
                        st["state_since_utc"] = now_iso
                        st["cycle_started_utc"] = now_iso
                        st["cycle_is_emergency"] = emerg_flag
                        st["armed_by_prearm"] = False
                        st["active_window_start_local"] = run_win_start
                        st["active_window_end_local"] = run_win_end
                        st["base_window_end_local"] = run_win_end
                        st["weather_deferred_date"] = None
                        st["min_end_temp_extended"] = False
                        st["min_end_ext_count"] = 0
                        st["target_pdc_setpoint_c"] = regime_sp
                        st["calculated_pdc_setpoint_c"] = start_sp
                        st["calculated_target_lwt_c"] = start_lwt
                        st["calculated_curve_shift"] = target_shift
                        st["soft_start_last_step_utc"] = now_iso
                        st["cycle_defrost_episodes"] = 0
                        st["prev_phase_was_defrost"] = False
                        st["soft_curve_trim_k"] = 0
                        st["soft_curve_last_trim_utc"] = None
                        st["last_action_utc"] = now_iso
                        soft_note = f" (Soft-Start da {start_sp}°C -> regime {regime_sp}°C)" if start_sp < regime_sp else ""
                        sh_note = f", Shift={target_shift:+d}" if target_shift != 0 else ""
                        st["last_action_reason"] = f"Avvio ciclo ({trigger_why}): Target Acqua {start_lwt}°C (SP={start_sp}°C{sh_note}){soft_note}. {msg}"
                    else:
                        st["last_action_reason"] = f"Errore avvio ciclo ({trigger_why}): {msg}"
                else:
                    st["state"] = "HEATING_SYNC"
                    st["state_since_utc"] = now_iso
                    st["cycle_started_utc"] = now_iso
                    st["cycle_is_emergency"] = bool(is_emergency or is_steep_drop)
                    st["armed_by_prearm"] = False
                    st["active_window_start_local"] = run_win_start
                    st["active_window_end_local"] = run_win_end
                    st["base_window_end_local"] = run_win_end
                    st["weather_deferred_date"] = None
                    st["min_end_temp_extended"] = False
                    st["min_end_ext_count"] = 0
                    st["target_pdc_setpoint_c"] = regime_sp
                    st["calculated_pdc_setpoint_c"] = start_sp
                    st["calculated_target_lwt_c"] = start_lwt
                    st["calculated_curve_shift"] = target_shift
                    st["soft_start_last_step_utc"] = now_iso
                    st["cycle_defrost_episodes"] = 0
                    st["prev_phase_was_defrost"] = False
                    st["soft_curve_trim_k"] = 0
                    sh_note = f",Sh={target_shift:+d}" if target_shift != 0 else ""
                    st["last_action_reason"] = f"[DRY-RUN] Avvio ({trigger_why}) LWT={start_lwt}°C (SP={start_sp}->{regime_sp}°C{sh_note})"

    elif cur_state == "HEATING_SYNC":
        cycle_dt = _parse_iso(st.get("cycle_started_utc")) or now_utc
        elapsed_min = (now_utc - cycle_dt).total_seconds() / 60.0
        is_emerg_cycle = bool(st.get("cycle_is_emergency"))

        # Track distinct defrost episodes inside this cycle
        is_defrost_now = "defrost" in comp_phase
        if is_defrost_now and not bool(st.get("prev_phase_was_defrost")):
            st["cycle_defrost_episodes"] = int(st.get("cycle_defrost_episodes") or 0) + 1
        st["prev_phase_was_defrost"] = is_defrost_now

        # Re-assert Grundfos ON only if truly dropped (and setpoint actually fell below room + 2 C)
        bt_sp_live = sample.get("indoor_setpoint_bticino_c")
        if gf_active == 0 and elapsed_min >= 5 and (bt_sp_live is None or float(bt_sp_live) < t_in_f + 2.0) and not dry_run:
            b_conn = BTicinoConnector()
            rem_min = max(30, int(cfg["max_cycle_minutes"] - elapsed_min) + int(cfg["puffer_drain_minutes"]))
            b_conn.set_thermostat_setpoint(float(cfg["bticino_force_on_temp_c"]), mode="manual", duration_minutes=rem_min)
            record_api_usage(b_reads=1, b_writes=1, event_label="ap_reassert_grundfos", state_dict=st)

        # 1) Controlled Soft-Start Ramp-Up (+1 C setpoint step toward regime_sp if no defrost derating active)
        cur_trim = int(st.get("soft_curve_trim_k") or 0)
        soft_stepped_now = False
        if (
            cfg.get("soft_start_enabled", True)
            and cur_trim == 0
            and pdc_setpoint < regime_sp
            and not is_defrost_now
        ):
            last_step_dt = _parse_iso(st.get("soft_start_last_step_utc")) or cycle_dt
            step_elapsed = (now_utc - last_step_dt).total_seconds() / 60.0
            step_min = float(cfg.get("soft_start_step_minutes") or 25)
            buf_caught_up = buf_temp is not None and float(buf_temp) >= (target_lwt - 1.2)
            if step_elapsed >= step_min or (step_elapsed >= 12.0 and buf_caught_up):
                next_sp = min(regime_sp, pdc_setpoint + 1)
                next_lwt = compute_wo1c_lwt(float(oat), float(next_sp), float(curve_slope), float(target_shift))
                if not dry_run:
                    v_conn = ViessmannConnector()
                    v_conn.connect()
                    ok_r, _ = v_conn.set_reduced_temperature(float(next_sp))
                    ok_n, _ = v_conn.set_normal_temperature(float(next_sp))
                    record_api_usage(v_reads=3, v_writes=2, event_label="ap_soft_start_step", state_dict=st)
                    if ok_r or ok_n:
                        pdc_setpoint = next_sp
                        target_lwt = next_lwt
                        st["calculated_pdc_setpoint_c"] = next_sp
                        st["calculated_target_lwt_c"] = next_lwt
                        st["soft_start_last_step_utc"] = now_iso
                        st["last_action_utc"] = now_iso
                        st["last_action_reason"] = f"Soft-Start step +1°C -> SP={next_sp}°C (Target Acqua {next_lwt}°C, Puffer {buf_temp}°C)."
                        soft_stepped_now = True
                else:
                    pdc_setpoint = next_sp
                    target_lwt = next_lwt
                    st["calculated_pdc_setpoint_c"] = next_sp
                    st["calculated_target_lwt_c"] = next_lwt
                    st["soft_start_last_step_utc"] = now_iso
                    st["last_action_reason"] = f"[DRY-RUN] Soft-Start +1°C -> SP={next_sp}°C (LWT={next_lwt}°C)"
                    soft_stepped_now = True

        # 2) Defrost-Aware Derating & Anti-Overshoot Soft Curve Trim
        # CRITICAL HYSTERESIS SAFETY RULE: Never lower Target LWT while buffer_temp_c > new_lwt + 1.0 K,
        # otherwise WO1C trips its +2.5 K upper buffer cutoff immediately! Wait until buffer is near/below
        # new_lwt (e.g. right after a defrost or during steady modulation) before stepping down -1 C.
        soft_trimmed_now = False
        if not soft_stepped_now and elapsed_min >= 15:
            max_trim = int(cfg.get("soft_curve_max_shift_delta_k") or 2)
            last_trim_dt = _parse_iso(st.get("soft_curve_last_trim_utc"))
            cooldown_min = float(cfg.get("soft_curve_cooldown_minutes") or 45)
            cooldown_ok = last_trim_dt is None or ((now_utc - last_trim_dt).total_seconds() / 60.0) >= cooldown_min

            # Configurable Hydraulic & Defrost-BPHE safety floor (no hardcoded magic numbers):
            # Defaults (22.0 C / +13.5 K) keep BPHE outlet LWT >= 13-14 C during reverse-cycle defrost
            # and stay above the measured inverter minimum continuous floor (~38%).
            bphe_floor = float(cfg.get("defrost_min_safe_lwt_c") or 23.0)
            min_dt_rad = float(cfg.get("defrost_min_delta_k") or 13.5)
            min_safe_lwt = max(bphe_floor, t_in_f + min_dt_rad)
            candidate_sp = max(11, pdc_setpoint - 1)
            candidate_lwt = compute_wo1c_lwt(float(oat), float(candidate_sp), float(curve_slope), float(target_shift))
            # Dual WO1C full-buffer saturation guard (verified on Nov 21 & Nov 24 logs):
            # WO1C trips switch-off (param 7209) when BOTH buffer top exceeds target AND return (EWT / bottom) reaches target.
            buf_safe = (buf_temp is None) or (float(buf_temp) <= candidate_lwt + 1.0)
            ewt_safe = (ewt_temp is None) or (float(ewt_temp) <= candidate_lwt - 0.8)
            hysteresis_safe = buf_safe and ewt_safe
            floor_ok = candidate_lwt >= min_safe_lwt and candidate_sp < pdc_setpoint

            # Trigger A: Defrost Guard in humid cold air (breaks 88% <-> defrost resonance loop)
            defrost_thresh = int(cfg.get("defrost_trim_threshold_count") or 2)
            oat_frost_max = float(cfg.get("defrost_guard_oat_max_c") or 5.5)
            evap_dep = (float(oat) - float(suction_temp)) if suction_temp is not None else 0.0
            defrost_overload = (
                bool(cfg.get("defrost_guard_enabled", True))
                and float(oat) <= oat_frost_max
                and (
                    int(st.get("cycle_defrost_episodes") or 0) >= defrost_thresh
                    or (evap_dep >= 13.0 and (comp_mod or 0) >= 75.0)
                )
            )

            # Trigger B: Indoor temperature approaching T_max fast
            overshoot_risk = (
                bool(cfg.get("soft_curve_tuning_enabled", True))
                and (
                    (slope_c_h > 0.30 and t_in_f >= float(cfg["t_min_c"]) + 0.4)
                    or (t_in_f >= float(cfg["t_max_c"]) - 0.1)
                )
            )

            if (defrost_overload or overshoot_risk) and cooldown_ok and hysteresis_safe and floor_ok and abs(cur_trim - 1) <= max_trim:
                why_trim = (
                    f"Defrost Guard ({st.get('cycle_defrost_episodes', 0)} brin., ΔEvap={evap_dep:.0f}K)"
                    if defrost_overload
                    else "Self-tuning soft anti-overshoot"
                )
                if not dry_run:
                    v_conn = ViessmannConnector()
                    v_conn.connect()
                    ok_r, _ = v_conn.set_reduced_temperature(float(candidate_sp))
                    ok_n, _ = v_conn.set_normal_temperature(float(candidate_sp))
                    record_api_usage(v_reads=3, v_writes=2, event_label="ap_soft_curve_trim", state_dict=st)
                    if ok_r or ok_n:
                        st["soft_curve_trim_k"] = cur_trim - 1
                        st["soft_curve_last_trim_utc"] = now_iso
                        st["calculated_pdc_setpoint_c"] = candidate_sp
                        st["calculated_target_lwt_c"] = candidate_lwt
                        st["last_action_utc"] = now_iso
                        st["last_action_reason"] = f"{why_trim}: ridotto SP −1°C -> {candidate_sp}°C (Target Acqua {candidate_lwt}°C) per modulare dolce senza stacchi."
                        soft_trimmed_now = True
                else:
                    st["soft_curve_trim_k"] = cur_trim - 1
                    st["soft_curve_last_trim_utc"] = now_iso
                    st["calculated_pdc_setpoint_c"] = candidate_sp
                    st["calculated_target_lwt_c"] = candidate_lwt
                    st["last_action_reason"] = f"[DRY-RUN] {why_trim} -> SP={candidate_sp}°C (LWT={candidate_lwt}°C)"
                    soft_trimmed_now = True

        ext_count = int(st.get("min_end_ext_count") or (1 if st.get("min_end_temp_extended") else 0))
        min_end_t = float(cfg.get("min_cycle_end_temp_c") or 0.0)
        base_max_min = float(cfg["max_cycle_minutes"])
        effective_max_min = base_max_min + (60.0 * ext_count)
        hard_cap_min = base_max_min + 120.0

        stop_target = (t_in_f >= float(cfg["t_max_c"])) and not soft_trimmed_now
        if cfg.get("soft_curve_tuning_enabled") and t_in_f < float(cfg["t_max_c"]) + 0.2:
            if abs(int(st.get("soft_curve_trim_k") or 0)) < int(cfg.get("soft_curve_max_shift_delta_k") or 2):
                stop_target = False

        # Early clean exit while running inside a min-end-temp extension once min_end_t (e.g. 8.2 C) is reached.
        # Use base_window_end_local (original pre-extension end) because weather_planner locks eff_win_end
        # to the already-extended active_window_end_local during HEATING_SYNC!
        base_win_end = str(st.get("base_window_end_local") or cfg.get("cop_window_end") or "16:00")
        stop_ext_target = (
            ext_count > 0
            and min_end_t > 0.0
            and t_in_f >= min_end_t
            and (elapsed_min >= base_max_min or _is_past_cop_window_end(now_local, cfg, end_override=base_win_end))
        )
        if stop_ext_target:
            stop_target = True

        stop_max_dur = elapsed_min >= effective_max_min
        active_win_end = str(st.get("active_window_end_local") or eff_win_end)
        stop_window = (not is_emerg_cycle) and _is_past_cop_window_end(now_local, cfg, end_override=active_win_end)

        cur_local_min = now_local.hour * 60 + now_local.minute
        active_win_end_min = _hhmm_to_minutes(active_win_end)
        # Pre-trigger extension 15 min BEFORE schedule/duration expiry so WO1C internal clock drift
        # (~3-5 min ahead) never switches active_program -> standby and causes an avoidable stop/restart!
        ext_lead_min = 15
        near_window_end = (not is_emerg_cycle) and (cur_local_min >= active_win_end_min - ext_lead_min)
        near_max_dur = elapsed_min >= (effective_max_min - float(ext_lead_min))

        ext_refusal_note = None
        if (
            (stop_window or stop_max_dur or near_window_end or near_max_dur)
            and not stop_target
            and min_end_t > 0.0
            and t_in_f < min_end_t
            and ext_count < 2
            and elapsed_min < hard_cap_min
            and cur_local_min < _hhmm_to_minutes("18:30")
        ):
            # Weather-aware extension gate: extend +60 min (up to 2x, max 18:30 / +120m) ONLY IF:
            # (A) stopping now risks falling below safe_floor before tomorrow's window, OR
            # (B) the upcoming extra hour's COP is within arbitrage tolerance of tomorrow's COP
            # (fallback when weather unavailable: allow 1 unconditional +60 min step).
            wx_avail = bool(weather_plan.get("available"))
            safe_floor = float(cfg["t_emergency_c"]) + float(cfg.get("prearm_emergency_margin_c") or 0.4)
            proj_min = (weather_plan.get("projection_to_tomorrow") or {}).get("min_tin_c")
            next_h_cop = weather_plan.get("next_hour_cop_net")
            tom_cop = (weather_plan.get("tomorrow_window") or {}).get("avg_cop_net")
            arb_delta = float(cfg.get("weather_arbitrage_cop_delta") or 0.25)

            night_at_risk = (proj_min is not None and float(proj_min) < safe_floor)
            cop_extra_ok = (
                next_h_cop is None
                or tom_cop is None
                or float(next_h_cop) >= (float(tom_cop) - arb_delta)
            )
            allow_ext = (night_at_risk or cop_extra_ok) if wx_avail else (ext_count == 0)

            if allow_ext:
                if not st.get("base_window_end_local"):
                    st["base_window_end_local"] = active_win_end
                ext_count += 1
                ext_end_min = min(_hhmm_to_minutes("18:30"), max(active_win_end_min, cur_local_min) + 60)
                new_end = f"{ext_end_min // 60:02d}:{ext_end_min % 60:02d}"
                st["active_window_end_local"] = new_end
                st["min_end_temp_extended"] = True
                st["min_end_ext_count"] = ext_count
                stop_window = False
                stop_max_dur = False
                why_ext = (
                    f"evita emergenza notte (min {float(proj_min):.1f}°C < {safe_floor:.1f}°C)"
                    if night_at_risk
                    else (
                        f"COP ora extra buono ({float(next_h_cop):.2f} vs dom {float(tom_cop):.2f})"
                        if (next_h_cop is not None and tom_cop is not None)
                        else "fallback meteo"
                    )
                )
                if not dry_run:
                    v_conn = ViessmannConnector()
                    v_conn.connect()
                    active_win_start = str(st.get("active_window_start_local") or eff_win_start)
                    hw_ext_end_min = min(23 * 60 + 50, ext_end_min + 10)
                    hw_ext_end = f"{hw_ext_end_min // 60:02d}:{hw_ext_end_min % 60:02d}"
                    v_conn.set_heating_schedule_simple(
                        days=[_weekday_code(now_local)],
                        start=_round_hhmm_10m(active_win_start, round_up=False),
                        end=_round_hhmm_10m(hw_ext_end, round_up=True),
                        mode="reduced",
                        clear=False,
                    )
                    # Also extend BTicino manual timer so Grundfos stays ON through extension + drain
                    b_conn = BTicinoConnector()
                    rem_bt_min = max(75, int((base_max_min + 60.0 * ext_count) - elapsed_min) + int(cfg["puffer_drain_minutes"]))
                    b_conn.set_thermostat_setpoint(
                        float(cfg["bticino_force_on_temp_c"]),
                        mode="manual",
                        duration_minutes=rem_bt_min,
                    )
                    record_api_usage(v_reads=2, v_writes=1, b_reads=1, b_writes=1, event_label="ap_min_end_ext", state_dict=st)
                    st["last_action_utc"] = now_iso
                lead_tag = " (anticipo anti-stacco fascia)" if not (
                    _is_past_cop_window_end(now_local, cfg, end_override=active_win_end) or elapsed_min >= effective_max_min
                ) else ""
                st["last_action_reason"] = (
                    f"Estensione #{ext_count} T_min fine ciclo{lead_tag}: casa a {t_in_f:.1f}°C (<{min_end_t:.1f}°C), "
                    f"estendo fino alle {new_end} ({why_ext}; chiusura anticipata appena ≥{min_end_t:.1f}°C)."
                )
            elif stop_window or stop_max_dur:
                ext_refusal_note = (
                    f"stop preferito a estensione: notte sicura (min {float(proj_min):.1f}°C ≥ {safe_floor:.1f}°C) "
                    f"e domani COP migliore ({float(tom_cop):.2f} vs {float(next_h_cop):.2f})"
                )

        if stop_target or stop_max_dur or stop_window:
            if stop_ext_target:
                why = f"Target minimo fine ciclo raggiunto ({t_in_f:.1f}°C ≥ {min_end_t:.1f}°C in estensione)"
            elif stop_target:
                why = "Target raggiunto"
            elif stop_max_dur:
                why = f"Durata max raggiunta ({int(effective_max_min)}m)"
            else:
                why = f"Fine finestra COP ({active_win_end})"
            if ext_refusal_note:
                why = f"{why} — {ext_refusal_note}"
            if not dry_run:
                ok, msg = _apply_stop_pdc_keep_drain(cfg)
                record_api_usage(v_reads=2, v_writes=1, b_reads=1, b_writes=1, event_label="ap_stop_pdc_drain", state_dict=st)
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
                ok, msg = _apply_full_idle_shutdown(cfg, cur_slope=float(curve_slope), cur_shift=float(curve_shift))
                shift_rst = int(round(float(curve_shift))) != 0
                record_api_usage(
                    v_reads=6 + (2 if shift_rst else 0),
                    v_writes=4 + (1 if shift_rst else 0),
                    b_reads=1,
                    b_writes=1,
                    event_label="ap_idle_shutdown",
                    state_dict=st,
                )
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
            st["armed_by_prearm"] = False
            st["active_window_start_local"] = None
            st["active_window_end_local"] = None
            st["base_window_end_local"] = None
            st["calculated_curve_shift"] = 0
            st["min_end_temp_extended"] = False
            st["min_end_ext_count"] = 0
            st["soft_curve_trim_k"] = 0
            st["soft_curve_last_trim_utc"] = None
            st["cycle_defrost_episodes"] = 0
            st["prev_phase_was_defrost"] = False
            st["soft_start_last_step_utc"] = None
            # Auto-recalibrate physical mathematical model at end of every completed heating cycle
            if cfg.get("adaptive_model_enabled", True) and not dry_run:
                try:
                    from scripts.thermal_model import update_model_from_log, recommend_operating_targets
                    new_m = update_model_from_log(write_file=True)
                    rec_post = recommend_operating_targets(new_m, t_in_f, float(oat), cfg)
                    st["thermal_model"] = {
                        "cycles_observed": new_m.get("cycles_observed", 0),
                        "confidence_pct": new_m.get("confidence_pct", 15),
                        "k_rad_kw_per_k": new_m.get("k_rad_kw_per_k"),
                        "inverter_min_mod_pct": new_m.get("inverter_min_mod_pct"),
                        "defrost_lwt_drop_p90_k": new_m.get("defrost_lwt_drop_p90_k"),
                        "ua_building_c_24h_per_k": new_m.get("ua_building_c_24h_per_k"),
                        "recommended_target_lwt_c": rec_post.get("recommended_target_lwt_c"),
                        "pred_autonomy_hours": rec_post.get("pred_autonomy_hours"),
                        "updated_utc": new_m.get("updated_utc"),
                    }
                except Exception as me:
                    logger.warning("Aggiornamento thermal_model fallito: %s", me)

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
            record_api_usage(cron_patches=1, event_label="ap_cron_adapt", state_dict=st)
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
