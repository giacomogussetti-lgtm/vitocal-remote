"""
Main Window for Vitocal 111-S & BTicino Smarther Management Application.
Includes Live Dashboard, Control Bench, JSON Feature Inspector,
and Advanced Interactive Multi-Axis History Charts with Fuzzy Channel Search.
"""
import bisect
import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import requests

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QLabel,
    QPushButton,
    QGroupBox,
    QGridLayout,
    QDoubleSpinBox,
    QSpinBox,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QTextEdit,
    QLineEdit,
    QMessageBox,
    QSplitter,
    QCheckBox,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QFrame,
)
import pyqtgraph as pg
from rapidfuzz import fuzz, process

from config import Config
from api.viessmann import ViessmannConnector
from api.bticino import BTicinoConnector
from storage.database import DatabaseManager
from storage.analytics import analyze_telemetry_period
from models.telemetry import TelemetrySample
from ui.heating_curve_widget import HeatingCurveWidget
from ui.synoptic_widget import PlantSynopticWidget

logger = logging.getLogger(__name__)

# Channel metadata definition:
# (db_column, display_name, unit, axis, hex_color, default_active, pen_style)
AVAILABLE_CHANNELS = [
    # Left Axis: Temperatures (°C)
    ("external_temp_c", "T Esterna Sonda PdC", "°C", "left", "#38bdf8", True, Qt.PenStyle.SolidLine),
    ("buffer_temp_c", "T Accumulo Puffer 200L", "°C", "left", "#f59e0b", True, Qt.PenStyle.SolidLine),
    ("pdc_supply_temp_c", "T Mandata Pompa di Calore", "°C", "left", "#ef4444", True, Qt.PenStyle.SolidLine),
    ("pdc_return_temp_c", "T Ritorno Pompa di Calore", "°C", "left", "#f43f5e", False, Qt.PenStyle.SolidLine),
    ("indoor_temp_bticino_c", "T Interna Corridoio (BTicino)", "°C", "left", "#10b981", True, Qt.PenStyle.SolidLine),
    ("indoor_setpoint_bticino_c", "Setpoint Termostato BTicino", "°C", "left", "#eab308", True, Qt.PenStyle.DashLine),
    ("dhw_storage_temp_c", "T Bollitore Sanitario ACS", "°C", "left", "#a855f7", False, Qt.PenStyle.SolidLine),
    ("hot_gas_temp_c", "T Gas Caldo Compressore", "°C", "left", "#fb923c", False, Qt.PenStyle.SolidLine),
    ("liquid_gas_temp_c", "T Gas Liquido Refrigerante", "°C", "left", "#06b6d4", False, Qt.PenStyle.SolidLine),
    ("suction_gas_temp_c", "T Gas Aspirazione Compressore", "°C", "left", "#3b82f6", False, Qt.PenStyle.SolidLine),
    # Right Axis: %, bar, COP
    ("compressor_modulation_percent", "Modulazione Compressore (%)", "%", "right", "#facc15", True, Qt.PenStyle.SolidLine),
    ("hot_gas_pressure_bar", "Pressione Gas Caldo (bar)", "bar", "right", "#ec4899", True, Qt.PenStyle.SolidLine),
    ("cop_heating", "COP Istantaneo Riscaldamento", "COP", "right", "#34d399", False, Qt.PenStyle.SolidLine),
    ("cop_total", "COP Totale Macchina", "COP", "right", "#4ade80", False, Qt.PenStyle.SolidLine),
    ("primary_pump_rotation_percent", "Velocità Pompa Primaria PdC (%)", "%", "right", "#818cf8", False, Qt.PenStyle.SolidLine),
    ("humidity_percent", "Umidità Ambiente Corridoio (%)", "%", "right", "#60a5fa", False, Qt.PenStyle.DashLine),
]


class ScalableAxisItem(pg.AxisItem):
    """
    AxisItem that supports double-clicking to configure custom axis limits or auto-scale.
    """
    axisDoubleClicked = pyqtSignal(str)

    def mouseDoubleClickEvent(self, event):
        self.axisDoubleClicked.emit(self.orientation)
        event.accept()


