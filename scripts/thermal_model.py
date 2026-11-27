"""
Self-Converging Thermodynamic & Hydraulic Model for Vitocal 111-S + Radiant Floor.
Eliminates hardcoded empirical setpoints by identifying real physical plant parameters
directly from cloud telemetry (`data/cloud_telemetry.jsonl`) with progressive Bayesian
shrinkage / EWMA convergence as more heating cycles and cold-weather regimes accumulate.

Identified physical parameters:
  1. k_rad_kw_per_k            : Radiant floor + Grundfos heat-transfer coefficient (kW / K of Buf - T_in)
  2. inverter_min_mod_pct      : Observed continuous minimum inverter modulation (%)
  3. p_min_continuous_kw_ref   : Minimum continuous thermal power at reference OAT (+4 C) (kW_t)
  4. defrost_lwt_drop_p90_k    : 90th-percentile BPHE outlet (LWT) drop during reverse-cycle defrost (K)
  5. defrost_buf_drop_p90_k    : 90th-percentile 200L buffer drop during reverse-cycle defrost (K)
  6. ua_building_c_24h_per_k   : Standby indoor cooling rate per K of (T_in - OAT) ((C/24h)/K)
  7. heating_gain_c_per_kwh_t  : Indoor temperature rise per net thermal kWh injected (C / kWh_t)

Usage:
    python scripts/thermal_model.py [--write]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config import Config

MODEL_FILE = Config.DATA_DIR / "thermal_model.json"

# Conservative physical priors (used only with weak weight when observed cycles are few)
PRIOR_MODEL: dict[str, Any] = {
    "k_rad_kw_per_k": 0.344,
    "k_rad_end_kw_per_k": 0.320,
    "inverter_min_mod_pct": 38.0,
    "p_min_continuous_kw_ref": 3.8,
    "defrost_lwt_drop_p90_k": 9.8,
    "defrost_buf_drop_p90_k": 4.2,
    "ua_building_c_24h_per_k": 0.170,
    "alpha_heat_c_h_per_k": 0.0171,
    "bphe_safe_outlet_min_c": 12.0,
}


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _percentile(vals: list[float], p: float) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    idx = (len(s) - 1) * max(0.0, min(1.0, p))
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return float(s[lo])
    frac = idx - lo
    return float(s[lo] + frac * (s[hi] - s[lo]))


def _shrink(obs: Optional[float], prior: float, n_obs: int, prior_weight: float = 3.0) -> float:
    """Bayesian shrinkage: starts near physical prior and converges smoothly to real data as n_obs grows."""
    if obs is None or n_obs <= 0:
        return float(prior)
    w = float(n_obs) / (float(n_obs) + float(prior_weight))
    return float(prior * (1.0 - w) + obs * w)


def _estimate_sample_thermal_kw(sample: dict[str, Any]) -> float:
    """Unified EN 14511 / R410A Vitocal 111-S 111.A16 thermal output model matching analytics & charts."""
    phase = str(sample.get("compressor_phase") or "").lower()
    if "defrost" in phase:
        return -3.5
    mod = sample.get("compressor_modulation_percent")
    comp_on = (sample.get("compressor_active") == 1) or (mod is not None and float(mod) > 0)
    if not comp_on:
        return 0.0
    m = max(0.0, min(100.0, float(mod if mod is not None else 45.0)))
    p_raw = sample.get("hot_gas_pressure_bar")
    p_cond = float(p_raw) if p_raw is not None else 17.0
    p_factor = max(0.72, min(1.25, 0.82 + 0.18 * ((p_cond - 14.0) / 6.0)))
    p1_kw = 0.045 if (sample.get("primary_pump_rotation_percent") or 0) > 0 else 0.0
    p_el = 0.28 + 2.95 * (m / 100.0) * p_factor + p1_kw

    lwt = float(sample.get("pdc_supply_temp_c") if sample.get("pdc_supply_temp_c") is not None else 25.0)
    oat = float(sample.get("external_temp_c") if sample.get("external_temp_c") is not None else 5.0)
    t_suc_raw = sample.get("suction_gas_temp_c")
    t_cond = (22.86 * math.log(max(5.0, float(p_raw))) - 38.4) if p_raw is not None else (lwt + 3.0)
    t_evap = min(oat - 3.5, float(t_suc_raw) + 1.5) if t_suc_raw is not None else (oat - 6.5)

    carnot = (t_cond + 273.15) / max(12.0, t_cond - t_evap)
    eta = 0.48 if m <= 55.0 else (0.44 if m <= 75.0 else 0.39)
    cop_dyn = max(1.7, min(5.3, carnot * eta))
    return round(p_el * cop_dyn, 3)


def fit_thermal_model(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Identifies all physical parameters from chronological telemetry samples.
    Returns a complete self-contained dictionary suitable for JSON persistence and UI display.
    """
    chrono: list[tuple[datetime, dict[str, Any]]] = []
    for s in samples:
        dt = _parse_ts(s.get("timestamp_utc"))
        if dt is not None:
            chrono.append((dt, s))
    chrono.sort(key=lambda x: x[0])

    # 1. Split real compressor heating cycles (filtering single corrupted Viessmann polls)
    cycles: list[list[tuple[datetime, dict[str, Any]]]] = []
    cur: list[tuple[datetime, dict[str, Any]]] = []
    for dt, s in chrono:
        v_empty = (
            s.get("pdc_supply_temp_c") is None
            and s.get("buffer_temp_c") is None
            and s.get("compressor_modulation_percent") is None
        )
        if v_empty and cur:
            continue
        is_on = (s.get("compressor_active") == 1) or ((s.get("compressor_modulation_percent") or 0) > 0)
        if is_on:
            if cur and (dt - cur[-1][0]).total_seconds() > 1500:
                cycles.append(cur)
                cur = [(dt, s)]
            else:
                cur.append((dt, s))
        else:
            if cur:
                cycles.append(cur)
                cur = []
    if cur:
        cycles.append(cur)

    # Filter to meaningful heating cycles (>= 30 min with Grundfos mostly ON)
    valid_cycles = []
    for cyc in cycles:
        dur_m = (cyc[-1][0] - cyc[0][0]).total_seconds() / 60.0
        gf_ratio = sum(1 for _, s in cyc if s.get("grundfos_pump_active") == 1) / max(1, len(cyc))
        if dur_m >= 30.0 and gf_ratio >= 0.5:
            valid_cycles.append(cyc)

    # 2. Identify k_rad (overall & late-cycle asymptotic after slab warm-up), inverter floor %, p_min_kw, heating gain
    krad_samples: list[float] = []
    krad_end_samples: list[float] = []
    steady_mods: list[float] = []
    p_min_obs_list: list[float] = []
    gain_obs_list: list[float] = []
    oat_seen: list[float] = []

    for cyc in valid_cycles:
        t0 = cyc[0][0]
        dur_h_cyc = max(0.5, (cyc[-1][0] - t0).total_seconds() / 3600.0)
        tins_cyc = [float(s["indoor_temp_bticino_c"]) for _, s in cyc if s.get("indoor_temp_bticino_c") is not None]
        dt_buf_in_list: list[float] = []
        for i, (dt, s) in enumerate(cyc):
            if s.get("external_temp_c") is not None:
                oat_seen.append(float(s["external_temp_c"]))
            p_th = _estimate_sample_thermal_kw(s)
            elapsed_m = (dt - t0).total_seconds() / 60.0
            phase = str(s.get("compressor_phase") or "").lower()
            mod = s.get("compressor_modulation_percent")
            buf = s.get("buffer_temp_c")
            tin = s.get("indoor_temp_bticino_c")
            gf = s.get("grundfos_pump_active")
            if buf is not None and tin is not None and (float(buf) - float(tin)) > 2.0:
                dt_buf_in_list.append(float(buf) - float(tin))
            if elapsed_m >= 25.0 and "defrost" not in phase and mod is not None and float(mod) > 10.0 and gf == 1:
                steady_mods.append(float(mod))
                if buf is not None and tin is not None and (float(buf) - float(tin)) >= 8.0 and p_th > 1.5:
                    # Only use quasi-steady points where buffer isn't rapidly ramping
                    prev_buf = cyc[i - 1][1].get("buffer_temp_c") if i > 0 else buf
                    if prev_buf is not None and abs(float(buf) - float(prev_buf)) <= 0.4:
                        kr_val = p_th / (float(buf) - float(tin))
                        krad_samples.append(kr_val)
                        # Asymptotic late-cycle k_rad (>= 90 min, once radiant screed C_slab is thermally charged)
                        if elapsed_m >= 90.0:
                            krad_end_samples.append(kr_val)
                if float(mod) <= 42.0 and p_th > 1.5:
                    oat = float(s.get("external_temp_c") if s.get("external_temp_c") is not None else 5.0)
                    # Normalize thermal power to reference OAT = +4 C (~2.5% per K)
                    p_ref = p_th / max(0.7, 1.0 + 0.025 * (oat - 4.0))
                    p_min_obs_list.append(p_ref)

        # Direct sensor-based room heating rate per K of (Buf - T_in): completely independent of kW estimation!
        if len(tins_cyc) >= 2 and len(dt_buf_in_list) >= 10 and dur_h_cyc >= 1.0:
            dt_in = tins_cyc[-1] - tins_cyc[0]
            avg_dt_buf_in = sum(dt_buf_in_list) / len(dt_buf_in_list)
            if dt_in > 0.2 and avg_dt_buf_in >= 8.0:
                alpha_obs = (dt_in / dur_h_cyc) / avg_dt_buf_in
                if 0.005 <= alpha_obs <= 0.050:
                    gain_obs_list.append(alpha_obs)

    # 3. Identify defrost thermal drops (LWT and Buffer) across distinct episodes
    defrost_episodes: list[list[tuple[datetime, dict[str, Any]]]] = []
    cur_def: list[tuple[datetime, dict[str, Any]]] = []
    for idx, (dt, s) in enumerate(chrono):
        ph = str(s.get("compressor_phase") or "").lower()
        if "defrost" in ph:
            if cur_def and (dt - cur_def[-1][0]).total_seconds() > 600:
                defrost_episodes.append(cur_def)
                cur_def = [(dt, s)]
            else:
                cur_def.append((dt, s))
        elif cur_def:
            defrost_episodes.append(cur_def)
            cur_def = []
    if cur_def:
        defrost_episodes.append(cur_def)

    # Map timestamps to index for pre/post lookup
    ts_to_idx = {dt: i for i, (dt, _) in enumerate(chrono)}
    lwt_drops: list[float] = []
    buf_drops: list[float] = []
    for ep in defrost_episodes:
        first_idx = ts_to_idx.get(ep[0][0], 0)
        last_idx = ts_to_idx.get(ep[-1][0], first_idx)
        pre_slice = chrono[max(0, first_idx - 3):first_idx + 1]
        in_post_slice = chrono[first_idx:min(len(chrono), last_idx + 3)]
        pre_bufs = [float(x["buffer_temp_c"]) for _, x in pre_slice if x.get("buffer_temp_c") is not None]
        pre_lwts = [float(x["pdc_supply_temp_c"]) for _, x in pre_slice if x.get("pdc_supply_temp_c") is not None]
        in_lwts = [float(x["pdc_supply_temp_c"]) for _, x in in_post_slice if x.get("pdc_supply_temp_c") is not None]
        in_bufs = [float(x["buffer_temp_c"]) for _, x in in_post_slice if x.get("buffer_temp_c") is not None]
        # Exclude cold-start defrosts where pre_buf < 18 C from steady-state drop sizing, or measure relative drop cleanly
        if pre_bufs and in_lwts and max(pre_bufs) >= 18.0:
            drop_lwt = max(pre_bufs) - min(in_lwts)
            if 2.0 <= drop_lwt <= 18.0:
                lwt_drops.append(drop_lwt)
        if pre_bufs and in_bufs and max(pre_bufs) >= 18.0:
            drop_buf = max(pre_bufs) - min(in_bufs)
            if 0.5 <= drop_buf <= 10.0:
                buf_drops.append(drop_buf)

    # 4. Identify building standby cooling coefficient UA ((C/24h) per K of T_in - OAT)
    ua_obs_list: list[float] = []
    standby_seg: list[tuple[datetime, dict[str, Any]]] = []
    for dt, s in chrono:
        active = (s.get("compressor_active") == 1) or (s.get("grundfos_pump_active") == 1)
        if not active:
            if standby_seg and (dt - standby_seg[-1][0]).total_seconds() > 7200:
                # evaluate segment
                pass
            standby_seg.append((dt, s))
        else:
            if len(standby_seg) >= 12:
                _eval_standby_ua(standby_seg, ua_obs_list)
            standby_seg = []
    if len(standby_seg) >= 12:
        _eval_standby_ua(standby_seg, ua_obs_list)

    # 5. Converge parameters via Bayesian shrinkage (higher weight as real cycles/episodes grow)
    n_cycles = len(valid_cycles)
    n_defrosts = len(lwt_drops)
    n_standby = len(ua_obs_list)

    krad_obs = _percentile(krad_samples, 0.50) if len(krad_samples) >= 5 else None
    krad_end_obs = _percentile(krad_end_samples, 0.45) if len(krad_end_samples) >= 5 else (krad_obs * 0.90 if krad_obs is not None else None)
    mod_floor_obs = _percentile(steady_mods, 0.05) if len(steady_mods) >= 15 else None
    pmin_obs = _percentile(p_min_obs_list, 0.35) if len(p_min_obs_list) >= 5 else None
    lwt_drop_obs = _percentile(lwt_drops, 0.90) if lwt_drops else None
    buf_drop_obs = _percentile(buf_drops, 0.90) if buf_drops else None
    ua_obs = _percentile(ua_obs_list, 0.50) if ua_obs_list else None
    gain_obs = _percentile(gain_obs_list, 0.50) if gain_obs_list else None

    k_rad = round(_shrink(krad_obs, PRIOR_MODEL["k_rad_kw_per_k"], n_cycles, prior_weight=3.0), 3)
    k_rad = max(0.18, min(0.85, k_rad))

    k_rad_end = round(_shrink(krad_end_obs, PRIOR_MODEL["k_rad_end_kw_per_k"], n_cycles, prior_weight=3.0), 3)
    k_rad_end = max(0.18, min(k_rad, k_rad_end))

    inv_floor = round(_shrink(mod_floor_obs, PRIOR_MODEL["inverter_min_mod_pct"], n_cycles, prior_weight=2.0), 1)
    inv_floor = max(25.0, min(50.0, inv_floor))

    p_min_ref = round(_shrink(pmin_obs, PRIOR_MODEL["p_min_continuous_kw_ref"], n_cycles, prior_weight=3.0), 2)
    p_min_ref = max(2.5, min(6.0, p_min_ref))

    defrost_lwt_drop = round(_shrink(lwt_drop_obs, PRIOR_MODEL["defrost_lwt_drop_p90_k"], n_defrosts, prior_weight=4.0), 1)
    defrost_lwt_drop = max(6.0, min(14.0, defrost_lwt_drop))

    defrost_buf_drop = round(_shrink(buf_drop_obs, PRIOR_MODEL["defrost_buf_drop_p90_k"], n_defrosts, prior_weight=4.0), 1)
    defrost_buf_drop = max(2.0, min(7.0, defrost_buf_drop))

    ua_building = round(_shrink(ua_obs, PRIOR_MODEL["ua_building_c_24h_per_k"], n_standby, prior_weight=3.0), 3)
    ua_building = max(0.05, min(0.45, ua_building))

    alpha_heat = round(_shrink(gain_obs, PRIOR_MODEL["alpha_heat_c_h_per_k"], n_cycles, prior_weight=2.0), 4)
    alpha_heat = max(0.008, min(0.040, alpha_heat))

    # Confidence grows smoothly from ~25% (1 cycle) toward 95% (15+ cycles across wider OAT span)
    oat_span = (max(oat_seen) - min(oat_seen)) if len(oat_seen) >= 2 else 0.0
    conf_cycles = min(1.0, n_cycles / 10.0)
    conf_oat = min(1.0, oat_span / 12.0)
    confidence_pct = int(round(15 + 65 * conf_cycles + 20 * conf_oat))

    def _diag_entry(
        obs_val: Optional[float],
        prior_val: float,
        shrunk_val: float,
        n_obs: int,
        prior_w: float,
        raw_list: Optional[list[float]] = None,
        digits: int = 3,
    ) -> dict[str, Any]:
        w_pct = round(100.0 * n_obs / (n_obs + prior_w)) if (obs_val is not None and n_obs > 0) else 0
        iqr = None
        if raw_list and len(raw_list) >= 4:
            p75 = _percentile(raw_list, 0.75)
            p25 = _percentile(raw_list, 0.25)
            if p75 is not None and p25 is not None:
                iqr = round(p75 - p25, digits)
        status = "Convergente" if n_obs >= 8 else ("In convergenza" if n_obs >= 3 else "In raccolta")
        return {
            "prior": round(float(prior_val), digits),
            "raw_observed": round(float(obs_val), digits) if obs_val is not None else None,
            "value": shrunk_val,
            "n_obs": int(n_obs),
            "prior_weight": float(prior_w),
            "data_weight_pct": int(w_pct),
            "spread_iqr": iqr,
            "status": status,
        }

    diagnostics = {
        "k_rad_kw_per_k": _diag_entry(krad_obs, PRIOR_MODEL["k_rad_kw_per_k"], k_rad, n_cycles, 3.0, krad_samples, 3),
        "k_rad_end_kw_per_k": _diag_entry(krad_end_obs, PRIOR_MODEL["k_rad_end_kw_per_k"], k_rad_end, n_cycles, 3.0, krad_end_samples, 3),
        "inverter_min_mod_pct": _diag_entry(mod_floor_obs, PRIOR_MODEL["inverter_min_mod_pct"], inv_floor, n_cycles, 2.0, steady_mods, 1),
        "p_min_continuous_kw_ref": _diag_entry(pmin_obs, PRIOR_MODEL["p_min_continuous_kw_ref"], p_min_ref, n_cycles, 3.0, p_min_obs_list, 2),
        "defrost_lwt_drop_p90_k": _diag_entry(lwt_drop_obs, PRIOR_MODEL["defrost_lwt_drop_p90_k"], defrost_lwt_drop, n_defrosts, 4.0, lwt_drops, 1),
        "defrost_buf_drop_p90_k": _diag_entry(buf_drop_obs, PRIOR_MODEL["defrost_buf_drop_p90_k"], defrost_buf_drop, n_defrosts, 4.0, buf_drops, 1),
        "ua_building_c_24h_per_k": _diag_entry(ua_obs, PRIOR_MODEL["ua_building_c_24h_per_k"], ua_building, n_standby, 3.0, ua_obs_list, 3),
        "alpha_heat_c_h_per_k": _diag_entry(gain_obs, PRIOR_MODEL["alpha_heat_c_h_per_k"], alpha_heat, n_cycles, 2.0, gain_obs_list, 4),
    }

    return {
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "cycles_observed": n_cycles,
        "defrost_episodes_observed": len(defrost_episodes),
        "defrost_steady_observed": n_defrosts,
        "standby_segments_observed": n_standby,
        "oat_range_observed_c": [round(min(oat_seen), 1), round(max(oat_seen), 1)] if oat_seen else None,
        "confidence_pct": confidence_pct,
        "k_rad_kw_per_k": k_rad,
        "k_rad_end_kw_per_k": k_rad_end,
        "inverter_min_mod_pct": inv_floor,
        "p_min_continuous_kw_ref": p_min_ref,
        "defrost_lwt_drop_p90_k": defrost_lwt_drop,
        "defrost_buf_drop_p90_k": defrost_buf_drop,
        "ua_building_c_24h_per_k": ua_building,
        "alpha_heat_c_h_per_k": alpha_heat,
        "bphe_safe_outlet_min_c": PRIOR_MODEL["bphe_safe_outlet_min_c"],
        "diagnostics": diagnostics,
    }


