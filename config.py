"""
Configuration manager for Vitocal Remote.
Loads settings from .env file with validation.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    # Viessmann API
    VIESSMANN_USER = os.getenv("VIESSMANN_USER", "")
    VIESSMANN_PASSWORD = os.getenv("VIESSMANN_PASSWORD", "")
    VIESSMANN_CLIENT_ID = os.getenv("VIESSMANN_CLIENT_ID", "")
    VIESSMANN_TOKEN_FILE = str(BASE_DIR / os.getenv("VIESSMANN_TOKEN_FILE", "token.save"))

    # Netatmo / BTicino API
    NETATMO_CLIENT_ID = os.getenv("NETATMO_CLIENT_ID", "")
    NETATMO_CLIENT_SECRET = os.getenv("NETATMO_CLIENT_SECRET", "")
    NETATMO_USER = os.getenv("NETATMO_USER", "")
    NETATMO_PASSWORD = os.getenv("NETATMO_PASSWORD", "")
    NETATMO_REFRESH_TOKEN = os.getenv("NETATMO_REFRESH_TOKEN", "")

    # Storage & Polling
    POLL_INTERVAL_MINUTES = int(os.getenv("POLL_INTERVAL_MINUTES", "10"))
    DATABASE_PATH = str(BASE_DIR / os.getenv("DATABASE_PATH", "data/vitocal_telemetry.db"))
    DATA_DIR = BASE_DIR / "data"
    DUMPS_DIR = DATA_DIR / "dumps"

    # GitHub Cloud Integration
    GITHUB_REPO = os.getenv("GITHUB_REPO", "giacomogussetti-lgtm/vitocal-remote")
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

    @classmethod
    def validate_viessmann(cls) -> tuple[bool, str]:
        if not cls.VIESSMANN_CLIENT_ID:
            return False, "VIESSMANN_CLIENT_ID mancante in .env"
        if not cls.VIESSMANN_USER or "@" not in cls.VIESSMANN_USER:
            return False, "VIESSMANN_USER non configurato o non valido in .env"
        if not cls.VIESSMANN_PASSWORD:
            return False, "VIESSMANN_PASSWORD mancante in .env"
        return True, "Configurazione Viessmann valida"

    @classmethod
    def validate_netatmo(cls) -> tuple[bool, str]:
        if not cls.NETATMO_CLIENT_ID or not cls.NETATMO_CLIENT_SECRET:
            return False, "NETATMO_CLIENT_ID o NETATMO_CLIENT_SECRET mancante in .env"
        if not cls.NETATMO_REFRESH_TOKEN and (not cls.NETATMO_USER or not cls.NETATMO_PASSWORD):
            return False, "Necessario inserire o NETATMO_REFRESH_TOKEN o (NETATMO_USER e NETATMO_PASSWORD) in .env"
        return True, "Configurazione Netatmo valida"


# Ensure data and dumps directories exist
Config.DATA_DIR.mkdir(parents=True, exist_ok=True)
Config.DUMPS_DIR.mkdir(parents=True, exist_ok=True)
