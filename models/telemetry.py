"""
Data models for telemetry and presets.
"""
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class TelemetrySample(BaseModel):
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    external_temp_c: Optional[float] = None
    indoor_temp_bticino_c: Optional[float] = None
    indoor_setpoint_bticino_c: Optional[float] = None
    grundfos_pump_active: Optional[int] = None  # 0 or 1
    pdc_supply_temp_c: Optional[float] = None
    pdc_return_temp_c: Optional[float] = None
    buffer_temp_c: Optional[float] = None
    dhw_storage_temp_c: Optional[float] = None
    compressor_active: Optional[int] = None      # 0 or 1
    compressor_hours: Optional[float] = None
    compressor_starts: Optional[int] = None
    heating_curve_slope: Optional[float] = None
    heating_curve_shift: Optional[float] = None
    active_mode: Optional[str] = None
    active_program: Optional[str] = None
    heating_elec_kwh_total: Optional[float] = None
    heating_thermal_kwh_total: Optional[float] = None
    dhw_elec_kwh_total: Optional[float] = None
    dhw_thermal_kwh_total: Optional[float] = None
    hot_gas_pressure_bar: Optional[float] = None
    hot_gas_temp_c: Optional[float] = None
    liquid_gas_temp_c: Optional[float] = None
    suction_gas_temp_c: Optional[float] = None
    compressor_modulation_percent: Optional[float] = None
    primary_pump_rotation_percent: Optional[float] = None
    cop_heating: Optional[float] = None
    cop_dhw: Optional[float] = None
    cop_total: Optional[float] = None
    humidity_percent: Optional[float] = None
    active_preset: Optional[str] = "manual"
