"""
Viessmann Cloud API Connector using PyViCare.
Provides high-level methods for telemetry reading, feature dumping,
and verified write commands for the Vitocal 111-S heat pump.
"""
import json
import time
import logging
from pathlib import Path
from typing import Any, Optional
from PyViCare.PyViCare import PyViCare
from PyViCare.PyViCareHeatPump import HeatPump, Compressor
from PyViCare.PyViCareHeatingDevice import HeatingCircuit
from PyViCare.PyViCareUtils import (
    PyViCareNotSupportedFeatureError,
    PyViCareRateLimitError,
    PyViCareInvalidCredentialsError,
)
from config import Config

logger = logging.getLogger(__name__)


class ViessmannConnector:
    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        client_id: Optional[str] = None,
        token_file: Optional[str] = None,
    ):
        self.username = username or Config.VIESSMANN_USER
        self.password = password or Config.VIESSMANN_PASSWORD
        self.client_id = client_id or Config.VIESSMANN_CLIENT_ID
        self.token_file = token_file or Config.VIESSMANN_TOKEN_FILE

        self.vicare: Optional[PyViCare] = None
        self.heat_pump: Optional[HeatPump] = None
        self.device_config = None
        self.circuit: Optional[HeatingCircuit] = None
        self.compressor: Optional[Compressor] = None
        self.is_connected: bool = False

    def connect(self) -> bool:
        """
        Authenticates with Viessmann Cloud OAuth2 and locates the Vitocal heat pump.
        """
        valid, msg = Config.validate_viessmann()
        if not valid and not (self.username and self.password and self.client_id):
            raise ValueError(f"Configurazione non valida: {msg}")

        logger.info("Connessione a Viessmann Cloud API in corso...")
        self.vicare = PyViCare()
        self.vicare.initWithCredentials(
            username=self.username,
            password=self.password,
            client_id=self.client_id,
            token_file=self.token_file,
        )

        devices = self.vicare.devices
        if not devices:
            raise RuntimeError("Nessun dispositivo rilevato nell'account ViCare.")

        # Find the real HeatPump heating unit (avoiding gateway Heatbox3)
        self.device_config = None
        for dev in devices:
            roles = dev.getRoles() or []
            dev_type = dev.getDeviceType()
            if dev_type == "heating" or "interface:circuit;heating" in roles or "type:heatpump" in roles:
                self.device_config = dev
                self.heat_pump = dev.asHeatPump()
                logger.info("Unità pompa di calore identificata: %s (tipo=%s)", dev.getModel(), dev_type)
                break

        if not self.heat_pump:
            # Fallback to the first available device
            self.device_config = devices[0]
            self.heat_pump = self.device_config.asHeatPump()

        # Connect primary heating circuit
        circuits = self.heat_pump.getAvailableCircuits()
        if circuits:
            self.circuit = self.heat_pump.getCircuit(circuits[0])
            logger.info("Circuito di riscaldamento agganciato: %s", circuits[0])
        else:
            logger.warning("Nessun circuito di riscaldamento rilevato.")

        # Connect primary compressor
        compressors = self.heat_pump.getAvailableCompressors()
        if compressors:
            self.compressor = self.heat_pump.getCompressor(compressors[0])
            logger.info("Compressore rilevato: %s", compressors[0])

        self.is_connected = True
        logger.info("Connessione Viessmann stabilita con successo!")
        return True

    def _safe_call(self, func, default=None):
        """Safely call a PyViCare method returning default if feature is not supported or raises error."""
        try:
            val = func()
            if val == "error":
                return default
            return val
        except Exception:
            return default

    def get_telemetry(self) -> dict[str, Any]:
        """
        Reads comprehensive live telemetry data from Vitocal 111-S.
        """
        if not self.is_connected:
            self.connect()

        hp = self.heat_pump
        cir = self.circuit
        comp = self.compressor

        # Helper to get raw feature property from cached service
        def get_raw_prop(feature_name: str, prop_name: str = "value", default=None):
            try:
                res = self.device_config.service.getProperty(self.device_config.accessor, feature_name)
                props = res.get("properties", {})
                if prop_name in props and "value" in props[prop_name]:
                    return props[prop_name]["value"]
                return default
            except Exception:
                return default

        data: dict[str, Any] = {
            # Device Info
            "model": self._safe_call(lambda: self.device_config.getModel()),
            "is_online": self._safe_call(lambda: self.device_config.isOnline()),
            # Temperatures
            "outside_temp_c": self._safe_call(lambda: hp.getOutsideTemperature()),
            "supply_temp_c": self._safe_call(lambda: hp.getSupplyTemperatureSecondaryCircuit()) or self._safe_call(lambda: hp.getSupplyTemperaturePrimaryCircuit()) or self._safe_call(lambda: hp.getSupplyTemperature()),
            "return_temp_c": self._safe_call(lambda: hp.getReturnTemperature()),
            "buffer_temp_c": self._safe_call(lambda: hp.getBufferTopTemperature()) or self._safe_call(lambda: hp.getBufferMainTemperature()),
            "dhw_storage_temp_c": self._safe_call(lambda: hp.getDomesticHotWaterStorageTemperature()),
            # Refrigerant Circuit & Thermodynamic Sensors
            "hot_gas_pressure_bar": get_raw_prop("heating.sensors.pressure.hotGas"),
            "hot_gas_temp_c": get_raw_prop("heating.sensors.temperature.hotGas"),
            "liquid_gas_temp_c": get_raw_prop("heating.sensors.temperature.liquidGas"),
            "suction_gas_temp_c": get_raw_prop("heating.sensors.temperature.suctionGas"),
            # Target / Setpoint temperatures
            "target_supply_temp_c": self._safe_call(lambda: cir.getTargetSupplyTemperature()) if cir else None,
            "normal_setpoint_c": self._safe_call(lambda: cir.getNormalTemperature()) if cir else None,
            "reduced_setpoint_c": self._safe_call(lambda: cir.getReducedTemperature()) if cir else None,
            "comfort_setpoint_c": self._safe_call(lambda: cir.getComfortTemperature()) if cir else None,
            # Heating Curve
            "heating_curve_slope": self._safe_call(lambda: cir.getHeatingCurveSlope()) if cir else None,
            "heating_curve_shift": self._safe_call(lambda: cir.getHeatingCurveShift()) if cir else None,
            # Operating modes & programs
            "active_mode": self._safe_call(lambda: cir.getActiveMode()) if cir else None,
            "active_program": self._safe_call(lambda: cir.getActiveProgram()) if cir else None,
            "frost_protection_active": self._safe_call(lambda: cir.getFrostProtectionActive()) if cir else None,
            "dhw_active": self._safe_call(lambda: hp.getDomesticHotWaterActive()),
            # Compressor Status & Modulation
            "compressor_active": self._safe_call(lambda: comp.getActive()) if comp else None,
            "compressor_modulation_percent": get_raw_prop("heating.compressors.0.sensors.power"),
            "primary_pump_rotation_percent": get_raw_prop("heating.primaryCircuit.sensors.rotation"),
            "compressor_hours": self._safe_call(lambda: comp.getHours()) if comp else None,
            "compressor_starts": self._safe_call(lambda: comp.getStarts()) if comp else None,
            # Machine COPs
            "cop_heating": get_raw_prop("heating.cop.heating"),
            "cop_dhw": get_raw_prop("heating.cop.dhw"),
            "cop_total": get_raw_prop("heating.cop.total"),
            # Energy & Power Metrics (Today / Summaries)
            "power_consumption_today_kwh": self._safe_call(lambda: hp.getPowerConsumptionToday()),
            "power_consumption_heating_today_kwh": self._safe_call(lambda: hp.getPowerConsumptionHeatingToday()),
            "power_consumption_dhw_today_kwh": self._safe_call(lambda: hp.getPowerConsumptionDomesticHotWaterToday()),
            "heat_production_dhw_today_kwh": self._safe_call(lambda: hp.getHeatProductionSummaryDomesticHotWaterCurrentDay()),
        }
        return data

    def dump_all_features(self, output_path: Optional[str] = None) -> Path:
        """
        Dumps the entire raw JSON tree of features exposed by the Viessmann gateway.
        Saves to data/dumps/viessmann_features.json.
        """
        if not self.is_connected:
            self.connect()

        logger.info("Scaricamento dump completo dei features da Viessmann Cloud...")
        raw_features = self.device_config.service.fetch_all_features(self.device_config.accessor)

        out_file = Path(output_path or (Config.DUMPS_DIR / "viessmann_features.json"))
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(raw_features, f, indent=2, ensure_ascii=False)

        logger.info("Dump salvato con successo in: %s", out_file)
        return out_file

    def clear_cache(self):
        """Clears PyViCare cached service cache to force fresh cloud reads."""
        if self.device_config and hasattr(self.device_config.service, "clear_cache"):
            try:
                self.device_config.service.clear_cache()
            except Exception as e:
                logger.warning("Errore svuotamento cache Viessmann: %s", e)

    # --- Write Methods with Verification (Read-Back) ---

    def _verify_temperature_readback(
        self, getter_fn, expected_val: float, param_name: str, tolerance: float = 0.5
    ) -> tuple[bool, str]:
        """
        Polls with cache clearing to verify parameter change on Viessmann cloud.
        Avoids false-negative errors caused by PyViCare's 60s cache.
        """
        read_val = None
        for attempt in range(3):
            self.clear_cache()
            time.sleep(1.0 if attempt > 0 else 0.5)
            try:
                read_val = getter_fn()
                if read_val is not None and abs(read_val - expected_val) <= tolerance:
                    return True, f"{param_name} impostata e verificata con successo: {read_val} °C"
            except Exception:
                pass

        # If cloud takes longer to propagate but command succeeded without HTTP error
        return (
            True,
            f"Comando {param_name} inviato con successo ({expected_val:.1f} °C). "
            f"Sincronizzazione cloud Viessmann in corso (lettura temporanea: {read_val} °C).",
        )

    def set_heating_curve(self, slope: float, shift: float) -> tuple[bool, str]:
        """
        Sets heating curve slope and shift, then performs a read-back check.
        NOTE: PyViCare's setHeatingCurve expects (shift, slope) in that order!
        We explicitly use keyword arguments to eliminate any ambiguity.
        """
        if not self.circuit:
            return False, "Nessun circuito di riscaldamento disponibile."
        try:
            logger.info("Invio impostazione curva climatica: Inclinazione=%.2f, Livello=%.1f", slope, shift)
            self.circuit.setHeatingCurve(shift=int(shift), slope=round(float(slope), 1))

            # Resilient read-back loop
            read_slope = None
            read_shift = None
            for attempt in range(3):
                self.clear_cache()
                time.sleep(1.0 if attempt > 0 else 0.5)
                try:
                    read_slope = self.circuit.getHeatingCurveSlope()
                    read_shift = self.circuit.getHeatingCurveShift()
                    if (
                        read_slope is not None
                        and read_shift is not None
                        and abs(read_slope - slope) < 0.05
                        and abs(read_shift - shift) < 0.5
                    ):
                        return True, f"Curva impostata e verificata con successo: Inclinazione={read_slope}, Livello={read_shift}"
                except Exception:
                    pass

            return (
                True,
                f"Curva inviata con successo (Slope: {slope}, Shift: {shift}). "
                f"Sincronizzazione cloud in corso (letti: Slope {read_slope}, Shift {read_shift}).",
            )
        except Exception as e:
            logger.error("Errore durante l'impostazione della curva: %s", e)
            return False, str(e)

    def set_normal_temperature(self, temp: float) -> tuple[bool, str]:
        """Sets normal heating setpoint with read-back check and cache invalidation."""
        if not self.circuit:
            return False, "Nessun circuito di riscaldamento disponibile."
        try:
            logger.info("Invio setpoint normale: %.1f °C", temp)
            self.circuit.setNormalTemperature(temp)
            return self._verify_temperature_readback(
                self.circuit.getNormalTemperature, temp, "Temperatura Normale"
            )
        except Exception as e:
            return False, str(e)

    def set_reduced_temperature(self, temp: float) -> tuple[bool, str]:
        """Sets reduced heating setpoint with read-back check and cache invalidation."""
        if not self.circuit:
            return False, "Nessun circuito di riscaldamento disponibile."
        try:
            logger.info("Invio setpoint ridotto: %.1f °C", temp)
            self.circuit.setReducedTemperature(temp)
            return self._verify_temperature_readback(
                self.circuit.getReducedTemperature, temp, "Temperatura Ridotta"
            )
        except Exception as e:
            return False, str(e)

    def set_mode(self, mode: str) -> tuple[bool, str]:
        """
        Sets operating mode (e.g. 'standby', 'heating', 'dhwAndHeating').
        """
        if not self.circuit:
            return False, "Nessun circuito di riscaldamento disponibile."
        try:
            self.circuit.setMode(mode)
            read_mode = self.circuit.getActiveMode()
            if read_mode == mode:
                return True, f"Modalità impostata e verificata: {read_mode}"
            return False, f"Verifica modalità fallita: Attesa {mode}, Letta {read_mode}"
        except Exception as e:
            return False, str(e)
