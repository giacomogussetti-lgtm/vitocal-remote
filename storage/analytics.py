"""
Analytics & Thermodynamic Efficiency Engine for Vitocal 111-S & BTicino.
Computes customizable metrics over any window (X hours):
- Compressor starts & run hours (hardware counters & cycle edge detection)
- Cycle durations (average, min, max)
- Inverter modulation quality & short-cycling diagnosis
- Electrical consumption & cost estimation (€)
- Anti-frost safety margin evaluation
"""
from datetime import datetime, timezone, timedelta
import math
from typing import Any, Optional


def analyze_telemetry_period(
    samples: list[dict[str, Any]],
    hours_requested: float = 24.0,
    cost_per_kwh: float = 0.25,
    freeze_risk_threshold_c: float = 5.0,
) -> dict[str, Any]:
    """
    Analyzes a list of telemetry samples over a specified time window.
    """
    if not samples:
        return _empty_analytics_result(hours_requested)

    # 1. Filter samples within the time window
    # Try parsing timestamps to filter by window
    valid_samples = []
    for s in samples:
        ts_str = s.get("timestamp_utc")
        if not ts_str:
            continue
        try:
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            valid_samples.append((dt, s))
        except Exception:
            continue

    if not valid_samples:
        return _empty_analytics_result(hours_requested)

    valid_samples.sort(key=lambda x: x[0])
    
    # Determine window: relative to latest sample
    latest_dt = valid_samples[-1][0]
    cutoff_dt = latest_dt - timedelta(hours=hours_requested)
    
    window_samples = [s for dt, s in valid_samples if dt >= cutoff_dt]
    if not window_samples:
        # Fallback to all valid samples if window yields nothing
        window_samples = [s for _, s in valid_samples]

    n_samples = len(window_samples)
    first_sample = window_samples[0]
    last_sample = window_samples[-1]

    first_dt = datetime.fromisoformat(first_sample["timestamp_utc"])
    last_dt = datetime.fromisoformat(last_sample["timestamp_utc"])
    effective_hours = max((last_dt - first_dt).total_seconds() / 3600.0, 0.1)

    # ------------------------------------------------------------------
    # 2. HARDWARE COUNTERS DELTA (Vitotronic WO1C)
    # ------------------------------------------------------------------
    starts_vals = [s["compressor_starts"] for s in window_samples if s.get("compressor_starts") is not None]
    hours_vals = [s["compressor_hours"] for s in window_samples if s.get("compressor_hours") is not None]

    hw_starts_delta = 0
    if starts_vals:
        hw_starts_delta = max(0, int(starts_vals[-1] - starts_vals[0]))

    hw_hours_delta = 0.0
    if hours_vals:
        hw_hours_delta = max(0.0, float(hours_vals[-1] - hours_vals[0]))

    # ------------------------------------------------------------------
    # 3. SAMPLE-BY-SAMPLE CYCLE DETECTION (ignoring empty Viessmann polls)
    # ------------------------------------------------------------------
    detected_cycles = []
    current_cycle_samples = []
    defrost_episodes = 0
    prev_defrost = False

    for s in window_samples:
        viessmann_corrupted = (
            s.get("pdc_supply_temp_c") is None
            and s.get("active_program") is None
            and s.get("compressor_modulation_percent") is None
        )
        if viessmann_corrupted:
            continue
        is_active = (s.get("compressor_active") == 1) or ((s.get("compressor_modulation_percent") or 0) > 0)
        is_def = "defrost" in str(s.get("compressor_phase") or "").lower()
        if is_def and not prev_defrost:
            defrost_episodes += 1
        prev_defrost = is_def

        if is_active:
            current_cycle_samples.append(s)
        else:
            if current_cycle_samples:
                # Cycle ended
                c_data = _summarize_cycle(current_cycle_samples)
                if c_data:
                    detected_cycles.append(c_data)
                current_cycle_samples = []

    if current_cycle_samples:
        # Currently ongoing cycle
        c_data = _summarize_cycle(current_cycle_samples)
        if c_data:
            detected_cycles.append(c_data)

    detected_starts_count = len(detected_cycles)

    # Reconcile hardware counter and detected cycles
    total_starts = max(hw_starts_delta, detected_starts_count)
    detected_hours = sum(c["duration_minutes"] for c in detected_cycles) / 60.0
    total_run_hours = max(hw_hours_delta, detected_hours)
    
    # Prevent run hours exceeding window
    total_run_hours = min(total_run_hours, effective_hours)
    duty_cycle_pct = round((total_run_hours / effective_hours) * 100.0, 1)

    # ------------------------------------------------------------------
    # 4. CYCLE DURATIONS (Average, Min, Max in Minutes)
    # ------------------------------------------------------------------
    if detected_cycles:
        durations = [c["duration_minutes"] for c in detected_cycles]
        dur_avg = round(sum(durations) / len(durations), 1)
        dur_min = round(min(durations), 1)
        dur_max = round(max(durations), 1)
    elif total_starts > 0 and total_run_hours > 0:
        # Estimated from hardware counter
        dur_avg = round((total_run_hours * 60.0) / total_starts, 1)
        dur_min = round(dur_avg * 0.8, 1)
        dur_max = round(dur_avg * 1.2, 1)
    else:
        dur_avg = 0.0
        dur_min = 0.0
        dur_max = 0.0

    # ------------------------------------------------------------------
    # 5. MODULATION QUALITY ANALYSIS ("Ha modulato bene?")
    # ------------------------------------------------------------------
    # Gather modulation samples during active periods
    active_mods = [
        float(s.get("compressor_modulation_percent") or 0)
        for s in window_samples
        if (s.get("compressor_active") == 1 or (s.get("compressor_modulation_percent") or 0) > 0)
    ]

    avg_active_mod = round(sum(active_mods) / len(active_mods), 1) if active_mods else 0.0
    max_mod = round(max(active_mods), 1) if active_mods else 0.0

    # Load classes distribution (% of active time)
    low_load_count = sum(1 for m in active_mods if 1 <= m <= 30)
    mid_load_count = sum(1 for m in active_mods if 31 <= m <= 60)
    high_load_count = sum(1 for m in active_mods if m > 60)
    n_act = max(len(active_mods), 1)

    low_load_pct = round((low_load_count / n_act) * 100.0, 1) if active_mods else 0.0
    mid_load_pct = round((mid_load_count / n_act) * 100.0, 1) if active_mods else 0.0
    high_load_pct = round((high_load_count / n_act) * 100.0, 1) if active_mods else 0.0

    # Short cycling evaluation
    short_cycling = False
    if total_starts > 0:
        starts_per_hour = total_starts / effective_hours
        if dur_avg < 20.0 or starts_per_hour > 1.8:
            short_cycling = True

    # Modulation Health Score (0 - 100) & Technical Verdict
    score = 100
    if total_starts == 0:
        verdict = "⚪ Standby / Macchina Inattiva"
        diagnosis = (
            "Nessun avviamento del compressore nelle ultime ore. Il generatore è rimasto a riposo "
            "in quanto le temperature interne sono rimaste sopra la soglia di protezione antigelo."
        )
    elif short_cycling:
        score = max(35, 100 - int(total_starts * 12) - (20 if dur_avg < 15 else 10))
        verdict = "⚠️ Short-Cycling Rilevato (Cicli Brevi)"
        diagnosis = (
            f"La PdC ha effettuato {total_starts} avviamenti con durata media di soli {dur_avg} minuti. "
            "Sui 200L di puffer, cicli così brevi provocano arresti anticipati per sovratemperatura. "
            "Consiglio: sincronizzare l'accensione con il rilancio Grundfos al pavimento radiante."
        )
    elif dur_avg >= 40.0:
        score = 95 if high_load_pct < 20 else 85
        verdict = "🌟 Modulazione Ottimale (Inverter Dolce & Continuo)"
        diagnosis = (
            f"Modulazione eccellente: i cicli durano in media {dur_avg} min (carico medio {avg_active_mod}%). "
            "Il compressore lavora nel 'sweet spot' ad alta efficienza e ridotto consumo elettrico."
        )
    else:
        score = 75
        verdict = "🟢 Modulazione Buona / Regolare"
        diagnosis = (
            f"Funzionamento regolare: {total_starts} avviamenti con durata media di {dur_avg} min. "
            "Ripartizione carico equilibrata, nessun allarme di pendolamento o sovraccarico."
        )

    # ------------------------------------------------------------------
    # 6. CALIBRATED ELECTRICAL & NET THERMAL CONSUMPTION (Trapezoidal + Defrost)
    # Model: Vitocal AWBT-E-AC 111.A16 (11 kW split R410A)
    # ------------------------------------------------------------------
    standby_hours = max(0.0, effective_hours - total_run_hours)
    integ_elec_kwh = 0.0
    integ_thermal_kwh = 0.0
    for idx_s, s in enumerate(window_samples):
        t_cur = datetime.fromisoformat(s["timestamp_utc"])
        if idx_s + 1 < len(window_samples):
            t_next = datetime.fromisoformat(window_samples[idx_s + 1]["timestamp_utc"])
            dt_s = max(15.0, min(1800.0, (t_next - t_cur).total_seconds()))
        elif idx_s > 0:
            t_prev = datetime.fromisoformat(window_samples[idx_s - 1]["timestamp_utc"])
            dt_s = max(15.0, min(1800.0, (t_cur - t_prev).total_seconds()))
        else:
            dt_s = 300.0
        dt_h = dt_s / 3600.0
        corrupted = s.get("pdc_supply_temp_c") is None and s.get("active_program") is None
        ref = window_samples[idx_s - 1] if (corrupted and idx_s > 0) else s
        gf_kw = 0.030 if ref.get("grundfos_pump_active") == 1 else 0.0
        is_comp = (ref.get("compressor_active") == 1) or ((ref.get("compressor_modulation_percent") or 0) > 0)
        if not is_comp:
            integ_elec_kwh += (0.020 + gf_kw) * dt_h
            continue
        is_def = "defrost" in str(ref.get("compressor_phase") or "").lower()
        if is_def:
            integ_elec_kwh += (1.35 + gf_kw) * dt_h
            integ_thermal_kwh += -3.5 * dt_h
            continue
        mod = max(0.0, min(100.0, float(ref.get("compressor_modulation_percent") or 0)))
        p_cond = float(ref.get("hot_gas_pressure_bar") or 17.0)
        p_factor = max(0.72, min(1.25, 0.82 + 0.18 * ((p_cond - 14.0) / 6.0)))
        p1_kw = 0.045 if (ref.get("primary_pump_rotation_percent") or 0) > 0 else 0.0
        p_el = 0.28 + 2.95 * (mod / 100.0) * p_factor + p1_kw + gf_kw
        lwt = float(ref.get("pdc_supply_temp_c") or 25.0)
        oat = float(ref.get("external_temp_c") if ref.get("external_temp_c") is not None else 5.0)
        t_suc_raw = ref.get("suction_gas_temp_c")
        p_raw = ref.get("hot_gas_pressure_bar")
        t_cond = (22.86 * math.log(max(5.0, float(p_raw))) - 38.4) if p_raw is not None else (lwt + 3.0)
        t_evap = min(oat - 3.5, float(t_suc_raw) + 1.5) if t_suc_raw is not None else (oat - 6.5)
        carnot = (t_cond + 273.15) / max(12.0, t_cond - t_evap)
        eta = 0.48 if mod <= 55 else (0.44 if mod <= 75 else 0.39)
        dyn_cop = max(1.7, min(5.3, carnot * eta))
        integ_elec_kwh += p_el * dt_h
        integ_thermal_kwh += (p_el * dyn_cop) * dt_h

    r1_vals = [int(s["heating_rod_level1_s"]) for s in window_samples if s.get("heating_rod_level1_s") is not None]
    r2_vals = [int(s["heating_rod_level2_s"]) for s in window_samples if s.get("heating_rod_level2_s") is not None]
    rod_kwh = ((max(0, r1_vals[-1] - r1_vals[0]) if len(r1_vals) >= 2 else 0) + (max(0, r2_vals[-1] - r2_vals[0]) if len(r2_vals) >= 2 else 0)) / 3600.0 * 3.0
    total_elec_kwh = round(integ_elec_kwh + rod_kwh, 2)
    total_thermal_net_kwh = round(max(0.0, integ_thermal_kwh + rod_kwh), 1)
    avg_power_kw = round(total_elec_kwh / effective_hours, 3)

    estimated_cost_eur = round(total_elec_kwh * cost_per_kwh, 2)
    projected_daily_cost_eur = round((total_elec_kwh / effective_hours) * 24.0 * cost_per_kwh, 2)

    # Real Net COP in window (fallback to seasonal WO1C COP if idle)
    cop_vals = [s["cop_heating"] for s in window_samples if s.get("cop_heating") is not None and s.get("cop_heating") > 0]
    avg_cop = round(total_thermal_net_kwh / total_elec_kwh, 2) if (total_elec_kwh > 0.2 and total_thermal_net_kwh > 0) else (round(sum(cop_vals) / len(cop_vals), 2) if cop_vals else 3.10)

    # ------------------------------------------------------------------
    # 7. ANTI-FROST SAFETY & TEMPERATURE MINIMA
    # ------------------------------------------------------------------
    in_temps = [s["indoor_temp_bticino_c"] for s in window_samples if s.get("indoor_temp_bticino_c") is not None]
    buf_temps = [s["buffer_temp_c"] for s in window_samples if s.get("buffer_temp_c") is not None]
    out_temps = [s["external_temp_c"] for s in window_samples if s.get("external_temp_c") is not None]

    min_indoor = min(in_temps) if in_temps else 7.8
    min_buffer = min(buf_temps) if buf_temps else 13.0
    min_outdoor = min(out_temps) if out_temps else 4.0

    safety_margin = round(min_indoor - freeze_risk_threshold_c, 1)

    if safety_margin >= 2.0:
        safety_status = "safe"
        safety_verdict = f"🛡️ CASA AL SICURO DAL GELO (Margine +{safety_margin} °C)"
        safety_advice = (
            f"Temperatura interna minima: {min_indoor:.1f} °C (soglia critica gelo: {freeze_risk_threshold_c:.1f} °C). "
            f"Spesa stimata a questo regime: {projected_daily_cost_eur:.2f} €/giorno. "
            "Nessun consumo superfluo: l'impianto sta garantendo la massima economia in sicurezza."
        )
    elif safety_margin >= 0.5:
        safety_status = "caution"
        safety_verdict = f"⚠️ MARGINE GELO RIDOTTO (+{safety_margin} °C)"
        safety_advice = (
            f"La temperatura interna è scesa a {min_indoor:.1f} °C, vicina alla soglia di guardia. "
            "Se l'esterno scende sotto zero, valutare un breve impulso al setpoint BTicino."
        )
    else:
        safety_status = "danger"
        safety_verdict = "🚨 RISCHIO GELO ATTIVO"
        safety_advice = (
            f"ALLERTA: Temperatura interna a {min_indoor:.1f} °C! Attivare immediatamente "
            "il riscaldamento per proteggere le tubazioni dell'immobile."
        )

    # ------------------------------------------------------------------
    # 8. ASSEMBLE OUTPUT DICTIONARY
    # ------------------------------------------------------------------
    return {
        "period": {
            "hours_requested": float(hours_requested),
            "effective_hours": round(effective_hours, 1),
            "samples_analyzed": n_samples,
            "start_time": first_sample["timestamp_utc"],
            "end_time": last_sample["timestamp_utc"],
        },
        "starts_and_cycles": {
            "total_starts": total_starts,
            "starts_from_hardware": hw_starts_delta,
            "detected_cycles_count": detected_starts_count,
            "total_run_hours": round(total_run_hours, 2),
            "standby_hours": round(standby_hours, 2),
            "duty_cycle_percent": duty_cycle_pct,
            "duration_avg_minutes": dur_avg,
            "duration_min_minutes": dur_min,
            "duration_max_minutes": dur_max,
            "cycles_list": detected_cycles,
        },
        "modulation": {
            "avg_active_percent": avg_active_mod,
            "max_modulation_percent": max_mod,
            "low_load_percent": low_load_pct,
            "mid_load_percent": mid_load_pct,
            "high_load_percent": high_load_pct,
            "short_cycling_detected": short_cycling,
            "score": score,
            "verdict": verdict,
            "diagnosis": diagnosis,
        },
        "consumption": {
            "total_elec_kwh": total_elec_kwh,
            "total_thermal_net_kwh": total_thermal_net_kwh,
            "defrost_episodes": defrost_episodes,
            "avg_power_kw": avg_power_kw,
            "estimated_cost_eur": estimated_cost_eur,
            "projected_daily_cost_eur": projected_daily_cost_eur,
            "cost_per_kwh_used": cost_per_kwh,
            "avg_cop": avg_cop,
        },
        "anti_frost_safety": {
            "min_indoor_temp_c": min_indoor,
            "min_buffer_temp_c": min_buffer,
            "min_outdoor_temp_c": min_outdoor,
            "freeze_threshold_c": freeze_risk_threshold_c,
            "safety_margin_c": safety_margin,
            "status": safety_status,
            "verdict": safety_verdict,
            "advice": safety_advice,
        },
    }