class AxisRangeDialog(QDialog):
    """
    Dialog to set custom Min and Max axis limits or enable Auto-Range.
    """
    def __init__(self, title: str, unit: str, current_min: float, current_max: float, is_auto: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(360)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.chk_auto = QCheckBox("Scala Automatica (Auto-Range)")
        self.chk_auto.setChecked(is_auto)
        self.chk_auto.toggled.connect(self._on_auto_toggled)
        layout.addWidget(self.chk_auto)

        grid = QGridLayout()
        grid.addWidget(QLabel("Valore Minimo (Inizio Scala):"), 0, 0)
        self.spin_min = QDoubleSpinBox()
        self.spin_min.setRange(-100.0, 500.0)
        self.spin_min.setDecimals(1)
        self.spin_min.setValue(current_min)
        self.spin_min.setSuffix(f" {unit}")
        grid.addWidget(self.spin_min, 0, 1)

        grid.addWidget(QLabel("Valore Massimo (Fondo Scala):"), 1, 0)
        self.spin_max = QDoubleSpinBox()
        self.spin_max.setRange(-100.0, 500.0)
        self.spin_max.setDecimals(1)
        self.spin_max.setValue(current_max)
        self.spin_max.setSuffix(f" {unit}")
        grid.addWidget(self.spin_max, 1, 1)

        layout.addLayout(grid)

        # Quick preset buttons
        row_presets = QHBoxLayout()
        if unit == "°C":
            presets = [("0 - 45 °C", 0, 45), ("-10 - 40 °C", -10, 40), ("5 - 30 °C", 5, 30)]
        else:
            presets = [("0 - 100 %", 0, 100), ("0 - 20 bar", 0, 20), ("0 - 6 COP", 0, 6)]

        for p_name, p_min, p_max in presets:
            btn = QPushButton(p_name)
            btn.setStyleSheet("background: #1e293b; color: #94a3b8; font-size: 11px; padding: 4px;")
            btn.clicked.connect(lambda _, mi=p_min, ma=p_max: self._set_range(mi, ma))
            row_presets.addWidget(btn)
        layout.addLayout(row_presets)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Annulla")
        btn_cancel.setStyleSheet("background: #334155;")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("Applica")
        btn_ok.clicked.connect(self.accept)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        layout.addLayout(btns)

        self._on_auto_toggled(is_auto)

    def _set_range(self, p_min: float, p_max: float):
        self.chk_auto.setChecked(False)
        self.spin_min.setValue(p_min)
        self.spin_max.setValue(p_max)

    def _on_auto_toggled(self, checked: bool):
        self.spin_min.setEnabled(not checked)
        self.spin_max.setEnabled(not checked)

    def get_values(self) -> tuple[bool, float, float]:
        return self.chk_auto.isChecked(), self.spin_min.value(), self.spin_max.value()


class AbsoluteTimeAxisItem(pg.AxisItem):
    """
    Renders absolute timestamp on X-axis as human readable local Date & Time.
    e.g. '18/11 01:25' or '01:25:30'.
    """
    def tickStrings(self, values, scale, spacing):
        strings = []
        for val in values:
            try:
                dt = datetime.fromtimestamp(val)
                if spacing < 120:
                    strings.append(dt.strftime("%H:%M:%S"))
                elif spacing < 86400:
                    strings.append(dt.strftime("%d/%m\n%H:%M"))
                else:
                    strings.append(dt.strftime("%d/%m/%y"))
            except Exception:
                strings.append("")
        return strings


class FetchDataWorker(QThread):
    finished = pyqtSignal(dict, dict, object)
    error = pyqtSignal(str)

    def __init__(self, v_conn: ViessmannConnector, b_conn: Optional[BTicinoConnector], db: DatabaseManager):
        super().__init__()
        self.v_conn = v_conn
        self.b_conn = b_conn
        self.db = db

    def run(self):
        try:
            v_data = {}
            b_data = {}

            # Fetch Viessmann
            try:
                v_data = self.v_conn.get_telemetry()
            except Exception as e:
                logger.error("Errore Viessmann: %s", e)

            # Fetch BTicino
            if self.b_conn:
                try:
                    b_data = self.b_conn.get_status()
                except Exception as e:
                    logger.error("Errore BTicino: %s", e)

            # Prevent missing sensor drop: fallback to previous valid readings if temporary drop occurred
            if not b_data or b_data.get("indoor_temp_c") is None or b_data.get("setpoint_c") is None:
                try:
                    with self.db._get_connection() as conn:
                        c = conn.cursor()
                        c.execute(
                            "SELECT indoor_temp_bticino_c, indoor_setpoint_bticino_c, humidity_percent "
                            "FROM telemetry_samples WHERE indoor_temp_bticino_c IS NOT NULL ORDER BY id DESC LIMIT 1"
                        )
                        prev = c.fetchone()
                        if prev:
                            if b_data.get("indoor_temp_c") is None:
                                b_data["indoor_temp_c"] = prev["indoor_temp_bticino_c"]
                            if b_data.get("setpoint_c") is None:
                                b_data["setpoint_c"] = prev["indoor_setpoint_bticino_c"]
                            if b_data.get("humidity_percent") is None:
                                b_data["humidity_percent"] = prev["humidity_percent"]
                except Exception as e:
                    logger.warning("Errore fallback SQLite per BTicino: %s", e)

            # Save full rich TelemetrySample to SQLite
            sample = TelemetrySample(
                external_temp_c=v_data.get("outside_temp_c"),
                indoor_temp_bticino_c=b_data.get("indoor_temp_c"),
                indoor_setpoint_bticino_c=b_data.get("setpoint_c"),
                grundfos_pump_active=b_data.get("grundfos_pump_active"),
                pdc_supply_temp_c=v_data.get("supply_temp_c"),
                pdc_return_temp_c=v_data.get("return_temp_c"),
                buffer_temp_c=v_data.get("buffer_temp_c"),
                dhw_storage_temp_c=v_data.get("dhw_storage_temp_c"),
                compressor_active=1 if (v_data.get("compressor_active") or (v_data.get("compressor_modulation_percent", 0) or 0) > 0) else 0,
                compressor_hours=v_data.get("compressor_hours"),
                compressor_starts=v_data.get("compressor_starts"),
                heating_curve_slope=v_data.get("heating_curve_slope"),
                heating_curve_shift=v_data.get("heating_curve_shift"),
                active_mode=v_data.get("active_mode"),
                active_program=v_data.get("active_program"),
                heating_elec_kwh_total=v_data.get("power_consumption_heating_today_kwh"),
                dhw_elec_kwh_total=v_data.get("power_consumption_dhw_today_kwh"),
                dhw_thermal_kwh_total=v_data.get("heat_production_dhw_today_kwh"),
                hot_gas_pressure_bar=v_data.get("hot_gas_pressure_bar"),
                hot_gas_temp_c=v_data.get("hot_gas_temp_c"),
                liquid_gas_temp_c=v_data.get("liquid_gas_temp_c"),
                suction_gas_temp_c=v_data.get("suction_gas_temp_c"),
                compressor_modulation_percent=v_data.get("compressor_modulation_percent"),
                primary_pump_rotation_percent=v_data.get("primary_pump_rotation_percent"),
                cop_heating=v_data.get("cop_heating"),
                cop_dhw=v_data.get("cop_dhw"),
                cop_total=v_data.get("cop_total"),
                humidity_percent=b_data.get("humidity_percent"),
                active_preset="desktop_gui",
            )
            sample_id = self.db.insert_sample(sample)

            self.finished.emit(v_data, b_data, sample_id)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vitocal 111-S & BTicino Smarther — Gestionale Impianto")
        self.resize(1300, 850)

        # Connectors & DB
        self.db = DatabaseManager()
        self.v_conn = ViessmannConnector()
        self.b_conn = BTicinoConnector()

        self.latest_v_data: dict[str, Any] = {}
        self.latest_b_data: dict[str, Any] = {}
        self.all_features_data: list[dict] = []

        # Channel active states: db_col -> bool
        self.active_channels: dict[str, bool] = {c[0]: c[5] for c in AVAILABLE_CHANNELS}
        self.channel_curves: dict[str, Any] = {}
        self.region_items: list[Any] = []

        # Auto-polling state
        self.poll_interval_seconds = Config.POLL_INTERVAL_MINUTES * 60
        self.countdown_remaining = self.poll_interval_seconds

        # Synoptic and Heating Curve widgets
        self.synoptic_widget = PlantSynopticWidget()
        self.heating_curve_widget = HeatingCurveWidget()

        # Chart axis scaling modes: 'auto' or 'fixed'
        self.left_axis_mode = "auto"
        self.left_axis_min = 0.0
        self.left_axis_max = 45.0
        self.right_axis_mode = "auto"
        self.right_axis_min = 0.0
        self.right_axis_max = 100.0

        # Confirmed Hardware State for Staging & Sync LEDs
        self.saved_slope = 0.6
        self.saved_shift = 0
        self.saved_temp_norm = 12.0
        self.saved_temp_red = 12.0
        self.saved_bt_setpoint = 7.0

        # Cached chart data for dynamic crosshair hover inspection
        self.cached_chart_timestamps: list[float] = []
        self.cached_chart_rows: list[Any] = []
        self.current_hovered_channel: Optional[str] = None

        self._init_theme()
        self._init_ui()
        self._init_timers()
        self._load_latest_db_sample()

        # Startup in offline/manual mode by default (no automatic API calls)
        self.footer_label.setText("Pronto. Dati storici caricati da SQLite locale. Nessuna chiamata automatica alle API.")

    def _init_theme(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #121417;
                color: #e0e0e0;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            QWidget {
                color: #e0e0e0;
                font-size: 13px;
            }
            QTabWidget::pane {
                border: 1px solid #2a2e35;
                background-color: #1a1d24;
                border-radius: 8px;
            }
            QTabBar::tab {
                background: #1e222b;
                color: #9aa0a6;
                padding: 10px 24px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #1a1d24;
                color: #38bdf8;
                border-bottom: 2px solid #38bdf8;
            }
            QGroupBox {
                border: 1px solid #2a2e35;
                border-radius: 8px;
                margin-top: 12px;
                font-weight: bold;
                padding-top: 18px;
                background-color: #1a1d24;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 6px;
                color: #38bdf8;
            }
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            QPushButton:pressed {
                background-color: #1e40af;
            }
            QPushButton#btn-refresh {
                background-color: #059669;
            }
            QPushButton#btn-refresh:hover {
                background-color: #047857;
            }
            QPushButton#btn-preset {
                background-color: #4338ca;
                padding: 12px;
                text-align: left;
            }
            QPushButton#btn-preset:hover {
                background-color: #3730a3;
            }
            QPushButton#btn-auto-fit {
                background-color: #0891b2;
            }
            QPushButton#btn-auto-fit:hover {
                background-color: #0e7490;
            }
            QLineEdit, QComboBox {
                background-color: #222630;
                border: 1px solid #374151;
                border-radius: 6px;
                padding: 6px;
                color: #f3f4f6;
            }
            QSpinBox, QDoubleSpinBox {
                background-color: #1e222b;
                border: 1px solid #374151;
                border-radius: 6px;
                padding-left: 8px;
                padding-right: 28px;
                padding-top: 2px;
                padding-bottom: 2px;
                color: #f3f4f6;
                font-size: 13px;
                font-weight: bold;
                min-height: 30px;
            }
            QSpinBox::up-button, QDoubleSpinBox::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 24px;
                height: 15px;
                border-left: 1px solid #374151;
                background-color: #2a313d;
                border-top-right-radius: 5px;
            }
            QSpinBox::down-button, QDoubleSpinBox::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 24px;
                height: 15px;
                border-left: 1px solid #374151;
                border-top: 1px solid #374151;
                background-color: #2a313d;
                border-bottom-right-radius: 5px;
            }
            QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
            QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
                background-color: #2563eb;
            }
            QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
            QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {
                background-color: #1d4ed8;
            }
            QPushButton.btn-step {
                background-color: #1e293b;
                color: #e2e8f0;
                border: 1px solid #475569;
                border-radius: 6px;
                font-size: 15px;
                font-weight: bold;
                min-width: 32px;
                max-width: 32px;
                min-height: 32px;
                max-height: 32px;
            }
            QPushButton.btn-step:hover {
                background-color: #334155;
                color: #38bdf8;
                border-color: #38bdf8;
            }
            QPushButton.btn-step:pressed {
                background-color: #2563eb;
                color: #ffffff;
            }
            QPushButton.btn-reset-val {
                background-color: #1e222b;
                color: #94a3b8;
                border: 1px solid #374151;
                border-radius: 6px;
                font-size: 14px;
                min-width: 32px;
                max-width: 32px;
                min-height: 32px;
                max-height: 32px;
            }
            QPushButton.btn-reset-val:hover {
                background-color: #374151;
                color: #facc15;
                border-color: #facc15;
            }
            QTableWidget, QListWidget {
                background-color: #1a1d24;
                border: 1px solid #2a2e35;
                gridline-color: #2a2e35;
                border-radius: 6px;
            }
            QHeaderView::section {
                background-color: #222630;
                color: #9aa0a6;
                padding: 6px;
                font-weight: bold;
                border: 1px solid #2a2e35;
            }
            QTextEdit {
                background-color: #16181e;
                border: 1px solid #2a2e35;
                border-radius: 6px;
                font-family: 'Consolas', 'Courier New', monospace;
                color: #7dd3fc;
            }
            QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #4b5563;
                background-color: #222630;
            }
            QCheckBox::indicator:checked {
                background-color: #38bdf8;
                border-color: #38bdf8;
            }
            /* High-Contrast Dialogs, Popups, and MessageBoxes */
            QDialog, QMessageBox {
                background-color: #1e222b;
                color: #f8fafc;
            }
            QDialog QLabel, QMessageBox QLabel {
                color: #f8fafc;
                font-size: 13px;
                font-weight: 500;
            }
            QDialog QPushButton, QMessageBox QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                border-radius: 6px;
                padding: 8px 18px;
                font-weight: bold;
                min-width: 80px;
                border: 1px solid #3b82f6;
            }
            QDialog QPushButton:hover, QMessageBox QPushButton:hover {
                background-color: #1d4ed8;
            }
            QDialog QDoubleSpinBox, QDialog QSpinBox, QDialog QLineEdit {
                background-color: #0f172a;
                color: #f8fafc;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 6px;
            }
        """)

    def _init_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Top Bar
        top_bar = QHBoxLayout()
        title_label = QLabel("VITOCAL 111-S & BTICINO SMARTHER")
        title_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #38bdf8;")

        subtitle = QLabel("Gestionale Unificato & Banchetto Prova")
        subtitle.setStyleSheet("color: #9ca3af; margin-left: 10px;")

        top_bar.addWidget(title_label)
        top_bar.addWidget(subtitle)
        top_bar.addStretch()

        # Polling Controls (Default OFF / Manual on startup)
        self.chk_auto_poll = QCheckBox("Auto-Logger")
        self.chk_auto_poll.setChecked(False)
        self.chk_auto_poll.toggled.connect(self._on_auto_poll_toggled)

        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(5, 60)
        self.spin_interval.setSingleStep(5)
        self.spin_interval.setValue(Config.POLL_INTERVAL_MINUTES)
        self.spin_interval.setSuffix(" min")
        self.spin_interval.valueChanged.connect(self._on_interval_changed)

        self.lbl_countdown = QLabel("Auto-Logger: PAUSA")
        self.lbl_countdown.setStyleSheet("color: #94a3b8; font-weight: bold; padding: 4px 8px; background: #1e293b; border-radius: 4px;")

        top_bar.addWidget(self.chk_auto_poll)
        top_bar.addWidget(self.spin_interval)
        top_bar.addWidget(self.lbl_countdown)

        self.status_viessmann = QLabel("Viessmann: Offline / Manuale")
        self.status_viessmann.setStyleSheet("color: #94a3b8; font-weight: bold; padding: 4px 10px; background: #1f2937; border-radius: 4px;")
        self.status_bticino = QLabel("BTicino: Offline / Manuale")
        self.status_bticino.setStyleSheet("color: #94a3b8; font-weight: bold; padding: 4px 10px; background: #1f2937; border-radius: 4px;")

        self.btn_refresh = QPushButton("Aggiorna Ora")
        self.btn_refresh.setObjectName("btn-refresh")
        self.btn_refresh.clicked.connect(self.refresh_data)

        self.btn_cloud_sync = QPushButton("☁️ Sync Cloud (GitHub)")
        self.btn_cloud_sync.setStyleSheet("background-color: #0284c7; color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold;")
        self.btn_cloud_sync.setToolTip("Importa le letture registrate in background 24/7 dal workflow GitHub Actions")
        self.btn_cloud_sync.clicked.connect(self._on_sync_cloud_clicked)

        top_bar.addWidget(self.status_viessmann)
        top_bar.addWidget(self.status_bticino)
        top_bar.addWidget(self.btn_refresh)
        top_bar.addWidget(self.btn_cloud_sync)
        main_layout.addLayout(top_bar)

        # Tabs
        self.tabs = QTabWidget()
        self.tab_dashboard = QWidget()
        self.tab_control = QWidget()
        self.tab_inspector = QWidget()
        self.tab_history = QWidget()
        self.tab_analytics = QWidget()

        self.tabs.addTab(self.tab_dashboard, "📊 Dashboard Live")
        self.tabs.addTab(self.synoptic_widget, "🗺️ Sinottico Impianto & Sonde")
        self.tabs.addTab(self.tab_control, "🎛️ Banchetto Comandi & Preset")
        self.tabs.addTab(self.tab_inspector, "🔍 JSON Feature Inspector (193+ Parametri)")
        self.tabs.addTab(self.tab_history, "📈 Grafici & Cicli Compressore (SQLite)")
        self.tabs.addTab(self.tab_analytics, "⏱️ Statistiche & Efficienza (X Ore)")

        self._build_dashboard_tab()
        self._build_control_tab()
        self._build_inspector_tab()
        self._build_history_tab()
        self._build_analytics_tab()

        main_layout.addWidget(self.tabs)

        # Status Bar Info
        self.footer_label = QLabel("Pronto.")
        self.footer_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        main_layout.addWidget(self.footer_label)

        self.setCentralWidget(main_widget)

    def _init_timers(self):
        # 1-second timer for UI countdown
        self.timer_countdown = QTimer(self)
        self.timer_countdown.timeout.connect(self._tick_countdown)
        self.timer_countdown.start(1000)

    def _tick_countdown(self):
        if not self.chk_auto_poll.isChecked():
            self.lbl_countdown.setText("Auto-Logger: PAUSA")
            return

        self.countdown_remaining -= 1
        if self.countdown_remaining <= 0:
            self.countdown_remaining = self.poll_interval_seconds
            self.refresh_data()
        else:
            mins = self.countdown_remaining // 60
            secs = self.countdown_remaining % 60
            self.lbl_countdown.setText(f"Prossimo: {mins:02d}:{secs:02d}")

    def _on_auto_poll_toggled(self, checked: bool):
        if checked:
            self.countdown_remaining = self.poll_interval_seconds
        else:
            self.lbl_countdown.setText("Auto-Logger: PAUSA")

    def _on_interval_changed(self, val: int):
        self.poll_interval_seconds = val * 60
        self.countdown_remaining = self.poll_interval_seconds

    # --------------------------------------------------------------------------
    # Tab 1: Dashboard
    # --------------------------------------------------------------------------
    def _build_dashboard_tab(self):
        layout = QHBoxLayout(self.tab_dashboard)
        layout.setSpacing(16)

        left_box = QGroupBox("POMPA DI CALORE VIESSMANN VITOCAL 111-S (Circuito Primario & Puffer 200 L)")
        left_layout = QVBoxLayout(left_box)

        grid_v = QGridLayout()
        grid_v.setSpacing(10)

        def add_metric(row, col, title, initial_val="--"):
            lbl_title = QLabel(title)
            lbl_title.setStyleSheet("color: #9ca3af; font-size: 11px;")
            lbl_val = QLabel(initial_val)
            lbl_val.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
            lbl_val.setStyleSheet("color: #f3f4f6;")
            box = QWidget()
            b_lay = QVBoxLayout(box)
            b_lay.setContentsMargins(6, 6, 6, 6)
            b_lay.addWidget(lbl_title)
            b_lay.addWidget(lbl_val)
            box.setStyleSheet("background-color: #222630; border-radius: 6px;")
            grid_v.addWidget(box, row, col)
            return lbl_val

        self.val_ext_temp = add_metric(0, 0, "TEMPERATURA ESTERNA")
        self.val_buffer_temp = add_metric(0, 1, "PUFFER INERZIALE 200L")
        self.val_dhw_temp = add_metric(0, 2, "BOLLITORE ACS")

        self.val_supply_temp = add_metric(1, 0, "MANDATA PDC")
        self.val_return_temp = add_metric(1, 1, "RITORNO PDC")
        self.val_curve = add_metric(1, 2, "CURVA CLIMATICA")

        self.val_comp_status = add_metric(2, 0, "COMPRESSORE 11 kW")
        self.val_comp_modul = add_metric(2, 1, "MODULAZIONE %")
        self.val_comp_hours = add_metric(2, 2, "ORE TOTALI COMPRESSORE")

        self.val_cop_heating = add_metric(3, 0, "COP RISCALDAMENTO")
        self.val_cop_dhw = add_metric(3, 1, "COP ACS")
        self.val_gas_pressure = add_metric(3, 2, "PRESSIONE GAS CALDO")

        left_layout.addLayout(grid_v)
        left_layout.addStretch()

        right_box = QGroupBox("TERMOSTATO SMART BTICINO & CIRCOLATORE GRUNDFOS (Circuito Secondario)")
        right_layout = QVBoxLayout(right_box)

        grid_b = QGridLayout()
        grid_b.setSpacing(10)

        def add_b_metric(row, col, title, initial_val="--"):
            lbl_title = QLabel(title)
            lbl_title.setStyleSheet("color: #9ca3af; font-size: 11px;")
            lbl_val = QLabel(initial_val)
            lbl_val.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
            lbl_val.setStyleSheet("color: #f3f4f6;")
            box = QWidget()
            b_lay = QVBoxLayout(box)
            b_lay.setContentsMargins(6, 6, 6, 6)
            b_lay.addWidget(lbl_title)
            b_lay.addWidget(lbl_val)
            box.setStyleSheet("background-color: #222630; border-radius: 6px;")
            grid_b.addWidget(box, row, col)
            return lbl_val

        self.val_indoor_temp = add_b_metric(0, 0, "TEMPERATURA INTERNA REALE")
        self.val_indoor_setpoint = add_b_metric(0, 1, "SETPOINT ATTIVO")
        self.val_humidity = add_b_metric(1, 0, "UMIDITÀ RELATIVA")
        self.val_bticino_mode = add_b_metric(1, 1, "MODALITÀ TERMOSTATO")

        right_layout.addLayout(grid_b)

        self.banner_grundfos = QLabel("POMPA GRUNDFOS: SPENTA (Massetto radiante disaccoppiato)")
        self.banner_grundfos.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner_grundfos.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.banner_grundfos.setStyleSheet("background-color: #374151; color: #d1d5db; padding: 16px; border-radius: 8px; margin-top: 10px;")
        right_layout.addWidget(self.banner_grundfos)

        self.lbl_hydraulic_sync = QLabel(
            "Stato Accoppiamento Termodinamico:\n• Grundfos SPENTA: la PdC carica solo i 200 L di puffer.\n"
            "• Grundfos ACCESA: calore trasferito direttamente al massetto radiante ad alta inerzia."
        )
        self.lbl_hydraulic_sync.setStyleSheet("color: #9ca3af; font-size: 12px; background: #16181e; padding: 12px; border-radius: 6px; margin-top: 10px;")
        right_layout.addWidget(self.lbl_hydraulic_sync)
        right_layout.addStretch()

        layout.addWidget(left_box, 60)
        layout.addWidget(right_box, 40)

    # --------------------------------------------------------------------------
    # Tab 2: Control Bench & Presets
    # --------------------------------------------------------------------------
    def _build_control_tab(self):
        layout = QHBoxLayout(self.tab_control)
        layout.setSpacing(16)

        direct_box = QGroupBox("COMANDI DIRETTI (Scrittura con verifica Read-Back)")
        d_layout = QVBoxLayout(direct_box)

        # Curve Adjustment
        curve_sub = QGroupBox("Regolazione Curva Climatica PdC")
        c_lay = QVBoxLayout(curve_sub)
        c_lay.setSpacing(10)

        # Slope row with steppers and reset button
        r_slope = QHBoxLayout()
        lbl_slope = QLabel("Inclinazione (Slope):")
        lbl_slope.setFixedWidth(140)
        btn_slope_minus = QPushButton("−")
        btn_slope_minus.setProperty("class", "btn-step")
        self.spin_slope = QDoubleSpinBox()
        self.spin_slope.setRange(0.2, 2.5)
        self.spin_slope.setSingleStep(0.1)
        self.spin_slope.setDecimals(2)
        self.spin_slope.setValue(self.saved_slope)
        btn_slope_plus = QPushButton("+")
        btn_slope_plus.setProperty("class", "btn-step")
        btn_slope_reset = QPushButton("↺")
        btn_slope_reset.setProperty("class", "btn-reset-val")
        btn_slope_reset.setToolTip("Ripristina al valore confermato da Vitocal")

        btn_slope_minus.clicked.connect(lambda: self.spin_slope.setValue(round(self.spin_slope.value() - 0.1, 2)))
        btn_slope_plus.clicked.connect(lambda: self.spin_slope.setValue(round(self.spin_slope.value() + 0.1, 2)))
        btn_slope_reset.clicked.connect(self._reset_slope_to_saved)

        r_slope.addWidget(lbl_slope)
        r_slope.addWidget(btn_slope_minus)
        r_slope.addWidget(self.spin_slope)
        r_slope.addWidget(btn_slope_plus)
        r_slope.addWidget(btn_slope_reset)
        c_lay.addLayout(r_slope)

        # Shift row with steppers and reset button
        r_shift = QHBoxLayout()
        lbl_shift = QLabel("Livello (Shift):")
        lbl_shift.setFixedWidth(140)
        btn_shift_minus = QPushButton("−")
        btn_shift_minus.setProperty("class", "btn-step")
        self.spin_shift = QSpinBox()
        self.spin_shift.setRange(-15, 15)
        self.spin_shift.setValue(self.saved_shift)
        self.spin_shift.setSuffix(" K")
        btn_shift_plus = QPushButton("+")
        btn_shift_plus.setProperty("class", "btn-step")
        btn_shift_reset = QPushButton("↺")
        btn_shift_reset.setProperty("class", "btn-reset-val")
        btn_shift_reset.setToolTip("Ripristina al valore confermato da Vitocal")

        btn_shift_minus.clicked.connect(lambda: self.spin_shift.setValue(self.spin_shift.value() - 1))
        btn_shift_plus.clicked.connect(lambda: self.spin_shift.setValue(self.spin_shift.value() + 1))
        btn_shift_reset.clicked.connect(self._reset_shift_to_saved)

        r_shift.addWidget(lbl_shift)
        r_shift.addWidget(btn_shift_minus)
        r_shift.addWidget(self.spin_shift)
        r_shift.addWidget(btn_shift_plus)
        r_shift.addWidget(btn_shift_reset)
        c_lay.addLayout(r_shift)

        # LED status line & apply button
        r_curve_action = QHBoxLayout()
        self.led_curve = QLabel("🟢 Sincronizzato con Vitocal")
        self.led_curve.setStyleSheet("color: #10b981; font-weight: bold; font-size: 11px;")
        self.btn_apply_curve = QPushButton("Applica Curva Climatica")
        self.btn_apply_curve.clicked.connect(self._on_apply_curve)
        r_curve_action.addWidget(self.led_curve)
        r_curve_action.addStretch()
        r_curve_action.addWidget(self.btn_apply_curve)
        c_lay.addLayout(r_curve_action)

        d_layout.addWidget(curve_sub)

        # Setpoints
        setp_sub = QGroupBox("Temperature Target Riscaldamento PdC")
        s_lay = QVBoxLayout(setp_sub)
        s_lay.setSpacing(10)

        # Temp Normale row with steppers and reset button
        r_norm = QHBoxLayout()
        lbl_norm = QLabel("Temp. Normale (°C):")
        lbl_norm.setFixedWidth(140)
        btn_norm_minus = QPushButton("−")
        btn_norm_minus.setProperty("class", "btn-step")
        self.spin_temp_norm = QDoubleSpinBox()
        self.spin_temp_norm.setRange(10, 30)
        self.spin_temp_norm.setSingleStep(0.5)
        self.spin_temp_norm.setValue(self.saved_temp_norm)
        self.spin_temp_norm.setSuffix(" °C")
        btn_norm_plus = QPushButton("+")
        btn_norm_plus.setProperty("class", "btn-step")
        btn_norm_reset = QPushButton("↺")
        btn_norm_reset.setProperty("class", "btn-reset-val")
        btn_norm_reset.setToolTip("Ripristina al valore confermato da Vitocal")

        btn_norm_minus.clicked.connect(lambda: self.spin_temp_norm.setValue(round(self.spin_temp_norm.value() - 0.5, 1)))
        btn_norm_plus.clicked.connect(lambda: self.spin_temp_norm.setValue(round(self.spin_temp_norm.value() + 0.5, 1)))
        btn_norm_reset.clicked.connect(self._reset_temp_norm_to_saved)

        self.btn_apply_norm = QPushButton("Imposta Normale")
        self.btn_apply_norm.clicked.connect(self._on_apply_temp_norm)

        r_norm.addWidget(lbl_norm)
        r_norm.addWidget(btn_norm_minus)
        r_norm.addWidget(self.spin_temp_norm)
        r_norm.addWidget(btn_norm_plus)
        r_norm.addWidget(btn_norm_reset)
        r_norm.addWidget(self.btn_apply_norm)
        s_lay.addLayout(r_norm)

        self.led_norm = QLabel("🟢 Sincronizzato con Vitocal")
        self.led_norm.setStyleSheet("color: #10b981; font-weight: bold; font-size: 11px; margin-bottom: 4px;")
        s_lay.addWidget(self.led_norm)

        # Temp Ridotta row with steppers and reset button
        r_red = QHBoxLayout()
        lbl_red = QLabel("Temp. Ridotta (°C):")
        lbl_red.setFixedWidth(140)
        btn_red_minus = QPushButton("−")
        btn_red_minus.setProperty("class", "btn-step")
        self.spin_temp_red = QDoubleSpinBox()
        self.spin_temp_red.setRange(10, 30)
        self.spin_temp_red.setSingleStep(0.5)
        self.spin_temp_red.setValue(self.saved_temp_red)
        self.spin_temp_red.setSuffix(" °C")
        btn_red_plus = QPushButton("+")
        btn_red_plus.setProperty("class", "btn-step")
        btn_red_reset = QPushButton("↺")
        btn_red_reset.setProperty("class", "btn-reset-val")
        btn_red_reset.setToolTip("Ripristina al valore confermato da Vitocal")

        btn_red_minus.clicked.connect(lambda: self.spin_temp_red.setValue(round(self.spin_temp_red.value() - 0.5, 1)))
        btn_red_plus.clicked.connect(lambda: self.spin_temp_red.setValue(round(self.spin_temp_red.value() + 0.5, 1)))
        btn_red_reset.clicked.connect(self._reset_temp_red_to_saved)

        self.btn_apply_red = QPushButton("Imposta Ridotta")
        self.btn_apply_red.clicked.connect(self._on_apply_temp_red)

        r_red.addWidget(lbl_red)
        r_red.addWidget(btn_red_minus)
        r_red.addWidget(self.spin_temp_red)
        r_red.addWidget(btn_red_plus)
        r_red.addWidget(btn_red_reset)
        r_red.addWidget(self.btn_apply_red)
        s_lay.addLayout(r_red)

        self.led_red = QLabel("🟢 Sincronizzato con Vitocal")
        self.led_red.setStyleSheet("color: #10b981; font-weight: bold; font-size: 11px;")
        s_lay.addWidget(self.led_red)

        d_layout.addWidget(setp_sub)

        # BTicino Setpoint
        bt_sub = QGroupBox("Regolazione Termostato BTicino (Corridoio)")
        b_lay = QVBoxLayout(bt_sub)
        b_lay.setSpacing(10)

        r_bt = QHBoxLayout()
        lbl_bt = QLabel("Nuovo Setpoint Manuale (°C):")
        lbl_bt.setFixedWidth(180)
        btn_bt_minus = QPushButton("−")
        btn_bt_minus.setProperty("class", "btn-step")
        self.spin_bt_setpoint = QDoubleSpinBox()
        self.spin_bt_setpoint.setRange(5.0, 25.0)
        self.spin_bt_setpoint.setSingleStep(0.5)
        self.spin_bt_setpoint.setValue(self.saved_bt_setpoint)
        self.spin_bt_setpoint.setSuffix(" °C")
        btn_bt_plus = QPushButton("+")
        btn_bt_plus.setProperty("class", "btn-step")
        btn_bt_reset = QPushButton("↺")
        btn_bt_reset.setProperty("class", "btn-reset-val")
        btn_bt_reset.setToolTip("Ripristina al valore confermato da BTicino")

        btn_bt_minus.clicked.connect(lambda: self.spin_bt_setpoint.setValue(round(self.spin_bt_setpoint.value() - 0.5, 1)))
        btn_bt_plus.clicked.connect(lambda: self.spin_bt_setpoint.setValue(round(self.spin_bt_setpoint.value() + 0.5, 1)))
        btn_bt_reset.clicked.connect(self._reset_bt_setpoint_to_saved)

        self.btn_apply_bt = QPushButton("Invia a BTicino")
        self.btn_apply_bt.clicked.connect(self._on_apply_bticino_setpoint)

        r_bt.addWidget(lbl_bt)
        r_bt.addWidget(btn_bt_minus)
        r_bt.addWidget(self.spin_bt_setpoint)
        r_bt.addWidget(btn_bt_plus)
        r_bt.addWidget(btn_bt_reset)
        r_bt.addWidget(self.btn_apply_bt)
        b_lay.addLayout(r_bt)

        self.led_bt = QLabel("🟢 Sincronizzato con BTicino")
        self.led_bt.setStyleSheet("color: #10b981; font-weight: bold; font-size: 11px;")
        b_lay.addWidget(self.led_bt)

        r_modes = QHBoxLayout()
        self.btn_bt_home = QPushButton("📅 Ripristina Programma (Home)")
        self.btn_bt_home.clicked.connect(lambda: self._on_apply_bticino_mode("home"))
        self.btn_bt_hg = QPushButton("❄️ Antigelo Fisso (HG)")
        self.btn_bt_hg.clicked.connect(lambda: self._on_apply_bticino_mode("hg"))
        r_modes.addWidget(self.btn_bt_home)
        r_modes.addWidget(self.btn_bt_hg)
        b_lay.addLayout(r_modes)

        d_layout.addWidget(bt_sub)

        d_layout.addStretch()

        presets_box = QGroupBox("PRESET MULTI-DISPOSITIVO (Viessmann + BTicino)")
        p_layout = QVBoxLayout(presets_box)
        p_layout.setSpacing(10)

        # Fictitious button to create presets
        self.btn_new_preset = QPushButton("➕ Crea Nuovo Preset Personalizzato")
        self.btn_new_preset.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #60a5fa;
                font-size: 13px;
                font-weight: bold;
                padding: 12px 16px;
                border: 2px dashed #3b82f6;
                border-radius: 8px;
                text-align: center;
            }
            QPushButton:hover {
                background-color: #1e3a8a;
                color: #ffffff;
                border: 2px solid #60a5fa;
            }
        """)
        self.btn_new_preset.clicked.connect(self._on_placeholder_preset_clicked)
        p_layout.addWidget(self.btn_new_preset)

        # Informative descriptive card so user remembers how presets work
        memo_box = QWidget()
        memo_lay = QVBoxLayout(memo_box)
        memo_lay.setContentsMargins(12, 12, 12, 12)
        memo_lay.setSpacing(8)
        memo_box.setStyleSheet("background-color: #161a22; border: 1px solid #30363d; border-radius: 8px;")

        lbl_memo_title = QLabel("📋 GESTIONE PRESET MULTI-DISPOSITIVO (Promemoria Funzionamento):")
        lbl_memo_title.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 12px;")
        memo_lay.addWidget(lbl_memo_title)

        lbl_memo_desc = QLabel(
            "I preset consentiranno di orchestrare con un singolo clic sia la Pompa di Calore Viessmann "
            "che il termostato ambiente BTicino Smarther:\n\n"
            "• <b>Parametri Viessmann:</b> Curva Climatica (Inclinazione & Livello), "
            "Temperatura Normale, Temperatura Ridotta, Modalità Operativa.\n"
            "• <b>Parametri BTicino:</b> Setpoint temperatura ambiente, modalità (Manuale / Programma Home / Antigelo HG) "
            "e consenso relè pompa Grundfos a pavimento.\n\n"
            "💡 <b>Obiettivo Termodinamico Chiave:</b>\n"
            "Sincronizzare l'accensione della PdC nelle ore centrali più calde (massimo COP) "
            "con l'avvio forzato della Grundfos per immagazzinare calore nel massetto radiante, "
            "evitando che la PdC da 11 kW saturi i soli 200 litri di puffer lavorando a cicli brevi."
        )
        lbl_memo_desc.setWordWrap(True)
        lbl_memo_desc.setStyleSheet("color: #cbd5e1; font-size: 11px; line-height: 1.4;")
        memo_lay.addWidget(lbl_memo_desc)

        p_layout.addWidget(memo_box)
        p_layout.addStretch()

        left_scroll = QWidget()
        l_scroll_lay = QVBoxLayout(left_scroll)
        l_scroll_lay.setContentsMargins(0, 0, 0, 0)
        l_scroll_lay.addWidget(direct_box)
        l_scroll_lay.addWidget(presets_box)

        layout.addWidget(left_scroll, 45)
        layout.addWidget(self.heating_curve_widget, 55)

        # Connect input changed signals for real-time validation, heating curve preview and sync status
        self.spin_slope.valueChanged.connect(self._on_slope_input_changed)
        self.spin_shift.valueChanged.connect(self._on_shift_input_changed)
        self.spin_temp_norm.valueChanged.connect(self._on_temp_norm_input_changed)
        self.spin_temp_red.valueChanged.connect(self._on_temp_red_input_changed)
        self.spin_bt_setpoint.valueChanged.connect(self._on_bt_setpoint_input_changed)
        self.heating_curve_widget.curve_changed.connect(self._on_curve_widget_changed)

    # --------------------------------------------------------------------------
    # Tab 3: JSON Feature Explorer
    # --------------------------------------------------------------------------
    def _build_inspector_tab(self):
        layout = QVBoxLayout(self.tab_inspector)

        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("Filtra Proprietà:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Es. temp, curve, compressor, cop, pressure...")
        self.search_input.textChanged.connect(self._filter_features_table)
        filter_bar.addWidget(self.search_input)

        self.btn_reload_dump = QPushButton("Riscarica Dump Integrale")
        self.btn_reload_dump.clicked.connect(self._reload_full_dump)
        filter_bar.addWidget(self.btn_reload_dump)

        layout.addLayout(filter_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.features_table = QTableWidget()
        self.features_table.setColumnCount(3)
        self.features_table.setHorizontalHeaderLabels(["Categoria", "Feature Path", "Valore Attuale"])
        self.features_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.features_table.itemSelectionChanged.connect(self._on_feature_selected)
        splitter.addWidget(self.features_table)

        right_pane = QWidget()
        rp_lay = QVBoxLayout(right_pane)
        rp_lay.addWidget(QLabel("Dettaglio Proprietà JSON:"))
        self.feature_detail = QTextEdit()
        self.feature_detail.setReadOnly(True)
        rp_lay.addWidget(self.feature_detail)
        splitter.addWidget(right_pane)

        splitter.setSizes([650, 450])
        layout.addWidget(splitter)

    # --------------------------------------------------------------------------
    # Tab 4: History, Shading & Fuzzy Channel Search
    # --------------------------------------------------------------------------
    def _build_history_tab(self):
        layout = QHBoxLayout(self.tab_history)
        layout.setSpacing(12)

        # Left Control Panel: Fuzzy Channel Selector
        ctrl_panel = QWidget()
        c_layout = QVBoxLayout(ctrl_panel)
        c_layout.setContentsMargins(0, 0, 0, 0)

        # Header with Auto-fit
        h_top = QHBoxLayout()
        lbl_ch = QLabel("Canali Telemetrici:")
        lbl_ch.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        h_top.addWidget(lbl_ch)

        self.btn_autorange = QPushButton("Auto-Adatta Assi")
        self.btn_autorange.setObjectName("btn-auto-fit")
        self.btn_autorange.clicked.connect(self._auto_fit_chart)
        h_top.addWidget(self.btn_autorange)
        c_layout.addLayout(h_top)

        # Fuzzy Search Input
        self.channel_search_input = QLineEdit()
        self.channel_search_input.setPlaceholderText("🔍 Cerca canale (Fuzzy search: es. mandata, cop, bar)...")
        self.channel_search_input.textChanged.connect(self._on_channel_search_changed)
        c_layout.addWidget(self.channel_search_input)

        # Quick select buttons
        btn_bar = QHBoxLayout()
        btn_def = QPushButton("Default")
        btn_def.clicked.connect(self._set_default_channels)
        btn_none = QPushButton("Nessuno")
        btn_none.clicked.connect(self._clear_all_channels)
        btn_reset = QPushButton("Reset Dati")
        btn_reset.setStyleSheet("background-color: #991b1b; color: white;")
        btn_reset.clicked.connect(self._reset_database_history)
        btn_bar.addWidget(btn_def)
        btn_bar.addWidget(btn_none)
        btn_bar.addWidget(btn_reset)
        c_layout.addLayout(btn_bar)

        # Channel ListWidget with Checkboxes
        self.channel_list = QListWidget()
        self.channel_list.itemChanged.connect(self._on_channel_item_changed)
        c_layout.addWidget(self.channel_list)

        # Shading Options
        shading_box = QGroupBox("Evidenziazione Eventi ON/OFF")
        s_lay = QVBoxLayout(shading_box)
        self.chk_shade_compressor = QCheckBox("Evidenzia Aree Compressore ON (Ambra)")
        self.chk_shade_compressor.setChecked(True)
        self.chk_shade_compressor.toggled.connect(self._update_charts)
        s_lay.addWidget(self.chk_shade_compressor)

        self.chk_shade_grundfos = QCheckBox("Evidenzia Pompa Grundfos ON (Verde)")
        self.chk_shade_grundfos.setChecked(True)
        self.chk_shade_grundfos.toggled.connect(self._update_charts)
        s_lay.addWidget(self.chk_shade_grundfos)
        c_layout.addWidget(shading_box)

        ctrl_panel.setFixedWidth(340)
        layout.addWidget(ctrl_panel)

        # Right Chart Area
        chart_container = QWidget()
        ch_layout = QVBoxLayout(chart_container)
        ch_layout.setContentsMargins(0, 0, 0, 0)

        # Cycle statistics banner
        self.lbl_chart_stats = QLabel("Statistiche: Caricamento dati...")
        self.lbl_chart_stats.setStyleSheet("background: #1e222b; color: #38bdf8; font-weight: bold; padding: 8px 12px; border-radius: 6px;")
        ch_layout.addWidget(self.lbl_chart_stats)

        # Dual Axis pyqtgraph Setup with Scalable Axes and Absolute Time
        self.time_axis = AbsoluteTimeAxisItem(orientation="bottom")
        self.left_axis = ScalableAxisItem(orientation="left")
        self.right_axis = ScalableAxisItem(orientation="right")

        # Toolbar for axes scale control
        tb_axes = QHBoxLayout()
        self.btn_scale_left = QPushButton("📐 Scala Sx (°C): AUTO")
        self.btn_scale_left.setStyleSheet("background: #1e293b; color: #38bdf8; font-size: 11px; padding: 5px 12px; border: 1px solid #334155; border-radius: 4px;")
        self.btn_scale_left.clicked.connect(lambda: self._open_axis_scale_dialog("left"))
        tb_axes.addWidget(self.btn_scale_left)

        self.btn_scale_right = QPushButton("📐 Scala Dx (%/bar): AUTO")
        self.btn_scale_right.setStyleSheet("background: #1e293b; color: #facc15; font-size: 11px; padding: 5px 12px; border: 1px solid #334155; border-radius: 4px;")
        self.btn_scale_right.clicked.connect(lambda: self._open_axis_scale_dialog("right"))
        tb_axes.addWidget(self.btn_scale_right)

        lbl_hint = QLabel("💡 <i>Doppio clic direttamente sui numeri di un asse per impostare Min/Max personalizzati (Fixed / Auto).</i>")
        lbl_hint.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 10px;")
        tb_axes.addWidget(lbl_hint)
        tb_axes.addStretch()
        ch_layout.addLayout(tb_axes)

        self.plot_widget = pg.PlotWidget(
            axisItems={"bottom": self.time_axis, "left": self.left_axis, "right": self.right_axis}
        )
        self.plot_widget.setBackground("#16181e")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.addLegend(offset=(10, 10))

        # Main PlotItem (Left Axis = °C)
        self.p1 = self.plot_widget.plotItem
        self.p1.setLabel("left", "Temperature", units="°C", color="#38bdf8")
        self.p1.setLabel("bottom", "Tempo Assoluto (Data & Ora Locale)", color="#9ca3af")

        # Secondary ViewBox (Right Axis = %, bar, COP)
        self.p2 = pg.ViewBox()
        self.p1.showAxis("right")
        self.p1.scene().addItem(self.p2)
        self.right_axis.linkToView(self.p2)
        self.p2.setXLink(self.p1)
        self.p1.setLabel("right", "Modulazione % / Pressione bar / COP", color="#facc15")

        # Connect double-click on axes
        self.left_axis.axisDoubleClicked.connect(lambda _: self._open_axis_scale_dialog("left"))
        self.right_axis.axisDoubleClicked.connect(lambda _: self._open_axis_scale_dialog("right"))

        # Crosshair dynamic cursor lines with Magnetic X-Snap
        self.crosshair_v = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(color="#38bdf8", width=1.5, style=Qt.PenStyle.DashLine))
        self.crosshair_h = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(color="#64748b", width=1, style=Qt.PenStyle.DotLine))
        self.crosshair_v.setVisible(False)
        self.crosshair_h.setVisible(False)
        self.p1.addItem(self.crosshair_v, ignoreBounds=True)
        self.p1.addItem(self.crosshair_h, ignoreBounds=True)

        # Dynamic Hover Marker & Tooltip Badge for Left Axis (p1)
        self.hover_marker_left = pg.ScatterPlotItem(
            size=14,
            pen=pg.mkPen(color="#ffffff", width=2),
            brush=pg.mkBrush(color="#38bdf8"),
        )
        self.hover_marker_left.setVisible(False)
        self.p1.addItem(self.hover_marker_left, ignoreBounds=True)

        self.hover_tooltip_left = pg.TextItem(anchor=(0.5, 1.25))
        self.hover_tooltip_left.setVisible(False)
        self.p1.addItem(self.hover_tooltip_left, ignoreBounds=True)

        # Dynamic Hover Marker & Tooltip Badge for Right Axis (p2)
        self.hover_marker_right = pg.ScatterPlotItem(
            size=14,
            pen=pg.mkPen(color="#ffffff", width=2),
            brush=pg.mkBrush(color="#facc15"),
        )
        self.hover_marker_right.setVisible(False)
        self.p2.addItem(self.hover_marker_right)

        self.hover_tooltip_right = pg.TextItem(anchor=(0.5, 1.25))
        self.hover_tooltip_right.setVisible(False)
        self.p2.addItem(self.hover_tooltip_right)

        self.plot_widget.scene().sigMouseMoved.connect(self._on_chart_mouse_moved)

        # Sync ViewBox geometry on resize
        def update_views():
            self.p2.setGeometry(self.p1.vb.sceneBoundingRect())
            self.p2.linkedViewChanged(self.p1.vb, self.p2.XAxis)

        self.p1.vb.sigResized.connect(update_views)

        # Real-time Interactive HUD Inspector
        self.lbl_chart_hover_info = QLabel("🖱️ Cursore Interattivo: Muovi il mouse sul grafico per ispezionare le grandezze esatte nel punto temporale.")
        self.lbl_chart_hover_info.setStyleSheet(
            "background: #111827; color: #94a3b8; font-size: 12px; padding: 7px 12px; "
            "border: 1px solid #1f2937; border-radius: 6px; font-family: 'Segoe UI', sans-serif;"
        )
        ch_layout.addWidget(self.lbl_chart_hover_info)
        ch_layout.addWidget(self.plot_widget)
        layout.addWidget(chart_container)

        self._populate_channel_list()

    def _populate_channel_list(self, filter_text: str = ""):
        self.channel_list.blockSignals(True)
        self.channel_list.clear()

        # If filter text provided, use RapidFuzz
        if filter_text.strip():
            names = [c[1] for c in AVAILABLE_CHANNELS]
            matches = process.extract(filter_text, names, scorer=fuzz.partial_ratio, limit=len(names))
            matched_names = {m[0] for m in matches if m[1] >= 40}
            channels_to_show = [c for c in AVAILABLE_CHANNELS if c[1] in matched_names]
        else:
            channels_to_show = AVAILABLE_CHANNELS

        for db_col, label, unit, axis, hex_color, _, _ in channels_to_show:
            axis_tag = "[Asse Sx °C]" if axis == "left" else f"[Asse Dx {unit}]"
            item = QListWidgetItem(f"● {label} {axis_tag}")
            item.setForeground(QColor(hex_color))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            is_active = self.active_channels.get(db_col, False)
            item.setCheckState(Qt.CheckState.Checked if is_active else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, db_col)
            self.channel_list.addItem(item)

        self.channel_list.blockSignals(False)

    def _on_channel_search_changed(self, text: str):
        self._populate_channel_list(text)

    def _on_channel_item_changed(self, item: QListWidgetItem):
        db_col = item.data(Qt.ItemDataRole.UserRole)
        is_checked = item.checkState() == Qt.CheckState.Checked
        self.active_channels[db_col] = is_checked
        self._update_charts()

    def _set_default_channels(self):
        for c in AVAILABLE_CHANNELS:
            self.active_channels[c[0]] = c[5]
        self._populate_channel_list(self.channel_search_input.text())
        self._update_charts()

    def _clear_all_channels(self):
        for c in AVAILABLE_CHANNELS:
            self.active_channels[c[0]] = False
        self._populate_channel_list(self.channel_search_input.text())
        self._update_charts()

    def _reset_database_history(self):
        reply = QMessageBox.question(
            self,
            "Reset Storico Dati",
            "Vuoi cancellare i vecchi campioni di test nel database per avere uno storico pulito?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            with self.db._get_connection() as conn:
                conn.cursor().execute("DELETE FROM telemetry_samples;")
                conn.commit()
            self._update_charts()
            self.refresh_data()
            QMessageBox.information(self, "Reset Completato", "Database ripulito con successo!")

    def _auto_fit_chart(self):
        """Resets both axes to automatic scale and updates UI indicators."""
        self.left_axis_mode = "auto"
        self.right_axis_mode = "auto"
        self.p1.enableAutoRange(axis="y")
        self.p2.enableAutoRange(axis="y")
        self.btn_scale_left.setText("📐 Scala Sx (°C): AUTO")
        self.btn_scale_right.setText("📐 Scala Dx (%/bar): AUTO")
        self.p1.autoRange()
        self.p2.autoRange()
        self._update_charts()

    def _open_axis_scale_dialog(self, axis_name: str):
        """Opens modal dialog to customize min and max scale for left or right axis."""
        if axis_name == "left":
            vr = self.p1.vb.viewRange()[1]
            dlg = AxisRangeDialog(
                title="Imposta Scala Asse Sinistro (Temperature)",
                unit="°C",
                current_min=round(vr[0], 1) if vr else 0.0,
                current_max=round(vr[1], 1) if vr else 45.0,
                is_auto=(self.left_axis_mode == "auto"),
                parent=self,
            )
            if dlg.exec() == QDialog.DialogCode.Accepted:
                is_auto, min_val, max_val = dlg.get_values()
                if is_auto:
                    self.left_axis_mode = "auto"
                    self.p1.enableAutoRange(axis="y")
                    self.btn_scale_left.setText("📐 Scala Sx (°C): AUTO")
                else:
                    self.left_axis_mode = "fixed"
                    self.left_axis_min = min_val
                    self.left_axis_max = max_val
                    self.p1.disableAutoRange(axis="y")
                    self.p1.setYRange(min_val, max_val, padding=0)
                    self.btn_scale_left.setText(f"📐 Scala Sx (°C): [{min_val:.0f} - {max_val:.0f}]")
                self._update_charts()

        elif axis_name == "right":
            vr = self.p2.viewRange()[1]
            dlg = AxisRangeDialog(
                title="Imposta Scala Asse Destro (Modulazione % / bar / COP)",
                unit="%",
                current_min=round(vr[0], 1) if vr else 0.0,
                current_max=round(vr[1], 1) if vr else 100.0,
                is_auto=(self.right_axis_mode == "auto"),
                parent=self,
            )
            if dlg.exec() == QDialog.DialogCode.Accepted:
                is_auto, min_val, max_val = dlg.get_values()
                if is_auto:
                    self.right_axis_mode = "auto"
                    self.p2.enableAutoRange(axis="y")
                    self.btn_scale_right.setText("📐 Scala Dx (%/bar): AUTO")
                else:
                    self.right_axis_mode = "fixed"
                    self.right_axis_min = min_val
                    self.right_axis_max = max_val
                    self.p2.disableAutoRange(axis="y")
                    self.p2.setYRange(min_val, max_val, padding=0)
                    self.btn_scale_right.setText(f"📐 Scala Dx: [{min_val:.0f} - {max_val:.0f}]")
                self._update_charts()

    def _on_curve_widget_changed(self, slope: float, shift: float):
        """Called when user drags or clicks curve presets on HeatingCurveWidget."""
        self.spin_slope.blockSignals(True)
        self.spin_shift.blockSignals(True)
        self.spin_slope.setValue(slope)
        self.spin_shift.setValue(int(shift))
        self.spin_slope.blockSignals(False)
        self.spin_shift.blockSignals(False)

    def _on_spin_temp_norm_changed(self, val: float):
        """Updates reference room temperature on HeatingCurveWidget when normal temp is edited."""
        self.heating_curve_widget.set_reference_temperature(val)

    def _on_spin_curve_changed(self):
        """Called when user edits spin_slope or spin_shift in control panel."""
        self.heating_curve_widget.set_parameters(
            self.spin_slope.value(),
            float(self.spin_shift.value()),
            current_oat=self.latest_v_data.get("outside_temp_c", 5.9),
            t_room_normal=self.spin_temp_norm.value(),
        )

    def _load_latest_db_sample(self):
        """Preloads latest sample from SQLite so Synoptic and Dashboard have instant data on startup."""
        try:
            with self.db._get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT * FROM telemetry_samples ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                if row:
                    row_dict = dict(row)
                    v_preload = {
                        "outside_temp_c": row_dict.get("external_temp_c"),
                        "supply_temp_c": row_dict.get("pdc_supply_temp_c"),
                        "return_temp_c": row_dict.get("pdc_return_temp_c"),
                        "buffer_temp_c": row_dict.get("buffer_temp_c"),
                        "dhw_storage_temp_c": row_dict.get("dhw_storage_temp_c"),
                        "hot_gas_pressure_bar": row_dict.get("hot_gas_pressure_bar"),
                        "hot_gas_temp_c": row_dict.get("hot_gas_temp_c"),
                        "liquid_gas_temp_c": row_dict.get("liquid_gas_temp_c"),
                        "suction_gas_temp_c": row_dict.get("suction_gas_temp_c"),
                        "compressor_active": row_dict.get("compressor_active"),
                        "compressor_modulation_percent": row_dict.get("compressor_modulation_percent"),
                        "primary_pump_rotation_percent": row_dict.get("primary_pump_rotation_percent"),
                        "cop_heating": row_dict.get("cop_heating"),
                        "cop_dhw": row_dict.get("cop_dhw"),
                        "cop_total": row_dict.get("cop_total"),
                        "compressor_hours": row_dict.get("compressor_hours"),
                        "compressor_starts": row_dict.get("compressor_starts"),
                        "heating_curve_slope": row_dict.get("heating_curve_slope"),
                        "heating_curve_shift": row_dict.get("heating_curve_shift"),
                        "active_mode": row_dict.get("active_mode"),
                        "active_program": row_dict.get("active_program"),
                    }
                    b_preload = {
                        "indoor_temp_c": row_dict.get("indoor_temp_bticino_c"),
                        "setpoint_c": row_dict.get("indoor_setpoint_bticino_c"),
                        "humidity_percent": row_dict.get("humidity_percent"),
                        "grundfos_pump_active": row_dict.get("grundfos_pump_active"),
                        "mode": row_dict.get("active_program"),
                    }
                    self.latest_v_data = v_preload
                    self.latest_b_data = b_preload

                    # Refresh Synoptic SCADA Canvas
                    self.synoptic_widget.update_telemetry({**v_preload, **b_preload})

                    # Preload Dashboard Tiles
                    if row_dict.get("external_temp_c") is not None:
                        self.val_ext_temp.setText(f"{row_dict['external_temp_c']:.1f} °C")
                    if row_dict.get("buffer_temp_c") is not None:
                        self.val_buffer_temp.setText(f"{row_dict['buffer_temp_c']:.1f} °C")
                    if row_dict.get("dhw_storage_temp_c") is not None:
                        self.val_dhw_temp.setText(f"{row_dict['dhw_storage_temp_c']:.1f} °C")
                    if row_dict.get("pdc_supply_temp_c") is not None:
                        self.val_supply_temp.setText(f"{row_dict['pdc_supply_temp_c']:.1f} °C")
                    if row_dict.get("pdc_return_temp_c") is not None:
                        self.val_return_temp.setText(f"{row_dict['pdc_return_temp_c']:.1f} °C")
                    if row_dict.get("indoor_temp_bticino_c") is not None:
                        self.val_indoor_temp.setText(f"{row_dict['indoor_temp_bticino_c']:.1f} °C")
                    if row_dict.get("indoor_setpoint_bticino_c") is not None:
                        self.val_indoor_setpoint.setText(f"{row_dict['indoor_setpoint_bticino_c']:.1f} °C")
                    if row_dict.get("humidity_percent") is not None:
                        self.val_humidity.setText(f"{row_dict['humidity_percent']:.0f} %")
                    if row_dict.get("compressor_hours") is not None:
                        self.val_comp_hours.setText(f"{row_dict['compressor_hours']} h ({row_dict.get('compressor_starts', 0)} avvii)")
                    if row_dict.get("hot_gas_pressure_bar") is not None:
                        self.val_gas_pressure.setText(f"{row_dict['hot_gas_pressure_bar']} bar")
                    if row_dict.get("cop_heating") is not None:
                        self.val_cop_heating.setText(str(row_dict["cop_heating"]))
                    if row_dict.get("cop_dhw") is not None:
                        self.val_cop_dhw.setText(str(row_dict["cop_dhw"]))

                    slope = row_dict.get("heating_curve_slope")
                    shift = row_dict.get("heating_curve_shift")
                    if slope is not None and shift is not None:
                        self.val_curve.setText(f"Slope: {slope} | Shift: {shift}")
                        self.saved_slope = float(slope)
                        self.saved_shift = int(shift)
                        self.spin_slope.blockSignals(True)
                        self.spin_slope.setValue(self.saved_slope)
                        self.spin_slope.blockSignals(False)
                        self.spin_shift.blockSignals(True)
                        self.spin_shift.setValue(self.saved_shift)
                        self.spin_shift.blockSignals(False)
                        self._check_curve_sync_state()

                    # Heating Curve Widget update
                    if row_dict.get("external_temp_c") is not None:
                        self.heating_curve_widget.set_current_oat(float(row_dict["external_temp_c"]))
                    if slope is not None and shift is not None:
                        self.heating_curve_widget.set_parameters(
                            float(slope),
                            float(shift),
                            current_oat=float(row_dict.get("external_temp_c", 5.9)),
                            t_room_normal=self.saved_temp_norm,
                        )

                    comp_on = (row_dict.get("compressor_active") or 0) > 0 or (row_dict.get("compressor_modulation_percent") or 0) > 0
                    self.val_comp_status.setText("ATTIVO" if comp_on else "SPENTO")
                    self.val_comp_status.setStyleSheet("color: #10b981;" if comp_on else "color: #9ca3af;")
                    self.val_comp_modul.setText(f"{row_dict.get('compressor_modulation_percent') or 0} %")

                    pump_active = row_dict.get("grundfos_pump_active")
                    if pump_active == 1:
                        self.banner_grundfos.setText("POMPA GRUNDFOS: ACCESA (Rilancio attivo al pavimento radiante)")
                        self.banner_grundfos.setStyleSheet("background-color: #065f46; color: #6ee7b7; padding: 16px; border-radius: 8px; margin-top: 10px;")
                    else:
                        self.banner_grundfos.setText("POMPA GRUNDFOS: SPENTA (Massetto isolato, riscalda solo Puffer)")
                        self.banner_grundfos.setStyleSheet("background-color: #374151; color: #d1d5db; padding: 16px; border-radius: 8px; margin-top: 10px;")

                    self._update_charts()
        except Exception as e:
            logger.error("Preload DB sample: %s", e)

    # --------------------------------------------------------------------------
    # Data Refresh & UI Update
    # --------------------------------------------------------------------------
    def refresh_data(self):
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("Lettura...")
        self.footer_label.setText("Interrogazione cloud Viessmann e BTicino in corso...")

        self.worker = FetchDataWorker(self.v_conn, self.b_conn, self.db)
        self.worker.finished.connect(self._on_data_fetched)
        self.worker.error.connect(self._on_data_error)
        self.worker.start()

    def _on_data_fetched(self, v_data: dict, b_data: dict, sample_id):
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("Aggiorna Ora")

        self.latest_v_data = v_data
        self.latest_b_data = b_data

        # Update Connection Status
        if v_data.get("is_online"):
            self.status_viessmann.setText(f"Viessmann: ONLINE ({v_data.get('model', 'Vitocal 111-S')})")
            self.status_viessmann.setStyleSheet("color: #10b981; font-weight: bold; padding: 4px 10px; background: #064e3b; border-radius: 4px;")

        if b_data.get("indoor_temp_c") is not None:
            self.status_bticino.setText(f"BTicino: ONLINE ({b_data.get('room_name', 'Corridoio')})")
            self.status_bticino.setStyleSheet("color: #10b981; font-weight: bold; padding: 4px 10px; background: #064e3b; border-radius: 4px;")

        # Update Viessmann Metrics
        self.val_ext_temp.setText(f"{v_data.get('outside_temp_c', '--')} °C")
        self.val_buffer_temp.setText(f"{v_data.get('buffer_temp_c', '--')} °C")
        self.val_dhw_temp.setText(f"{v_data.get('dhw_storage_temp_c', '--')} °C")
        self.val_supply_temp.setText(f"{v_data.get('supply_temp_c', '--')} °C")
        self.val_return_temp.setText(f"{v_data.get('return_temp_c', '--')} °C")

        slope = v_data.get("heating_curve_slope", "--")
        shift = v_data.get("heating_curve_shift", "--")
        self.val_curve.setText(f"Slope: {slope} | Shift: {shift}")
        if isinstance(slope, (int, float)):
            self.saved_slope = round(float(slope), 2)
            self.spin_slope.blockSignals(True)
            self.spin_slope.setValue(self.saved_slope)
            self.spin_slope.blockSignals(False)
        if isinstance(shift, (int, float)):
            self.saved_shift = int(shift)
            self.spin_shift.blockSignals(True)
            self.spin_shift.setValue(self.saved_shift)
            self.spin_shift.blockSignals(False)
        self._check_curve_sync_state()

        comp_active = v_data.get("compressor_active") or (v_data.get("compressor_modulation_percent", 0) or 0) > 0
        self.val_comp_status.setText("ATTIVO" if comp_active else "SPENTO")
        self.val_comp_status.setStyleSheet("color: #10b981;" if comp_active else "color: #9ca3af;")

        self.val_comp_modul.setText(f"{v_data.get('compressor_modulation_percent', 0)} %")
        self.val_comp_hours.setText(f"{v_data.get('compressor_hours', '--')} h ({v_data.get('compressor_starts', '--')} avvii)")

        self.val_cop_heating.setText(str(v_data.get("cop_heating", "--")))
        self.val_cop_dhw.setText(str(v_data.get("cop_dhw", "--")))
        self.val_gas_pressure.setText(f"{v_data.get('hot_gas_pressure_bar', '--')} bar")

        # Update BTicino Metrics
        self.val_indoor_temp.setText(f"{b_data.get('indoor_temp_c', '--')} °C")
        self.val_indoor_setpoint.setText(f"{b_data.get('setpoint_c', '--')} °C")
        self.val_humidity.setText(f"{b_data.get('humidity_percent', '--')} %")
        self.val_bticino_mode.setText(str(b_data.get("mode", "--")))

        if b_data.get("setpoint_c") is not None:
            self.saved_bt_setpoint = round(float(b_data["setpoint_c"]), 1)
            self.spin_bt_setpoint.blockSignals(True)
            self.spin_bt_setpoint.setValue(self.saved_bt_setpoint)
            self.spin_bt_setpoint.blockSignals(False)
            self._check_bt_setpoint_sync_state()

        # Grundfos Banner
        pump_active = b_data.get("grundfos_pump_active")
        if pump_active == 1:
            self.banner_grundfos.setText("POMPA GRUNDFOS: ACCESA (Rilancio attivo al pavimento radiante)")
            self.banner_grundfos.setStyleSheet("background-color: #065f46; color: #6ee7b7; padding: 16px; border-radius: 8px; margin-top: 10px;")
        else:
            self.banner_grundfos.setText("POMPA GRUNDFOS: SPENTA (Massetto isolato, riscalda solo Puffer)")
            self.banner_grundfos.setStyleSheet("background-color: #374151; color: #d1d5db; padding: 16px; border-radius: 8px; margin-top: 10px;")

        # Populate features table if empty
        if not self.all_features_data:
            self._load_features_from_dump()

        # Update Plant Synoptic Widget
        combined_telemetry = {**v_data, **b_data}
        self.synoptic_widget.update_telemetry(combined_telemetry)

        # Update Heating Curve Widget
        if v_data.get("outside_temp_c") is not None:
            self.heating_curve_widget.set_current_oat(float(v_data["outside_temp_c"]))

        norm_t = v_data.get("normal_setpoint_c")
        if norm_t is not None:
            self.saved_temp_norm = round(float(norm_t), 1)
            self.heating_curve_widget.set_reference_temperature(self.saved_temp_norm)
            self.spin_temp_norm.blockSignals(True)
            self.spin_temp_norm.setValue(self.saved_temp_norm)
            self.spin_temp_norm.blockSignals(False)
            self._check_temp_norm_sync_state()

        red_t = v_data.get("reduced_setpoint_c")
        if red_t is not None:
            self.saved_temp_red = round(float(red_t), 1)
            self.spin_temp_red.blockSignals(True)
            self.spin_temp_red.setValue(self.saved_temp_red)
            self.spin_temp_red.blockSignals(False)
            self._check_temp_red_sync_state()

        if isinstance(v_data.get("heating_curve_slope"), (int, float)) and isinstance(v_data.get("heating_curve_shift"), (int, float)):
            self.heating_curve_widget.set_parameters(
                float(v_data["heating_curve_slope"]),
                float(v_data["heating_curve_shift"]),
                current_oat=v_data.get("outside_temp_c", 5.9),
                t_room_normal=float(norm_t) if norm_t is not None else 12.0,
            )

        # Update History Charts & Analytics
        self._update_charts()
        self._calculate_analytics()

        now_str = datetime.now().strftime("%H:%M:%S")
        self.footer_label.setText(f"Ultimo aggiornamento: {now_str} — Campione ID {sample_id} salvato su SQLite.")

    def _on_data_error(self, err_msg: str):
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("Aggiorna Ora")
        self.footer_label.setText(f"Errore: {err_msg}")
        QMessageBox.warning(self, "Errore Comunicazione", f"Impossibile completare la lettura:\n{err_msg}")

    # --------------------------------------------------------------------------
    # Feature Inspector Helpers
    # --------------------------------------------------------------------------
    def _load_features_from_dump(self):
        dump_path = Path("data/dumps/device_1_heating.json")
        if not dump_path.exists():
            return
        try:
            with open(dump_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.all_features_data = data.get("data", [])
            self._filter_features_table("")
        except Exception as e:
            logger.error("Errore caricamento dump: %s", e)

    def _filter_features_table(self, query: str):
        query = self.search_input.text().strip().lower()
        self.features_table.setRowCount(0)

        row = 0
        for feat in self.all_features_data:
            name = feat.get("feature", "")
            if query and query not in name.lower():
                continue

            cat = name.split(".")[0].upper()
            props = feat.get("properties", {})
            val_str = ""
            for pk, pv in props.items():
                if "value" in pv:
                    val_str += f"{pk}={pv['value']} "

            self.features_table.insertRow(row)
            self.features_table.setItem(row, 0, QTableWidgetItem(cat))
            item_name = QTableWidgetItem(name)
            item_name.setData(Qt.ItemDataRole.UserRole, feat)
            self.features_table.setItem(row, 1, item_name)
            self.features_table.setItem(row, 2, QTableWidgetItem(val_str.strip() or "--"))
            row += 1

    def _on_feature_selected(self):
        items = self.features_table.selectedItems()
        if not items:
            return
        row = items[0].row()
        name_item = self.features_table.item(row, 1)
        if name_item:
            feat_data = name_item.data(Qt.ItemDataRole.UserRole)
            self.feature_detail.setText(json.dumps(feat_data, indent=2, ensure_ascii=False))

    def _reload_full_dump(self):
        self.footer_label.setText("Scaricamento dump completo in corso...")
        try:
            path = self.v_conn.dump_all_features()
            self._load_features_from_dump()
            QMessageBox.information(self, "Dump Completato", f"Dump scaricato con successo in:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Errore Dump", str(e))

    # --------------------------------------------------------------------------
    # Advanced Multi-Axis Charts & Shading
    # --------------------------------------------------------------------------
    def _update_charts(self):
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM telemetry_samples ORDER BY id ASC")
            rows = cursor.fetchall()

        if not rows:
            return

        # Extract timestamps in Epoch seconds (converted to local timezone)
        timestamps = []
        for r in rows:
            ts_str = r["timestamp_utc"]
            try:
                dt = datetime.fromisoformat(ts_str)
                if dt.tzinfo is not None:
                    dt = dt.astimezone()
                timestamps.append(dt.timestamp())
            except Exception:
                timestamps.append(float(r["id"]))

        # Cache timestamps and rows for dynamic crosshair hover inspection
        self.cached_chart_timestamps = timestamps
        self.cached_chart_rows = rows

        # Remove old shading regions
        for reg in self.region_items:
            try:
                self.p1.removeItem(reg)
            except Exception:
                pass
        self.region_items.clear()

        # Shading for Compressor ON and Grundfos ON (borderless translucent wash)
        shade_comp = self.chk_shade_compressor.isChecked()
        shade_pump = self.chk_shade_grundfos.isChecked()
        null_pen = pg.mkPen(color=(0, 0, 0, 0), width=0)

        compressor_cycles_count = 0
        in_comp_cycle = False
        cycle_start_ts = None
        last_comp_ts = None

        for i, r in enumerate(rows):
            comp_on = (r["compressor_active"] or 0) > 0 or (r["compressor_modulation_percent"] or 0) > 0
            ts = timestamps[i]

            # Cycle tracking
            if comp_on:
                if not in_comp_cycle:
                    in_comp_cycle = True
                    cycle_start_ts = ts
                    compressor_cycles_count += 1
                last_comp_ts = ts
            else:
                if in_comp_cycle:
                    in_comp_cycle = False
                    if shade_comp and cycle_start_ts is not None:
                        end_t = last_comp_ts if last_comp_ts and last_comp_ts > cycle_start_ts else ts
                        region = pg.LinearRegionItem(
                            values=(cycle_start_ts, end_t),
                            orientation="vertical",
                            brush=QColor(245, 158, 11, 40),  # Soft translucent amber
                            pen=null_pen,
                            movable=False,
                        )
                        for line in region.lines:
                            line.setPen(null_pen)
                            line.setHoverPen(null_pen)
                        self.p1.addItem(region)
                        self.region_items.append(region)

        # Close open cycle
        if in_comp_cycle and shade_comp and cycle_start_ts is not None and timestamps:
            region = pg.LinearRegionItem(
                values=(cycle_start_ts, timestamps[-1]),
                orientation="vertical",
                brush=QColor(245, 158, 11, 40),
                pen=null_pen,
                movable=False,
            )
            for line in region.lines:
                line.setPen(null_pen)
                line.setHoverPen(null_pen)
            self.p1.addItem(region)
            self.region_items.append(region)

        # Grundfos ON Shading (Translucent Emerald Green, no yellow borders)
        if shade_pump:
            in_pump_cycle = False
            p_start_ts = None
            last_pump_ts = None
            for i, r in enumerate(rows):
                pump_on = (r["grundfos_pump_active"] or 0) > 0
                ts = timestamps[i]
                if pump_on:
                    if not in_pump_cycle:
                        in_pump_cycle = True
                        p_start_ts = ts
                    last_pump_ts = ts
                else:
                    if in_pump_cycle:
                        in_pump_cycle = False
                        if p_start_ts is not None:
                            # End precisely at last active sample to not encroach on the OFF point
                            end_t = last_pump_ts if last_pump_ts and last_pump_ts > p_start_ts else ts
                            reg_pump = pg.LinearRegionItem(
                                values=(p_start_ts, end_t),
                                orientation="vertical",
                                brush=QColor(16, 185, 129, 35),  # Soft translucent emerald green
                                pen=null_pen,
                                movable=False,
                            )
                            for line in reg_pump.lines:
                                line.setPen(null_pen)
                                line.setHoverPen(null_pen)
                            self.p1.addItem(reg_pump)
                            self.region_items.append(reg_pump)
            if in_pump_cycle and p_start_ts is not None and timestamps:
                reg_pump = pg.LinearRegionItem(
                    values=(p_start_ts, timestamps[-1]),
                    orientation="vertical",
                    brush=QColor(16, 185, 129, 35),
                    pen=null_pen,
                    movable=False,
                )
                for line in reg_pump.lines:
                    line.setPen(null_pen)
                    line.setHoverPen(null_pen)
                self.p1.addItem(reg_pump)
                self.region_items.append(reg_pump)

        # Update curves for each channel
        for db_col, label, unit, axis, hex_color, _, pen_style in AVAILABLE_CHANNELS:
            is_active = self.active_channels.get(db_col, False)
            curve = self.channel_curves.get(db_col)

            if not is_active:
                if curve:
                    if axis == "left":
                        self.p1.removeItem(curve)
                    else:
                        self.p2.removeItem(curve)
                    del self.channel_curves[db_col]
                continue

            # Extract data points (use float('nan') instead of 0 to avoid false drops to zero)
            y_data = [float(r[db_col]) if r[db_col] is not None else float("nan") for r in rows]

            pen = pg.mkPen(color=hex_color, width=2, style=pen_style)
            brush = pg.mkBrush(color=hex_color)
            if not curve:
                if axis == "left":
                    curve = self.p1.plot(timestamps, y_data, connect="finite", name=f"{label} ({unit})", pen=pen, symbol="o", symbolSize=5, symbolBrush=brush)
                else:
                    curve = pg.PlotCurveItem(timestamps, y_data, connect="finite", name=f"{label} ({unit})", pen=pen, symbol="o", symbolSize=5, symbolBrush=brush)
                    self.p2.addItem(curve)
                self.channel_curves[db_col] = curve
            else:
                curve.setData(timestamps, y_data, connect="finite")

        # Smart X Range padding if points are close together
        if timestamps:
            t_min = min(timestamps)
            t_max = max(timestamps)
            if t_max - t_min < 600:
                self.p1.setXRange(t_min - 300, t_max + 300, padding=0.05)

        # Apply Fixed scale on Y left / Y right if user customized range
        if self.left_axis_mode == "fixed":
            self.p1.setYRange(self.left_axis_min, self.left_axis_max, padding=0)
        if self.right_axis_mode == "fixed":
            self.p2.setYRange(self.right_axis_min, self.right_axis_max, padding=0)

        # Update Cycle Stats Header
        tot_samples = len(rows)
        latest_r = rows[-1]
        c_hours = latest_r["compressor_hours"] or "--"
        c_starts = latest_r["compressor_starts"] or "--"
        self.lbl_chart_stats.setText(
            f"📊 Campioni nel DB: {tot_samples}  |  "
            f"Cicli di carica rilevati: {compressor_cycles_count}  |  "
            f"Ore totali compressore: {c_hours} h  |  "
            f"Avvii totali: {c_starts}"
        )

    # --------------------------------------------------------------------------
    # Interactive Crosshair Cursor & Dynamic Hover HUD Inspector (Magnetic X-Snap)
    # --------------------------------------------------------------------------
    def _on_chart_mouse_moved(self, pos):
        if not self.p1.sceneBoundingRect().contains(pos):
            self.crosshair_v.setVisible(False)
            self.crosshair_h.setVisible(False)
            return

        if not self.cached_chart_timestamps or not self.cached_chart_rows:
            self.crosshair_v.setVisible(False)
            self.crosshair_h.setVisible(False)
            return

        mouse_point = self.p1.vb.mapSceneToView(pos)
        x_val = mouse_point.x()
        y_val = mouse_point.y()

        # Binary search in O(log N) to find the closest real measurement timestamp
        timestamps = self.cached_chart_timestamps
        idx = bisect.bisect_left(timestamps, x_val)
        if idx == 0:
            closest_idx = 0
        elif idx >= len(timestamps):
            closest_idx = len(timestamps) - 1
        else:
            left_diff = abs(timestamps[idx - 1] - x_val)
            right_diff = abs(timestamps[idx] - x_val)
            closest_idx = idx - 1 if left_diff <= right_diff else idx

        closest_ts = timestamps[closest_idx]

        # Magnetic Snap: Lock vertical crosshair directly onto the exact discrete sample timestamp
        self.crosshair_v.setPos(closest_ts)
        self.crosshair_h.setPos(y_val)
        self.crosshair_v.setVisible(True)
        self.crosshair_h.setVisible(True)

        row = self.cached_chart_rows[closest_idx]
        dt_str = datetime.fromtimestamp(closest_ts).strftime("%d/%m/%Y %H:%M:%S")

        # Telemetry summary snippet for HUD with exact recorded values (not interpolated)
        sample_id = row["id"]
        parts = [f"<b style='color:#38bdf8;'>📍 Campione #{sample_id}</b> ({dt_str})"]

        # Display active channels with their specific color code
        for db_col, label, unit, axis, hex_color, _, _ in AVAILABLE_CHANNELS:
            if not self.active_channels.get(db_col, False):
                continue
            val = row[db_col]
            if val is None:
                continue

            if unit == "°C":
                val_str = f"{val:.1f} °C"
            elif unit == "%":
                val_str = f"{val:.0f} %"
            elif unit == "bar":
                val_str = f"{val:.1f} bar"
            elif unit == "COP":
                val_str = f"{val:.1f}"
            else:
                val_str = f"{val} {unit}"

            short_label = label.replace("Pompa di Calore", "PdC").replace("Termostato BTicino", "BTicino").replace("Sonda PdC", "").strip()
            parts.append(f"<span style='color:{hex_color}; font-weight:600;'>{short_label}: {val_str}</span>")

        # Compressor ON/OFF status
        mod = row["compressor_modulation_percent"]
        comp_on = (row["compressor_active"] or 0) > 0 or (mod or 0) > 0
        if comp_on:
            parts.append(f"<span style='color:#facc15; font-weight:bold;'>Compressore: {mod or 0:.0f}% ON</span>")
        else:
            parts.append("<span style='color:#9ca3af;'>Compressore: OFF</span>")

        # Grundfos ON/OFF status
        pump_on = (row["grundfos_pump_active"] or 0) > 0
        if pump_on:
            parts.append("<span style='color:#10b981; font-weight:bold;'>Grundfos: ON (Pavimento)</span>")
        else:
            parts.append("<span style='color:#6b7280;'>Grundfos: OFF</span>")

        self.lbl_chart_hover_info.setText(" &nbsp;│&nbsp; ".join(parts))

        # ----------------------------------------------------------------------
        # Dynamic Trace Hover Detection & Floating Highlight Tooltip Badge
        # ----------------------------------------------------------------------
        min_dist_px = float("inf")
        hovered_ch = None
        hovered_real_y = None

        for db_col, label, unit, axis, hex_color, _, pen_style in AVAILABLE_CHANNELS:
            if not self.active_channels.get(db_col, False):
                continue

            y_real = row[db_col]
            if y_real is None:
                continue
            try:
                y_real_f = float(y_real)
            except (ValueError, TypeError):
                continue
            if math.isnan(y_real_f):
                continue

            vb = self.p1.vb if axis == "left" else self.p2

            # Calculate curve Y at current x_val to find vertical distance to line
            y_at_x = None
            if 0 < idx < len(timestamps):
                t1, t2 = timestamps[idx - 1], timestamps[idx]
                r1, r2 = self.cached_chart_rows[idx - 1], self.cached_chart_rows[idx]
                y1, y2 = r1[db_col], r2[db_col]
                if y1 is not None and y2 is not None and t2 > t1:
                    try:
                        y1_f, y2_f = float(y1), float(y2)
                        if not math.isnan(y1_f) and not math.isnan(y2_f):
                            y_at_x = y1_f + (y2_f - y1_f) * ((x_val - t1) / (t2 - t1))
                    except Exception:
                        pass
            if y_at_x is None:
                y_at_x = y_real_f

            scene_pt = vb.mapViewToScene(pg.Point(x_val, y_at_x))
            dist_px = abs(scene_pt.y() - pos.y())

            if dist_px < min_dist_px:
                min_dist_px = dist_px
                hovered_ch = (db_col, label, unit, axis, hex_color, pen_style)
                hovered_real_y = y_real_f

        # Hover threshold: 28 screen pixels
        if hovered_ch and min_dist_px <= 28.0:
            db_col, label, unit, axis, hex_color, pen_style = hovered_ch

            if unit == "°C":
                val_str = f"{hovered_real_y:.1f} °C"
            elif unit == "%":
                val_str = f"{hovered_real_y:.0f} %"
            elif unit == "bar":
                val_str = f"{hovered_real_y:.1f} bar"
            elif unit == "COP":
                val_str = f"{hovered_real_y:.1f}"
            else:
                val_str = f"{hovered_real_y} {unit}"

            html_badge = (
                f"<div style='background-color: rgba(15, 23, 42, 0.95); "
                f"border: 2px solid {hex_color}; border-radius: 6px; padding: 4px 8px; "
                f"font-family: Segoe UI, sans-serif; text-align: center; white-space: nowrap;'>"
                f"<div style='color: #cbd5e1; font-size: 11px; font-weight: 600;'>{label}</div>"
                f"<div style='color: {hex_color}; font-size: 14px; font-weight: bold;'>{val_str}</div>"
                f"</div>"
            )

            if axis == "left":
                self.hover_marker_left.setData([closest_ts], [hovered_real_y], brush=pg.mkBrush(hex_color))
                self.hover_marker_left.setVisible(True)
                self.hover_tooltip_left.setHtml(html_badge)
                self.hover_tooltip_left.setPos(closest_ts, hovered_real_y)
                self.hover_tooltip_left.setVisible(True)
                self.hover_marker_right.setVisible(False)
                self.hover_tooltip_right.setVisible(False)
            else:
                self.hover_marker_right.setData([closest_ts], [hovered_real_y], brush=pg.mkBrush(hex_color))
                self.hover_marker_right.setVisible(True)
                self.hover_tooltip_right.setHtml(html_badge)
                self.hover_tooltip_right.setPos(closest_ts, hovered_real_y)
                self.hover_tooltip_right.setVisible(True)
                self.hover_marker_left.setVisible(False)
                self.hover_tooltip_left.setVisible(False)

            if self.current_hovered_channel != db_col:
                self.current_hovered_channel = db_col
                self._apply_curve_highlight(db_col)
        else:
            self.hover_marker_left.setVisible(False)
            self.hover_tooltip_left.setVisible(False)
            self.hover_marker_right.setVisible(False)
            self.hover_tooltip_right.setVisible(False)
            if self.current_hovered_channel is not None:
                self.current_hovered_channel = None
                self._apply_curve_highlight(None)

    def _apply_curve_highlight(self, highlighted_col: Optional[str]):
        """Dynamically thickens and accents the hovered trace while softly dimming other traces."""
        for db_col, label, unit, axis, hex_color, _, pen_style in AVAILABLE_CHANNELS:
            curve = self.channel_curves.get(db_col)
            if not curve:
                continue
            if highlighted_col is None:
                # Normal state
                curve.setPen(pg.mkPen(color=hex_color, width=2, style=pen_style))
                if hasattr(curve, "setSymbolSize"):
                    curve.setSymbolSize(5)
                curve.setZValue(1)
            elif db_col == highlighted_col:
                # Highlighted state: width 4.5, larger dots, top z-order
                curve.setPen(pg.mkPen(color=hex_color, width=4.5, style=pen_style))
                if hasattr(curve, "setSymbolSize"):
                    curve.setSymbolSize(9)
                curve.setZValue(100)
            else:
                # Dimmed background curves
                dimmed = QColor(hex_color).darker(130)
                dimmed.setAlpha(150)
                curve.setPen(pg.mkPen(color=dimmed, width=1.5, style=pen_style))
                if hasattr(curve, "setSymbolSize"):
                    curve.setSymbolSize(4)
                curve.setZValue(1)

    # --------------------------------------------------------------------------
    # Staging, Steppers & Sync Status Checker Callbacks
    # --------------------------------------------------------------------------
    def _check_curve_sync_state(self):
        cur_slope = round(self.spin_slope.value(), 2)
        cur_shift = int(self.spin_shift.value())
        if abs(cur_slope - self.saved_slope) > 0.01 or cur_shift != self.saved_shift:
            self.led_curve.setText(f"🟠 Modifica in sospeso (Non inviata: Slp {cur_slope:.2f}, Shf {cur_shift:+d})")
            self.led_curve.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 11px;")
        else:
            self.led_curve.setText(f"🟢 Sincronizzato con Vitocal (Slp {self.saved_slope:.2f} | Shf {self.saved_shift:+d})")
            self.led_curve.setStyleSheet("color: #10b981; font-weight: bold; font-size: 11px;")

    def _reset_slope_to_saved(self):
        self.spin_slope.setValue(self.saved_slope)
        self._check_curve_sync_state()

    def _reset_shift_to_saved(self):
        self.spin_shift.setValue(self.saved_shift)
        self._check_curve_sync_state()

    def _on_slope_input_changed(self, val: float):
        self._on_spin_curve_changed()
        self._check_curve_sync_state()

    def _on_shift_input_changed(self, val: int):
        self._on_spin_curve_changed()
        self._check_curve_sync_state()

    def _check_temp_norm_sync_state(self):
        cur_norm = round(self.spin_temp_norm.value(), 1)
        if abs(cur_norm - self.saved_temp_norm) > 0.1:
            self.led_norm.setText(f"🟠 Modifica non inviata (Nuovo target: {cur_norm} °C)")
            self.led_norm.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 11px; margin-bottom: 4px;")
        else:
            self.led_norm.setText(f"🟢 Sincronizzato con Vitocal ({self.saved_temp_norm} °C)")
            self.led_norm.setStyleSheet("color: #10b981; font-weight: bold; font-size: 11px; margin-bottom: 4px;")

    def _reset_temp_norm_to_saved(self):
        self.spin_temp_norm.setValue(self.saved_temp_norm)
        self._check_temp_norm_sync_state()

    def _on_temp_norm_input_changed(self, val: float):
        self._on_spin_temp_norm_changed(val)
        self._check_temp_norm_sync_state()

    def _check_temp_red_sync_state(self):
        cur_red = round(self.spin_temp_red.value(), 1)
        if abs(cur_red - self.saved_temp_red) > 0.1:
            self.led_red.setText(f"🟠 Modifica non inviata (Nuovo target: {cur_red} °C)")
            self.led_red.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 11px;")
        else:
            self.led_red.setText(f"🟢 Sincronizzato con Vitocal ({self.saved_temp_red} °C)")
            self.led_red.setStyleSheet("color: #10b981; font-weight: bold; font-size: 11px;")

    def _reset_temp_red_to_saved(self):
        self.spin_temp_red.setValue(self.saved_temp_red)
        self._check_temp_red_sync_state()

    def _on_temp_red_input_changed(self, val: float):
        self._check_temp_red_sync_state()

    def _check_bt_setpoint_sync_state(self):
        cur_bt = round(self.spin_bt_setpoint.value(), 1)
        if abs(cur_bt - self.saved_bt_setpoint) > 0.1:
            self.led_bt.setText(f"🟠 Modifica non inviata (Nuovo setpoint: {cur_bt} °C)")
            self.led_bt.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 11px;")
        else:
            self.led_bt.setText(f"🟢 Sincronizzato con BTicino ({self.saved_bt_setpoint} °C)")
            self.led_bt.setStyleSheet("color: #10b981; font-weight: bold; font-size: 11px;")

    def _reset_bt_setpoint_to_saved(self):
        self.spin_bt_setpoint.setValue(self.saved_bt_setpoint)
        self._check_bt_setpoint_sync_state()

    def _on_bt_setpoint_input_changed(self, val: float):
        self._check_bt_setpoint_sync_state()

    # --------------------------------------------------------------------------
    # Explicit Write Commands with Modal Confirmation & Read-back
    # --------------------------------------------------------------------------
    def _on_apply_curve(self):
        slope = round(self.spin_slope.value(), 2)
        shift = int(self.spin_shift.value())

        reply = QMessageBox.question(
            self,
            "Conferma Regolazione Curva Climatica",
            f"Confermi l'invio della nuova Curva Climatica alla Vitocal 111-S?\n\n"
            f"• Inclinazione (Slope): {slope:.2f}\n"
            f"• Livello (Shift): {shift:+d} K\n\n"
            "La centralina WO1C ricalcolerà la curva di mandata.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.btn_apply_curve.setEnabled(False)
        self.btn_apply_curve.setText("Invio...")
        ok, msg = self.v_conn.set_heating_curve(slope=slope, shift=shift)
        self.btn_apply_curve.setEnabled(True)
        self.btn_apply_curve.setText("Applica Curva Climatica")
        if ok:
            self.saved_slope = slope
            self.saved_shift = shift
            self._check_curve_sync_state()
            QMessageBox.information(self, "Curva Climatica Aggiornata", msg)
            self.refresh_data()
        else:
            QMessageBox.warning(self, "Errore Impostazione Curva", msg)

    def _on_apply_temp_norm(self):
        val = round(self.spin_temp_norm.value(), 1)
        reply = QMessageBox.question(
            self,
            "Conferma Temperatura Normale",
            f"Confermi di voler impostare la Temperatura Normale PdC a {val:.1f} °C?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.btn_apply_norm.setEnabled(False)
        self.btn_apply_norm.setText("Invio...")
        ok, msg = self.v_conn.set_normal_temperature(val)
        self.btn_apply_norm.setEnabled(True)
        self.btn_apply_norm.setText("Imposta Normale")
        if ok:
            self.saved_temp_norm = val
            self._check_temp_norm_sync_state()
            QMessageBox.information(self, "Temperatura Normale", msg)
            self.refresh_data()
        else:
            QMessageBox.warning(self, "Errore", msg)

    def _on_apply_temp_red(self):
        val = round(self.spin_temp_red.value(), 1)
        reply = QMessageBox.question(
            self,
            "Conferma Temperatura Ridotta",
            f"Confermi di voler impostare la Temperatura Ridotta PdC a {val:.1f} °C?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.btn_apply_red.setEnabled(False)
        self.btn_apply_red.setText("Invio...")
        ok, msg = self.v_conn.set_reduced_temperature(val)
        self.btn_apply_red.setEnabled(True)
        self.btn_apply_red.setText("Imposta Ridotta")
        if ok:
            self.saved_temp_red = val
            self._check_temp_red_sync_state()
            QMessageBox.information(self, "Temperatura Ridotta", msg)
            self.refresh_data()
        else:
            QMessageBox.warning(self, "Errore", msg)

    def _on_apply_bticino_setpoint(self):
        val = round(self.spin_bt_setpoint.value(), 1)
        reply = QMessageBox.question(
            self,
            "Conferma Setpoint BTicino",
            f"Confermi l'invio del nuovo Setpoint Manuale di {val:.1f} °C al termostato BTicino Smarther?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.btn_apply_bt.setEnabled(False)
        self.btn_apply_bt.setText("Invio...")
        ok, msg = self.b_conn.set_thermostat_setpoint(val, mode="manual", duration_minutes=180)
        self.btn_apply_bt.setEnabled(True)
        self.btn_apply_bt.setText("Invia a BTicino")
        if ok:
            self.saved_bt_setpoint = val
            self._check_bt_setpoint_sync_state()
            QMessageBox.information(self, "BTicino Aggiornato", msg)
            self.refresh_data()
        else:
            QMessageBox.warning(self, "Errore BTicino", msg)

    def _on_apply_bticino_mode(self, mode: str):
        if not self.b_conn:
            return
        mode_desc = "Programma Automatico (Home)" if mode == "home" else "Antigelo Fisso (HG a 7.0 °C)"
        reply = QMessageBox.question(
            self,
            "Conferma Cambio Modalità BTicino",
            f"Confermi di voler attivare la modalità '{mode_desc}' sul termostato Smarther?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        ok, msg = self.b_conn.set_thermostat_mode(mode)
        if ok:
            QMessageBox.information(self, "BTicino Modalità", msg)
            self.refresh_data()
        else:
            QMessageBox.warning(self, "Errore BTicino", msg)

    # --------------------------------------------------------------------------
    # Cloud Sync with GitHub Actions Telemetry Logs
    # --------------------------------------------------------------------------
    def _on_sync_cloud_clicked(self):
        self.btn_cloud_sync.setEnabled(False)
        self.btn_cloud_sync.setText("☁️ Download Cloud...")
        self.footer_label.setText("Connessione a GitHub Cloud per scaricare i campioni...")
        QApplication.processEvents()

        # Cache-busting query parameter + headers to bypass GitHub Fastly CDN 300s cache
        raw_url = f"https://raw.githubusercontent.com/{Config.GITHUB_REPO}/main/data/cloud_telemetry.jsonl?t={int(time.time())}"
        cloud_file = Config.DATA_DIR / "cloud_telemetry.jsonl"
        cloud_file.parent.mkdir(parents=True, exist_ok=True)

        headers = {
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        if Config.GITHUB_TOKEN:
            headers["Authorization"] = f"token {Config.GITHUB_TOKEN}"

        download_ok = False
        try:
            resp = requests.get(raw_url, headers=headers, timeout=12)
            if resp.status_code == 200 and resp.text.strip():
                with open(cloud_file, "w", encoding="utf-8") as f:
                    f.write(resp.text)
                download_ok = True
                logger.info("Scaricato con successo file telemetria da GitHub!")
            elif resp.status_code == 404:
                logger.info("Repo privato o file non trovato con HTTP 404 senza token.")
        except Exception as net_err:
            logger.warning("Download diretto da GitHub non riuscito (%s).", net_err)

        self.btn_cloud_sync.setEnabled(True)
        self.btn_cloud_sync.setText("☁️ Sync Cloud (GitHub)")

        if not cloud_file.exists() or cloud_file.stat().st_size == 0:
            QMessageBox.information(
                self,
                "Sincronizzazione Cloud GitHub",
                f"Impossibile scaricare direttamente dal repository GitHub:\n{Config.GITHUB_REPO}\n\n"
                "📌 Motivo:\n"
                "Il repository GitHub è impostato su 'Private', quindi richiede autorizzazione per il download automatico.\n\n"
                "💡 Per abilitare la sincronizzazione automatica con 1 clic:\n"
                "• Opzione A (Più comoda): Rendi il repo Pubblico su GitHub (i segreti sono nei Secrets crittografati, e i minuti GitHub diventano infiniti!).\n"
                "• Opzione B: Inserisci un GITHUB_TOKEN nel file .env."
            )
            return

        try:
            imported_count = self.db.import_file(cloud_file)

            # Controlla anche eventuali archivi storici mensili compressi (.jsonl.gz)
            archive_dir = Config.DATA_DIR / "archive"
            if archive_dir.exists():
                for arch_file in sorted(archive_dir.glob("*.jsonl.gz")):
                    arch_imported = self.db.import_file(arch_file)
                    if arch_imported > 0:
                        imported_count += arch_imported
                        logger.info("Importati %d campioni storici da archivio %s", arch_imported, arch_file.name)

            if imported_count > 0:
                self._load_latest_db_sample()
                self._update_charts()
                self._calculate_analytics()
                self.footer_label.setText(f"Sincronizzazione completata: {imported_count} nuovi campioni importati dal Cloud.")
                QMessageBox.information(
                    self,
                    "Sincronizzazione Riuscita",
                    f"✅ Scaricati e importati con successo {imported_count} nuovi campioni registrati da GitHub Cloud!\n\n"
                    "Grafici, sinottico, statistiche e dashboard aggiornati con le ultime letture."
                )
            else:
                self._load_latest_db_sample()
                self._update_charts()
                self._calculate_analytics()
                self.footer_label.setText("Database locale già allineato con il Cloud GitHub.")
                QMessageBox.information(
                    self,
                    "Database Già Aggiornato",
                    f"Tutti i campioni presenti nel file Cloud ({len(lines)} righe) sono già archiviati nel database SQLite locale.\n\n"
                    "Sinottico, dashboard, statistiche e grafici ricaricati con l'ultimo campione disponibile."
                )
        except Exception as e:
            QMessageBox.warning(self, "Errore Sincronizzazione Cloud", f"Impossibile completare la sincronizzazione:\n{e}")

    def _on_placeholder_preset_clicked(self):
        QMessageBox.information(
            self,
            "Gestione Preset Multi-Dispositivo",
            "Configurazione Preset Personalizzati (In fase di definizione):\n\n"
            "Questo spazio è predisposto per salvare profili personalizzati "
            "(es. Assenza Feriale, Pre-Riscaldamento Weekend, Massima Resa Solare).\n\n"
            "Quando definirai i valori di default desiderati, potremo collegarli qui per orchestrare "
            "con un solo clic sia la PdC Viessmann che il termostato BTicino Smarther.",
        )

    def _apply_preset_dialog(self, preset_name: str):
        reply = QMessageBox.question(
            self,
            f"Conferma Preset: {preset_name}",
            f"Sei sicuro di voler applicare il preset '{preset_name}' all'impianto?\n"
            "Questo modificherà contemporaneamente i parametri della Vitocal e del termostato BTicino.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            if preset_name == "Solo Antigelo / Standby":
                self.v_conn.set_mode("standby")
                self.b_conn.set_thermostat_setpoint(7.5, mode="manual", duration_minutes=0)
            elif preset_name == "Weekend Comfort":
                self.v_conn.set_heating_curve(0.6, 0)
                self.v_conn.set_normal_temperature(20.0)
                self.b_conn.set_thermostat_setpoint(20.5, mode="home")
            elif preset_name == "Pre-Riscaldamento Arrivo":
                self.v_conn.set_heating_curve(0.6, 0)
                self.v_conn.set_normal_temperature(20.0)
                self.b_conn.set_thermostat_setpoint(19.0, mode="manual", duration_minutes=720)
            elif preset_name == "Assenza Impulso Diurno (Inverno)":
                self.v_conn.set_heating_curve(0.6, -6)
                self.v_conn.set_reduced_temperature(10.0)
                self.b_conn.set_thermostat_setpoint(8.0, mode="manual", duration_minutes=0)

            QMessageBox.information(self, "Preset Inviato", f"Preset '{preset_name}' inviato con successo!")
            self.refresh_data()
            self.refresh_data()

    # --------------------------------------------------------------------------
    # Tab 6: Advanced Analytics & Thermodynamic Efficiency Engine
    # --------------------------------------------------------------------------
    def _build_analytics_tab(self):
        tab_layout = QVBoxLayout(self.tab_analytics)
        tab_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background-color: #0c1322; border: none;")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(14)
        layout.setContentsMargins(18, 18, 18, 18)

        # 1. TOP BAR: TIMEFRAME SELECTOR & CONTROLS
        top_box = QFrame()
        top_box.setStyleSheet("background-color: #161f30; border: 1px solid #334155; border-radius: 10px; padding: 10px;")
        t_lay = QVBoxLayout(top_box)
        t_lay.setSpacing(10)

        r1 = QHBoxLayout()
        lbl_title = QLabel("⏱️ Analisi & Statistiche di Funzionamento (Finestra Personalizzabile)")
        lbl_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #38bdf8;")
        r1.addWidget(lbl_title)
        r1.addStretch()

        # Preset Buttons
        self.preset_btn_group = []
        for hours_val, label in [(6, "6h"), (12, "12h"), (24, "24h"), (48, "48h"), (72, "72h"), (168, "7 Giorni"), (0, "Tutto")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            if hours_val == 24:
                btn.setChecked(True)
            btn.setStyleSheet("""
                QPushButton { background: #0f172a; border: 1px solid #334155; color: #94a3b8; padding: 5px 12px; border-radius: 6px; font-weight: 600; font-size: 11px; }
                QPushButton:checked { background: #38bdf8; color: #04121e; border-color: #38bdf8; font-weight: bold; }
                QPushButton:hover:!checked { background: #1e293b; color: #f8fafc; }
            """)
            btn.clicked.connect(lambda checked, h=hours_val, b=btn: self._on_analytics_preset_clicked(h, b))
            r1.addWidget(btn)
            self.preset_btn_group.append((btn, hours_val))

        t_lay.addLayout(r1)

        # Row 2: Custom Hours Spinbox + Cost + Calc Button
        r2 = QHBoxLayout()
        r2.setSpacing(10)

        lbl_custom = QLabel("Finestra Ore Personalizzata:")
        lbl_custom.setStyleSheet("color: #cbd5e1; font-weight: 600; font-size: 11px;")
        r2.addWidget(lbl_custom)

        self.spin_analytics_hours = QSpinBox()
        self.spin_analytics_hours.setRange(1, 720)
        self.spin_analytics_hours.setValue(24)
        self.spin_analytics_hours.setSuffix(" ore")
        self.spin_analytics_hours.setFixedWidth(110)
        self.spin_analytics_hours.setStyleSheet("background: #0f172a; color: #38bdf8; border: 1px solid #334155; border-radius: 6px; padding: 4px; font-weight: bold;")
        self.spin_analytics_hours.valueChanged.connect(self._on_custom_hours_spin_changed)

        btn_h_minus = QPushButton("-")
        btn_h_minus.setFixedSize(26, 26)
        btn_h_minus.setStyleSheet("background: #1e293b; color: #38bdf8; border: 1px solid #334155; border-radius: 4px; font-weight: bold;")
        btn_h_minus.clicked.connect(lambda: self.spin_analytics_hours.setValue(max(1, self.spin_analytics_hours.value() - 6)))

        btn_h_plus = QPushButton("+")
        btn_h_plus.setFixedSize(26, 26)
        btn_h_plus.setStyleSheet("background: #1e293b; color: #38bdf8; border: 1px solid #334155; border-radius: 4px; font-weight: bold;")
        btn_h_plus.clicked.connect(lambda: self.spin_analytics_hours.setValue(min(720, self.spin_analytics_hours.value() + 6)))

        r2.addWidget(btn_h_minus)
        r2.addWidget(self.spin_analytics_hours)
        r2.addWidget(btn_h_plus)

        r2.addSpacing(14)
        lbl_cost = QLabel("Costo Elettricità:")
        lbl_cost.setStyleSheet("color: #cbd5e1; font-weight: 600; font-size: 11px;")
        r2.addWidget(lbl_cost)

        self.spin_analytics_cost = QDoubleSpinBox()
        self.spin_analytics_cost.setRange(0.05, 1.50)
        self.spin_analytics_cost.setSingleStep(0.01)
        self.spin_analytics_cost.setValue(0.25)
        self.spin_analytics_cost.setSuffix(" €/kWh")
        self.spin_analytics_cost.setFixedWidth(100)
        self.spin_analytics_cost.setStyleSheet("background: #0f172a; color: #facc15; border: 1px solid #334155; border-radius: 6px; padding: 4px; font-weight: bold;")
        self.spin_analytics_cost.valueChanged.connect(self._calculate_analytics)
        r2.addWidget(self.spin_analytics_cost)

        r2.addSpacing(14)
        self.btn_calc_analytics = QPushButton("🔄 Calcola")
        self.btn_calc_analytics.setStyleSheet("""
            QPushButton { background: #0284c7; color: white; border: none; border-radius: 6px; padding: 6px 14px; font-weight: bold; font-size: 11px; }
            QPushButton:hover { background: #0369a1; }
        """)
        self.btn_calc_analytics.clicked.connect(self._calculate_analytics)
        r2.addWidget(self.btn_calc_analytics)

        r2.addStretch()
        self.lbl_analytics_effective_range = QLabel("Analisi in corso...")
        self.lbl_analytics_effective_range.setStyleSheet("color: #94a3b8; font-size: 11px; font-style: italic;")
        r2.addWidget(self.lbl_analytics_effective_range)

        t_lay.addLayout(r2)
        layout.addWidget(top_box)

        # 2. ANTI-FROST SAFETY BANNER
        self.banner_frost_safety = QFrame()
        self.banner_frost_safety.setStyleSheet("background-color: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.4); border-radius: 10px; padding: 12px;")
        b_lay = QVBoxLayout(self.banner_frost_safety)
        b_lay.setSpacing(6)

        b_top = QHBoxLayout()
        self.lbl_safety_verdict = QLabel("🛡️ CASA AL SICURO DAL GELO")
        self.lbl_safety_verdict.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.lbl_safety_verdict.setStyleSheet("color: #6ee7b7;")
        b_top.addWidget(self.lbl_safety_verdict)
        b_top.addStretch()

        self.lbl_safety_margin = QLabel("+2.8 °C")
        self.lbl_safety_margin.setStyleSheet("background: rgba(16, 185, 129, 0.25); color: #10b981; font-weight: bold; font-size: 13px; padding: 3px 8px; border-radius: 6px; border: 1px solid rgba(16, 185, 129, 0.5);")
        b_top.addWidget(self.lbl_safety_margin)
        b_lay.addLayout(b_top)

        self.lbl_safety_advice = QLabel("Caricamento consigli operativi...")
        self.lbl_safety_advice.setStyleSheet("color: #cbd5e1; font-size: 11.5px; line-height: 1.4;")
        self.lbl_safety_advice.setWordWrap(True)
        b_lay.addWidget(self.lbl_safety_advice)
        layout.addWidget(self.banner_frost_safety)

        # 3. KPI CARDS GRID (4 Cards)
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)

        def make_kpi_card(title_txt, color_hex):
            card = QFrame()
            card.setStyleSheet("background-color: #161f30; border: 1px solid #334155; border-radius: 10px; padding: 12px;")
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(10, 10, 10, 10)
            c_lay.setSpacing(4)
            lbl_t = QLabel(title_txt.upper())
            lbl_t.setStyleSheet("font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px;")
            c_lay.addWidget(lbl_t)
            lbl_val = QLabel("--")
            lbl_val.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
            lbl_val.setStyleSheet(f"color: {color_hex};")
            c_lay.addWidget(lbl_val)
            lbl_sub = QLabel("--")
            lbl_sub.setStyleSheet("font-size: 10px; color: #64748b;")
            c_lay.addWidget(lbl_sub)
            return card, lbl_val, lbl_sub

        card1, self.kpi_starts_val, self.kpi_starts_sub = make_kpi_card("Avviamenti Compressore", "#38bdf8")
        card2, self.kpi_dur_val, self.kpi_dur_sub = make_kpi_card("Durata Media Ciclo", "#f59e0b")
        card3, self.kpi_run_val, self.kpi_run_sub = make_kpi_card("Ore Marcia PdC", "#10b981")
        card4, self.kpi_cost_val, self.kpi_cost_sub = make_kpi_card("Spesa Stimata Periodo", "#facc15")

        kpi_row.addWidget(card1)
        kpi_row.addWidget(card2)
        kpi_row.addWidget(card3)
        kpi_row.addWidget(card4)
        layout.addLayout(kpi_row)

        # 4. MODULATION QUALITY BOX ("Ha modulato bene?")
        mod_box = QFrame()
        mod_box.setStyleSheet("background-color: #161f30; border: 1px solid #334155; border-radius: 10px; padding: 14px;")
        m_lay = QVBoxLayout(mod_box)
        m_lay.setSpacing(8)

        m_top = QHBoxLayout()
        lbl_mod_hdr = QLabel("🎯 Diagnostica Qualità Modulazione Inverter")
        lbl_mod_hdr.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        lbl_mod_hdr.setStyleSheet("color: #38bdf8;")
        m_top.addWidget(lbl_mod_hdr)
        m_top.addStretch()

        self.lbl_mod_score = QLabel("Score 95/100")
        self.lbl_mod_score.setStyleSheet("background: rgba(56, 189, 248, 0.15); color: #38bdf8; font-weight: bold; font-size: 12px; padding: 3px 10px; border-radius: 6px; border: 1px solid rgba(56, 189, 248, 0.3);")
        m_top.addWidget(self.lbl_mod_score)
        m_lay.addLayout(m_top)

        self.lbl_mod_verdict = QLabel("Valutazione in corso...")
        self.lbl_mod_verdict.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.lbl_mod_verdict.setStyleSheet("color: #f8fafc;")
        m_lay.addWidget(self.lbl_mod_verdict)

        self.lbl_mod_diagnosis = QLabel("Dettagli diagnosi...")
        self.lbl_mod_diagnosis.setStyleSheet("color: #cbd5e1; font-size: 11.5px; line-height: 1.4;")
        self.lbl_mod_diagnosis.setWordWrap(True)
        m_lay.addWidget(self.lbl_mod_diagnosis)

        # Ripartizione Carico Inverter
        load_strip = QFrame()
        load_strip.setStyleSheet("background-color: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 10px; margin-top: 6px;")
        ls_lay = QHBoxLayout(load_strip)
        ls_lay.setContentsMargins(10, 8, 10, 8)

        self.lbl_load_low = QLabel("🟢 Basso Carico (1-30%): <b>0%</b>")
        self.lbl_load_low.setStyleSheet("color: #10b981; font-size: 11px;")
        self.lbl_load_mid = QLabel("🔵 Medio Carico (31-60%): <b>0%</b>")
        self.lbl_load_mid.setStyleSheet("color: #38bdf8; font-size: 11px;")
        self.lbl_load_high = QLabel("🔴 Alto Carico (>60%): <b>0%</b>")
        self.lbl_load_high.setStyleSheet("color: #f43f5e; font-size: 11px;")
        self.lbl_max_mod = QLabel("Picco Max: <b>0%</b>")
        self.lbl_max_mod.setStyleSheet("color: #facc15; font-size: 11px;")

        ls_lay.addWidget(self.lbl_load_low)
        ls_lay.addStretch()
        ls_lay.addWidget(self.lbl_load_mid)
        ls_lay.addStretch()
        ls_lay.addWidget(self.lbl_load_high)
        ls_lay.addStretch()
        ls_lay.addWidget(self.lbl_max_mod)
        m_lay.addWidget(load_strip)

        layout.addWidget(mod_box)

        # 5. ELECTRICAL CONSUMPTION & POWER BOX
        cons_box = QFrame()
        cons_box.setStyleSheet("background-color: #161f30; border: 1px solid #334155; border-radius: 10px; padding: 14px;")
        c_lay = QVBoxLayout(cons_box)
        c_lay.setSpacing(8)

        c_top = QHBoxLayout()
        lbl_cons_hdr = QLabel("⚡ Bilancio Energetico & Stima Spesa Elettrica")
        lbl_cons_hdr.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        lbl_cons_hdr.setStyleSheet("color: #facc15;")
        c_top.addWidget(lbl_cons_hdr)
        c_top.addStretch()

        self.lbl_cop_avg = QLabel("COP Medio: 3.10")
        self.lbl_cop_avg.setStyleSheet("background: rgba(52, 211, 153, 0.15); color: #34d399; font-weight: bold; font-size: 11px; padding: 3px 8px; border-radius: 6px; border: 1px solid rgba(52, 211, 153, 0.3);")
        c_top.addWidget(self.lbl_cop_avg)
        c_lay.addLayout(c_top)

        self.lbl_cons_desc = QLabel(
            "Stima basata sulla potenza modulante del compressore Vitocal 111-S (11-12 kW nominali), "
            "assorbimento inverter, circolatore primario integrato e consumo standby dei controlli elettronici."
        )
        self.lbl_cons_desc.setStyleSheet("color: #94a3b8; font-size: 11px;")
        self.lbl_cons_desc.setWordWrap(True)
        c_lay.addWidget(self.lbl_cons_desc)

        cons_stats_row = QHBoxLayout()
        self.lbl_elec_kwh_detail = QLabel("Energia Totale: <b>-- kWh</b>")
        self.lbl_elec_kwh_detail.setStyleSheet("color: #facc15; font-size: 11.5px;")
        self.lbl_power_avg_detail = QLabel("Potenza Media: <b>-- kW</b>")
        self.lbl_power_avg_detail.setStyleSheet("color: #38bdf8; font-size: 11.5px;")
        self.lbl_cost_detail = QLabel("Costo Periodo: <b>-- €</b>")
        self.lbl_cost_detail.setStyleSheet("color: #4ade80; font-size: 11.5px;")
        self.lbl_daily_cost_detail = QLabel("Proiezione Giornaliera: <b>-- €/giorno</b>")
        self.lbl_daily_cost_detail.setStyleSheet("color: #cbd5e1; font-size: 11.5px;")

        cons_stats_row.addWidget(self.lbl_elec_kwh_detail)
        cons_stats_row.addStretch()
        cons_stats_row.addWidget(self.lbl_power_avg_detail)
        cons_stats_row.addStretch()
        cons_stats_row.addWidget(self.lbl_cost_detail)
        cons_stats_row.addStretch()
        cons_stats_row.addWidget(self.lbl_daily_cost_detail)
        c_lay.addLayout(cons_stats_row)

        layout.addWidget(cons_box)

        # 6. DETAILED TABLE OF DETECTED CYCLES
        tbl_box = QFrame()
        tbl_box.setStyleSheet("background-color: #161f30; border: 1px solid #334155; border-radius: 10px; padding: 12px;")
        tb_lay = QVBoxLayout(tbl_box)
        tb_lay.setSpacing(8)

        lbl_tbl_hdr = QLabel("📋 Dettaglio Singoli Cicli Accesi Rilevati")
        lbl_tbl_hdr.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        lbl_tbl_hdr.setStyleSheet("color: #38bdf8;")
        tb_lay.addWidget(lbl_tbl_hdr)

        self.table_analytics_cycles = QTableWidget()
        self.table_analytics_cycles.setColumnCount(6)
        self.table_analytics_cycles.setHorizontalHeaderLabels([
            "#", "Ora Inizio", "Ora Fine", "Durata (min)", "Carico Inverter (%)", "T Mandata PdC (°C)"
        ])
        self.table_analytics_cycles.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_analytics_cycles.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_analytics_cycles.setStyleSheet("""
            QTableWidget { background-color: #0f172a; color: #f8fafc; border: 1px solid #334155; border-radius: 6px; }
            QHeaderView::section { background-color: #1e293b; color: #38bdf8; font-weight: bold; padding: 4px; border: 1px solid #334155; }
        """)
        self.table_analytics_cycles.setFixedHeight(180)
        tb_lay.addWidget(self.table_analytics_cycles)
        layout.addWidget(tbl_box)

        scroll.setWidget(container)
        tab_layout.addWidget(scroll)

        # Initial calculation
        self._calculate_analytics()

    def _on_analytics_preset_clicked(self, hours: int, clicked_btn: QPushButton):
        for btn, h in self.preset_btn_group:
            btn.setChecked(btn == clicked_btn)
        if hours > 0:
            self.spin_analytics_hours.blockSignals(True)
            self.spin_analytics_hours.setValue(hours)
            self.spin_analytics_hours.blockSignals(False)
        self._calculate_analytics()

    def _on_custom_hours_spin_changed(self, val: int):
        for btn, h in self.preset_btn_group:
            btn.setChecked(h == val)
        self._calculate_analytics()

    def _calculate_analytics(self):
        hours = float(self.spin_analytics_hours.value())
        # Check if "Tutto" was clicked
        for btn, h in self.preset_btn_group:
            if btn.isChecked() and h == 0:
                hours = 8760.0  # 1 year / all

        cost = float(self.spin_analytics_cost.value())

        # Load samples from SQLite database
        try:
            with self.db._get_connection() as conn:
                rows = [dict(r) for r in conn.execute("SELECT * FROM telemetry_samples ORDER BY id ASC").fetchall()]
        except Exception as e:
            logger.error("Errore lettura database per analytics: %s", e)
            return

        res = analyze_telemetry_period(rows, hours_requested=hours, cost_per_kwh=cost)

        # Update Effective Range Header
        p = res["period"]
        self.lbl_analytics_effective_range.setText(
            f"Analisi su {p['effective_hours']} ore effettive ({p['samples_analyzed']} campioni)"
        )

        # Update Frost Safety Banner
        sf = res["anti_frost_safety"]
        self.lbl_safety_verdict.setText(sf["verdict"])
        self.lbl_safety_margin.setText(f"+{sf['safety_margin_c']} °C" if sf['safety_margin_c'] is not None else "--")
        self.lbl_safety_advice.setText(sf["advice"])

        if sf["status"] == "safe":
            self.banner_frost_safety.setStyleSheet("background-color: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.4); border-radius: 10px; padding: 12px;")
            self.lbl_safety_verdict.setStyleSheet("color: #6ee7b7;")
            self.lbl_safety_margin.setStyleSheet("background: rgba(16, 185, 129, 0.25); color: #10b981; font-weight: bold; font-size: 13px; padding: 3px 8px; border-radius: 6px; border: 1px solid rgba(16, 185, 129, 0.5);")
        elif sf["status"] == "caution":
            self.banner_frost_safety.setStyleSheet("background-color: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.4); border-radius: 10px; padding: 12px;")
            self.lbl_safety_verdict.setStyleSheet("color: #facc15;")
            self.lbl_safety_margin.setStyleSheet("background: rgba(245, 158, 11, 0.25); color: #f59e0b; font-weight: bold; font-size: 13px; padding: 3px 8px; border-radius: 6px; border: 1px solid rgba(245, 158, 11, 0.5);")
        else:
            self.banner_frost_safety.setStyleSheet("background-color: rgba(239, 68, 68, 0.2); border: 1px solid rgba(239, 68, 68, 0.5); border-radius: 10px; padding: 12px;")
            self.lbl_safety_verdict.setStyleSheet("color: #f87171;")
            self.lbl_safety_margin.setStyleSheet("background: rgba(239, 68, 68, 0.25); color: #ef4444; font-weight: bold; font-size: 13px; padding: 3px 8px; border-radius: 6px; border: 1px solid rgba(239, 68, 68, 0.5);")

        # Update KPI Cards
        sc = res["starts_and_cycles"]
        self.kpi_starts_val.setText(str(sc["total_starts"]))
        self.kpi_starts_sub.setText(f"Duty Cycle: {sc['duty_cycle_percent']}% | Hardware Δ: {sc['starts_from_hardware']}")

        self.kpi_dur_val.setText(f"{sc['duration_avg_minutes']} min")
        self.kpi_dur_sub.setText(f"Min: {sc['duration_min_minutes']}m | Max: {sc['duration_max_minutes']}m")

        self.kpi_run_val.setText(f"{sc['total_run_hours']} h")
        self.kpi_run_sub.setText(f"Standby: {sc['standby_hours']} h ({100 - sc['duty_cycle_percent']:.1f}%)")

        cs = res["consumption"]
        self.kpi_cost_val.setText(f"{cs['estimated_cost_eur']:.2f} €")
        self.kpi_cost_sub.setText(f"Proiezione: {cs['projected_daily_cost_eur']:.2f} €/giorno")

        # Update Modulation Box
        mo = res["modulation"]
        self.lbl_mod_score.setText(f"Score {mo['score']}/100")
        self.lbl_mod_score.setStyleSheet(
            f"background: rgba(56, 189, 248, 0.15); color: {'#10b981' if mo['score'] >= 80 else ('#facc15' if mo['score'] >= 50 else '#f87171')}; "
            "font-weight: bold; font-size: 12px; padding: 3px 10px; border-radius: 6px; border: 1px solid #334155;"
        )
        self.lbl_mod_verdict.setText(mo["verdict"])
        self.lbl_mod_diagnosis.setText(mo["diagnosis"])

        self.lbl_load_low.setText(f"🟢 Basso Carico (1-30%): <b>{mo['low_load_percent']}%</b>")
        self.lbl_load_mid.setText(f"🔵 Medio Carico (31-60%): <b>{mo['mid_load_percent']}%</b>")
        self.lbl_load_high.setText(f"🔴 Alto Carico (>60%): <b>{mo['high_load_percent']}%</b>")
        self.lbl_max_mod.setText(f"Picco Inverter: <b>{mo['max_modulation_percent']}%</b>")

        # Update Consumption Box
        self.lbl_cop_avg.setText(f"COP Medio: {cs['avg_cop']:.2f}")
        self.lbl_elec_kwh_detail.setText(f"Energia Totale: <b>{cs['total_elec_kwh']:.2f} kWh</b>")
        self.lbl_power_avg_detail.setText(f"Potenza Media: <b>{cs['avg_power_kw']:.3f} kW</b>")
        self.lbl_cost_detail.setText(f"Costo Periodo: <b>{cs['estimated_cost_eur']:.2f} €</b>")
        self.lbl_daily_cost_detail.setText(f"Proiezione Giornaliera: <b>{cs['projected_daily_cost_eur']:.2f} €/giorno</b>")

        # Update Detected Cycles Table
        cycles = sc["cycles_list"]
        self.table_analytics_cycles.setRowCount(0)
        if cycles:
            self.table_analytics_cycles.setRowCount(len(cycles))
            for i, c in enumerate(cycles):
                self.table_analytics_cycles.setItem(i, 0, QTableWidgetItem(f"#{i+1}"))
                self.table_analytics_cycles.setItem(i, 1, QTableWidgetItem(str(c.get("start", ""))[:19].replace("T", " ")))
                self.table_analytics_cycles.setItem(i, 2, QTableWidgetItem(str(c.get("end", ""))[:19].replace("T", " ")))
                self.table_analytics_cycles.setItem(i, 3, QTableWidgetItem(f"{c.get('duration_minutes', 0):.1f} min"))
                self.table_analytics_cycles.setItem(i, 4, QTableWidgetItem(f"{c.get('avg_modulation', 0):.0f}% (max {c.get('max_modulation', 0):.0f}%)"))
                t_m = c.get('avg_supply_temp')
                self.table_analytics_cycles.setItem(i, 5, QTableWidgetItem(f"{t_m:.1f} °C" if t_m is not None else "--"))
        else:
            self.table_analytics_cycles.setRowCount(1)
            self.table_analytics_cycles.setItem(0, 0, QTableWidgetItem("-"))
            self.table_analytics_cycles.setItem(0, 1, QTableWidgetItem("Nessun ciclo attivo continuo rilevato"))
            self.table_analytics_cycles.setItem(0, 2, QTableWidgetItem("Standby protettivo attivo"))
            self.table_analytics_cycles.setItem(0, 3, QTableWidgetItem("0 min"))
            self.table_analytics_cycles.setItem(0, 4, QTableWidgetItem("0%"))
            self.table_analytics_cycles.setItem(0, 5, QTableWidgetItem("--"))
