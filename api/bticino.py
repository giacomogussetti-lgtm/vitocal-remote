"""
BTicino / Legrand / Netatmo Energy API Connector.
Communicates with Netatmo Connect API for reading indoor room temperature,
target setpoint, thermostat relay status (Grundfos pump call), and setting setpoints.
"""
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional
import requests
from config import Config

logger = logging.getLogger(__name__)


class BTicinoConnector:
    TOKEN_URL = "https://api.netatmo.com/oauth2/token"
    HOMES_DATA_URL = "https://api.netatmo.com/api/homesdata"
    HOME_STATUS_URL = "https://api.netatmo.com/api/homestatus"
    SET_STATE_URL = "https://api.netatmo.com/api/setstate"
    # Legacy Netatmo thermostat endpoint (kept for reference, forbidden for BNS Smarther)
    SET_ROOM_THERM_POINT_URL = "https://api.netatmo.com/api/setroomthermpoint"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        refresh_token: Optional[str] = None,
        token_cache_file: Optional[str] = None,
    ):
        self.client_id = client_id or Config.NETATMO_CLIENT_ID
        self.client_secret = client_secret or Config.NETATMO_CLIENT_SECRET
        self.username = username or Config.NETATMO_USER
        self.password = password or Config.NETATMO_PASSWORD
        self.refresh_token = refresh_token or Config.NETATMO_REFRESH_TOKEN or None
        self.token_cache_file = Path(token_cache_file or (Config.DATA_DIR / "netatmo_token.json"))

        self.access_token: Optional[str] = None
        self.token_expires_at: float = 0.0

        self.home_id: Optional[str] = None
        self.room_id: Optional[str] = None
        self.room_name: Optional[str] = None
        self.is_connected: bool = False
        self.last_status: Optional[dict[str, Any]] = None

    def _load_cached_token(self) -> bool:
        if not self.token_cache_file.exists():
            return False
        try:
            with open(self.token_cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                self.token_expires_at = data.get("expires_at", 0)
                if self.access_token and time.time() < (self.token_expires_at - 60):
                    return True
        except Exception as e:
            logger.warning("Impossibile caricare cache token Netatmo: %s", e)
        return False

    def _save_cached_token(self, token_data: dict[str, Any]):
        try:
            self.access_token = token_data.get("access_token")
            self.refresh_token = token_data.get("refresh_token")
            expires_in = token_data.get("expires_in", 10800)
            self.token_expires_at = time.time() + expires_in

            with open(self.token_cache_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "access_token": self.access_token,
                        "refresh_token": self.refresh_token,
                        "expires_at": self.token_expires_at,
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            logger.warning("Impossibile salvare cache token Netatmo: %s", e)

    def authenticate(self, force_refresh: bool = False) -> bool:
        """Authenticates with Netatmo OAuth2 using cached token, refresh token, or password grant."""
        if not force_refresh and self._load_cached_token():
            logger.info("Utilizzo del token di accesso Netatmo dalla cache.")
            return True

        if self.refresh_token:
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
            resp = requests.post(self.TOKEN_URL, data=payload, timeout=15)
            if resp.status_code == 200:
                self._save_cached_token(resp.json())
                logger.info("Token Netatmo aggiornato con refresh_token con successo.")
                return True
            else:
                logger.error("Errore aggiornamento token Netatmo (%s): %s", resp.status_code, resp.text)

        # Fallback to Password grant
        valid, msg = Config.validate_netatmo()
        if not valid and not (self.client_id and self.client_secret and self.username and self.password):
            raise ValueError(f"Configurazione Netatmo non valida: {msg}")

        payload = {
            "grant_type": "password",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
            "password": self.password,
            "scope": "read_smarther write_smarther",
        }
        resp = requests.post(self.TOKEN_URL, data=payload, timeout=15)
        if resp.status_code != 200:
            raise RuntimeError(f"Autenticazione Netatmo fallita ({resp.status_code}): {resp.text}")

        self._save_cached_token(resp.json())
        logger.info("Autenticazione Netatmo completata con successo!")
        return True

    def _get_headers(self, force_refresh: bool = False) -> dict[str, str]:
        if force_refresh or not self.access_token or time.time() >= self.token_expires_at - 60:
            self.authenticate(force_refresh=force_refresh)
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def discover_home_and_room(self) -> tuple[str, str]:
        """Discovers the primary home ID and thermostat room ID from Netatmo homesdata."""
        headers = self._get_headers()
        resp = requests.get(self.HOMES_DATA_URL, headers=headers, timeout=10)
        if resp.status_code != 200:
            raise RuntimeError(f"Errore lettura homesdata ({resp.status_code}): {resp.text}")

        data = resp.json().get("body", {})
        homes = data.get("homes", [])
        if not homes:
            raise RuntimeError("Nessuna abitazione trovata nell'account Netatmo/Legrand.")

        home = homes[0]
        self.home_id = home.get("id")

        rooms = home.get("rooms", [])
        if not rooms:
            raise RuntimeError(f"Nessuna stanza trovata nell'abitazione '{home.get('name')}'.")

        # Pick the room that has thermostat module or first room
        self.room_id = rooms[0].get("id")
        self.room_name = rooms[0].get("name", "Stanza")

        logger.info("Home identificata: %s (%s), Stanza: %s (%s)", home.get("name"), self.home_id, self.room_name, self.room_id)
        self.is_connected = True
        return self.home_id, self.room_id

    def get_status(self) -> dict[str, Any]:
        """
        Reads indoor temperature, target setpoint, and relay status from BTicino Smarther.
        Handles transient disconnects (code 6) and token expiration transparently.
        """
        if not self.is_connected or not self.home_id:
            self.discover_home_and_room()

        headers = self._get_headers()
        resp = requests.get(
            self.HOME_STATUS_URL,
            headers=headers,
            params={"home_id": self.home_id},
            timeout=15,
        )

        if resp.status_code in (401, 403):
            # Token might be stale/expired; force refresh and retry once
            logger.info("Token Netatmo scaduto o invalido (%s). Rigenerazione...", resp.status_code)
            headers = self._get_headers(force_refresh=True)
            resp = requests.get(
                self.HOME_STATUS_URL,
                headers=headers,
                params={"home_id": self.home_id},
                timeout=15,
            )

        if resp.status_code != 200:
            raise RuntimeError(f"Errore homestatus Netatmo ({resp.status_code}): {resp.text}")

        resp_json = resp.json()
        body = resp_json.get("body", {}).get("home", {})
        rooms = body.get("rooms", [])

        # Check for transient device unreachable error (error code 6)
        errors = resp_json.get("body", {}).get("errors", []) or resp_json.get("errors", [])
        is_unreachable = any(e.get("code") == 6 for e in errors)

        if not rooms:
            if is_unreachable:
                logger.warning("Termostato BTicino momentaneamente irraggiungibile via Wi-Fi (code 6).")
            # If we have a previously cached status, return it to avoid false 0 or None drops
            if self.last_status:
                cached = dict(self.last_status)
                cached["device_reachable"] = False
                return cached
            return {
                "room_name": self.room_name,
                "indoor_temp_c": None,
                "setpoint_c": None,
                "humidity_percent": None,
                "mode": None,
                "heating_power_request": 0,
                "boiler_status": False,
                "grundfos_pump_active": 0,
                "device_reachable": False,
            }

        room_data = next((r for r in rooms if r.get("id") == self.room_id), rooms[0] if rooms else {})

        # Extract telemetry
        temp = room_data.get("therm_measured_temperature")
        setpoint = room_data.get("therm_setpoint_temperature")
        mode = room_data.get("therm_setpoint_mode")
        humidity = room_data.get("humidity")
        # heating_power_request is > 0 when the thermostat closes the relay (Grundfos ON)
        heating_power_request = room_data.get("heating_power_request", 0)

        # Check boiler_status on modules as well
        modules = body.get("modules", [])
        boiler_status = any(
            m.get("boiler_status")
            for m in modules
            if m.get("type") == "BNS" or "smarther" in str(m.get("type", "")).lower() or m.get("boiler_status") is not None
        )
        is_demanding_heat = (heating_power_request and heating_power_request > 0) or boiler_status

        # Thermodynamic sanity check: in heating mode, if setpoint <= measured temp,
        # heating demand is satisfied and the relay is opened.
        # This prevents transient Netatmo cloud keep-alive latency (~60-120s) from falsely
        # logging Grundfos as active after lowering setpoint below room temperature.
        if temp is not None and setpoint is not None and setpoint <= temp:
            pump_active = 0
        else:
            pump_active = 1 if is_demanding_heat else 0

        status = {
            "room_name": self.room_name,
            "indoor_temp_c": temp,
            "setpoint_c": setpoint,
            "humidity_percent": humidity,
            "mode": mode,
            "heating_power_request": heating_power_request,
            "boiler_status": boiler_status,
            "grundfos_pump_active": pump_active,
            "device_reachable": not is_unreachable,
        }

        # Cache last valid reading
        if temp is not None:
            self.last_status = dict(status)

        return status

    def set_thermostat_setpoint(
        self, temp: float, mode: str = "manual", duration_minutes: int = 180
    ) -> tuple[bool, str]:
        """
        Sets target setpoint for the BTicino Smarther thermostat via Legrand / Netatmo Home + Control API (/setstate).
        mode can be 'manual', 'home' (programma), 'away' (assente), or 'hg' (antigelo).
        """
        if not self.home_id or not self.room_id:
            self.discover_home_and_room()

        headers = self._get_headers()
        room_payload: dict[str, Any] = {
            "id": self.room_id,
            "therm_setpoint_mode": mode,
        }
        if mode == "manual":
            room_payload["therm_setpoint_temperature"] = round(float(temp), 1)
            if duration_minutes and duration_minutes > 0:
                room_payload["therm_setpoint_end_time"] = int(time.time()) + (duration_minutes * 60)

        payload = {
            "home": {
                "id": self.home_id,
                "rooms": [room_payload],
            }
        }

        resp = requests.post(self.SET_STATE_URL, headers=headers, json=payload, timeout=15)
        if resp.status_code in (401, 403):
            # Token might be stale, force refresh and retry once
            headers = self._get_headers(force_refresh=True)
            resp = requests.post(self.SET_STATE_URL, headers=headers, json=payload, timeout=15)

        if resp.status_code != 200:
            logger.error("Errore setstate BTicino (%s): %s", resp.status_code, resp.text)
            return False, f"Errore impostazione setpoint BTicino ({resp.status_code}): {resp.text}"

        logger.info("Setpoint BTicino impostato con successo a %.1f °C (modalità: %s)", temp, mode)
        if self.last_status:
            self.last_status["setpoint_c"] = round(float(temp), 1)
            self.last_status["mode"] = mode
        return True, f"Setpoint BTicino aggiornato con successo a {temp:.1f} °C (modalità: {mode})"

    def set_thermostat_mode(self, mode: str) -> tuple[bool, str]:
        """
        Sets thermostat mode directly ('home', 'away', or 'hg').
        """
        if not self.home_id or not self.room_id:
            self.discover_home_and_room()

        headers = self._get_headers()
        payload = {
            "home": {
                "id": self.home_id,
                "rooms": [
                    {
                        "id": self.room_id,
                        "therm_setpoint_mode": mode,
                    }
                ],
            }
        }
        resp = requests.post(self.SET_STATE_URL, headers=headers, json=payload, timeout=15)
        if resp.status_code in (401, 403):
            headers = self._get_headers(force_refresh=True)
            resp = requests.post(self.SET_STATE_URL, headers=headers, json=payload, timeout=15)

        if resp.status_code != 200:
            return False, f"Errore cambio modalità BTicino ({resp.status_code}): {resp.text}"

        logger.info("Modalità BTicino impostata su '%s'", mode)
        if self.last_status:
            self.last_status["mode"] = mode
        return True, f"Modalità BTicino aggiornata su '{mode}'"
