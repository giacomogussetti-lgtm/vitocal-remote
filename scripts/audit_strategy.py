"""
Thermodynamic Strategy & Telemetry Audit Script for Vitocal 111-S & BTicino Smarther.
Fetches the latest cloud telemetry (GitHub raw with local fallback), inspects active
autopilot config/state, breaks down compressor & Grundfos cycles, defrosts, backup
electric heater runtime, indoor cooling derivatives, and prints objective tuning checks.

Usage:
    python scripts/audit_strategy.py [--hours 168] [--local-only]
"""
import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config import Config

CET = timezone(timedelta(hours=1))


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


def load_telemetry(local_only: bool = False) -> tuple[list[dict[str, Any]], str]:
    local_file = Config.DATA_DIR / "cloud_telemetry.jsonl"
    if not local_only:
        try:
            url = f"https://raw.githubusercontent.com/{Config.GITHUB_REPO}/main/data/cloud_telemetry.jsonl?t={int(time.time())}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                lines = [ln.strip() for ln in r.read().decode("utf-8").splitlines() if ln.strip()]
            return [json.loads(ln) for ln in lines], "GitHub Cloud (live)"
        except Exception as e:
            print(f"[!] Fallback su file locale (GitHub fetch non riuscito: {e})")

    if local_file.exists():
        lines = [ln.strip() for ln in local_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        return [json.loads(ln) for ln in lines], "Locale (data/cloud_telemetry.jsonl)"
    return [], "Nessuna sorgente"


def load_json_safe(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Strategia & Telemetria Vitocal")
    parser.add_argument("--hours", type=float, default=168.0, help="Ore da analizzare (default 168 = 7gg)")
    parser.add_argument("--local-only", action="store_true", help="Leggi solo file locale senza scaricare da GitHub")
    args = parser.parse_args()

    samples, src = load_telemetry(local_only=args.local_only)
    if not samples:
        print("[!] Nessun campione trovato.")
        return 1

    # Sort chronologically and filter timeframe
    with_dt = []
    for s in samples:
        dt = _parse_ts(s.get("timestamp_utc"))
        if dt:
            with_dt.append((dt, s))
    with_dt.sort(key=lambda x: x[0])

    latest_dt = with_dt[-1][0]
    cutoff = latest_dt - timedelta(hours=args.hours)
    window = [(dt, s) for dt, s in with_dt if dt >= cutoff]
    if not window:
        window = with_dt

    t_start = window[0][0].astimezone(CET)
    t_end = window[-1][0].astimezone(CET)
    span_h = max(0.01, (window[-1][0] - window[0][0]).total_seconds() / 3600.0)

    cfg = load_json_safe(Config.DATA_DIR / "autopilot_config.json")
    st = load_json_safe(Config.DATA_DIR / "autopilot_state.json")

    print("=" * 78)
    print("  VITOCAL REMOTE - THERMODYNAMIC STRATEGY AUDIT")
    print("=" * 78)
    print(f"Sorgente Dati   : {src} ({len(window)} campioni)")
    print(f"Finestra        : {t_start.strftime('%d/%m %H:%M')} -> {t_end.strftime('%d/%m %H:%M')} ({span_h:.1f} h)")
    print(
        f"Autopilota      : enabled={cfg.get('enabled')} | state={st.get('state')} "
        f"| T_min={cfg.get('t_min_c')}°C | T_max={cfg.get('t_max_c')}°C | Emergenza={cfg.get('t_emergency_c')}°C "
        f"| SoftStart={cfg.get('soft_start_enabled', False)} | DefrostGuard={cfg.get('defrost_guard_enabled', False)} | SoftTune={cfg.get('soft_curve_tuning_enabled', False)}"
    )
    ci = cfg.get("cron_idle_minutes", cfg.get("cron_idle_min", 15))
    ca = cfg.get("cron_armed_minutes", cfg.get("cron_armed_min", 5))
    cact = cfg.get("cron_active_minutes", cfg.get("cron_active_min", 1))
    print(
        f"Cron / Target   : cron_attivo={st.get('current_cron_interval_min', '--')}m "
        f"(idle={ci}m / armed={ca}m / active={cact}m) "
        f"| TargetLWT={st.get('calculated_target_lwt_c', '--')}°C (min={cfg.get('min_target_lwt_c', 22.5)} / max={cfg.get('max_target_lwt_c', 26.5)} / ΔT={cfg.get('target_lwt_delta_k', 15.5)}K) "
        f"| PdC_SP={st.get('calculated_pdc_setpoint_c', '--')}°C | d6_err={st.get('error_counter_d6', 0)}"
    )
    print(f"Ultimo motivo   : {st.get('last_action_reason', '--')}")

    # Indoor, outdoor, buffer summaries
    t_ins = [s["indoor_temp_bticino_c"] for _, s in window if s.get("indoor_temp_bticino_c") is not None]
    oats = [s["external_temp_c"] for _, s in window if s.get("external_temp_c") is not None]
    bufs = [s["buffer_temp_c"] for _, s in window if s.get("buffer_temp_c") is not None]
    starts = [s["compressor_starts"] for _, s in window if s.get("compressor_starts") is not None]
    hours = [s["compressor_hours"] for _, s in window if s.get("compressor_hours") is not None]
    r1s = [s["heating_rod_level1_s"] for _, s in window if s.get("heating_rod_level1_s") is not None]
    r2s = [s["heating_rod_level2_s"] for _, s in window if s.get("heating_rod_level2_s") is not None]

    print("\n--- BILANCIO TERMICO & HARDWARE ---")
    if t_ins:
        print(f"T Interna Casa  : min={min(t_ins):.1f}°C | max={max(t_ins):.1f}°C | attuale={t_ins[-1]:.1f}°C")
    if oats:
        print(f"T Esterna OAT   : min={min(oats):.1f}°C | max={max(oats):.1f}°C | media={sum(oats)/len(oats):.1f}°C | attuale={oats[-1]:.1f}°C")
    if bufs:
        print(f"Puffer 200L     : min={min(bufs):.1f}°C | max={max(bufs):.1f}°C | attuale={bufs[-1]:.1f}°C")
    if len(starts) >= 2 and len(hours) >= 2:
        d_starts = starts[-1] - starts[0]
        d_hours = hours[-1] - hours[0]
        avg_dur = (d_hours * 60.0 / d_starts) if d_starts > 0 else 0.0
        print(f"Avvii / Ore PdC : +{d_starts} avvii | +{d_hours:.2f} h marcia | durata media hardware={avg_dur:.1f} min/avvio")
    if len(r1s) >= 2 or len(r2s) >= 2:
        dr1 = (r1s[-1] - r1s[0]) if len(r1s) >= 2 else 0
        dr2 = (r2s[-1] - r2s[0]) if len(r2s) >= 2 else 0
        cur_r1 = r1s[-1] if r1s else 0
        cur_r2 = r2s[-1] if r2s else 0
        today_cet = latest_dt.astimezone(CET).date()
        today_r1 = [s["heating_rod_level1_s"] for dt, s in with_dt if dt.astimezone(CET).date() == today_cet and s.get("heating_rod_level1_s") is not None]
        today_r2 = [s["heating_rod_level2_s"] for dt, s in with_dt if dt.astimezone(CET).date() == today_cet and s.get("heating_rod_level2_s") is not None]
        d_today_r1 = (today_r1[-1] - today_r1[0]) if len(today_r1) >= 2 else 0
        d_today_r2 = (today_r2[-1] - today_r2[0]) if len(today_r2) >= 2 else 0
        rod_on_cnt = sum(1 for _, s in window if s.get("heating_rod_active") == 1)
        last_rod_state = "ON" if window[-1][1].get("heating_rod_active") == 1 else "OFF"
        print(
            f"Resistenza El.  : stato={last_rod_state} (campioni ON={rod_on_cnt}) | "
            f"finestra S1 +{dr1}s, S2 +{dr2}s | oggi S1 +{d_today_r1}s, S2 +{d_today_r2}s | "
            f"vita S1={cur_r1/3600.0:.1f}h ({cur_r1}s), S2={cur_r2/3600.0:.1f}h ({cur_r2}s)"
        )
    else:
        dr1 = 0
        dr2 = 0
        rod_on_cnt = 0
        print("Resistenza El.  : Contatori non ancora storicizzati nei campioni precedenti.")

    # Defrost episodes (distinct) & BPHE thermal safety margin
    defrost_samples = [
        (dt, s) for dt, s in window
        if "defrost" in str(s.get("compressor_phase") or "").lower()
    ]
    defrost_episodes = []
    cur_def = []
    for dt, s in defrost_samples:
        if cur_def and (dt - cur_def[-1][0]).total_seconds() > 600:
            defrost_episodes.append(cur_def)
            cur_def = [(dt, s)]
        else:
            cur_def.append((dt, s))
    if cur_def:
        defrost_episodes.append(cur_def)

    def_lwt_mins = [s["pdc_supply_temp_c"] for _, s in defrost_samples if s.get("pdc_supply_temp_c") is not None]
    def_buf_mins = [s["buffer_temp_c"] for _, s in defrost_samples if s.get("buffer_temp_c") is not None]
    def_lwt_min = min(def_lwt_mins) if def_lwt_mins else None
    def_buf_min = min(def_buf_mins) if def_buf_mins else None
    frost_samples = [
        (dt, s) for dt, s in window
        if str(s.get("frost_protection_status") or "").lower() == "on"
    ]
    bphe_str = (
        f" | BPHE min in defrost: LWT_min={def_lwt_min:.1f}°C, Buf_min={def_buf_min:.1f}°C"
        if (def_lwt_min is not None and def_buf_min is not None)
        else ""
    )
    print(f"Defrost / Frost : {len(defrost_episodes)} episodi distinti ({len(defrost_samples)} campioni){bphe_str} | antigelo HW={len(frost_samples)}")

    # Modes & programs seen
    modes = sorted({str(s.get("active_mode")) for _, s in window if s.get("active_mode")})
    progs = sorted({str(s.get("active_program")) for _, s in window if s.get("active_program")})
    print(f"Modi / Programmi: modes={modes} | programs={progs}")

    # Calibrated energy consumption summary via storage.analytics
    try:
        from storage.analytics import analyze_telemetry_period
        an = analyze_telemetry_period([s for _, s in window], period_hours=args.hours)
        co = an.get("consumption", {})
        print(
            f"Consumi Stimati : {co.get('total_elec_kwh', 0):.2f} kWh_e (~{co.get('estimated_cost_eur', 0):.2f} EUR) "
            f"| Resa netta={co.get('total_thermal_net_kwh', 0):.1f} kWh_t | COP netto={co.get('avg_cop', '--')}"
        )
    except Exception:
        pass

    # Cycle breakdown (filtering out single empty Viessmann poll glitches)
    cycles = []
    cur_cycle = []
    for dt, s in window:
        v_empty = (
            s.get("pdc_supply_temp_c") is None
            and s.get("buffer_temp_c") is None
            and s.get("compressor_modulation_percent") is None
        )
        if v_empty and cur_cycle:
            continue
        is_on = (s.get("compressor_active") == 1) or ((s.get("compressor_modulation_percent") or 0) > 0)
        if is_on:
            cur_cycle.append((dt, s))
        else:
            if cur_cycle:
                cycles.append(cur_cycle)
                cur_cycle = []
    if cur_cycle:
        cycles.append(cur_cycle)

    print(f"\n--- DETTAGLIO CICLI COMPRESSORE ({len(cycles)} rilevati) ---")
    short_with_gf = 0
    short_no_gf = 0
    low_dt_prim_cycles = 0
    high_dt_sup_buf_cycles = 0
    for idx, cyc in enumerate(cycles, 1):
        c_start = cyc[0][0].astimezone(CET)
        c_end = cyc[-1][0].astimezone(CET)
        dur_min = max(1.0, (cyc[-1][0] - cyc[0][0]).total_seconds() / 60.0 + 1.0)
        mods = [s.get("compressor_modulation_percent") for _, s in cyc if (s.get("compressor_modulation_percent") or 0) > 0]
        sups = [s.get("pdc_supply_temp_c") for _, s in cyc if s.get("pdc_supply_temp_c") is not None]
        bufs_c = [s.get("buffer_temp_c") for _, s in cyc if s.get("buffer_temp_c") is not None]
        tins_c = [s.get("indoor_temp_bticino_c") for _, s in cyc if s.get("indoor_temp_bticino_c") is not None]
        p1s = [s.get("primary_pump_rotation_percent") for _, s in cyc if s.get("primary_pump_rotation_percent") is not None]
        dt_prim = [
            float(s["pdc_supply_temp_c"]) - float(s["pdc_return_temp_c"])
            for _, s in cyc
            if s.get("pdc_supply_temp_c") is not None and s.get("pdc_return_temp_c") is not None
        ]
        dt_sup_buf = [
            float(s["pdc_supply_temp_c"]) - float(s["buffer_temp_c"])
            for _, s in cyc
            if s.get("pdc_supply_temp_c") is not None and s.get("buffer_temp_c") is not None
        ]
        gf_cnt = sum(1 for _, s in cyc if s.get("grundfos_pump_active") == 1)
        gf_pct = 100.0 * gf_cnt / len(cyc)
        min_mod = min(mods) if mods else 0.0
        avg_mod = sum(mods) / len(mods) if mods else 0.0
        max_mod = max(mods) if mods else 0.0
        max_sup = max(sups) if sups else 0.0
        max_buf = max(bufs_c) if bufs_c else 0.0
        avg_p1 = sum(p1s) / len(p1s) if p1s else None
        avg_dt_p = sum(dt_prim) / len(dt_prim) if dt_prim else None
        avg_dt_sb = sum(dt_sup_buf) / len(dt_sup_buf) if dt_sup_buf else None
        tin_str = f"Casa={tins_c[0]:.1f}->{tins_c[-1]:.1f}°C ({tins_c[-1]-tins_c[0]:+.1f}K)" if len(tins_c) >= 2 else "Casa=--"
        if dur_min < 35:
            if gf_pct >= 50:
                short_with_gf += 1
            else:
                short_no_gf += 1
        if avg_dt_p is not None and dur_min >= 15 and avg_dt_p < 2.8:
            low_dt_prim_cycles += 1
        if avg_dt_sb is not None and dur_min >= 15 and gf_pct >= 50 and avg_dt_sb > 2.5:
            high_dt_sup_buf_cycles += 1
        p1_str = f"P1={avg_p1:3.0f}%" if avg_p1 is not None else "P1=--"
        dtp_str = f"ΔTp={avg_dt_p:4.1f}K" if avg_dt_p is not None else "ΔTp=--"
        print(
            f"  #{idx:2d} {c_start.strftime('%d/%m %H:%M')}->{c_end.strftime('%H:%M')} (~{dur_min:3.0f}m)"
            f" | Mod={min_mod:2.0f}/{avg_mod:2.0f}/{max_mod:2.0f}% | LWTmax={max_sup:4.1f} BufMax={max_buf:4.1f}°C | {dtp_str} {p1_str} | {tin_str} | GF={gf_pct:3.0f}%"
        )

    # Automated tuning hints
    print("\n--- RACCOMANDAZIONI DIAGNOSTICHE ---")
    if def_lwt_min is not None and def_lwt_min < 12.0:
        print(f"  [!] ATTENZIONE BPHE: LWT minima in defrost scesa a {def_lwt_min:.1f}°C (<12°C). Verificare riserva termica puffer / alzare min_target_lwt_c!")
    if def_buf_min is not None and def_buf_min < 17.0:
        print(f"  [!] ATTENZIONE PUFFER: Puffer minimo in defrost sceso a {def_buf_min:.1f}°C (<17°C).")
    if short_no_gf > 0:
        print(f"  [!] {short_no_gf} cicli brevi (<35m) con Grundfos spenta: attivare o verificare sincronizzazione PdC<->BTicino.")
    if short_with_gf > 0:
        print(f"  [!] {short_with_gf} cicli brevi (<35m) nonostante Grundfos accesa: valutare aumento target_lwt_delta_k (+1..+2K) o verificare portata/velocità circolatore in box.")
    if dr1 > 0 or dr2 > 0 or rod_on_cnt > 0:
        print(f"  [!] Rilevata attività resistenza backup (S1 +{dr1}s, S2 +{dr2}s, ON={rod_on_cnt}): correlare con defrost, OAT e cicli ACS.")
    if low_dt_prim_cycles > 0:
        print(f"  [i] {low_dt_prim_cycles} cicli con ΔT Primario medio < 2.8K: verificare se dovuto a modulazione minima vicina a saturazione Target LWT.")
    if high_dt_sup_buf_cycles > 0:
        print(f"  [i] {high_dt_sup_buf_cycles} cicli con ΔT Mandata-Puffer medio > 2.5K a Grundfos ON: possibile squilibrio/stratificazione puffer.")
    if not short_no_gf and not short_with_gf and cycles:
        print("  [✓] Nessun ciclo breve rilevato sui cicli registrati.")
    if not cfg.get("enabled"):
        print("  [i] Autopilota attualmente DISATTIVATO (enabled=false). Attivabile dalla PWA con un tocco.")

    # Self-converging physical model summary
    try:
        from scripts.thermal_model import fit_thermal_model, recommend_operating_targets
        tm = fit_thermal_model([s for _, s in with_dt])
        rec4 = recommend_operating_targets(tm, t_in=float(cfg.get("t_min_c") or 7.5), oat=4.0, cfg=cfg)
        rec0 = recommend_operating_targets(tm, t_in=float(cfg.get("t_min_c") or 7.5), oat=0.0, cfg=cfg)
        recm5 = recommend_operating_targets(tm, t_in=float(cfg.get("t_min_c") or 7.5), oat=-5.0, cfg=cfg)
        print("\n--- MODELLO MATEMATICO AUTO-CONVERGENTE ---")
        print(
            f"  Cicli={tm['cycles_observed']} | Confidenza={tm['confidence_pct']}% "
            f"| k_rad={tm['k_rad_kw_per_k']:.3f} kW/K | FloorInv={tm['inverter_min_mod_pct']:.1f}% (~{tm['p_min_continuous_kw_ref']:.2f} kW_t) "
            f"| ΔBPHE_defrost=-{tm['defrost_lwt_drop_p90_k']:.1f}K | UA={tm['ua_building_c_24h_per_k']:.3f} (°C/24h)/K"
        )
        print(
            f"  Target consigliato @ T_min: OAT +4°C->{rec4['recommended_target_lwt_c']}°C (~{rec4['pred_autonomy_hours']:.0f}h) "
            f"| OAT 0°C->{rec0['recommended_target_lwt_c']}°C (~{rec0['pred_autonomy_hours']:.0f}h) "
            f"| OAT -5°C->{recm5['recommended_target_lwt_c']}°C (~{recm5['pred_autonomy_hours']:.0f}h)"
        )
        saved_tm = load_json_safe(Config.DATA_DIR / "thermal_model.json")
        diag = tm.get("diagnostics") or saved_tm.get("diagnostics") or {}
        if diag:
            w_parts = []
            for k, lbl in (("k_rad_kw_per_k", "k_rad"), ("inverter_min_mod_pct", "Floor"), ("defrost_lwt_drop_p90_k", "ΔBPHE"), ("ua_building_c_24h_per_k", "UA")):
                d_item = diag.get(k) or {}
                w_parts.append(f"{lbl}:w={d_item.get('data_weight_pct', 0)}%(n={d_item.get('n_obs', 0)})")
            print(f"  Pesi Convergenza: {' | '.join(w_parts)}")
        tm_hist = saved_tm.get("history") or []
        for h_ev in tm_hist[-3:]:
            ts_s = str(h_ev.get("ts_utc") or "")[:16].replace("T", " ")
            print(f"  Self-Tuning [{ts_s}]: {'; '.join(h_ev.get('changes') or [])}")
    except Exception:
        pass

    # Weather-Aware Dynamic Window & Predictive Plan summary
    wf_file = load_json_safe(Config.DATA_DIR / "weather_forecast.json")
    wp = st.get("weather_plan") if isinstance(st.get("weather_plan"), dict) else None
    if not wp:
        wp = wf_file.get("plan") if isinstance(wf_file.get("plan"), dict) else None
    print("\n--- PIANIFICATORE METEO & FINESTRA DINAMICA ---")
    if wp:
        assump = wp.get("assumptions") or {}
        tw = wp.get("today_window") or {}
        tmw = wp.get("tomorrow_window") or {}
        proj = wp.get("projection_to_tomorrow") or {}
        bias_s = f"{assump.get('oat_bias_c', 0.0):+.2f}°C"
        raw_mae_s = f"{assump['oat_raw_mae_c']:.2f}°C" if assump.get("oat_raw_mae_c") is not None else "--"
        mae_s = f"{assump['oat_mae_c']:.2f}°C" if assump.get("oat_mae_c") is not None else "--"
        max_err_s = f"{assump['oat_max_abs_err_c']:.2f}°C" if assump.get("oat_max_abs_err_c") is not None else "--"
        tin_mae_s = f"{assump['tin_projection_mae_c']:.2f}°C" if assump.get("tin_projection_mae_c") is not None else "--"
        print(
            f"  Sorgente Meteo  : available={wp.get('available')} ({wp.get('source', '--')}) | "
            f"Bias OAT={bias_s} (MAE grezzo={raw_mae_s} -> corr={mae_s}, max={max_err_s}, n={assump.get('oat_samples_matched', 0)}) | MAE T_in={tin_mae_s}"
        )
        print(
            f"  Finestra Attiva : {wp.get('effective_window_start', '--')}–{wp.get('effective_window_end', '--')} "
            f"| Oggi={tw.get('start_hhmm', '--')}–{tw.get('end_hhmm', '--')} (COP={tw.get('avg_cop_net', '--')}, {tw.get('frost_risk', '--')}) "
            f"| Domani={tmw.get('start_hhmm', '--')}–{tmw.get('end_hhmm', '--')} (COP={tmw.get('avg_cop_net', '--')}, {tmw.get('frost_risk', '--')})"
        )
        if proj:
            print(
                f"  Proiezione Casa : {proj.get('start_tin_c', '--')}°C -> min {proj.get('min_tin_c', '--')}°C / fine {proj.get('end_tin_c', '--')}°C "
                f"(orizzonte {proj.get('hours_simulated', '--')}h, pavimento {assump.get('safe_floor_c', '--')}°C)"
            )
        print(f"  Decisione Live  : {wp.get('decision_summary', '--')}")
        for line in (wp.get("decision_trace") or [])[:4]:
            print(f"    • {line}")
        oat_checks = wf_file.get("recent_oat_checks") or []
        if oat_checks:
            print("  Verifica Oraria (Open-Meteo vs Sonda OAT):")
            for chk in oat_checks[-5:]:
                print(
                    f"    • {str(chk.get('time_local', ''))[5:16].replace('T', ' ')}: "
                    f"Meteo={chk.get('forecast_raw_c')}°C -> Corr={chk.get('forecast_corr_c')}°C | "
                    f"Sonda={chk.get('actual_oat_c')}°C (scarto {chk.get('err_corr_c'):+.1f}K)"
                )
    else:
        print(f"  Stato Meteo     : Nessun piano meteo ancora generato (finestra statica {cfg.get('cop_window_start', '11:00')}–{cfg.get('cop_window_end', '16:00')}).")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
