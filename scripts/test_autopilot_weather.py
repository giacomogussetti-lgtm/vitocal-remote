"""
Comprehensive isolated unit & scenario tests for Weather-Aware Autopilot & Dynamic COP Window.
Uses synthetic weather fixtures and temporary state/config files (zero real API calls,
zero live data mutation, zero real geographic coordinates).

Usage:
    python scripts/test_autopilot_weather.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts import autopilot
from scripts import weather_planner as wp


def _rome_tz():
    return wp._get_rome_tz()


def _make_hourly_series(
    start_local: datetime,
    hours: int,
    day1_temp_fn,
    day1_rh_fn,
    day2_temp_fn=None,
    day2_rh_fn=None,
    precip_fn=None,
    solar_fn=None,
) -> list[dict[str, Any]]:
    day1_str = start_local.strftime("%Y-%m-%d")
    out: list[dict[str, Any]] = []
    base = start_local.replace(minute=0, second=0, microsecond=0)
    for h in range(hours):
        dt = base + timedelta(hours=h)
        is_d1 = (dt.strftime("%Y-%m-%d") == day1_str)
        t_fn = day1_temp_fn if is_d1 or day2_temp_fn is None else day2_temp_fn
        r_fn = day1_rh_fn if is_d1 or day2_rh_fn is None else day2_rh_fn
        out.append({
            "time_local": dt.strftime("%Y-%m-%dT%H:00"),
            "temp_raw_c": float(t_fn(dt.hour)),
            "rh_pct": int(r_fn(dt.hour)),
            "dew_point_c": None,
            "precip_mm": float(precip_fn(dt.hour, is_d1)) if precip_fn else 0.0,
            "snowfall_cm": 0.0,
            "wmo_code": 0,
            "solar_wm2": float(solar_fn(dt.hour, is_d1)) if solar_fn else 0.0,
            "wind_kmh": 4.0,
        })
    return out


def _write_weather_cache(cache_path: Path, fetched_utc: datetime, hourly: list[dict[str, Any]], cal_hist=None) -> None:
    payload = {
        "location_label": "Abitazione di Montagna (Zona Climatica E)",
        "model": "Test Fixture",
        "fetched_utc": fetched_utc.isoformat(),
        "hourly": hourly,
        "calibration": {},
        "calibration_history": cal_hist or [],
        "prediction_history": [],
    }
    cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _sample(ts_utc: datetime, t_in: float, oat: float = 4.0, buf: float = 12.0) -> dict[str, Any]:
    return {
        "timestamp_utc": ts_utc.isoformat(),
        "indoor_temp_bticino_c": t_in,
        "external_temp_c": oat,
        "buffer_temp_c": buf,
        "pdc_return_temp_c": buf - 0.5,
        "pdc_supply_temp_c": buf + 0.5,
        "heating_curve_slope": 0.6,
        "heating_curve_shift": 0,
        "grundfos_pump_active": 0,
        "compressor_active": 0,
        "compressor_modulation_percent": 0,
        "compressor_phase": "off",
        "frost_protection_status": "off",
    }


def _run_case(name: str, fn) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        cfg_file = tmp_dir / "autopilot_config.json"
        st_file = tmp_dir / "autopilot_state.json"
        wx_file = tmp_dir / "weather_forecast.json"
        with patch.object(autopilot, "CONFIG_FILE", cfg_file), \
             patch.object(autopilot, "STATE_FILE", st_file), \
             patch.object(autopilot, "_load_recent_samples", return_value=[]):
            fn(cfg_file, st_file, wx_file)
    print(f"  [PASS] {name}")


def test_1_short_cycle_deferral(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    tz = _rome_tz()
    now_local = datetime(2026, 11, 27, 15, 40, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True, weather_dynamic_window_enabled=False)
    autopilot.save_config(cfg)
    autopilot.save_state({
        "state": "ARMED",
        "state_since_utc": (now_utc - timedelta(minutes=30)).isoformat(),
    })
    hourly = _make_hourly_series(
        now_local.replace(hour=0),
        48,
        day1_temp_fn=lambda h: 7.0 if 11 <= h <= 16 else 6.5,
        day1_rh_fn=lambda h: 65,
    )
    _write_weather_cache(wx_file, now_utc, hourly)
    res = autopilot.run_autopilot_tick(
        _sample(now_utc, t_in=7.6, oat=7.0),
        dry_run=True,
        now_utc_override=now_utc,
        weather_cache_file=wx_file,
    )
    assert res["state"] == "ARMED", f"Expected ARMED (short-cycle defer), got {res['state']}"
    assert res["weather_plan"]["short_cycle_action"] == "defer_short_cycle"


def test_2_short_cycle_extension_and_no_1600_cutoff(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    tz = _rome_tz()
    now_local = datetime(2026, 11, 27, 15, 40, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True, weather_dynamic_window_enabled=False)
    autopilot.save_config(cfg)
    autopilot.save_state({
        "state": "ARMED",
        "state_since_utc": (now_utc - timedelta(minutes=30)).isoformat(),
    })
    # Severe freeze overnight (-12 C) pushes projected T_in below safe floor (7.2 C)
    hourly = _make_hourly_series(
        now_local.replace(hour=0),
        48,
        day1_temp_fn=lambda h: -12.0,
        day1_rh_fn=lambda h: 80,
    )
    _write_weather_cache(wx_file, now_utc, hourly)
    res1 = autopilot.run_autopilot_tick(
        _sample(now_utc, t_in=7.4, oat=-5.0),
        dry_run=True,
        now_utc_override=now_utc,
        weather_cache_file=wx_file,
    )
    assert res1["state"] == "HEATING_SYNC", f"Expected HEATING_SYNC extension, got {res1['state']}"
    assert res1["active_window_end_local"] == "17:40", f"Expected 17:40 end, got {res1['active_window_end_local']}"

    # Advance to 16:15 (past static 16:00): must stay in HEATING_SYNC until 17:40!
    later_local = datetime(2026, 11, 27, 16, 15, tzinfo=tz)
    later_utc = later_local.astimezone(timezone.utc)
    res2 = autopilot.run_autopilot_tick(
        _sample(later_utc, t_in=7.7, oat=-6.0, buf=22.0),
        dry_run=True,
        now_utc_override=later_utc,
        weather_cache_file=wx_file,
    )
    assert res2["state"] == "HEATING_SYNC", f"Must not cut off at 16:00 during extension, got {res2['state']}"


def test_3_predictive_prearm_night_freeze_and_no_bounce(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    tz = _rome_tz()
    now_local = datetime(2026, 11, 27, 12, 0, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True, weather_dynamic_window_enabled=False)
    autopilot.save_config(cfg)
    autopilot.save_state({"state": "IDLE", "state_since_utc": (now_utc - timedelta(hours=4)).isoformat()})
    hourly = _make_hourly_series(
        now_local.replace(hour=0),
        48,
        day1_temp_fn=lambda h: 1.0 if 11 <= h <= 16 else -10.0,
        day1_rh_fn=lambda h: 75,
    )
    _write_weather_cache(wx_file, now_utc, hourly)
    # T_in = 7.85 (> T_min 7.5 + 0.3!) -> normally would bounce back in ARMED, must NOT bounce!
    res1 = autopilot.run_autopilot_tick(
        _sample(now_utc, t_in=7.85, oat=1.0),
        dry_run=True,
        now_utc_override=now_utc,
        weather_cache_file=wx_file,
    )
    assert res1["state"] == "ARMED", f"Expected predictive IDLE->ARMED, got {res1['state']}"
    assert res1["armed_by_prearm"] is True

    # Next tick 5 min later: must transition ARMED -> HEATING_SYNC (NOT bounce to IDLE!)
    t2_utc = now_utc + timedelta(minutes=5)
    res2 = autopilot.run_autopilot_tick(
        _sample(t2_utc, t_in=7.85, oat=1.0),
        dry_run=True,
        now_utc_override=t2_utc,
        weather_cache_file=wx_file,
    )
    assert res2["state"] == "HEATING_SYNC", f"Expected ARMED->HEATING_SYNC after prearm, got {res2['state']}"


def test_4_no_prearm_when_warm(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    tz = _rome_tz()
    now_local = datetime(2026, 11, 27, 12, 0, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True)
    autopilot.save_config(cfg)
    autopilot.save_state({"state": "IDLE", "state_since_utc": (now_utc - timedelta(hours=4)).isoformat()})
    hourly = _make_hourly_series(
        now_local.replace(hour=0),
        48,
        day1_temp_fn=lambda h: -8.0,
        day1_rh_fn=lambda h: 80,
    )
    _write_weather_cache(wx_file, now_utc, hourly)
    res = autopilot.run_autopilot_tick(
        _sample(now_utc, t_in=8.5, oat=0.0),
        dry_run=True,
        now_utc_override=now_utc,
        weather_cache_file=wx_file,
    )
    assert res["state"] == "IDLE", f"Warm house (8.5C) must stay IDLE, got {res['state']}"


def test_5_weather_arbitrage_deferral(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    tz = _rome_tz()
    now_local = datetime(2026, 11, 27, 12, 0, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True, weather_dynamic_window_enabled=False)
    autopilot.save_config(cfg)
    autopilot.save_state({"state": "ARMED", "state_since_utc": (now_utc - timedelta(minutes=40)).isoformat()})
    # Today foggy wet +2.5C / 96% RH (heavy frost), tomorrow sunny +9C / 50% RH, overnight mild (+6.5C)
    hourly = _make_hourly_series(
        now_local.replace(hour=0),
        48,
        day1_temp_fn=lambda h: 2.5 if 10 <= h <= 17 else 6.5,
        day1_rh_fn=lambda h: 96,
        day2_temp_fn=lambda h: 9.0 if 11 <= h <= 16 else 6.5,
        day2_rh_fn=lambda h: 50,
    )
    _write_weather_cache(wx_file, now_utc, hourly)
    res = autopilot.run_autopilot_tick(
        _sample(now_utc, t_in=7.7, oat=2.5),
        dry_run=True,
        now_utc_override=now_utc,
        weather_cache_file=wx_file,
    )
    assert res["state"] == "ARMED", f"Expected arbitrage deferral in ARMED, got {res['state']}"
    assert res["weather_deferred_date"] == "2026-11-27"


def test_6_safety_override_blocks_deferral(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    tz = _rome_tz()
    now_local = datetime(2026, 11, 27, 12, 0, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True, weather_dynamic_window_enabled=False)
    autopilot.save_config(cfg)
    autopilot.save_state({"state": "ARMED", "state_since_utc": (now_utc - timedelta(minutes=40)).isoformat()})
    hourly = _make_hourly_series(
        now_local.replace(hour=0),
        48,
        day1_temp_fn=lambda h: 0.5,
        day1_rh_fn=lambda h: 96,
        day2_temp_fn=lambda h: 8.5 if 11 <= h <= 16 else 3.5,
        day2_rh_fn=lambda h: 50,
    )
    _write_weather_cache(wx_file, now_utc, hourly)
    # T_in = 7.1 C <= safe_floor (7.2 C) -> must refuse deferral and start today!
    res = autopilot.run_autopilot_tick(
        _sample(now_utc, t_in=7.1, oat=0.5),
        dry_run=True,
        now_utc_override=now_utc,
        weather_cache_file=wx_file,
    )
    assert res["state"] == "HEATING_SYNC", f"Expected safety override HEATING_SYNC, got {res['state']}"


def test_7_anti_starvation_prevents_double_deferral(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    tz = _rome_tz()
    now_local = datetime(2026, 11, 27, 12, 0, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True, weather_dynamic_window_enabled=False)
    autopilot.save_config(cfg)
    autopilot.save_state({
        "state": "ARMED",
        "state_since_utc": (now_utc - timedelta(hours=20)).isoformat(),
        "weather_deferred_date": "2026-11-26",
    })
    hourly = _make_hourly_series(
        now_local.replace(hour=0),
        48,
        day1_temp_fn=lambda h: 2.5 if 10 <= h <= 17 else 6.5,
        day1_rh_fn=lambda h: 96,
        day2_temp_fn=lambda h: 9.0 if 11 <= h <= 16 else 6.5,
        day2_rh_fn=lambda h: 50,
    )
    _write_weather_cache(wx_file, now_utc, hourly)
    res = autopilot.run_autopilot_tick(
        _sample(now_utc, t_in=7.7, oat=2.5),
        dry_run=True,
        now_utc_override=now_utc,
        weather_cache_file=wx_file,
    )
    assert res["state"] == "HEATING_SYNC", f"Anti-starvation must force start today, got {res['state']}"


def test_8_night_emergency_overrides_all(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    tz = _rome_tz()
    now_local = datetime(2026, 11, 27, 3, 30, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True)
    autopilot.save_config(cfg)
    autopilot.save_state({"state": "ARMED", "state_since_utc": (now_utc - timedelta(hours=2)).isoformat()})
    hourly = _make_hourly_series(now_local.replace(hour=0), 48, lambda h: 2.0, lambda h: 80)
    _write_weather_cache(wx_file, now_utc, hourly)
    res = autopilot.run_autopilot_tick(
        _sample(now_utc, t_in=6.7, oat=-4.0),
        dry_run=True,
        now_utc_override=now_utc,
        weather_cache_file=wx_file,
    )
    assert res["state"] == "HEATING_SYNC"
    assert res["cycle_is_emergency"] is True


def test_9_dynamic_window_selection_and_lock(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    tz = _rome_tz()
    now_local = datetime(2026, 11, 27, 12, 30, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True, weather_dynamic_window_enabled=True)
    autopilot.save_config(cfg)
    autopilot.save_state({"state": "ARMED", "state_since_utc": (now_utc - timedelta(minutes=30)).isoformat()})
    # Cold/foggy at 11:00 (-2C/95%), warm sunny 12:00-17:00 (+8C/55%) -> picks 12:00-17:00
    hourly = _make_hourly_series(
        now_local.replace(hour=0),
        48,
        day1_temp_fn=lambda h: 8.0 if 12 <= h <= 16 else -2.0,
        day1_rh_fn=lambda h: 55 if 12 <= h <= 16 else 95,
        solar_fn=lambda h, d1: 450.0 if 12 <= h <= 16 else 0.0,
    )
    _write_weather_cache(wx_file, now_utc, hourly)
    res = autopilot.run_autopilot_tick(
        _sample(now_utc, t_in=7.4, oat=8.0),
        dry_run=True,
        now_utc_override=now_utc,
        weather_cache_file=wx_file,
    )
    assert res["state"] == "HEATING_SYNC"
    assert res["active_window_start_local"] == "12:00"
    assert res["active_window_end_local"] == "17:00"

    # At 16:20, even if window were re-evaluated, HEATING_SYNC stays locked until 17:00
    t2_local = datetime(2026, 11, 27, 16, 20, tzinfo=tz)
    t2_utc = t2_local.astimezone(timezone.utc)
    res2 = autopilot.run_autopilot_tick(
        _sample(t2_utc, t_in=8.0, oat=6.0, buf=22.5),
        dry_run=True,
        now_utc_override=t2_utc,
        weather_cache_file=wx_file,
    )
    assert res2["state"] == "HEATING_SYNC", f"Must stay HEATING_SYNC until 17:00, got {res2['state']}"


def test_10_offline_missing_secrets_fallback(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    tz = _rome_tz()
    now_local = datetime(2026, 11, 27, 15, 45, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True)
    autopilot.save_config(cfg)
    autopilot.save_state({"state": "ARMED", "state_since_utc": (now_utc - timedelta(minutes=30)).isoformat()})
    with patch.dict(os.environ, {"WEATHER_LAT": "", "WEATHER_LON": ""}, clear=False), \
         patch.object(wp.Config, "WEATHER_LAT", ""), \
         patch.object(wp.Config, "WEATHER_LON", ""):
        res = autopilot.run_autopilot_tick(
            _sample(now_utc, t_in=7.6, oat=8.0),
            dry_run=True,
            now_utc_override=now_utc,
            weather_cache_file=wx_file,
        )
    assert res["weather_plan"]["available"] is False
    assert res["weather_plan"]["effective_window_start"] == "11:00"
    assert res["weather_plan"]["effective_window_end"] == "16:00"
    # With 15 min left and mild oat=6.0, anti-short-cycle defers cleanly even offline!
    assert res["state"] == "ARMED"


def test_11_privacy_and_calibration(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    tz = _rome_tz()
    now_local = datetime(2026, 11, 27, 13, 0, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    hourly = _make_hourly_series(now_local.replace(hour=0), 48, lambda h: 3.0, lambda h: 75)
    cal_hist = [
        {"time_local": (now_local - timedelta(hours=k)).strftime("%Y-%m-%dT%H:00"), "temp_raw_c": 4.0, "rh_pct": 75}
        for k in range(1, 13)
    ]
    samples = [
        _sample(now_utc - timedelta(hours=k), t_in=7.8, oat=2.0)  # Consistently -2.0C colder than forecast!
        for k in range(1, 13)
    ]
    _write_weather_cache(wx_file, now_utc, hourly, cal_hist=cal_hist)
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True)
    plan = wp.evaluate_weather_plan(
        now_local=now_local,
        t_in_c=7.8,
        current_oat_c=2.0,
        cur_state="IDLE",
        cfg=cfg,
        thermal_model=None,
        recent_samples=samples,
        st={},
        dry_run=False,
        cache_file=wx_file,
    )
    bias = plan["assumptions"]["oat_bias_c"]
    assert -1.5 <= bias <= -0.8, f"Expected Bayesian shrunk OAT bias near -1.0 C, got {bias}"
    assert plan["assumptions"]["oat_raw_mae_c"] is not None
    assert plan["assumptions"]["oat_mae_c"] < plan["assumptions"]["oat_raw_mae_c"], "Bias correction must reduce MAE"
    saved_wx = json.loads(wx_file.read_text(encoding="utf-8"))
    assert len(saved_wx.get("recent_oat_checks") or []) >= 6, "Expected recent_oat_checks populated"
    assert len(saved_wx.get("calibration_log") or []) >= 1, "Expected calibration_log populated"
    raw_txt = wx_file.read_text(encoding="utf-8")
    for forbidden in ("latitude", "longitude", "elevation"):
        assert forbidden not in raw_txt, f"Privacy breach: found {forbidden} in weather_forecast.json"


def test_12_thermal_model_convergence_and_changelog(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    from scripts import thermal_model as tm
    tz = _rome_tz()
    t0 = datetime(2026, 11, 20, 0, 0, tzinfo=tz).astimezone(timezone.utc)
    tmp_dir = cfg_file.parent
    log_p = tmp_dir / "cloud_telemetry.jsonl"
    mod_p = tmp_dir / "thermal_model.json"

    # Build 1 standby segment (16h cooling from 8.4 -> 7.6 at OAT 2.0)
    rows = []
    for i in range(17):
        ts = t0 + timedelta(hours=i)
        rows.append(_sample(ts, t_in=round(8.4 - (0.05 * i), 2), oat=2.0))
    log_p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    m1 = tm.update_model_from_log(write_file=True, log_path=log_p, model_file=mod_p)
    assert "diagnostics" in m1
    assert m1["diagnostics"]["ua_building_c_24h_per_k"]["n_obs"] == 1
    assert m1["diagnostics"]["ua_building_c_24h_per_k"]["data_weight_pct"] == 25
    assert len(m1.get("history") or []) == 1

    # Re-run unchanged -> delta == 0.0 and no duplicate history entry appended
    m2 = tm.update_model_from_log(write_file=True, log_path=log_p, model_file=mod_p)
    assert abs(m2["last_deltas"]["ua_building_c_24h_per_k"]) < 1e-6
    assert len(m2["history"]) == 1, f"Unchanged re-run should not append history, got {len(m2['history'])}"

    # Add a 2nd colder/higher-loss standby segment (16h cooling 8.4 -> 7.0 at OAT 0.0) -> UA must update & log change
    t1 = t0 + timedelta(hours=24)
    # Separator active sample so segments don't merge
    rows.append({**_sample(t1 - timedelta(minutes=30), t_in=8.4, oat=0.0), "compressor_active": 1})
    for i in range(17):
        ts = t1 + timedelta(hours=i)
        rows.append(_sample(ts, t_in=round(8.4 - (0.0875 * i), 2), oat=0.0))
    log_p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    m3 = tm.update_model_from_log(write_file=True, log_path=log_p, model_file=mod_p)
    assert m3["standby_segments_observed"] == 2
    assert m3["last_deltas"]["ua_building_c_24h_per_k"] > 0.001
    assert abs(m3["last_deltas"]["k_rad_kw_per_k"]) < 1e-6, "k_rad should stay unchanged when no cycles added"
    assert len(m3["history"]) == 2
    assert any("UA:" in c for c in m3["history"][-1]["changes"])


def test_13_en14511_calibration_and_continuous_precip(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    # EN 14511 Vitocal 111.A16 checkpoints at W35: A7/W35 (~4.37-4.50), A2/W35 (~3.32), A-7/W35 (~2.72)
    pts = [
        {"time_local": "2026-11-27T12:00", "temp_raw_c": 7.0, "rh_pct": 70, "precip_mm": 0.0, "snowfall_cm": 0.0, "solar_wm2": 0.0},
        {"time_local": "2026-11-27T13:00", "temp_raw_c": 2.0, "rh_pct": 85, "precip_mm": 0.0, "snowfall_cm": 0.0, "solar_wm2": 0.0},
        {"time_local": "2026-11-27T14:00", "temp_raw_c": -7.0, "rh_pct": 80, "precip_mm": 0.0, "snowfall_cm": 0.0, "solar_wm2": 0.0},
    ]
    res_w35 = wp.score_hourly_cop(pts, lwt_ref_c=35.0)
    assert 4.20 <= res_w35[0]["cop_dry"] <= 4.55, f"A7/W35 out of EN14511 range: {res_w35[0]['cop_dry']}"
    assert 3.15 <= res_w35[1]["cop_net"] <= 3.50, f"A2/W35 out of EN14511 range: {res_w35[1]['cop_net']}"
    assert 2.55 <= res_w35[2]["cop_net"] <= 2.95, f"A-7/W35 out of EN14511 range: {res_w35[2]['cop_net']}"

    # Continuous rain check: 0.4 mm light rain at +2.8C must NOT cause an artificial -0.36 COP jump vs +2.4C dry
    rain_pts = [
        {"time_local": "2026-11-27T16:00", "temp_raw_c": 2.8, "rh_pct": 97, "precip_mm": 0.4, "snowfall_cm": 0.0, "solar_wm2": 0.0},
        {"time_local": "2026-11-27T17:00", "temp_raw_c": 2.4, "rh_pct": 97, "precip_mm": 0.0, "snowfall_cm": 0.0, "solar_wm2": 0.0},
    ]
    res_rain = wp.score_hourly_cop(rain_pts, lwt_ref_c=23.0)
    assert abs(res_rain[0]["cop_net"] - res_rain[1]["cop_net"]) <= 0.12, (
        f"Binary rain cliff still present: {res_rain[0]['cop_net']} vs {res_rain[1]['cop_net']}"
    )


def test_14_horizon_lock_and_emergency_ceiling_guard(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    tz = _rome_tz()
    # Part A: 10:00 inside 90-min pre-start lock of committed 11:00-16:00 -> must NOT chase 13:00-18:00
    t_a_local = datetime(2026, 11, 27, 10, 0, tzinfo=tz)
    t_a_utc = t_a_local.astimezone(timezone.utc)
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True, weather_dynamic_window_enabled=True, window_lock_before_start_minutes=90)
    autopilot.save_config(cfg)
    autopilot.save_state({
        "state": "ARMED",
        "state_since_utc": (t_a_utc - timedelta(hours=3)).isoformat(),
        "committed_window_date": "2026-11-27",
        "committed_window_start": "11:00",
        "committed_window_end": "16:00",
    })
    hourly_a = _make_hourly_series(
        t_a_local.replace(hour=0),
        48,
        day1_temp_fn=lambda h: 8.0 if 13 <= h <= 17 else 1.5,
        day1_rh_fn=lambda h: 55 if 13 <= h <= 17 else 90,
        solar_fn=lambda h, d1: 450.0 if 13 <= h <= 17 else 0.0,
    )
    _write_weather_cache(wx_file, t_a_utc, hourly_a)
    res_a = autopilot.run_autopilot_tick(
        _sample(t_a_utc, t_in=7.4, oat=2.0),
        dry_run=True,
        now_utc_override=t_a_utc,
        weather_cache_file=wx_file,
    )
    assert res_a["weather_plan"]["window_locked"] is True
    assert res_a["weather_plan"]["effective_window_start"] == "11:00"
    assert res_a["weather_plan"]["effective_window_end"] == "16:00"

    # Part B: Emergency-Ceiling Guard: at 02:30 with T_in=7.2C and cold morning (proj <= 7.0C before 13:00),
    # must NOT postpone start past static 11:00 even if 13:00-18:00 looks slightly warmer
    t_b_local = datetime(2026, 11, 28, 2, 30, tzinfo=tz)
    t_b_utc = t_b_local.astimezone(timezone.utc)
    autopilot.save_state({
        "state": "ARMED",
        "state_since_utc": (t_b_utc - timedelta(hours=4)).isoformat(),
    })
    hourly_b = _make_hourly_series(
        t_b_local.replace(hour=0),
        48,
        day1_temp_fn=lambda h: 5.0 if 13 <= h <= 17 else -2.0,
        day1_rh_fn=lambda h: 65 if 13 <= h <= 17 else 92,
    )
    _write_weather_cache(wx_file, t_b_utc, hourly_b)
    res_b = autopilot.run_autopilot_tick(
        _sample(t_b_utc, t_in=7.2, oat=0.0),
        dry_run=True,
        now_utc_override=t_b_utc,
        weather_cache_file=wx_file,
    )
    assert res_b["weather_plan"]["effective_window_start"] <= "11:00", (
        f"Emergency ceiling failed, postponed to {res_b['weather_plan']['effective_window_start']}"
    )


def test_15_min_cycle_end_temp_extension(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    tz = _rome_tz()
    t1_local = datetime(2026, 11, 27, 16, 5, tzinfo=tz)
    t1_utc = t1_local.astimezone(timezone.utc)
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True, min_cycle_end_temp_c=8.2, max_cycle_minutes=300)
    autopilot.save_config(cfg)
    autopilot.save_state({
        "state": "HEATING_SYNC",
        "state_since_utc": (t1_utc - timedelta(minutes=300)).isoformat(),
        "cycle_started_utc": (t1_utc - timedelta(minutes=300)).isoformat(),
        "active_window_start_local": "11:00",
        "active_window_end_local": "16:00",
        "min_end_temp_extended": False,
        "min_end_ext_count": 0,
        "calculated_target_lwt_c": 24.0,
        "calculated_pdc_setpoint_c": 14,
        "target_pdc_setpoint_c": 14,
    })
    hourly = _make_hourly_series(t1_local.replace(hour=0), 48, lambda h: 3.0, lambda h: 75)
    _write_weather_cache(wx_file, t1_utc, hourly)

    # At 16:05 (300m elapsed) T_in=7.9 < 8.2 -> extends window +60 min (to 17:05) and keeps HEATING_SYNC
    res1 = autopilot.run_autopilot_tick(
        _sample(t1_utc, t_in=7.9, oat=3.0, buf=23.5),
        dry_run=True,
        now_utc_override=t1_utc,
        weather_cache_file=wx_file,
    )
    assert res1["state"] == "HEATING_SYNC", f"Expected min-end-temp extension, got {res1['state']}"
    assert res1["min_end_temp_extended"] is True
    assert res1["min_end_ext_count"] == 1
    assert res1["active_window_end_local"] == "17:05"

    # Regression test for stop_max_dur bug: 6 min later (306m elapsed, T_in=8.0 < 8.2) MUST stay in HEATING_SYNC!
    t_mid_local = datetime(2026, 11, 27, 16, 11, tzinfo=tz)
    t_mid_utc = t_mid_local.astimezone(timezone.utc)
    res_mid = autopilot.run_autopilot_tick(
        _sample(t_mid_utc, t_in=8.0, oat=3.0, buf=23.5),
        dry_run=True,
        now_utc_override=t_mid_utc,
        weather_cache_file=wx_file,
    )
    assert res_mid["state"] == "HEATING_SYNC", f"Bug regression: stopped early at 306m ({res_mid['last_action_reason']})"

    # Early clean exit during extension: at 16:30 (325m elapsed) T_in reaches 8.2 C -> stops cleanly without wasting extra 35m
    t2_local = datetime(2026, 11, 27, 16, 30, tzinfo=tz)
    t2_utc = t2_local.astimezone(timezone.utc)
    res2 = autopilot.run_autopilot_tick(
        _sample(t2_utc, t_in=8.2, oat=3.0, buf=23.5),
        dry_run=True,
        now_utc_override=t2_utc,
        weather_cache_file=wx_file,
    )
    assert res2["state"] == "PUFFER_DRAIN", f"Expected early clean exit at 8.2C in extension, got {res2['state']}"


def test_16_weather_aware_extension_gate_and_second_step(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    tz = _rome_tz()
    t1_local = datetime(2026, 11, 27, 16, 5, tzinfo=tz)
    t1_utc = t1_local.astimezone(timezone.utc)
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True, min_cycle_end_temp_c=8.2, max_cycle_minutes=300, weather_arbitrage_cop_delta=0.25)
    autopilot.save_config(cfg)

    # Part A: Cold/wet evening (16:00-18:00 = -2C, RH 92%) + mild night (+4.0C -> genuinely safe >= 7.2C) + sunny tomorrow (+6.5C)
    # With T_in=8.0 (<8.2), night is safe AND tomorrow COP is much better -> MUST refuse extension & stop cleanly!
    autopilot.save_state({
        "state": "HEATING_SYNC",
        "state_since_utc": (t1_utc - timedelta(minutes=300)).isoformat(),
        "cycle_started_utc": (t1_utc - timedelta(minutes=300)).isoformat(),
        "active_window_start_local": "11:00",
        "active_window_end_local": "16:00",
        "min_end_temp_extended": False,
        "min_end_ext_count": 0,
        "calculated_target_lwt_c": 23.5,
        "calculated_pdc_setpoint_c": 14,
        "target_pdc_setpoint_c": 14,
    })
    hourly_a = _make_hourly_series(
        t1_local.replace(hour=0),
        48,
        day1_temp_fn=lambda h: -2.0 if 16 <= h <= 18 else 4.0,
        day1_rh_fn=lambda h: 92 if 16 <= h <= 18 else 75,
        day2_temp_fn=lambda h: 6.5 if 11 <= h <= 15 else 4.0,
        day2_rh_fn=lambda h: 62 if 11 <= h <= 15 else 75,
    )
    _write_weather_cache(wx_file, t1_utc, hourly_a)
    res_a = autopilot.run_autopilot_tick(
        _sample(t1_utc, t_in=8.0, oat=-2.0, buf=23.0),
        dry_run=True,
        now_utc_override=t1_utc,
        weather_cache_file=wx_file,
    )
    assert res_a["state"] == "PUFFER_DRAIN", f"Expected refusal of bad-COP extension when night is safe, got {res_a['state']}"
    assert "domani COP migliore" in res_a["last_action_reason"]

    # Part B: Freezing night (-9C) puts night at risk (proj < 7.2C) -> MUST allow extension (even 2nd step up to 18:05!)
    t_b_local = datetime(2026, 11, 27, 17, 5, tzinfo=tz)
    t_b_utc = t_b_local.astimezone(timezone.utc)
    autopilot.save_state({
        "state": "HEATING_SYNC",
        "state_since_utc": (t_b_utc - timedelta(minutes=360)).isoformat(),
        "cycle_started_utc": (t_b_utc - timedelta(minutes=360)).isoformat(),
        "active_window_start_local": "11:00",
        "active_window_end_local": "17:00",
        "min_end_temp_extended": True,
        "min_end_ext_count": 1,
        "calculated_target_lwt_c": 24.5,
        "calculated_pdc_setpoint_c": 15,
        "target_pdc_setpoint_c": 15,
    })
    hourly_b = _make_hourly_series(
        t_b_local.replace(hour=0),
        48,
        day1_temp_fn=lambda h: -2.0 if 16 <= h <= 18 else -9.0,
        day1_rh_fn=lambda h: 90,
        day2_temp_fn=lambda h: 4.0 if 11 <= h <= 15 else -8.0,
        day2_rh_fn=lambda h: 70,
    )
    _write_weather_cache(wx_file, t_b_utc, hourly_b)
    res_b = autopilot.run_autopilot_tick(
        _sample(t_b_utc, t_in=7.6, oat=-2.0, buf=24.0),
        dry_run=True,
        now_utc_override=t_b_utc,
        weather_cache_file=wx_file,
    )
    assert res_b["state"] == "HEATING_SYNC", f"Expected 2nd extension to prevent freezing night emergency, got {res_b['state']}"
    assert res_b["min_end_ext_count"] == 2
    assert res_b["active_window_end_local"] == "18:05"


def test_17_smart_cold_lwt_and_anti_onoff_floor(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    from scripts import thermal_model as tm
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True, adaptive_model_apply_targets=True)
    model = {
        "k_rad_kw_per_k": 0.413,
        "p_min_continuous_kw_ref": 5.18,
        "defrost_lwt_drop_p90_k": 9.5,
        "ua_building_c_24h_per_k": 0.179,
        "alpha_heat_c_h_per_k": 0.0161,
        "bphe_safe_outlet_min_c": 12.0,
    }
    # 1) Mild OAT (+8 C): P_min(OAT) is high -> anti-ON/OFF floor must lift LWT >= 23.8 C to prevent short-cycling
    r_mild = tm.recommend_operating_targets(model, t_in=7.5, oat=8.0, cfg=cfg)
    assert r_mild["anti_onoff_floor_c"] >= 23.8, f"Mild-OAT anti-ON/OFF floor too low: {r_mild}"
    assert r_mild["recommended_target_lwt_c"] >= 23.8

    # 2) Cool OAT (+2 C) with cold start (6.8 C): SCOP-first -> must NOT spike to 26.5 C, stay gentle (<= 23.5 C)
    r_cool_cold = tm.recommend_operating_targets(model, t_in=6.8, oat=2.0, cfg=cfg)
    assert 22.5 <= r_cool_cold["recommended_target_lwt_c"] <= 23.5, f"Cool-OAT LWT spiked unnecessarily: {r_cool_cold}"

    # 3) Real frost (OAT -4 C -> -8 C): must scale progressively up toward 26.5 C so house doesn't stall
    r_frost4 = tm.recommend_operating_targets(model, t_in=6.8, oat=-4.0, cfg=cfg)
    r_frost8 = tm.recommend_operating_targets(model, t_in=6.8, oat=-8.0, cfg=cfg)
    assert r_frost4["recommended_target_lwt_c"] > r_cool_cold["recommended_target_lwt_c"], f"Expected frost ramp at -4C: {r_frost4}"
    assert r_frost8["recommended_target_lwt_c"] >= 25.5, f"Expected strong frost ramp at -8C: {r_frost8}"


def test_18_ceil_setpoint_floor_and_early_15m_extension(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    from api.viessmann import compute_inverse_setpoint_for_target_lwt, compute_wo1c_lwt

    # Part A: Never round below min_lwt_floor_c (regression for 26/11 SP=12 -> 21.4 C bug)
    sp_37 = compute_inverse_setpoint_for_target_lwt(23.5, oat_c=3.7, slope=0.6, shift=0.0, min_lwt_floor_c=23.5)
    sp_47 = compute_inverse_setpoint_for_target_lwt(23.5, oat_c=4.7, slope=0.6, shift=0.0, min_lwt_floor_c=23.5)
    assert sp_37 >= 13 and compute_wo1c_lwt(3.7, sp_37, 0.6, 0.0) >= 23.35, f"SP rounded too low at 3.7C: {sp_37}"
    assert sp_47 >= 14 and compute_wo1c_lwt(4.7, sp_47, 0.6, 0.0) >= 23.35, f"SP rounded too low at 4.7C: {sp_47}"

    # Part B: Early 15-min extension pre-trigger before WO1C hardware schedule expires (regression for 26/11 13:56 stop)
    tz = _rome_tz()
    t_early_local = datetime(2026, 11, 27, 13, 46, tzinfo=tz)  # 14 min before 14:00 window end!
    t_early_utc = t_early_local.astimezone(timezone.utc)
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True, min_cycle_end_temp_c=8.2, max_cycle_minutes=300)
    autopilot.save_config(cfg)
    autopilot.save_state({
        "state": "HEATING_SYNC",
        "state_since_utc": (t_early_utc - timedelta(minutes=286)).isoformat(),
        "cycle_started_utc": (t_early_utc - timedelta(minutes=286)).isoformat(),
        "active_window_start_local": "09:00",
        "active_window_end_local": "14:00",
        "min_end_temp_extended": False,
        "min_end_ext_count": 0,
        "calculated_target_lwt_c": 24.4,
        "calculated_pdc_setpoint_c": 14,
        "target_pdc_setpoint_c": 14,
    })
    hourly = _make_hourly_series(t_early_local.replace(hour=0), 48, lambda h: 4.0, lambda h: 80)
    _write_weather_cache(wx_file, t_early_utc, hourly)
    res = autopilot.run_autopilot_tick(
        _sample(t_early_utc, t_in=7.9, oat=4.5, buf=22.5),
        dry_run=True,
        now_utc_override=t_early_utc,
        weather_cache_file=wx_file,
    )
    assert res["state"] == "HEATING_SYNC", f"Expected early extension to keep HEATING_SYNC, got {res['state']}"
    assert res["min_end_ext_count"] == 1
    assert res["active_window_end_local"] == "15:00", f"Expected early extension to 15:00, got {res['active_window_end_local']}"


def test_19_standby_only_tin_mae_and_full_30h_preview(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    tz = _rome_tz()
    now_local = datetime(2026, 11, 27, 12, 0, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True)
    autopilot.save_config(cfg)

    # Prediction made at 06:00 for 12:00 (pred=7.2 C), but compressor ran at 10:00 -> MUST be skipped from standby MAE!
    # Pure standby prediction made at 00:00 for 06:00 (pred=7.6 C vs actual 7.5 C -> err=0.1 C) + 01:00->07:00 (err=0.1 C)
    hourly = _make_hourly_series(now_local.replace(hour=0), 48, lambda h: 3.0, lambda h: 80)
    payload = {
        "location_label": "Abitazione di Montagna (Zona Climatica E)",
        "model": "Test Fixture",
        "fetched_utc": now_utc.isoformat(),
        "hourly": hourly,
        "calibration": {},
        "calibration_history": [],
        "prediction_history": [
            {"created_utc": datetime(2026, 11, 27, 0, 0, tzinfo=tz).astimezone(timezone.utc).isoformat(), "target_local": "2026-11-27T06:00", "pred_tin_c": 7.6},
            {"created_utc": datetime(2026, 11, 27, 1, 0, tzinfo=tz).astimezone(timezone.utc).isoformat(), "target_local": "2026-11-27T07:00", "pred_tin_c": 7.5},
            {"created_utc": datetime(2026, 11, 27, 6, 0, tzinfo=tz).astimezone(timezone.utc).isoformat(), "target_local": "2026-11-27T12:00", "pred_tin_c": 7.2},
        ],
    }
    wx_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    recent_samples = [
        _sample(datetime(2026, 11, 27, 6, 0, tzinfo=tz).astimezone(timezone.utc), t_in=7.5, oat=3.0),
        _sample(datetime(2026, 11, 27, 7, 0, tzinfo=tz).astimezone(timezone.utc), t_in=7.4, oat=3.0),
        {**_sample(datetime(2026, 11, 27, 10, 0, tzinfo=tz).astimezone(timezone.utc), t_in=7.8, oat=3.0), "compressor_active": 1, "grundfos_pump_active": 1},
        {**_sample(now_utc, t_in=8.3, oat=3.0), "compressor_active": 1, "grundfos_pump_active": 1},
    ]
    st_active = {
        "state": "HEATING_SYNC",
        "active_window_start_local": "11:00",
        "active_window_end_local": "16:00",
    }
    plan = wp.evaluate_weather_plan(
        now_local=now_local,
        t_in_c=8.3,
        current_oat_c=3.0,
        cur_state="HEATING_SYNC",
        cfg=cfg,
        thermal_model={"ua_building_c_24h_per_k": 0.18, "alpha_heat_c_h_per_k": 0.0164},
        recent_samples=recent_samples,
        st=st_active,
        dry_run=False,
        cache_file=wx_file,
    )
    # MAE must reflect ONLY the 2 pure standby predictions (0.10 C), NOT the contaminated 12:00 heating point (1.10 C)!
    assert plan["assumptions"]["tin_projection_mae_c"] == 0.1, f"Standby MAE contaminated: {plan['assumptions']['tin_projection_mae_c']}"
    saved = json.loads(wx_file.read_text(encoding="utf-8"))
    hp = saved.get("hourly_preview") or []
    assert len(hp) == 30, f"Expected 30h preview, got {len(hp)}"
    assert all(h.get("tin_proj_c") is not None for h in hp), "Found None tin_proj_c in 30h preview!"
    # Next hour during HEATING_SYNC must rise, NOT cool!
    assert hp[1]["tin_mode"] == "heat" and hp[1]["tin_proj_c"] > 8.3, f"Expected rising T_in in HEATING_SYNC: {hp[:3]}"
    # Must NOT have appended a new standby prediction_history record while in HEATING_SYNC
    assert len(saved.get("prediction_history") or []) == 3, "Should not record standby checkpoint during HEATING_SYNC"


def test_20_counter_audit_fine_shift_and_midwindow_ext_exit(cfg_file: Path, st_file: Path, wx_file: Path) -> None:
    from api.viessmann import compute_optimal_sp_and_shift_for_target_lwt

    # Part A: (SP, Shift in [-1,0,+1]) hits 23.4 C at OAT=4.7 C instead of coarse 24.4 C jump!
    sp, sh, lwt = compute_optimal_sp_and_shift_for_target_lwt(
        target_lwt_c=23.5, oat_c=4.7, slope=0.6, base_shift=0, allowed_shifts=(-1, 0, 1), min_lwt_floor_c=23.5
    )
    assert (sp, sh, lwt) == (14, -1, 23.4), f"Expected fine (14, -1, 23.4), got {(sp, sh, lwt)}"

    # Part B: Cycle started mid-window (11:30 inside 11:00-16:00), extended early at 15:46 -> 17:00,
    # then reaches 8.2 C at 16:15 (elapsed=285m < 300m, past original base_window_end 16:00) -> MUST exit cleanly!
    tz = _rome_tz()
    t1_local = datetime(2026, 11, 27, 15, 46, tzinfo=tz)
    t1_utc = t1_local.astimezone(timezone.utc)
    start_utc = datetime(2026, 11, 27, 11, 30, tzinfo=tz).astimezone(timezone.utc)
    cfg = dict(autopilot.DEFAULT_CONFIG, enabled=True, min_cycle_end_temp_c=8.2, max_cycle_minutes=300)
    autopilot.save_config(cfg)
    autopilot.save_state({
        "state": "HEATING_SYNC",
        "state_since_utc": start_utc.isoformat(),
        "cycle_started_utc": start_utc.isoformat(),
        "active_window_start_local": "11:00",
        "active_window_end_local": "16:00",
        "base_window_end_local": "16:00",
        "min_end_temp_extended": False,
        "min_end_ext_count": 0,
        "calculated_target_lwt_c": 23.5,
        "calculated_pdc_setpoint_c": 14,
        "target_pdc_setpoint_c": 14,
        "calculated_curve_shift": -1,
    })
    hourly = _make_hourly_series(t1_local.replace(hour=0), 48, lambda h: 4.5, lambda h: 75)
    _write_weather_cache(wx_file, t1_utc, hourly)

    res_ext = autopilot.run_autopilot_tick(
        _sample(t1_utc, t_in=8.0, oat=4.5, buf=23.0),
        dry_run=True,
        now_utc_override=t1_utc,
        weather_cache_file=wx_file,
    )
    assert res_ext["state"] == "HEATING_SYNC" and res_ext["active_window_end_local"] == "17:00"
    assert res_ext["base_window_end_local"] == "16:00"

    # At 16:15 (elapsed=285m < 300m, but past base_window_end 16:00), T_in reaches 8.2 C -> MUST stop!
    t2_local = datetime(2026, 11, 27, 16, 15, tzinfo=tz)
    t2_utc = t2_local.astimezone(timezone.utc)
    res_exit = autopilot.run_autopilot_tick(
        _sample(t2_utc, t_in=8.2, oat=4.5, buf=23.5),
        dry_run=True,
        now_utc_override=t2_utc,
        weather_cache_file=wx_file,
    )
    assert res_exit["state"] == "PUFFER_DRAIN", f"Expected clean exit at 16:15 on 8.2C, got {res_exit['state']}"


def main() -> int:
    print("=" * 72)
    print("  VITOCAL REMOTE - TEST SUITE METEO & CASI LIMITE AUTOPILOTA")
    print("=" * 72)
    cases = [
        ("1. Short-cycle deferral (15:40, notte mite)", test_1_short_cycle_deferral),
        ("2. Short-cycle extension + niente taglio alle 16:00", test_2_short_cycle_extension_and_no_1600_cutoff),
        ("3. Pre-armamento predittivo + nessun rimbalzo", test_3_predictive_prearm_night_freeze_and_no_bounce),
        ("4. Nessun pre-armamento se casa calda (8.5°C)", test_4_no_prearm_when_warm),
        ("5. Arbitraggio meteo (rinvio a domani più mite)", test_5_weather_arbitrage_deferral),
        ("6. Guardia sicurezza blocca rinvio se T <= floor", test_6_safety_override_blocks_deferral),
        ("7. Anti-starvation vieta 2 rinvii consecutivi", test_7_anti_starvation_prevents_double_deferral),
        ("8. Emergenza notturna scavalca tutto", test_8_night_emergency_overrides_all),
        ("9. Finestra dinamica 12:00-17:00 + lock in HEATING_SYNC", test_9_dynamic_window_selection_and_lock),
        ("10. Fallback offline / Secrets mancanti", test_10_offline_missing_secrets_fallback),
        ("11. Privacy cache JSON, verifica OAT & self-tuning bias", test_11_privacy_and_calibration),
        ("12. Convergenza Bayesiana & changelog thermal_model.json", test_12_thermal_model_convergence_and_changelog),
        ("13. Calibrazione EN 14511 (111.A16) & pioggia continua", test_13_en14511_calibration_and_continuous_precip),
        ("14. Blocco finestra anti-slittamento & guardia emergenza", test_14_horizon_lock_and_emergency_ceiling_guard),
        ("15. Estensione T_min fine ciclo, fix 306m & uscita 8.2°C", test_15_min_cycle_end_temp_extension),
        ("16. Gate meteo estensione (rifiuto vs 2° step anti-gelo)", test_16_weather_aware_extension_gate_and_second_step),
        ("17. LWT intelligente su gelo + guardia anti-ON/OFF", test_17_smart_cold_lwt_and_anti_onoff_floor),
        ("18. Floor setpoint ceil (no SP=12) & anticipo 15m estensione", test_18_ceil_setpoint_floor_and_early_15m_extension),
        ("19. MAE T_casa solo standby & preview 30h continua", test_19_standby_only_tin_mae_and_full_30h_preview),
        ("20. Fine tuning (SP, Shift) 0.5°C & fix stop_ext mid-window", test_20_counter_audit_fine_shift_and_midwindow_ext_exit),
    ]
    for title, fn in cases:
        _run_case(title, fn)
    print(f"\n[✓] TUTTI I {len(cases)} TEST SUPERATI CON SUCCESSO!")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
