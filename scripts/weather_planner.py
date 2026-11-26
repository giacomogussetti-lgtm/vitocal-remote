"""
Weather-Aware Dynamic COP Window Planner & Predictive Look-Ahead for Vitocal 111-S.
Uses Open-Meteo (DWD ICON-D2 / Best Match) with mountain elevation correction.

PRIVACY & SECURITY:
- Coordinates (WEATHER_LAT, WEATHER_LON, WEATHER_ELEVATION_M) are read ONLY from
  environment variables / GitHub Secrets / local .env and are NEVER persisted into
  data/weather_forecast.json or any tracked file.
- No place names are ever stored in cached JSON or logs.

FAIL-SAFE DESIGN:
- If coordinates are missing or Open-Meteo is unreachable and cache is stale,
  gracefully falls back to the static configured COP window while preserving
  conservative anti-short-cycle protection.
"""
from __future__ import annotations

import json
import logging
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import Config

logger = logging.getLogger("weather_planner")

WEATHER_CACHE_FILE = Config.DATA_DIR / "weather_forecast.json"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
P_ATM_MOUNTAIN_HPA = 900.0  # ~950-1000 m mountain altitude barometric reference
T_EVAP_OFFSET_K = 6.5       # Steady-state OAT - T_evap depression at 45-55% inverter load
UA_SAFETY_FACTOR = 1.15     # Conservative 15% safety margin on building heat loss


def _get_rome_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Rome")
    except Exception:
        return timezone(timedelta(hours=1))


def _parse_iso(ts_str: Optional[str]) -> Optional[datetime]:
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(str(ts_str))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _parse_local_hour(ts_local: str, rome_tz) -> Optional[datetime]:
    if not ts_local:
        return None
    try:
        dt = datetime.fromisoformat(str(ts_local))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=rome_tz)
        else:
            dt = dt.astimezone(rome_tz)
        return dt
    except Exception:
        return None


def _hhmm_to_min(hhmm: str) -> int:
    parts = str(hhmm or "00:00").strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _min_to_hhmm(total_min: int) -> str:
    clamped = max(0, min(23 * 60 + 50, int(total_min)))
    return f"{clamped // 60:02d}:{clamped % 60:02d}"


def _saturation_vapor_hpa(temp_c: float) -> float:
    """Magnus-Tetens saturation vapor pressure (hPa) over liquid/ice blend."""
    return 6.112 * math.exp((17.67 * temp_c) / max(30.0, temp_c + 243.5))


def _mixing_ratio_g_kg(temp_c: float, rh_pct: float, p_hpa: float = P_ATM_MOUNTAIN_HPA) -> float:
    """Humidity mixing ratio W (g water vapor / kg dry air) at mountain pressure."""
    rh = max(5.0, min(100.0, float(rh_pct)))
    e = (rh / 100.0) * _saturation_vapor_hpa(temp_c)
    return 621.98 * e / max(100.0, p_hpa - e)


def _wmo_icon(code: Optional[int], solar_wm2: float = 0.0) -> str:
    c = int(code) if code is not None else 0
    if c == 0:
        return "☀️" if solar_wm2 > 40 else "🌙"
    if c in (1, 2):
        return "⛅" if solar_wm2 > 20 else "☁️"
    if c == 3:
        return "☁️"
    if c in (45, 48):
        return "🌫️"
    if c in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "🌧️"
    if c in (71, 73, 75, 77, 85, 86):
        return "❄️"
    if c >= 95:
        return "⛈️"
    return "🌤️"