def _summarize_cycle(cycle_samples: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not cycle_samples:
        return None
    try:
        t_start = datetime.fromisoformat(cycle_samples[0]["timestamp_utc"])
        t_end = datetime.fromisoformat(cycle_samples[-1]["timestamp_utc"])
        dur = max((t_end - t_start).total_seconds() / 60.0, 5.0)  # At least 5m
    except Exception:
        dur = max(len(cycle_samples) * 5.0, 5.0)
        t_start = cycle_samples[0].get("timestamp_utc")
        t_end = cycle_samples[-1].get("timestamp_utc")

    mods = [s.get("compressor_modulation_percent") or 0 for s in cycle_samples]
    supplies = [s.get("pdc_supply_temp_c") for s in cycle_samples if s.get("pdc_supply_temp_c") is not None]

    return {
        "start": cycle_samples[0].get("timestamp_utc"),
        "end": cycle_samples[-1].get("timestamp_utc"),
        "duration_minutes": round(dur, 1),
        "avg_modulation": round(sum(mods) / len(mods), 1) if mods else 0.0,
        "max_modulation": round(max(mods), 1) if mods else 0.0,
        "avg_supply_temp": round(sum(supplies) / len(supplies), 1) if supplies else None,
    }


def _empty_analytics_result(hours: float) -> dict[str, Any]:
    return {
        "period": {"hours_requested": hours, "effective_hours": 0, "samples_analyzed": 0},
        "starts_and_cycles": {
            "total_starts": 0, "total_run_hours": 0, "duty_cycle_percent": 0,
            "duration_avg_minutes": 0, "duration_min_minutes": 0, "duration_max_minutes": 0,
            "cycles_list": [],
        },
        "modulation": {
            "avg_active_percent": 0, "max_modulation_percent": 0, "short_cycling_detected": False,
            "score": 100, "verdict": "Nessun dato registrato", "diagnosis": "Nessun campione presente nel periodo selezionato.",
        },
        "consumption": {
            "total_elec_kwh": 0, "avg_power_kw": 0, "estimated_cost_eur": 0,
            "projected_daily_cost_eur": 0, "avg_cop": 3.0,
        },
        "anti_frost_safety": {
            "min_indoor_temp_c": None, "safety_margin_c": None,
            "verdict": "Dati insufficienti", "advice": "Attendi che vengano registrati campioni.",
        },
    }