def _eval_standby_ua(seg: list[tuple[datetime, dict[str, Any]]], out: list[float]) -> None:
    # Skip first 2 hours after a heating cycle (radiant slab still releasing heat)
    t_start = seg[0][0]
    trimmed = [(dt, s) for dt, s in seg if (dt - t_start).total_seconds() >= 7200]
    if len(trimmed) < 6:
        return
    span_h = (trimmed[-1][0] - trimmed[0][0]).total_seconds() / 3600.0
    if span_h < 8.0:
        return
    tins = [float(s["indoor_temp_bticino_c"]) for _, s in trimmed if s.get("indoor_temp_bticino_c") is not None]
    oats = [float(s["external_temp_c"]) for _, s in trimmed if s.get("external_temp_c") is not None]
    if len(tins) < 4 or len(oats) < 4:
        return
    loss_per_24h = (tins[0] - tins[-1]) * (24.0 / span_h)
    avg_dt_env = (sum(tins) / len(tins)) - (sum(oats) / len(oats))
    if loss_per_24h > 0.1 and avg_dt_env >= 2.0:
        ua = loss_per_24h / avg_dt_env
        if 0.04 <= ua <= 0.50:
            out.append(ua)


def recommend_operating_targets(
    model: dict[str, Any],
    t_in: float,
    oat: float,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """
    Computes non-hardcoded optimal operating targets from the converged physical model,
    strictly bounded by the user's configured guardrails.
    """
    k_rad = float(model.get("k_rad_kw_per_k") or PRIOR_MODEL["k_rad_kw_per_k"])
    # Use asymptotic late-cycle k_rad_end when identified (slab already warm at hours 2-5!)
    k_rad_anti = float(model["k_rad_end_kw_per_k"]) if model.get("k_rad_end_kw_per_k") is not None else k_rad
    p_min_ref = float(model.get("p_min_continuous_kw_ref") or PRIOR_MODEL["p_min_continuous_kw_ref"])
    lwt_drop = float(model.get("defrost_lwt_drop_p90_k") or PRIOR_MODEL["defrost_lwt_drop_p90_k"])
    ua = float(model.get("ua_building_c_24h_per_k") or PRIOR_MODEL["ua_building_c_24h_per_k"])
    alpha_heat = float(model.get("alpha_heat_c_h_per_k") or PRIOR_MODEL["alpha_heat_c_h_per_k"])
    bphe_min_c = float(model.get("bphe_safe_outlet_min_c") or 12.0)

    # 1. Anti-ON/OFF floor: Buffer must dissipate >= 1.15 * P_min(OAT) ALL THE WAY through the cycle.
    # Evaluate against expected end-of-cycle indoor temp (t_in + 0.8 C, capped at t_max) so that
    # even as the room warms up and (LWT - T_in) narrows, the radiant floor still absorbs P_min(OAT)
    # without tripping WO1C saturation cutoff (param 7209) at mild OAT (+4..+10 C).
    t_max = float(cfg.get("t_max_c") or 8.8)
    t_min_cfg = float(cfg.get("t_min_c") or 7.5)
    min_end_t = float(cfg.get("min_cycle_end_temp_c") or 8.2)
    ref_tin_end = min(t_max, float(t_in) + 0.8)
    p_min_at_oat = p_min_ref * max(0.72, min(1.30, 1.0 + 0.025 * (float(oat) - 4.0)))
    dt_anti_onoff = (p_min_at_oat * 1.15) / max(0.18, k_rad_anti)
    t_buf_anti_onoff = ref_tin_end + max(float(cfg.get("defrost_min_delta_k") or 13.5), dt_anti_onoff)

    # 2. BPHE Defrost thermal reserve floor (active when OAT <= defrost_guard_oat_max_c + 1.5 C)
    oat_frost_lim = float(cfg.get("defrost_guard_oat_max_c") or 5.5)
    t_buf_bphe_safe = bphe_min_c + lwt_drop if float(oat) <= oat_frost_lim + 1.5 else float(cfg.get("defrost_min_safe_lwt_c") or 22.0)
    t_buf_bphe_safe = max(float(cfg.get("defrost_min_safe_lwt_c") or 22.0), t_buf_bphe_safe)

    # 3. Cold-weather thermal demand (SCOP-first: prefer longer gentle low-LWT cycles over high LWT):
    # alpha_heat is calibrated on NET indoor rise at reference OAT ~ +5 C, so only extra heat loss
    # below +5 C is added (no double-counting). When starting cold (< t_min), use the adaptive
    # duration budget (+1.5h extension) targeting min_end_t (8.2 C) so LWT stays low (~22.5-24 C)
    # for OAT >= 0 C and scales progressively toward max_target_lwt_c (26.5 C) only on real frost (OAT <= -2..-8 C).
    base_cycle_h = max(2.0, float(cfg.get("max_cycle_minutes") or 300) / 60.0)
    est_loss_24h = max(0.2, ua * max(1.0, float(t_in) - float(oat)))
    extra_cold_loss_c_h = (ua / 24.0) * max(0.0, 5.0 - float(oat))
    if float(t_in) < t_min_cfg - 0.15:
        target_end_c = max(min_end_t, float(t_in) + 1.3)
        eff_cycle_h = base_cycle_h + 1.5
    else:
        target_end_c = min(t_max, max(min_end_t, float(t_in) + 1.1))
        eff_cycle_h = base_cycle_h + (0.5 if float(oat) < 0.0 else 0.0)
    req_rise_rate_c_h = (max(0.4, target_end_c - float(t_in)) / eff_cycle_h) + extra_cold_loss_c_h
    t_buf_cold_demand = float(t_in) + (req_rise_rate_c_h / max(0.008, alpha_heat))

    # Optimal buffer target balances all 3 physical constraints while keeping modulation low (~40-55%)
    raw_optimal = max(t_buf_anti_onoff, t_buf_bphe_safe, min(t_buf_cold_demand, float(cfg.get("max_target_lwt_c") or 26.5)))
    min_lim = float(cfg.get("min_target_lwt_c") or 22.5)
    max_lim = float(cfg.get("max_target_lwt_c") or 26.5)
    clamped = round(max(min_lim, min(max_lim, raw_optimal)), 1)

    est_autonomy_h = round(((t_max - float(cfg.get("t_min_c") or 7.5)) / max(0.05, est_loss_24h)) * 24.0, 1)

    return {
        "recommended_target_lwt_c": clamped,
        "anti_onoff_floor_c": round(t_buf_anti_onoff, 1),
        "bphe_defrost_floor_c": round(t_buf_bphe_safe, 1),
        "cold_demand_target_c": round(t_buf_cold_demand, 1),
        "pred_standby_loss_c_24h": round(est_loss_24h, 2),
        "pred_autonomy_hours": est_autonomy_h,
        "p_min_at_oat_kw": round(p_min_at_oat, 2),
    }


def load_thermal_model(model_file: Optional[Path] = None) -> dict[str, Any]:
    target = model_file or MODEL_FILE
    if target.exists():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                merged = dict(PRIOR_MODEL)
                merged.update(loaded)
                return merged
        except Exception:
            pass
    return dict(PRIOR_MODEL)


def save_thermal_model(model: dict[str, Any], model_file: Optional[Path] = None) -> dict[str, Any]:
    target = model_file or MODEL_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return model


TRACKED_MODEL_PARAMS = (
    ("k_rad_kw_per_k", "k_rad", 3),
    ("inverter_min_mod_pct", "FloorInv", 1),
    ("p_min_continuous_kw_ref", "P_min", 2),
    ("defrost_lwt_drop_p90_k", "ΔBPHE_def", 1),
    ("ua_building_c_24h_per_k", "UA", 3),
    ("alpha_heat_c_h_per_k", "Resa_α", 4),
)


def update_model_from_log(
    write_file: bool = True,
    log_path: Optional[Path] = None,
    model_file: Optional[Path] = None,
) -> dict[str, Any]:
    log_p = log_path or (Config.DATA_DIR / "cloud_telemetry.jsonl")
    mod_p = model_file or MODEL_FILE
    samples: list[dict[str, Any]] = []
    if log_p.exists():
        for line in log_p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    samples.append(json.loads(line))
                except Exception:
                    pass

    prev: dict[str, Any] = {}
    if mod_p.exists():
        try:
            loaded = json.loads(mod_p.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                prev = loaded
        except Exception:
            prev = {}

    model = fit_thermal_model(samples)

    last_deltas: dict[str, float] = {}
    changes: list[str] = []
    any_param_changed = False
    for key, label, digits in TRACKED_MODEL_PARAMS:
        if prev and prev.get(key) is not None:
            delta = round(float(model[key]) - float(prev[key]), 4)
            last_deltas[key] = delta
            if abs(delta) >= 0.0005:
                any_param_changed = True
                changes.append(f"{label}: {float(prev[key]):.{digits}f} → {float(model[key]):.{digits}f} ({delta:+.{digits}f})")
        else:
            last_deltas[key] = 0.0

    if not changes:
        changes = ["Nessuna variazione (parametri stabili)"]

    history = [h for h in (prev.get("history") or []) if isinstance(h, dict)]
    last_hist = history[-1] if history else None
    obs_grew = bool(
        last_hist is None
        or model["cycles_observed"] > int(last_hist.get("cycles_observed") or 0)
        or model["standby_segments_observed"] > int(last_hist.get("standby_segments_observed") or 0)
        or model["defrost_steady_observed"] > int(last_hist.get("defrost_steady_observed") or 0)
    )
    if any_param_changed or obs_grew:
        history.append({
            "ts_utc": model["updated_utc"],
            "cycles_observed": model["cycles_observed"],
            "defrost_steady_observed": model["defrost_steady_observed"],
            "standby_segments_observed": model["standby_segments_observed"],
            "confidence_pct": model["confidence_pct"],
            "k_rad_kw_per_k": model["k_rad_kw_per_k"],
            "inverter_min_mod_pct": model["inverter_min_mod_pct"],
            "defrost_lwt_drop_p90_k": model["defrost_lwt_drop_p90_k"],
            "ua_building_c_24h_per_k": model["ua_building_c_24h_per_k"],
            "alpha_heat_c_h_per_k": model["alpha_heat_c_h_per_k"],
            "deltas": last_deltas,
            "changes": changes,
        })
        history = history[-40:]

    model["last_deltas"] = last_deltas
    model["history"] = history

    if write_file:
        save_thermal_model(model, model_file=mod_p)
    return model


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrazione Modello Matematico Termodinamico Vitocal 111-S")
    parser.add_argument("--write", action="store_true", help="Salva il modello aggiornato in data/thermal_model.json")
    args = parser.parse_args()

    model = update_model_from_log(write_file=args.write)
    cfg_path = Config.DATA_DIR / "autopilot_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}

    print("=" * 78)
    print("  VITOCAL REMOTE - MODELLO MATEMATICO AUTO-CONVERGENTE")
    print("=" * 78)
    print(f"Cicli validi osservati : {model['cycles_observed']} | Defrost stazionari: {model['defrost_steady_observed']} | Standby: {model['standby_segments_observed']}")
    print(f"Range OAT osservato    : {model['oat_range_observed_c']} °C | Confidenza modello: {model['confidence_pct']}%")
    print(f"k_rad (pavimento)      : {model['k_rad_kw_per_k']:.3f} kW/K")
    print(f"Floor Inverter reale   : {model['inverter_min_mod_pct']:.1f}% (~{model['p_min_continuous_kw_ref']:.2f} kW_t a OAT +4°C)")
    print(f"Caduta Defrost (p90)   : ΔLWT_BPHE = -{model['defrost_lwt_drop_p90_k']:.1f} K | ΔPuffer = -{model['defrost_buf_drop_p90_k']:.1f} K")
    print(f"Dispersione Edificio UA: {model['ua_building_c_24h_per_k']:.3f} (°C/24h)/K | Resa diretta α: {model['alpha_heat_c_h_per_k']:.4f} (°C/h)/K")

    diag = model.get("diagnostics") or {}
    deltas = model.get("last_deltas") or {}
    if diag:
        print("\n--- CONVERGENZA BAYESIANA (Prior -> Osservato -> Convergente) ---")
        for key, lbl, digits in TRACKED_MODEL_PARAMS:
            d = diag.get(key) or {}
            obs_str = f"{d['raw_observed']:.{digits}f}" if d.get("raw_observed") is not None else "--"
            dl = float(deltas.get(key) or 0.0)
            dl_str = f"{dl:+.{digits}f}" if abs(dl) >= 0.0005 else "invariato"
            print(
                f"  {lbl:9s}: prior={d.get('prior'):.{digits}f} | obs={obs_str:>6s} | conv={d.get('value'):.{digits}f} "
                f"| peso dati={d.get('data_weight_pct', 0):2d}% (n={d.get('n_obs', 0)}) | Δ={dl_str} [{d.get('status', '--')}]"
            )

    hist = model.get("history") or []
    if hist:
        print("\n--- ULTIME REVISIONI SELF-TUNING ---")
        for entry in hist[-3:]:
            ts_short = str(entry.get("ts_utc") or "")[:16].replace("T", " ")
            chg = "; ".join(entry.get("changes") or [])
            print(f"  [{ts_short}] cicli={entry.get('cycles_observed')} standby={entry.get('standby_segments_observed')} | {chg}")

    print("\n--- PROIEZIONI DINAMICHE DEL MODELLO (T_casa = 7.5 °C) ---")
    for oat in (8.0, 4.0, 0.0, -5.0, -10.0):
        rec = recommend_operating_targets(model, t_in=7.5, oat=oat, cfg=cfg)
        print(
            f"  OAT={oat:+5.1f}°C -> Target={rec['recommended_target_lwt_c']:4.1f}°C "
            f"(Anti-ON/OFF≥{rec['anti_onoff_floor_c']:4.1f} | BPHE≥{rec['bphe_defrost_floor_c']:4.1f} | Freddo={rec['cold_demand_target_c']:4.1f}) "
            f"| Perdita={rec['pred_standby_loss_c_24h']:.2f}°C/24h | Autonomia≈{rec['pred_autonomy_hours']:.0f}h"
        )
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