def _load_cache_raw(cache_file: Path) -> dict[str, Any]:
    if not cache_file.exists():
        return {}
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache_raw(cache_file: Path, payload: dict[str, Any]) -> None:
    """Persists sanitized weather cache without any coordinates or location names."""
    sanitized = dict(payload)
    for forbidden in ("latitude", "longitude", "elevation", "utc_offset_seconds", "generationtime_ms"):
        sanitized.pop(forbidden, None)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(sanitized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fetch_or_load_weather(
    cfg: dict[str, Any],
    now_utc: Optional[datetime] = None,
    cache_file: Optional[Path] = None,
) -> dict[str, Any]:
    """
    Fetches sanitized Open-Meteo hourly forecast or returns fresh cache.
    Never writes coordinates into cache_file.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    cfile = cache_file or WEATHER_CACHE_FILE
    existing = _load_cache_raw(cfile)
    refresh_h = max(0.5, float(cfg.get("weather_refresh_hours") or 3.0))

    fetched_dt = _parse_iso(existing.get("fetched_utc"))
    cache_age_h = ((now_utc - fetched_dt).total_seconds() / 3600.0) if fetched_dt else 999.0
    has_hourly = isinstance(existing.get("hourly"), list) and len(existing["hourly"]) >= 12

    if has_hourly and cache_age_h < refresh_h:
        out = dict(existing)
        out["available"] = True
        out["source"] = "cache"
        out["cache_age_h"] = round(cache_age_h, 2)
        return out

    lat = os.environ.get("WEATHER_LAT", Config.WEATHER_LAT).strip()
    lon = os.environ.get("WEATHER_LON", Config.WEATHER_LON).strip()
    elev = os.environ.get("WEATHER_ELEVATION_M", Config.WEATHER_ELEVATION_M).strip()

    if not lat or not lon:
        if has_hourly and cache_age_h < 18.0:
            out = dict(existing)
            out["available"] = True
            out["source"] = "cache_no_env"
            out["cache_age_h"] = round(cache_age_h, 2)
            return out
        return {
            "available": False,
            "source": "missing_secrets",
            "fallback_reason": "Coordinate meteo non configurate (WEATHER_LAT / WEATHER_LON nei Secrets/.env): uso finestra statica.",
            "hourly": [],
            "calibration": existing.get("calibration") or {},
            "calibration_history": existing.get("calibration_history") or [],
            "prediction_history": existing.get("prediction_history") or [],
        }

    params: dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,snowfall,weather_code,shortwave_radiation,wind_speed_10m",
        "forecast_days": 3,
        "timezone": "Europe/Rome",
        "models": "best_match",
    }
    if elev:
        try:
            params["elevation"] = float(elev)
        except ValueError:
            pass

    try:
        resp = requests.get(OPEN_METEO_URL, params=params, timeout=12)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}")
        raw_json = resp.json()
        h_obj = raw_json.get("hourly") if isinstance(raw_json, dict) else None
        if not isinstance(h_obj, dict) or not h_obj.get("time"):
            raise RuntimeError("Payload hourly Open-Meteo vuoto")

        times = h_obj.get("time") or []
        temps = h_obj.get("temperature_2m") or []
        rhs = h_obj.get("relative_humidity_2m") or []
        dews = h_obj.get("dew_point_2m") or []
        precs = h_obj.get("precipitation") or []
        snows = h_obj.get("snowfall") or []
        codes = h_obj.get("weather_code") or []
        rads = h_obj.get("shortwave_radiation") or []
        winds = h_obj.get("wind_speed_10m") or []

        hourly_clean: list[dict[str, Any]] = []
        for idx, t_str in enumerate(times):
            t_val = temps[idx] if idx < len(temps) else None
            if t_val is None:
                continue
            hourly_clean.append({
                "time_local": str(t_str),
                "temp_raw_c": round(float(t_val), 1),
                "rh_pct": int(round(float(rhs[idx]))) if idx < len(rhs) and rhs[idx] is not None else 75,
                "dew_point_c": round(float(dews[idx]), 1) if idx < len(dews) and dews[idx] is not None else None,
                "precip_mm": round(float(precs[idx]), 2) if idx < len(precs) and precs[idx] is not None else 0.0,
                "snowfall_cm": round(float(snows[idx]), 2) if idx < len(snows) and snows[idx] is not None else 0.0,
                "wmo_code": int(codes[idx]) if idx < len(codes) and codes[idx] is not None else 0,
                "solar_wm2": round(float(rads[idx]), 0) if idx < len(rads) and rads[idx] is not None else 0.0,
                "wind_kmh": round(float(winds[idx]), 1) if idx < len(winds) and winds[idx] is not None else 0.0,
            })

        # Keep rolling history of forecast hours for self-tuning bias/error comparison
        hist_map: dict[str, dict[str, Any]] = {}
        for item in existing.get("calibration_history") or []:
            if isinstance(item, dict) and item.get("time_local"):
                hist_map[str(item["time_local"])] = item
        for item in hourly_clean:
            hist_map[item["time_local"]] = {
                "time_local": item["time_local"],
                "temp_raw_c": item["temp_raw_c"],
                "rh_pct": item["rh_pct"],
                "precip_mm": item["precip_mm"],
                "snowfall_cm": item["snowfall_cm"],
            }
        hist_sorted = [hist_map[k] for k in sorted(hist_map.keys())][-168:]

        return {
            "available": True,
            "source": "open_meteo_live",
            "cache_age_h": 0.0,
            "location_label": "Abitazione di Montagna (Zona Climatica E)",
            "model": "Open-Meteo ICON-D2 / Best Match",
            "fetched_utc": now_utc.isoformat(),
            "hourly": hourly_clean,
            "calibration": existing.get("calibration") or {},
            "calibration_history": hist_sorted,
            "calibration_log": existing.get("calibration_log") or [],
            "recent_oat_checks": existing.get("recent_oat_checks") or [],
            "prediction_history": existing.get("prediction_history") or [],
        }
    except Exception as exc:
        logger.warning("Errore fetch Open-Meteo: %s", exc)
        if has_hourly and cache_age_h < 18.0:
            out = dict(existing)
            out["available"] = True
            out["source"] = "cache_fallback"
            out["cache_age_h"] = round(cache_age_h, 2)
            out["warning_note"] = f"Open-Meteo temporaneamente non raggiungibile ({exc}); uso cache ({cache_age_h:.1f}h)."
            return out
        return {
            "available": False,
            "source": "fetch_error",
            "fallback_reason": f"Open-Meteo non raggiungibile ({exc}): uso finestra statica.",
            "hourly": [],
            "calibration": existing.get("calibration") or {},
            "calibration_history": existing.get("calibration_history") or [],
            "prediction_history": existing.get("prediction_history") or [],
        }


def calibrate_weather_from_telemetry(
    cache_data: dict[str, Any],
    recent_samples: list[dict[str, Any]],
    now_local: datetime,
    rome_tz,
) -> dict[str, Any]:
    """
    Self-tunes forecast OAT bias, OAT MAE, frost penalty scale, and T_in projection MAE
    by comparing past stored predictions against actual Viessmann/BTicino telemetry.
    """
    cal_hist = cache_data.get("calibration_history") or []
    pred_hist = cache_data.get("prediction_history") or []

    parsed_samples: list[tuple[datetime, dict[str, Any]]] = []
    for s in recent_samples or []:
        dt = _parse_iso(s.get("timestamp_utc"))
        if dt is not None:
            parsed_samples.append((dt.astimezone(rome_tz), s))
    parsed_samples.sort(key=lambda x: x[0])

    errors_oat: list[float] = []
    matched_pairs: list[dict[str, Any]] = []
    frost_active_hours = 0
    frost_expected_rate_sum = 0.0
    frost_observed_episodes = 0

    for h_rec in cal_hist:
        h_dt = _parse_local_hour(str(h_rec.get("time_local") or ""), rome_tz)
        if h_dt is None or h_dt > now_local:
            continue
        raw_t = h_rec.get("temp_raw_c")
        if raw_t is None:
            continue

        best_s = None
        best_diff = 1201.0  # +/- 20 min
        hour_samples: list[dict[str, Any]] = []
        for s_dt, s in parsed_samples:
            diff_s = abs((s_dt - h_dt).total_seconds())
            if diff_s <= 1800.0:
                hour_samples.append(s)
            if diff_s < best_diff and s.get("external_temp_c") is not None:
                best_diff = diff_s
                best_s = s

        if best_s is not None:
            act_oat = float(best_s["external_temp_c"])
            raw_f = float(raw_t)
            err_raw = act_oat - raw_f
            errors_oat.append(err_raw)
            matched_pairs.append({
                "time_local": str(h_rec.get("time_local")),
                "forecast_raw_c": round(raw_f, 1),
                "actual_oat_c": round(act_oat, 1),
                "err_raw_c": round(err_raw, 2),
            })

        # Check active heating defrost calibration inside this hour
        if hour_samples:
            active_cnt = sum(
                1 for x in hour_samples
                if (x.get("compressor_active") == 1) or ((x.get("compressor_modulation_percent") or 0) > 0)
            )
            if active_cnt >= max(1, len(hour_samples) // 2):
                t_c = float(raw_t)
                rh_c = float(h_rec.get("rh_pct") or 75)
                t_ev = t_c - T_EVAP_OFFSET_K
                if t_ev < -0.5:
                    dw = max(0.0, _mixing_ratio_g_kg(t_c, rh_c) - _mixing_ratio_g_kg(t_ev, 100.0))
                    exp_def_h = min(1.5, 0.25 + 0.55 * dw)
                    frost_active_hours += 1
                    frost_expected_rate_sum += exp_def_h
                    prev_def = False
                    for x in hour_samples:
                        is_d = "defrost" in str(x.get("compressor_phase") or "").lower()
                        if is_d and not prev_def:
                            frost_observed_episodes += 1
                        prev_def = is_d

    n_oat = len(errors_oat)
    if n_oat >= 2:
        sorted_err = sorted(errors_oat)
        if n_oat >= 10:
            trim = max(1, n_oat // 10)
            trimmed = sorted_err[trim:-trim]
        else:
            trimmed = sorted_err
        mid = len(trimmed) // 2
        med_err = trimmed[mid] if len(trimmed) % 2 == 1 else 0.5 * (trimmed[mid - 1] + trimmed[mid])
        # Bayesian shrinkage toward 0.0 (prior weight = 12 hours)
        oat_bias_c = round(max(-4.0, min(4.0, med_err * (n_oat / (n_oat + 12.0)))), 2)
        oat_raw_mae_c = round(sum(abs(e) for e in errors_oat) / n_oat, 2)
        oat_mae_c = round(sum(abs(e - oat_bias_c) for e in errors_oat) / n_oat, 2)
        oat_max_abs_err_c = round(max(abs(e - oat_bias_c) for e in errors_oat), 2)
    else:
        oat_bias_c = 0.0
        oat_raw_mae_c = None
        oat_mae_c = None
        oat_max_abs_err_c = None

    recent_oat_checks: list[dict[str, Any]] = []
    for p in matched_pairs[-18:]:
        f_corr = round(float(p["forecast_raw_c"]) + oat_bias_c, 1)
        err_corr = round(float(p["actual_oat_c"]) - f_corr, 1)
        recent_oat_checks.append({
            "time_local": p["time_local"],
            "forecast_raw_c": p["forecast_raw_c"],
            "forecast_corr_c": f_corr,
            "actual_oat_c": p["actual_oat_c"],
            "err_corr_c": err_corr,
        })

    if frost_active_hours >= 4 and frost_expected_rate_sum > 0.5:
        raw_scale = frost_observed_episodes / frost_expected_rate_sum
        w_f = frost_active_hours / (frost_active_hours + 8.0)
        frost_penalty_scale = round(max(0.6, min(1.7, (1.0 - w_f) * 1.0 + w_f * raw_scale)), 2)
    else:
        frost_penalty_scale = 1.0

    # Check past T_in standby projection accuracy (strictly exclude intervals with active heating!)
    tin_errors: list[float] = []
    for p_rec in pred_hist:
        if not isinstance(p_rec, dict):
            continue
        if p_rec.get("state") in ("HEATING_SYNC", "PUFFER_DRAIN"):
            continue
        t_dt = _parse_local_hour(str(p_rec.get("target_local") or ""), rome_tz)
        created_dt = _parse_iso(p_rec.get("created_utc"))
        pred_tin = p_rec.get("pred_tin_c")
        if t_dt is None or pred_tin is None or t_dt > now_local:
            continue
        created_local = created_dt.astimezone(rome_tz) if created_dt is not None else (t_dt - timedelta(hours=6))
        # Skip if compressor or Grundfos ran during [created_local, t_dt] (not a pure standby cooling span)
        had_heating = False
        best_tin = None
        best_diff = 1201.0
        for s_dt, s in parsed_samples:
            if created_local <= s_dt <= t_dt:
                if (s.get("compressor_active") == 1) or (s.get("grundfos_pump_active") == 1):
                    had_heating = True
                    break
            if s.get("indoor_temp_bticino_c") is None:
                continue
            d = abs((s_dt - t_dt).total_seconds())
            if d < best_diff:
                best_diff = d
                best_tin = float(s["indoor_temp_bticino_c"])
        if not had_heating and best_tin is not None:
            tin_errors.append(abs(best_tin - float(pred_tin)))

    tin_mae_c = round(sum(tin_errors) / len(tin_errors), 2) if len(tin_errors) >= 2 else None

    cal_log = [c for c in (cache_data.get("calibration_log") or []) if isinstance(c, dict)]
    last_cl = cal_log[-1] if cal_log else None
    should_log_cal = n_oat >= 2 and (
        last_cl is None
        or (n_oat - int(last_cl.get("oat_samples_matched") or 0)) >= 6
        or abs(oat_bias_c - float(last_cl.get("oat_bias_c") or 0.0)) >= 0.05
        or frost_penalty_scale != float(last_cl.get("frost_penalty_scale") or 1.0)
    )
    if should_log_cal:
        cal_log.append({
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "oat_samples_matched": n_oat,
            "oat_bias_c": oat_bias_c,
            "oat_raw_mae_c": oat_raw_mae_c,
            "oat_mae_c": oat_mae_c,
            "oat_max_abs_err_c": oat_max_abs_err_c,
            "frost_penalty_scale": frost_penalty_scale,
            "tin_projection_mae_c": tin_mae_c,
        })
        cal_log = cal_log[-40:]

    return {
        "oat_samples_matched": n_oat,
        "oat_bias_c": oat_bias_c,
        "oat_raw_mae_c": oat_raw_mae_c,
        "oat_mae_c": oat_mae_c,
        "oat_max_abs_err_c": oat_max_abs_err_c,
        "frost_active_hours_matched": frost_active_hours,
        "frost_penalty_scale": frost_penalty_scale,
        "tin_proj_samples_matched": len(tin_errors),
        "tin_projection_mae_c": tin_mae_c,
        "recent_oat_checks": recent_oat_checks,
        "calibration_log": cal_log,
        "calibrated_utc": datetime.now(timezone.utc).isoformat(),
    }


def score_hourly_cop(
    hourly_records: list[dict[str, Any]],
    oat_bias_c: float = 0.0,
    frost_penalty_scale: float = 1.0,
    lwt_ref_c: float = 23.5,
) -> list[dict[str, Any]]:
    """
    Scores each hourly forecast slot with bias-corrected OAT, EN 14511-calibrated
    dry Carnot COP, continuous psychrometric frost/precipitation degradation
    (Vocale et al. / EnergyPlus envelope), solar gain bonus, and net effective COP.
    """
    scored: list[dict[str, Any]] = []

    for rec in hourly_records:
        raw_t = rec.get("temp_raw_c")
        if raw_t is None:
            continue
        t_corr = round(float(raw_t) + float(oat_bias_c), 1)
        rh = int(rec.get("rh_pct") if rec.get("rh_pct") is not None else 75)
        precip = float(rec.get("precip_mm") or 0.0)
        snow = float(rec.get("snowfall_cm") or 0.0)
        solar = float(rec.get("solar_wm2") or 0.0)
        wmo = int(rec.get("wmo_code") or 0)

        # EN 14511 Vitocal 111.A16 Carnot-pinch COP with pressure-ratio efficiency decay:
        # A7/W35 dry=4.36, A2/W35@85%RH net=3.32, A-7/W35 net~2.79 (EN14511: 4.37, 3.32, 2.72)
        # Upper clamp raised to 6.0 so low radiant LWT (~23.5 C) preserves OAT sensitivity between +3 and +7 C.
        lift_pinch = max(14.0, (float(lwt_ref_c) - t_corr) + 8.0)
        eta_comp = max(0.38, min(0.51, 0.505 - 0.0025 * max(0.0, lift_pinch - 36.0)))
        cop_dry = max(1.7, min(6.0, eta_comp * ((float(lwt_ref_c) + 276.15) / lift_pinch)))

        t_evap = t_corr - T_EVAP_OFFSET_K
        if t_evap < 0.0:
            delta_w = max(0.0, _mixing_ratio_g_kg(t_corr, rh) - _mixing_ratio_g_kg(t_evap, 100.0))
        else:
            delta_w = 0.0

        # Literature frosting envelope peak in [-2.0, +2.5] C, tapering cleanly outside
        if delta_w > 0.0:
            if -2.0 <= t_corr <= 2.5:
                f_env = 1.25
            elif t_corr > 2.5:
                f_env = max(0.50, 1.25 - 0.25 * (t_corr - 2.5))
            else:
                f_env = max(0.75, 1.25 - 0.06 * (-2.0 - t_corr))
            frost_base = 0.082 * delta_w * f_env
        else:
            frost_base = 0.0

        # Continuous precipitation penalty (wet snow vs light liquid rain, zero binary cliff)
        if snow > 0.0 or (precip > 0.0 and t_corr <= 1.2):
            precip_loss = min(0.09, 0.05 * snow + 0.025 * min(3.0, precip))
        elif precip > 0.0 and 1.2 < t_corr <= 3.5:
            precip_loss = min(0.035, 0.012 * precip)
        else:
            precip_loss = 0.0

        frost_loss_frac = min(0.26, float(frost_penalty_scale) * (frost_base + precip_loss))
        solar_bonus = min(0.05, (max(0.0, solar) / 500.0) * 0.05) if solar > 100.0 else 0.0
        cop_net = round(cop_dry * (1.0 - frost_loss_frac) * (1.0 + solar_bonus), 2)

        frost_risk = "ALTO" if frost_loss_frac >= 0.14 else ("MEDIO" if frost_loss_frac >= 0.07 else "BASSO")
        scored.append({
            "time_local": str(rec["time_local"]),
            "temp_raw_c": round(float(raw_t), 1),
            "temp_c": t_corr,
            "rh_pct": rh,
            "dew_point_c": rec.get("dew_point_c"),
            "precip_mm": precip,
            "snowfall_cm": snow,
            "wmo_code": wmo,
            "icon": _wmo_icon(wmo, solar),
            "solar_wm2": solar,
            "wind_kmh": float(rec.get("wind_kmh") or 0.0),
            "t_evap_est_c": round(t_evap, 1),
            "cop_dry": round(cop_dry, 2),
            "frost_loss_pct": round(frost_loss_frac * 100.0, 1),
            "frost_risk": frost_risk,
            "cop_net": cop_net,
        })
    return scored


def _summarize_block(slots: list[dict[str, Any]], start_hhmm: str, end_hhmm: str) -> dict[str, Any]:
    n = max(1, len(slots))
    avg_cop_net = round(sum(s["cop_net"] for s in slots) / n, 2)
    avg_cop_dry = round(sum(s["cop_dry"] for s in slots) / n, 2)
    avg_temp = round(sum(s["temp_c"] for s in slots) / n, 1)
    avg_rh = int(round(sum(s["rh_pct"] for s in slots) / n))
    avg_frost_pct = sum(s["frost_loss_pct"] for s in slots) / n
    frost_risk = "ALTO" if avg_frost_pct >= 14.0 else ("MEDIO" if avg_frost_pct >= 6.0 else "BASSO")
    return {
        "start_hhmm": start_hhmm,
        "end_hhmm": end_hhmm,
        "avg_cop_net": avg_cop_net,
        "avg_cop_dry": avg_cop_dry,
        "avg_temp_c": avg_temp,
        "avg_rh_pct": avg_rh,
        "avg_frost_loss_pct": round(avg_frost_pct, 1),
        "frost_risk": frost_risk,
    }


def find_best_window_for_date(
    scored_hourly: list[dict[str, Any]],
    target_date_str: str,
    cfg: dict[str, Any],
    rome_tz,
) -> Optional[dict[str, Any]]:
    """
    Finds the highest-COP_net contiguous block of `weather_window_hours` hours
    within [weather_search_start, weather_search_end] for target_date_str (YYYY-MM-DD),
    applying anti-jitter stability against the static cop_window_start..cop_window_end.
    """
    static_start = str(cfg.get("cop_window_start") or "11:00")
    static_end = str(cfg.get("cop_window_end") or "16:00")
    search_start_h = _hhmm_to_min(str(cfg.get("weather_search_start") or "09:00")) // 60
    search_end_h = _hhmm_to_min(str(cfg.get("weather_search_end") or "18:00")) // 60
    win_hours = max(1, min(9, int(cfg.get("weather_window_hours") or 5)))
    min_gain = float(cfg.get("weather_min_cop_gain") if cfg.get("weather_min_cop_gain") is not None else 0.08)
    dynamic_enabled = bool(cfg.get("weather_dynamic_window_enabled", True))

    by_hour: dict[int, dict[str, Any]] = {}
    for s in scored_hourly:
        dt = _parse_local_hour(s["time_local"], rome_tz)
        if dt is not None and dt.strftime("%Y-%m-%d") == target_date_str:
            by_hour[dt.hour] = s

    if not by_hour:
        return None

    # Evaluate static baseline window
    st_h0 = _hhmm_to_min(static_start) // 60
    st_h1 = max(st_h0 + 1, (_hhmm_to_min(static_end) + 59) // 60)
    static_slots = [by_hour[h] for h in range(st_h0, st_h1) if h in by_hour]
    if not static_slots:
        return None
    static_sum = _summarize_block(static_slots, static_start, static_end)

    candidates: list[dict[str, Any]] = []
    for h0 in range(search_start_h, search_end_h - win_hours + 1):
        slots = [by_hour[h] for h in range(h0, h0 + win_hours) if h in by_hour]
        if len(slots) == win_hours:
            candidates.append(_summarize_block(slots, f"{h0:02d}:00", f"{h0 + win_hours:02d}:00"))

    if not candidates:
        return {
            **static_sum,
            "date": target_date_str,
            "static_start_hhmm": static_start,
            "static_end_hhmm": static_end,
            "static_cop_net": static_sum["avg_cop_net"],
            "cop_gain_vs_static": 0.0,
            "is_dynamic_shifted": False,
        }

    # Prefer higher COP_net; break ties closer to midday (13:00)
    best = max(
        candidates,
        key=lambda c: (c["avg_cop_net"], -abs((_hhmm_to_min(c["start_hhmm"]) + _hhmm_to_min(c["end_hhmm"])) / 2.0 - 13.5 * 60.0)),
    )
    gain = round(best["avg_cop_net"] - static_sum["avg_cop_net"], 2)

    if dynamic_enabled and gain >= min_gain:
        chosen = best
        shifted = (chosen["start_hhmm"] != static_start or chosen["end_hhmm"] != static_end)
    else:
        chosen = static_sum
        shifted = False

    return {
        **chosen,
        "date": target_date_str,
        "static_start_hhmm": static_start,
        "static_end_hhmm": static_end,
        "static_cop_net": static_sum["avg_cop_net"],
        "cop_gain_vs_static": round(chosen["avg_cop_net"] - static_sum["avg_cop_net"], 2),
        "best_candidate_start": best["start_hhmm"],
        "best_candidate_end": best["end_hhmm"],
        "best_candidate_cop_net": best["avg_cop_net"],
        "is_dynamic_shifted": shifted,
    }


def project_indoor_temp(
    t_in_c: float,
    now_local: datetime,
    target_dt_local: datetime,
    scored_hourly: list[dict[str, Any]],
    ua_building_c_24h_per_k: float,
    fallback_oat_c: float,
    rome_tz,
    safe_floor_c: float,
    t_min_c: float,
) -> dict[str, Any]:
    """
    Simulates hourly indoor cooling from now_local until target_dt_local using
    UA * UA_SAFETY_FACTOR (1.15x) so autonomy is never overestimated.
    """
    ua_eff = max(0.05, float(ua_building_c_24h_per_k)) * UA_SAFETY_FACTOR
    hour_oat_map: dict[str, float] = {}
    hour_wind_map: dict[str, float] = {}
    for s in scored_hourly:
        dt = _parse_local_hour(s["time_local"], rome_tz)
        if dt is not None:
            k_hm = dt.strftime("%Y-%m-%d %H")
            hour_oat_map[k_hm] = float(s["temp_c"])
            hour_wind_map[k_hm] = float(s.get("wind_kmh") or 0.0)

    cur_t = float(t_in_c)
    min_t = cur_t
    hourly_map: dict[str, float] = {}
    first_below_tmin_iso: Optional[str] = None
    first_below_safe_iso: Optional[str] = None
    first_below_tmin_hours: Optional[float] = None

    total_hours = max(0.0, (target_dt_local - now_local).total_seconds() / 3600.0)
    steps = int(math.ceil(total_hours))
    cursor = now_local
    for step_idx in range(steps):
        frac = min(1.0, max(0.0, total_hours - step_idx))
        if frac <= 1e-6:
            break
        key = cursor.strftime("%Y-%m-%d %H")
        oat_h = hour_oat_map.get(key, float(fallback_oat_c) - 2.0)
        wind_h = hour_wind_map.get(key, 0.0)
        wind_mult = 1.0 + min(0.15, max(0.0, wind_h - 15.0) * 0.008)
        loss_h = (ua_eff * wind_mult / 24.0) * max(0.5, cur_t - oat_h) * frac
        cur_t -= loss_h
        min_t = min(min_t, cur_t)
        cursor = cursor + timedelta(hours=frac)
        h_key = cursor.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00")
        hourly_map[h_key] = round(cur_t, 2)
        if first_below_tmin_iso is None and cur_t <= float(t_min_c):
            first_below_tmin_iso = cursor.strftime("%d/%m %H:%M")
            first_below_tmin_hours = round((cursor - now_local).total_seconds() / 3600.0, 1)
        if first_below_safe_iso is None and cur_t <= float(safe_floor_c):
            first_below_safe_iso = cursor.strftime("%d/%m %H:%M")

    return {
        "start_tin_c": round(float(t_in_c), 2),
        "min_tin_c": round(min_t, 2),
        "end_tin_c": round(cur_t, 2),
        "hours_simulated": round(total_hours, 1),
        "ua_raw": round(float(ua_building_c_24h_per_k), 3),
        "ua_effective": round(ua_eff, 3),
        "first_below_tmin_local": first_below_tmin_iso,
        "first_below_tmin_hours": first_below_tmin_hours,
        "first_below_safe_local": first_below_safe_iso,
        "hourly_tin_map": hourly_map,
    }


def evaluate_weather_plan(
    now_local: datetime,
    t_in_c: Optional[float],
    current_oat_c: Optional[float],
    cur_state: str,
    cfg: dict[str, Any],
    thermal_model: Optional[dict[str, Any]],
    recent_samples: list[dict[str, Any]],
    st: dict[str, Any],
    dry_run: bool = False,
    cache_file: Optional[Path] = None,
) -> dict[str, Any]:
    """
    Master evaluation of dynamic COP window, anti-short-cycle guard,
    predictive pre-arming, weather arbitrage deferral, and glass-box reasoning trace.
    """
    rome_tz = _get_rome_tz()
    now_local = now_local.astimezone(rome_tz) if now_local.tzinfo else now_local.replace(tzinfo=rome_tz)
    now_utc = now_local.astimezone(timezone.utc)
    cfile = cache_file or WEATHER_CACHE_FILE

    static_start = str(cfg.get("cop_window_start") or "11:00")
    static_end = str(cfg.get("cop_window_end") or "16:00")
    planner_enabled = bool(cfg.get("weather_planner_enabled", True))
    anti_sc_enabled = bool(cfg.get("anti_short_cycle_enabled", True))
    min_cycle_min = int(cfg.get("min_cycle_minutes") or 120)
    max_ext_min = int(cfg.get("max_window_extension_minutes") or 120)
    prearm_enabled = bool(cfg.get("predictive_prearm_enabled", True))
    prearm_max_above = float(cfg.get("prearm_max_above_tmin_c") if cfg.get("prearm_max_above_tmin_c") is not None else 0.6)
    prearm_emerg_margin = float(cfg.get("prearm_emergency_margin_c") if cfg.get("prearm_emergency_margin_c") is not None else 0.4)
    defer_enabled = bool(cfg.get("weather_defer_enabled", True))
    arb_delta = float(cfg.get("weather_arbitrage_cop_delta") if cfg.get("weather_arbitrage_cop_delta") is not None else 0.25)

    t_min = float(cfg.get("t_min_c") or 7.5)
    t_emerg = float(cfg.get("t_emergency_c") or 6.8)
    safe_floor_c = round(t_emerg + prearm_emerg_margin, 2)
    ua_raw = float((thermal_model or {}).get("ua_building_c_24h_per_k") or 0.173)
    lwt_ref = float((thermal_model or {}).get("recommended_target_lwt_c") or min(float(cfg.get("max_target_lwt_c") or 26.5), t_min + float(cfg.get("target_lwt_delta_k") or 15.5)))

    if planner_enabled:
        cache_data = fetch_or_load_weather(cfg, now_utc=now_utc, cache_file=cfile)
    else:
        cache_data = {
            "available": False,
            "source": "disabled",
            "fallback_reason": "Pianificatore Meteo disattivato da configurazione.",
            "hourly": [],
            "calibration": {},
            "calibration_history": [],
            "prediction_history": [],
        }

    cal = calibrate_weather_from_telemetry(cache_data, recent_samples, now_local, rome_tz) if cache_data.get("available") else (cache_data.get("calibration") or {})
    oat_bias = float(cal.get("oat_bias_c") or 0.0)
    frost_scale = float(cal.get("frost_penalty_scale") or 1.0)

    scored = score_hourly_cop(
        cache_data.get("hourly") or [],
        oat_bias_c=oat_bias,
        frost_penalty_scale=frost_scale,
        lwt_ref_c=lwt_ref,
    ) if cache_data.get("available") else []

    today_str = now_local.strftime("%Y-%m-%d")
    tomorrow_dt = now_local + timedelta(days=1)
    tomorrow_str = tomorrow_dt.strftime("%Y-%m-%d")
    yesterday_str = (now_local - timedelta(days=1)).strftime("%Y-%m-%d")

    today_win = find_best_window_for_date(scored, today_str, cfg, rome_tz) if scored else None
    tomorrow_win = find_best_window_for_date(scored, tomorrow_str, cfg, rome_tz) if scored else None

    # Target start tomorrow for overnight simulation
    tom_start_hhmm = tomorrow_win["start_hhmm"] if tomorrow_win else static_start
    tom_h, tom_m = [int(x) for x in tom_start_hhmm.split(":")]
    tom_target_dt = tomorrow_dt.replace(hour=tom_h, minute=tom_m, second=0, microsecond=0)

    tin_ref = float(t_in_c) if t_in_c is not None else t_min
    oat_fallback = float(current_oat_c) if current_oat_c is not None else 4.0
    proj = project_indoor_temp(
        t_in_c=tin_ref,
        now_local=now_local,
        target_dt_local=tom_target_dt,
        scored_hourly=scored,
        ua_building_c_24h_per_k=ua_raw,
        fallback_oat_c=oat_fallback,
        rome_tz=rome_tz,
        safe_floor_c=safe_floor_c,
        t_min_c=t_min,
    )

    cur_min = now_local.hour * 60 + now_local.minute
    win_hours = max(1, min(9, int(cfg.get("weather_window_hours") or 5)))
    search_start_h = _hhmm_to_min(str(cfg.get("weather_search_start") or "09:00")) // 60
    static_start_h = _hhmm_to_min(static_start) // 60
    min_gain = float(cfg.get("weather_min_cop_gain") if cfg.get("weather_min_cop_gain") is not None else 0.08)
    lock_before_min = int(cfg.get("window_lock_before_start_minutes") or 90)

    def _window_avg_cop(w_start: str, w_end: str) -> Optional[float]:
        h0 = _hhmm_to_min(w_start) // 60
        h1 = max(h0 + 1, (_hhmm_to_min(w_end) + 59) // 60)
        vals = []
        for s in scored:
            dt_s = _parse_local_hour(s["time_local"], rome_tz)
            if dt_s is not None and dt_s.strftime("%Y-%m-%d") == today_str and h0 <= dt_s.hour < h1:
                vals.append(float(s["cop_net"]))
        return round(sum(vals) / len(vals), 2) if vals else None

    window_locked = False
    was_postponed_now = False
    horizon_guard_notes: list[str] = []

    # Lock active window during HEATING_SYNC so it doesn't shift mid-cycle
    if cur_state == "HEATING_SYNC" and st.get("active_window_start_local") and st.get("active_window_end_local"):
        eff_start = str(st["active_window_start_local"])
        eff_end = str(st["active_window_end_local"])
        window_locked = True
    else:
        if today_win and cfg.get("weather_dynamic_window_enabled", True):
            eff_start = today_win["start_hhmm"]
            eff_end = today_win["end_hhmm"]
        else:
            eff_start = static_start
            eff_end = static_end

        # Layer 1: Emergency-Ceiling Guard (never postpone start past when T_in would drop <= T_emerg + 0.2 C)
        emerg_ceiling_triggered = False
        if cur_state == "ARMED" or tin_ref <= (t_min + 0.15):
            eff_start_h = _hhmm_to_min(eff_start) // 60
            tin_map_chk = proj.get("hourly_tin_map") or {}
            first_danger_h: Optional[int] = None
            for h_chk in range(now_local.hour + 1, eff_start_h + 1):
                t_chk = tin_map_chk.get(f"{today_str}T{h_chk:02d}:00")
                if t_chk is not None and float(t_chk) <= (t_emerg + 0.2):
                    first_danger_h = h_chk
                    break
            if first_danger_h is not None:
                safe_h = max(search_start_h, min(static_start_h, first_danger_h - 1))
                if safe_h < eff_start_h:
                    emerg_ceiling_triggered = True
                    eff_start = f"{safe_h:02d}:00"
                    eff_end = f"{min(23, safe_h + win_hours):02d}:00"
                    horizon_guard_notes.append(
                        f"Guardia Emergenza: T_casa ({tin_ref:.1f}°C) toccherebbe ≤{t_emerg + 0.2:.1f}°C alle {first_danger_h:02d}:00 → avvio anticipato/bloccato a {eff_start}–{eff_end}."
                    )

        # Layer 2 & 3: Anti-Chasing-Horizon Lock & Asymmetric Postponement Guard
        comm_date = st.get("committed_window_date")
        comm_start = st.get("committed_window_start")
        comm_end = st.get("committed_window_end")
        postponed_today = (st.get("window_postponed_date") == today_str)
        if comm_date == today_str and comm_start and comm_end:
            comm_start_min = _hhmm_to_min(str(comm_start))
            eff_start_min_cand = _hhmm_to_min(eff_start)
            if cur_min >= (comm_start_min - lock_before_min):
                # Within lock horizon: freeze committed window (only allow Emergency-Ceiling pull earlier)
                if not (emerg_ceiling_triggered and eff_start_min_cand < comm_start_min):
                    eff_start = str(comm_start)
                    eff_end = str(comm_end)
                    window_locked = True
                    horizon_guard_notes.append(
                        f"Finestra bloccata 🔒 ({eff_start}–{eff_end}): entro {lock_before_min}m dall'avvio non slitta più."
                    )
            elif eff_start_min_cand > comm_start_min:
                # Before lock horizon: allow postponing at most once/day and only on strong COP gain
                comm_cop = _window_avg_cop(str(comm_start), str(comm_end))
                cand_cop = _window_avg_cop(eff_start, eff_end)
                req_gain = max(0.14, 2.0 * min_gain)
                if not postponed_today and comm_cop is not None and cand_cop is not None and (cand_cop - comm_cop) >= req_gain:
                    was_postponed_now = True
                    horizon_guard_notes.append(
                        f"Posticipo controllato {comm_start}→{eff_start} (+{cand_cop - comm_cop:.2f} COP; bloccati ulteriori rinvii oggi)."
                    )
                else:
                    eff_start = str(comm_start)
                    eff_end = str(comm_end)
                    horizon_guard_notes.append(
                        f"Anti-Slittamento: mantenuta finestra {eff_start}–{eff_end} (miglioramento insufficiente o rinvio già usato oggi)."
                    )

    eff_start_min = _hhmm_to_min(eff_start)
    eff_end_min = _hhmm_to_min(eff_end)
    in_window_now = eff_start_min <= cur_min <= eff_end_min
    remaining_min = max(0, eff_end_min - cur_min) if in_window_now else 0

    # Decision evaluation
    short_cycle_action = "normal"
    extended_end_hhmm: Optional[str] = None
    prearm_recommended = False
    prearm_reason: Optional[str] = None
    defer_recommended = False
    defer_reason: Optional[str] = None
    trace: list[str] = []

    if cache_data.get("available") and today_win:
        trace.append(
            f"Finestra Oggi: {eff_start}–{eff_end}" + (" 🔒" if window_locked else "")
            + f" (COP netto stimato {today_win['avg_cop_net']:.2f}, OAT {today_win['avg_temp_c']:+.1f}°C, RH {today_win['avg_rh_pct']}%, Brina {today_win['frost_risk']}"
            + (f", +{today_win['cop_gain_vs_static']:.2f} vs statica" if today_win.get("is_dynamic_shifted") else ", allineata a statica")
            + ")."
        )
    else:
        trace.append(
            f"Finestra Attiva (statica): {eff_start}–{eff_end}. "
            + (cache_data.get("fallback_reason") or "Dati meteo non disponibili.")
        )
    trace.extend(horizon_guard_notes)

    if tomorrow_win:
        trace.append(
            f"Finestra Domani: {tomorrow_win['start_hhmm']}–{tomorrow_win['end_hhmm']} "
            f"(COP netto {tomorrow_win['avg_cop_net']:.2f}, OAT {tomorrow_win['avg_temp_c']:+.1f}°C, "
            f"RH {tomorrow_win['avg_rh_pct']}%, Brina {tomorrow_win['frost_risk']})."
        )

    trace.append(
        f"Proiezione casa fino a domani {tom_start_hhmm} ({proj['hours_simulated']:.1f}h, "
        f"UA×1.15={proj['ua_effective']:.3f}): {tin_ref:.1f}°C → {proj['end_tin_c']:.1f}°C "
        f"(min {proj['min_tin_c']:.1f}°C vs pavimento sicurezza {safe_floor_c:.1f}°C)."
    )

    # 1) Anti-Short-Cycle evaluation (when inside window with < min_cycle_minutes remaining)
    if anti_sc_enabled and in_window_now and remaining_min < min_cycle_min and cur_state in ("IDLE", "ARMED"):
        if proj["min_tin_c"] >= safe_floor_c + 0.05 and tin_ref > safe_floor_c:
            short_cycle_action = "defer_short_cycle"
            trace.append(
                f"Anti-Micro-Ciclo: restano solo {remaining_min}m (<{min_cycle_min}m) ma T_min notturna prevista "
                f"{proj['min_tin_c']:.1f}°C ≥ {safe_floor_c:.1f}°C → evito micro-ciclo e rimando a domani {tom_start_hhmm}."
            )
        else:
            needed_end_min = min(eff_end_min + max_ext_min, cur_min + min_cycle_min, 23 * 60 + 50)
            extended_end_hhmm = _min_to_hhmm(((needed_end_min + 9) // 10) * 10)
            short_cycle_action = "extend_short_cycle"
            trace.append(
                f"Anti-Micro-Ciclo + Sicurezza Notte: restano {remaining_min}m (<{min_cycle_min}m) ma notte scenderebbe "
                f"a {proj['min_tin_c']:.1f}°C → avvio ora garantendo ciclo minimo fino alle {extended_end_hhmm}."
            )

    # 2) Predictive Pre-Arming (IDLE/ARMED inside today's window with sufficient duration left)
    if (
        prearm_enabled
        and cur_state in ("IDLE", "ARMED")
        and in_window_now
        and remaining_min >= min_cycle_min
        and t_min < tin_ref <= (t_min + prearm_max_above)
    ):
        if proj["min_tin_c"] < safe_floor_c:
            prearm_recommended = True
            prearm_reason = (
                f"Pre-Armamento Predittivo: T={tin_ref:.1f}°C è sopra {t_min:.1f}°C ma scenderebbe a "
                f"{proj['min_tin_c']:.1f}°C (<{safe_floor_c:.1f}°C) prima di domani {tom_start_hhmm} — anticipo in finestra COP."
            )
            trace.append(prearm_reason)
        elif (
            today_win
            and tomorrow_win
            and tin_ref <= (t_min + 0.3)
            and (proj["first_below_tmin_hours"] is not None and proj["first_below_tmin_hours"] <= 12.0)
            and today_win["avg_cop_net"] >= (tomorrow_win["avg_cop_net"] + arb_delta)
        ):
            prearm_recommended = True
            prearm_reason = (
                f"Arbitraggio Meteo Anticipato: Oggi COP {today_win['avg_cop_net']:.2f} > Domani "
                f"{tomorrow_win['avg_cop_net']:.2f} (+{today_win['avg_cop_net'] - tomorrow_win['avg_cop_net']:.2f}) "
                f"e casa toccherebbe {t_min:.1f}°C entro {proj['first_below_tmin_hours']:.1f}h."
            )
            trace.append(prearm_reason)

    # 3) Weather Arbitrage Deferral (ARMED inside today's window when tomorrow is much better & night is safe)
    already_deferred_yesterday = (st.get("weather_deferred_date") == yesterday_str)
    if (
        defer_enabled
        and cur_state == "ARMED"
        and in_window_now
        and remaining_min >= min_cycle_min
        and today_win
        and tomorrow_win
        and not already_deferred_yesterday
        and tin_ref > safe_floor_c
        and proj["min_tin_c"] >= safe_floor_c + 0.05
        and tomorrow_win["avg_cop_net"] >= (today_win["avg_cop_net"] + arb_delta)
    ):
        defer_recommended = True
        defer_reason = (
            f"Rinvio Meteo Intelligente: Domani COP {tomorrow_win['avg_cop_net']:.2f} > Oggi "
            f"{today_win['avg_cop_net']:.2f} (+{tomorrow_win['avg_cop_net'] - today_win['avg_cop_net']:.2f}) "
            f"e notte sicura (min {proj['min_tin_c']:.1f}°C ≥ {safe_floor_c:.1f}°C)."
        )
        trace.append(defer_reason)
    elif already_deferred_yesterday and cur_state == "ARMED" and in_window_now:
        trace.append("Anti-starvation attivo: ciclo già rinviato ieri, oggi parte normalmente nella finestra COP.")

    if short_cycle_action == "defer_short_cycle":
        decision_summary = f"⏸️ Rinvio anti-micro-ciclo a domani {tom_start_hhmm} (restano {remaining_min}m, notte sicura {proj['min_tin_c']:.1f}°C)"
    elif short_cycle_action == "extend_short_cycle":
        decision_summary = f"🔥 Estensione anti-micro-ciclo fino alle {extended_end_hhmm} (evita emergenza notte {proj['min_tin_c']:.1f}°C)"
    elif prearm_recommended:
        decision_summary = f"⚡ Pre-armamento predittivo consigliato ora (notte attesa {proj['min_tin_c']:.1f}°C)"
    elif defer_recommended:
        decision_summary = f"🌤️ Rinvio conveniente a domani {tom_start_hhmm} (COP {tomorrow_win['avg_cop_net']:.2f} vs {today_win['avg_cop_net']:.2f})"
    elif in_window_now:
        decision_summary = f"☀️ In finestra COP attiva ({eff_start}–{eff_end}, restano {remaining_min}m)"
    else:
        decision_summary = f"🕒 Fuori finestra ({eff_start}–{eff_end}): attesa ora migliore o emergenza ≤ {t_emerg:.1f}°C"

    # Build compact 30-hour preview for PWA Glass-Box drawer with full, physically consistent T_casa simulation
    eff_win_hours_today = set(range(eff_start_min // 60, (eff_end_min + 59) // 60))
    tom_win_hours = set(
        range(
            _hhmm_to_min(tomorrow_win["start_hhmm"]) // 60,
            (_hhmm_to_min(tomorrow_win["end_hhmm"]) + 59) // 60,
        )
    ) if tomorrow_win else set()

    cur_hour_floor = now_local.replace(minute=0, second=0, microsecond=0)
    t_max_cfg = float(cfg.get("t_max_c") or 8.8)
    alpha_heat = float((thermal_model or {}).get("alpha_heat_c_h_per_k") or 0.0164)
    preview_slots = []
    for s in scored:
        s_dt = _parse_local_hour(s["time_local"], rome_tz)
        if s_dt is None or s_dt < cur_hour_floor:
            continue
        preview_slots.append((s_dt, s))
        if len(preview_slots) >= 30:
            break

    hourly_preview: list[dict[str, Any]] = []
    sim_tin = float(tin_ref)
    tom_cycle_latched = False
    for idx_p, (s_dt, s) in enumerate(preview_slots):
        d_str = s_dt.strftime("%Y-%m-%d")
        day_tag = "Oggi" if d_str == today_str else ("Dom" if d_str == tomorrow_str else s_dt.strftime("%d/%m"))
        in_today_win = (d_str == today_str and s_dt.hour in eff_win_hours_today)
        in_tom_win = (d_str == tomorrow_str and s_dt.hour in tom_win_hours)
        in_win = in_today_win or in_tom_win

        if idx_p == 0:
            tin_mode = "heat" if cur_state == "HEATING_SYNC" else "now"
            tin_val = round(sim_tin, 2)
        else:
            oat_h = float(s["temp_c"])
            wind_h = float(s.get("wind_kmh") or 0.0)
            wind_mult = 1.0 + min(0.15, max(0.0, wind_h - 15.0) * 0.008)
            is_heating_now = (cur_state == "HEATING_SYNC" and in_today_win)
            is_armed_today = (cur_state == "ARMED" and in_today_win and not defer_recommended)
            if in_tom_win and sim_tin <= t_min:
                tom_cycle_latched = True
            elif not in_tom_win:
                tom_cycle_latched = False

            if (is_heating_now or is_armed_today or tom_cycle_latched) and sim_tin < t_max_cfg:
                extra_cold = (ua_raw / 24.0) * max(0.0, 5.0 - oat_h)
                gain_h = max(0.05, alpha_heat * max(10.0, lwt_ref - sim_tin) - extra_cold)
                sim_tin = min(t_max_cfg, sim_tin + gain_h)
                tin_mode = "heat" if is_heating_now else "heat_est"
                if sim_tin >= t_max_cfg - 0.02:
                    tom_cycle_latched = False
            else:
                loss_h = (ua_raw * wind_mult / 24.0) * max(0.5, sim_tin - oat_h)
                sim_tin = max(2.0, sim_tin - loss_h)
                tin_mode = "cool"
            tin_val = round(sim_tin, 2)

        hourly_preview.append({
            "time_local": s["time_local"],
            "hh": s_dt.strftime("%H:%M"),
            "day_tag": day_tag,
            "icon": s["icon"],
            "temp_c": s["temp_c"],
            "rh_pct": s["rh_pct"],
            "cop_net": s["cop_net"],
            "frost_risk": s["frost_risk"],
            "precip_mm": s["precip_mm"],
            "solar_wm2": s["solar_wm2"],
            "tin_proj_c": tin_val,
            "tin_mode": tin_mode,
            "in_window": in_win,
        })

    # Record a future standby T_in checkpoint (~6h ahead) ONLY when currently in pure standby (IDLE/ARMED)
    # and the 6h-ahead slot is also pure standby cooling (never contaminate standby MAE with heating cycles!).
    pred_hist = list(cache_data.get("prediction_history") or [])
    if (
        not dry_run
        and cur_state in ("IDLE", "ARMED")
        and len(hourly_preview) >= 7
        and hourly_preview[6].get("tin_mode") == "cool"
        and hourly_preview[6].get("tin_proj_c") is not None
    ):
        cp_dt = _parse_local_hour(hourly_preview[6]["time_local"], rome_tz)
        if cp_dt is not None:
            cp_key = cp_dt.strftime("%Y-%m-%dT%H:00")
            if not any(isinstance(p, dict) and p.get("target_local") == cp_key for p in pred_hist):
                pred_hist.append({
                    "created_utc": now_utc.isoformat(),
                    "state": cur_state,
                    "target_local": cp_key,
                    "pred_tin_c": hourly_preview[6]["tin_proj_c"],
                })
                pred_hist = pred_hist[-72:]

    assumptions = {
        "ua_raw_c_24h_k": round(ua_raw, 3),
        "ua_safety_factor": UA_SAFETY_FACTOR,
        "ua_effective_c_24h_k": proj["ua_effective"],
        "t_evap_offset_k": T_EVAP_OFFSET_K,
        "lwt_ref_c": round(lwt_ref, 1),
        "p_atm_hpa": P_ATM_MOUNTAIN_HPA,
        "safe_floor_c": safe_floor_c,
        "min_cycle_minutes": min_cycle_min,
        "arbitrage_cop_delta": arb_delta,
        "oat_bias_c": oat_bias,
        "oat_raw_mae_c": cal.get("oat_raw_mae_c"),
        "oat_mae_c": cal.get("oat_mae_c"),
        "oat_max_abs_err_c": cal.get("oat_max_abs_err_c"),
        "oat_samples_matched": cal.get("oat_samples_matched", 0),
        "frost_penalty_scale": frost_scale,
        "tin_projection_mae_c": cal.get("tin_projection_mae_c"),
    }

    # Upcoming hour net COP for weather-aware extension decisions during HEATING_SYNC
    next_hour_cop_net: Optional[float] = None
    next_hour_label: Optional[str] = None
    if hourly_preview:
        idx_nh = 1 if (now_local.minute >= 35 and len(hourly_preview) > 1) else 0
        if hourly_preview[idx_nh].get("cop_net") is not None:
            next_hour_cop_net = float(hourly_preview[idx_nh]["cop_net"])
            next_hour_label = f"{hourly_preview[idx_nh].get('day_tag', '')} {hourly_preview[idx_nh].get('hh', '')}".strip()

    plan_result = {
        "available": bool(cache_data.get("available")),
        "source": cache_data.get("source"),
        "fallback_reason": cache_data.get("fallback_reason") or cache_data.get("warning_note"),
        "evaluated_local": now_local.strftime("%d/%m %H:%M"),
        "effective_window_start": eff_start,
        "effective_window_end": eff_end,
        "window_locked": window_locked,
        "was_postponed_now": was_postponed_now,
        "committed_window_start": eff_start,
        "committed_window_end": eff_end,
        "in_window_now": in_window_now,
        "remaining_window_min": remaining_min,
        "next_hour_cop_net": next_hour_cop_net,
        "next_hour_label": next_hour_label,
        "today_window": today_win,
        "tomorrow_window": tomorrow_win,
        "projection_to_tomorrow": {
            "start_tin_c": proj["start_tin_c"],
            "min_tin_c": proj["min_tin_c"],
            "end_tin_c": proj["end_tin_c"],
            "hours_simulated": proj["hours_simulated"],
            "target_local": tom_target_dt.strftime("%d/%m %H:%M"),
            "first_below_tmin_local": proj["first_below_tmin_local"],
            "first_below_safe_local": proj["first_below_safe_local"],
        },
        "short_cycle_action": short_cycle_action,
        "extended_end_hhmm": extended_end_hhmm,
        "prearm_recommended": prearm_recommended,
        "prearm_reason": prearm_reason,
        "defer_recommended": defer_recommended,
        "defer_reason": defer_reason,
        "decision_summary": decision_summary,
        "decision_trace": trace,
        "assumptions": assumptions,
    }

    if not dry_run and cache_data.get("available"):
        cal_clean = {k: v for k, v in cal.items() if k not in ("recent_oat_checks", "calibration_log")}
        to_save = {
            "location_label": cache_data.get("location_label", "Abitazione di Montagna (Zona Climatica E)"),
            "model": cache_data.get("model", "Open-Meteo ICON-D2 / Best Match"),
            "fetched_utc": cache_data.get("fetched_utc"),
            "hourly": cache_data.get("hourly") or [],
            "calibration": cal_clean,
            "calibration_history": cache_data.get("calibration_history") or [],
            "calibration_log": cal.get("calibration_log") or cache_data.get("calibration_log") or [],
            "recent_oat_checks": (cal.get("recent_oat_checks") or cache_data.get("recent_oat_checks") or [])[-12:],
            "prediction_history": pred_hist,
            "hourly_preview": hourly_preview,
            "plan": plan_result,
        }
        try:
            _save_cache_raw(cfile, to_save)
        except Exception as save_err:
            logger.warning("Impossibile salvare weather_forecast.json: %s", save_err)

    return plan_result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    cfg_path = Config.DATA_DIR / "autopilot_config.json"
    cfg_now = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    res = evaluate_weather_plan(
        now_local=datetime.now(_get_rome_tz()),
        t_in_c=7.5,
        current_oat_c=4.5,
        cur_state="ARMED",
        cfg=cfg_now,
        thermal_model=None,
        recent_samples=[],
        st={},
        dry_run=True,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))
