"""
Interactive Heating Curve Widget (Curva Climatica LWT vs OAT).
Visualizes Leaving Water Temperature (LWT) as a function of Outside Air Temperature (OAT).
Explicitly displays the reference temperature (Temperatura Normale PdC) that shifts the curve.
Allows interactive adjustment of Slope (Inclinazione) and Shift (Livello) with live marker.
"""
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
)


def calculate_viessmann_lwt(oat: float, slope: float, shift: float, t_room: float = 12.0) -> float:
    """
    Standard Viessmann characteristic heating curve formula for radiant/underfloor heating:
    LWT = T_room + Shift + Slope * 1.83 * (T_room - OAT)^0.8
    T_room is the desired room temperature (Temperatura Normale) acting as the curve's pivot/base shift.
    """
    dt = t_room - oat
    if dt >= 0:
        val = t_room + shift + slope * 1.83 * (dt ** 0.8)
    else:
        val = t_room + shift - slope * 1.83 * (abs(dt) ** 0.8)
    # Floor heating design range: clamped between 18.0 °C and 40.0 °C
    return float(np.clip(val, 18.0, 40.0))


class HeatingCurveWidget(QWidget):
    curve_changed = pyqtSignal(float, float)  # (slope, shift)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.slope = 0.6
        self.shift = 0.0
        self.current_oat = 5.9
        self.t_room_normal = 12.0  # Reference baseline temperature from Viessmann

        self._init_ui()
        self._update_plot()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Plot Widget
        self.plot_widget = pg.PlotWidget(title="<b>CURVA CLIMATICA PDC (Mandata LWT vs Temp. Esterna OAT)</b>")
        self.plot_widget.setBackground("#111827")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel("left", "Temperatura Mandata LWT", units="°C", color="#38bdf8")
        self.plot_widget.setLabel("bottom", "Temperatura Esterna OAT", units="°C", color="#f59e0b")
        self.plot_widget.setXRange(-20, 20, padding=0.02)
        self.plot_widget.setYRange(15, 45, padding=0.05)

        # Shading regions
        # Floor heating safe zone (20 to 38 °C)
        self.safe_zone = pg.LinearRegionItem(
            values=(20, 38),
            orientation="horizontal",
            brush=QColor(16, 185, 129, 25),
            pen=pg.mkPen(color=(0, 0, 0, 0), width=0),
            movable=False,
        )
        for line in self.safe_zone.lines:
            line.setPen(pg.mkPen(color=(0, 0, 0, 0), width=0))
            line.setHoverPen(pg.mkPen(color=(0, 0, 0, 0), width=0))
        self.plot_widget.addItem(self.safe_zone)

        # Floor heating max limit warning line (40 °C)
        self.limit_line = pg.InfiniteLine(
            pos=40.0,
            angle=0,
            pen=pg.mkPen(color="#ef4444", width=2, style=Qt.PenStyle.DashLine),
            label="Limite Max Sicurezza Pavimento (40 °C)",
            labelOpts={"position": 0.85, "color": "#ef4444", "fill": (30, 20, 20, 180)},
        )
        self.plot_widget.addItem(self.limit_line)

        # Main curve line
        self.curve_item = self.plot_widget.plot(
            pen=pg.mkPen(color="#38bdf8", width=3),
            name="Curva Mandata",
        )

        # Current operating point marker
        self.live_marker = pg.ScatterPlotItem(
            size=14,
            pen=pg.mkPen(color="#ffffff", width=2),
            brush=pg.mkBrush("#f59e0b"),
            symbol="o",
        )
        self.plot_widget.addItem(self.live_marker)

        # Text label for live point
        self.marker_text = pg.TextItem(text="", color="#f59e0b", anchor=(0, 1))
        self.marker_text.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.plot_widget.addItem(self.marker_text)

        # On-chart info badge for reference parameters
        self.badge_text = pg.TextItem(text="", color="#e2e8f0", anchor=(0, 0))
        self.badge_text.setFont(QFont("Segoe UI", 10))
        self.plot_widget.addItem(self.badge_text)

        layout.addWidget(self.plot_widget, stretch=1)

        # Real-time calculation readout box
        self.box_readout = QGroupBox("ANALISI PUNTI DI LAVORO RADIANTE")
        r_lay = QVBoxLayout(self.box_readout)
        r_lay.setSpacing(6)

        self.lbl_ref_info = QLabel("🎯 Riferimento Base Curva: Temp. Normale = <b>-- °C</b>")
        self.lbl_ref_info.setStyleSheet("color: #c084fc; font-size: 13px;")

        row_metrics = QHBoxLayout()
        self.lbl_current_target = QLabel("🌡️ Mandata con OAT attuale: <b>-- °C</b>")
        self.lbl_current_target.setStyleSheet("color: #38bdf8; font-size: 13px;")

        self.lbl_ref_points = QLabel("❄️ Mandata a 0 °C: <b>-- °C</b>  |  Gelo a -10 °C: <b>-- °C</b>")
        self.lbl_ref_points.setStyleSheet("color: #e2e8f0; font-size: 13px;")

        row_metrics.addWidget(self.lbl_current_target)
        row_metrics.addStretch()
        row_metrics.addWidget(self.lbl_ref_points)

        r_lay.addWidget(self.lbl_ref_info)
        r_lay.addLayout(row_metrics)
        layout.addWidget(self.box_readout)

        # Quick preset slope/shift samples
        p_row = QHBoxLayout()
        presets = [
            ("Standard Radiante (0.6, 0)", 0.6, 0),
            ("Basso Consumo (0.4, -2)", 0.4, -2),
            ("Spinta Freddo (0.8, 0)", 0.8, 0),
            ("Notturno Assenza (0.6, -6)", 0.6, -6),
        ]
        for name, s, sh in presets:
            btn = QPushButton(name)
            btn.setStyleSheet("background: #1e293b; color: #cbd5e1; border: 1px solid #334155; padding: 5px 10px; border-radius: 4px;")
            btn.clicked.connect(lambda _, s=s, sh=sh: self.set_parameters(s, sh))
            p_row.addWidget(btn)
        layout.addLayout(p_row)

    def set_reference_temperature(self, t_norm: float):
        """Sets the reference room temperature (Normal Temperature) for curve calculation."""
        if t_norm is not None:
            self.t_room_normal = float(t_norm)
            self._update_plot()

    def set_parameters(self, slope: float, shift: float, current_oat: float = None, t_room_normal: float = None):
        """Sets curve parameters and refreshes graphic."""
        self.slope = float(slope)
        self.shift = float(shift)
        if current_oat is not None:
            self.current_oat = float(current_oat)
        if t_room_normal is not None:
            self.t_room_normal = float(t_room_normal)
        self._update_plot()
        self.curve_changed.emit(self.slope, self.shift)

    def set_current_oat(self, oat: float):
        """Updates the live outdoor temperature marker."""
        self.current_oat = float(oat)
        self._update_plot()

    def _update_plot(self):
        # Generate points from -20 °C to +20 °C
        oat_range = np.linspace(-20, 20, 81)
        lwt_values = [calculate_viessmann_lwt(t, self.slope, self.shift, self.t_room_normal) for t in oat_range]

        self.curve_item.setData(oat_range, lwt_values)

        # Update live marker
        live_lwt = calculate_viessmann_lwt(self.current_oat, self.slope, self.shift, self.t_room_normal)
        self.live_marker.setData([self.current_oat], [live_lwt])
        self.marker_text.setText(f" Live: {live_lwt:.1f} °C @ {self.current_oat:.1f} °C")
        self.marker_text.setPos(self.current_oat, live_lwt)

        # Update badge
        shift_sign = f"+{int(self.shift)}" if self.shift > 0 else f"{int(self.shift)}"
        self.badge_text.setHtml(
            f"<div style='background-color: rgba(17, 24, 39, 0.85); padding: 5px 8px; border: 1px solid #374151; border-radius: 5px;'>"
            f"<b style='color: #c084fc;'>🎯 Rif. Temp. Normale: {self.t_room_normal:.1f} °C</b><br>"
            f"<span style='color: #94a3b8; font-size: 11px;'>Pendenza: {self.slope:.2f} | Offset: {shift_sign}</span>"
            f"</div>"
        )
        self.badge_text.setPos(-19.5, 43.5)

        # Update readout labels
        self.lbl_ref_info.setText(
            f"🎯 <b>Riferimento Base Curva:</b> Temp. Normale PdC = <b style='color: #c084fc;'>{self.t_room_normal:.1f} °C</b> "
            f"<i>(Variare la Temp. Normale sposta parallelamente l'intera curva)</i>"
        )
        self.lbl_current_target.setText(
            f"🌡️ <b>T Mandata calcolata</b> (OAT attuale {self.current_oat:.1f} °C): <b style='color: #38bdf8;'>{live_lwt:.1f} °C</b>"
        )
        lwt_zero = calculate_viessmann_lwt(0.0, self.slope, self.shift, self.t_room_normal)
        lwt_minus10 = calculate_viessmann_lwt(-10.0, self.slope, self.shift, self.t_room_normal)
        self.lbl_ref_points.setText(
            f"❄️ Mandata a 0 °C: <b style='color: #fbbf24;'>{lwt_zero:.1f} °C</b>  |  "
            f"Gelo a -10 °C: <b style='color: {'#ef4444' if lwt_minus10 >= 40 else '#10b981'};'>{lwt_minus10:.1f} °C</b>"
        )
