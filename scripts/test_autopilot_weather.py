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
    ]
    for title, fn in cases:
        _run_case(title, fn)
    print("\n[✓] TUTTI I 12 TEST SUPERATI CON SUCCESSO!")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
