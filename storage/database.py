"""
SQLite storage manager for telemetry samples and event logging.
"""
import sqlite3
import logging
from pathlib import Path
from typing import Optional
from config import Config
from models.telemetry import TelemetrySample

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or Config.DATABASE_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT NOT NULL,
                    external_temp_c REAL,
                    indoor_temp_bticino_c REAL,
                    indoor_setpoint_bticino_c REAL,
                    grundfos_pump_active INTEGER,
                    pdc_supply_temp_c REAL,
                    pdc_return_temp_c REAL,
                    buffer_temp_c REAL,
                    dhw_storage_temp_c REAL,
                    compressor_active INTEGER,
                    compressor_hours REAL,
                    compressor_starts INTEGER,
                    heating_curve_slope REAL,
                    heating_curve_shift REAL,
                    active_mode TEXT,
                    active_program TEXT,
                    heating_elec_kwh_total REAL,
                    heating_thermal_kwh_total REAL,
                    dhw_elec_kwh_total REAL,
                    dhw_thermal_kwh_total REAL,
                    active_preset TEXT
                );
                """
            )
            # Add missing columns dynamically if migrating
            new_columns = [
                ("hot_gas_pressure_bar", "REAL"),
                ("hot_gas_temp_c", "REAL"),
                ("liquid_gas_temp_c", "REAL"),
                ("suction_gas_temp_c", "REAL"),
                ("compressor_modulation_percent", "REAL"),
                ("primary_pump_rotation_percent", "REAL"),
                ("cop_heating", "REAL"),
                ("cop_dhw", "REAL"),
                ("cop_total", "REAL"),
                ("humidity_percent", "REAL"),
            ]
            cursor.execute("PRAGMA table_info(telemetry_samples);")
            existing_cols = {row["name"] for row in cursor.fetchall()}
            for col_name, col_type in new_columns:
                if col_name not in existing_cols:
                    cursor.execute(f"ALTER TABLE telemetry_samples ADD COLUMN {col_name} {col_type};")

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_telemetry_timestamp 
                ON telemetry_samples (timestamp_utc);
                """
            )
            conn.commit()
            logger.info("Database SQLite verificato in: %s", self.db_path)

    def insert_sample(self, sample: TelemetrySample) -> int:
        fields = list(sample.model_dump().keys())
        cols = ", ".join(fields)
        vals = ", ".join(f":{f}" for f in fields)
        query = f"INSERT INTO telemetry_samples ({cols}) VALUES ({vals})"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, sample.model_dump())
            conn.commit()
            return cursor.lastrowid

    def get_latest_sample(self) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM telemetry_samples ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_samples(self, limit: int = 200) -> list[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM telemetry_samples ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_samples_count(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM telemetry_samples")
            return cursor.fetchone()[0]

    def import_file(self, file_path: Path) -> int:
        """
        Imports telemetry samples from a .jsonl or .jsonl.gz file into SQLite.
        Skips samples that already exist based on timestamp_utc.
        Returns the number of newly imported records.
        """
        import gzip
        import json

        if not file_path.exists() or file_path.stat().st_size == 0:
            return 0

        is_gz = file_path.suffix == ".gz" or file_path.name.endswith(".jsonl.gz")
        open_fn = gzip.open if is_gz else open

        imported = 0
        try:
            with open_fn(file_path, "rt", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()]

            with self._get_connection() as conn:
                cur = conn.cursor()
                for ln in lines:
                    try:
                        data = json.loads(ln)
                        ts = data.get("timestamp_utc")
                        if not ts:
                            continue
                        cur.execute("SELECT 1 FROM telemetry_samples WHERE timestamp_utc = ? LIMIT 1", (ts,))
                        if cur.fetchone():
                            continue
                        sample = TelemetrySample(**data)
                        self.insert_sample(sample)
                        imported += 1
                    except Exception:
                        pass
        except Exception as e:
            logger.error("Errore importazione file %s in SQLite: %s", file_path.name, e)

        return imported
