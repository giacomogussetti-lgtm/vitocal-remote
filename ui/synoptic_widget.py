"""
Plant Synoptic Widget (Sinottico Impianto Termico & Mappatura Sonde).
Industrial SCADA-style visual representation of the hydraulic and control architecture
for the Vitocal 111-S Heat Pump, 200L Buffer, Grundfos Pump, and BTicino Smarther.
Includes complete thermodynamic telemetry from Viessmann APIs with generous spacing
to eliminate any label or badge overlapping.
"""
from typing import Any, Optional
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import (
    QPainter,
    QColor,
    QPen,
    QBrush,
    QFont,
    QLinearGradient,
    QPainterPath,
)
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QFrame,
)


class SynopticCanvas(QWidget):
    """
    Vector-rendered SCADA canvas showing physical layout, pipes, valves, pumps,
    puffer tank, and live sensor badges with color-coded status.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(1280, 600)
        self.data: dict[str, Any] = {}

    def update_telemetry(self, telemetry: dict[str, Any]):
        self.data = telemetry
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = max(self.width(), 1280)
        h = max(self.height(), 600)

        # Background (industrial deep navy/slate)
        painter.fillRect(0, 0, w, h, QColor("#0c1322"))

        # -------------------------------------------------------------
        # LAYOUT GEOMETRY & PROPORTIONS
        # -------------------------------------------------------------
        # Zone A: PdC Vitocal 111-S (width: 385)
        pdc_x = 30
        pdc_y = 40
        pdc_w = 385
        pdc_h = 520
        pdc_rect = QRectF(pdc_x, pdc_y, pdc_w, pdc_h)

        # Zone B: Puffer Inerziale 200L (width: 160)
        # Primary pipe span = puffer_x - (pdc_x + pdc_w) = 555 - 415 = 140px!
        puffer_x = 555
        puffer_y = 80
        puffer_w = 160
        puffer_h = 440
        puffer_rect = QRectF(puffer_x, puffer_y, puffer_w, puffer_h)

        # Zone C: Abitazione Bratto (width: at least 410, stretches with window)
        # Secondary pipe span = house_x - (puffer_x + puffer_w) = 870 - 715 = 155px!
        house_x = 870
        house_w = max(410, w - house_x - 30)
        house_y = 40
        house_h = 520
        house_rect = QRectF(house_x, house_y, house_w, house_h)

        # Pipe Vertical Levels
        pipe_supply_y = 150
        pipe_return_y = 450

        # -------------------------------------------------------------
        # 1. DRAW PIPING & HYDRAULIC CONNECTIONS
        # -------------------------------------------------------------
        # Mandata Primaria (PdC -> Puffer Top) - Hot Red
        pipe_pen_hot = QPen(QColor("#ef4444"), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pipe_pen_hot)
        painter.drawLine(QPointF(pdc_rect.right(), pipe_supply_y), QPointF(puffer_rect.left(), pipe_supply_y))

        # Ritorno Primario (Puffer Bottom -> PdC) - Cold Blue
        pipe_pen_cold = QPen(QColor("#3b82f6"), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pipe_pen_cold)
        painter.drawLine(QPointF(puffer_rect.left(), pipe_return_y), QPointF(pdc_rect.right(), pipe_return_y))

        # Flow Arrows on Primary Pipes
        p1_mid_x = (pdc_rect.right() + puffer_rect.left()) / 2.0
        self._draw_arrow(painter, p1_mid_x + 35, pipe_supply_y, 1, 0, "#ef4444")
        self._draw_arrow(painter, p1_mid_x - 35, pipe_return_y, -1, 0, "#3b82f6")

        # Mandata Secondaria (Puffer Top -> Grundfos -> Pavimento)
        painter.setPen(pipe_pen_hot)
        grundfos_x = (puffer_rect.right() + house_rect.left()) / 2.0
        painter.drawLine(QPointF(puffer_rect.right(), pipe_supply_y), QPointF(grundfos_x - 24, pipe_supply_y))
        painter.drawLine(QPointF(grundfos_x + 24, pipe_supply_y), QPointF(house_rect.left(), pipe_supply_y))

        # Ritorno Secondario (Pavimento -> Puffer Bottom)
        painter.setPen(pipe_pen_cold)
        painter.drawLine(QPointF(house_rect.left(), pipe_return_y), QPointF(puffer_rect.right(), pipe_return_y))

        # Flow Arrows on Secondary Pipes
        self._draw_arrow(painter, (puffer_rect.right() + grundfos_x) / 2.0, pipe_supply_y, 1, 0, "#ef4444")
        self._draw_arrow(painter, (grundfos_x + house_rect.left()) / 2.0, pipe_supply_y, 1, 0, "#ef4444")
        self._draw_arrow(painter, grundfos_x, pipe_return_y, -1, 0, "#3b82f6")

        # -------------------------------------------------------------
        # 2. SENSOR TAGS ON PRIMARY PIPES (Zero Overlap with boxes)
        # -------------------------------------------------------------
        p_supply = self.data.get("supply_temp_c", "--")
        p_return = self.data.get("return_temp_c", "--")

        # Mandata PdC Tag (Above pipe, centered in the 140px gap)
        self._draw_pipe_sensor_tag(
            painter,
            p1_mid_x,
            pipe_supply_y - 42,
            "T Mandata PdC",
            f"{p_supply} °C",
            "#ef4444",
            pipe_y=pipe_supply_y,
            is_above=True,
        )

        # Ritorno PdC Tag (Below pipe, centered in the 140px gap)
        self._draw_pipe_sensor_tag(
            painter,
            p1_mid_x,
            pipe_return_y + 12,
            "T Ritorno PdC",
            f"{p_return} °C",
            "#3b82f6",
            pipe_y=pipe_return_y,
            is_above=False,
        )

        # -------------------------------------------------------------
        # 3. ZONE A: VITOCAL 111-S (PdC + Circuito Frigorifero Completo)
        # -------------------------------------------------------------
        self._draw_block(painter, pdc_rect, "POMPA DI CALORE VIESSMANN (Vitocal 111-S)", "#161f30", "#38bdf8")

        # Two columns of badges inside Zone A
        col1_x = pdc_rect.left() + 14
        col2_x = pdc_rect.left() + 198
        b_w = 172
        b_h = 48
        y_step = 54
        start_y = pdc_rect.top() + 40

        # Row 0: Sonda Esterna OAT & Bollitore ACS
        oat = self.data.get("outside_temp_c", "--")
        dhw_temp = self.data.get("dhw_storage_temp_c", "--")
        self._draw_badge(painter, col1_x, start_y, b_w, b_h, "Sonda Esterna OAT", f"{oat} °C", "#f59e0b")
        self._draw_badge(painter, col2_x, start_y, b_w, b_h, "Bollitore ACS 220L", f"{dhw_temp} °C", "#c084fc")

        # Row 1: Compressore & Pressione Gas Caldo
        comp_active = self.data.get("compressor_active") or (self.data.get("compressor_modulation_percent", 0) or 0) > 0
        comp_mod = self.data.get("compressor_modulation_percent", 0) or 0
        comp_color = "#10b981" if comp_active else "#64748b"
        comp_txt = f"{comp_mod} % (ON)" if comp_active else "SPENTO"
        gas_press = self.data.get("hot_gas_pressure_bar", "--")
        self._draw_badge(painter, col1_x, start_y + y_step, b_w, b_h, "Compressore Inverter", comp_txt, comp_color)
        self._draw_badge(painter, col2_x, start_y + y_step, b_w, b_h, "Pressione Gas Caldo", f"{gas_press} bar", "#ec4899")

        # Row 2: T Gas Caldo & T Gas Liquido Refrigerante
        t_hot_gas = self.data.get("hot_gas_temp_c", "--")
        t_liq_gas = self.data.get("liquid_gas_temp_c", "--")
        self._draw_badge(painter, col1_x, start_y + y_step * 2, b_w, b_h, "T Gas Caldo", f"{t_hot_gas} °C", "#f87171")
        self._draw_badge(painter, col2_x, start_y + y_step * 2, b_w, b_h, "T Gas Liquido Frigo", f"{t_liq_gas} °C", "#38bdf8")

        # Row 3: T Gas Aspirazione & Circolatore Primario PdC
        t_suc_gas = self.data.get("suction_gas_temp_c", "--")
        prim_pump_rot = self.data.get("primary_pump_rotation_percent", "--")
        prim_pump_txt = f"{prim_pump_rot} %" if prim_pump_rot != "--" else "Attivo"
        self._draw_badge(painter, col1_x, start_y + y_step * 3, b_w, b_h, "T Gas Aspirazione", f"{t_suc_gas} °C", "#93c5fd")
        self._draw_badge(painter, col2_x, start_y + y_step * 3, b_w, b_h, "Circolatore Primario", prim_pump_txt, "#34d399")

        # Row 4: COP Riscaldamento & COP Totale Macchina
        cop_h = self.data.get("cop_heating", "--")
        cop_tot = self.data.get("cop_total", "--")
        self._draw_badge(painter, col1_x, start_y + y_step * 4, b_w, b_h, "COP Riscaldamento", f"{cop_h}", "#10b981")
        self._draw_badge(painter, col2_x, start_y + y_step * 4, b_w, b_h, "COP Totale Macchina", f"{cop_tot}", "#6ee7b7")

        # Row 5: Ore Compressore & Avvii Compressore
        comp_h = self.data.get("compressor_hours", "--")
        comp_starts = self.data.get("compressor_starts", "--")
        self._draw_badge(painter, col1_x, start_y + y_step * 5, b_w, b_h, "Ore Compressore", f"{comp_h} h", "#e2e8f0")
        self._draw_badge(painter, col2_x, start_y + y_step * 5, b_w, b_h, "Avvii Totali", f"{comp_starts}", "#e2e8f0")

        # Row 6: COP Sanitario ACS & Curva Climatica
        cop_dhw = self.data.get("cop_dhw", "--")
        slope = self.data.get("heating_curve_slope", 0.6)
        shift = self.data.get("heating_curve_shift", 0)
        self._draw_badge(painter, col1_x, start_y + y_step * 6, b_w, b_h, "COP ACS Sanitario", f"{cop_dhw}", "#facc15")
        self._draw_badge(painter, col2_x, start_y + y_step * 6, b_w, b_h, "Curva Climatica", f"Slp {slope} | Shf {shift}", "#60a5fa")

        # Bottom info strip in PdC box
        prog = self.data.get("active_program", "normale")
        mode = self.data.get("active_mode", "dhwAndHeating")
        norm_t = self.data.get("normal_setpoint_c", 12.0)
        bot_strip = QRectF(pdc_rect.left() + 10, pdc_rect.bottom() - 36, pdc_rect.width() - 20, 26)
        painter.setBrush(QBrush(QColor("#0f172a")))
        painter.setPen(QPen(QColor("#334155"), 1))
        painter.drawRoundedRect(bot_strip, 4, 4)
        painter.setPen(QColor("#94a3b8"))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(
            bot_strip,
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextSingleLine,
            f"Prog: {prog.upper()}  |  Modo: {mode}  |  T. Norm: {norm_t} °C",
        )

        # -------------------------------------------------------------
        # 4. ZONE B: PUFFER INERZIALE 200 LITRI
        # -------------------------------------------------------------
        self._draw_tank(painter, puffer_rect, "PUFFER 200 L\n(Disaccoppiatore)", "#161f30", "#f59e0b")

        puffer_temp = self.data.get("buffer_temp_c", "--")
        self._draw_badge(
            painter,
            puffer_rect.center().x() - 65,
            puffer_rect.center().y() - 30,
            130,
            56,
            "Sonda Accumulo 200L",
            f"{puffer_temp} °C",
            "#f59e0b",
        )

        # Technical notes at the bottom of the puffer
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#64748b"))
        puffer_note_rect = QRectF(puffer_rect.left() + 8, puffer_rect.bottom() - 48, puffer_rect.width() - 16, 38)
        painter.drawText(
            puffer_note_rect,
            Qt.AlignmentFlag.AlignCenter,
            "Disaccoppiatore Idraulico\nPrimario / Secondario",
        )

        # -------------------------------------------------------------
        # 5. CIRCOLATORE GRUNDFOS (RILANCIO SECONDARIO)
        # -------------------------------------------------------------
        pump_active = self.data.get("grundfos_pump_active", 0) == 1
        pump_color = QColor("#10b981") if pump_active else QColor("#334155")
        painter.setBrush(QBrush(pump_color))
        painter.setPen(QPen(QColor("#ffffff" if pump_active else "#64748b"), 2.5))
        painter.drawEllipse(QPointF(grundfos_x, pipe_supply_y), 22, 22)

        # "P" letter inside pump
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        painter.drawText(QRectF(grundfos_x - 22, pipe_supply_y - 22, 44, 44), Qt.AlignmentFlag.AlignCenter, "P")

        # Labels around pump
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.setPen(QColor("#94a3b8"))
        painter.drawText(
            QRectF(grundfos_x - 70, pipe_supply_y - 42, 140, 20),
            Qt.AlignmentFlag.AlignCenter,
            "Pompa Grundfos",
        )
        painter.setPen(QColor("#10b981" if pump_active else "#94a3b8"))
        painter.drawText(
            QRectF(grundfos_x - 70, pipe_supply_y + 26, 140, 20),
            Qt.AlignmentFlag.AlignCenter,
            "ACCESA (Radiante)" if pump_active else "SPENTA (Standby)",
        )

        # -------------------------------------------------------------
        # 6. ZONE C: ABITAZIONE BRATTO & TERMOSTATO BTICINO
        # -------------------------------------------------------------
        self._draw_block(painter, house_rect, "ABITAZIONE BRATTO (Circuito Secondario)", "#161f30", "#10b981")

        # Underfloor radiant coil symbol
        coil_y = house_rect.top() + 45
        self._draw_radiant_floor_symbol(painter, house_rect.left() + 18, coil_y, house_rect.width() - 36, 75)

        # BTicino Smarther Thermostat Panel
        in_temp = self.data.get("indoor_temp_c", "--")
        setpoint = self.data.get("setpoint_c", "--")
        bt_mode = self.data.get("mode", "--")
        hum = self.data.get("humidity_percent", "--")

        thermo_box = QRectF(house_rect.left() + 18, coil_y + 90, house_rect.width() - 36, 330)
        painter.setBrush(QBrush(QColor("#0f172a")))
        painter.setPen(QPen(QColor("#10b981"), 1.5))
        painter.drawRoundedRect(thermo_box, 8, 8)

        # Thermostat header
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        painter.setPen(QColor("#38bdf8"))
        painter.drawText(
            QRectF(thermo_box.left() + 14, thermo_box.top() + 12, thermo_box.width() - 28, 24),
            "TERMOSTATO BTICINO SMARTHER (Corridoio)",
        )

        # 2 Columns inside Thermostat card
        t_col1_x = thermo_box.left() + 14
        t_col2_x = thermo_box.left() + (thermo_box.width() / 2.0) + 4
        t_bw = (thermo_box.width() / 2.0) - 18
        t_bh = 52

        # Badges
        self._draw_badge(painter, t_col1_x, thermo_box.top() + 44, t_bw, t_bh, "Temperatura Ambiente", f"{in_temp} °C", "#10b981")
        self._draw_badge(painter, t_col2_x, thermo_box.top() + 44, t_bw, t_bh, "Umidità Relativa", f"{hum} %", "#60a5fa")

        self._draw_badge(painter, t_col1_x, thermo_box.top() + 106, t_bw, t_bh, "Setpoint Impostato", f"{setpoint} °C", "#eab308")
        self._draw_badge(painter, t_col2_x, thermo_box.top() + 106, t_bw, t_bh, "Modalità Operativa", f"{bt_mode}".capitalize(), "#c084fc")

        # Full-width Relay Status Card
        consenso_active = pump_active
        consenso_txt = "ATTIVO — Relè Chiuso (Chiamata Calore)" if consenso_active else "APERTO — Nessuna Chiamata (Massetto a Riposo)"
        consenso_color = "#10b981" if consenso_active else "#94a3b8"
        self._draw_badge(
            painter,
            t_col1_x,
            thermo_box.top() + 170,
            thermo_box.width() - 28,
            56,
            "Consenso Relè Grundfos (Rilancio Pavimento)",
            consenso_txt,
            consenso_color,
        )

        # System Energy Strategy Description
        strat_box = QRectF(t_col1_x, thermo_box.top() + 238, thermo_box.width() - 28, 76)
        painter.setBrush(QBrush(QColor("#1e293b")))
        painter.setPen(QPen(QColor("#334155"), 1))
        painter.drawRoundedRect(strat_box, 6, 6)

        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.setPen(QColor("#f59e0b"))
        painter.drawText(QRectF(strat_box.left() + 8, strat_box.top() + 6, strat_box.width() - 16, 16), "STRATEGIA TERMODINAMICA IMPIANTO:")

        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#cbd5e1"))
        strat_text = (
            "• Circuito Primario: la Vitocal da 11 kW scalda il Puffer 200 L.\n"
            "• Circuito Secondario: il termostato Smarther attiva la Grundfos per riversare\n"
            "  l'energia nel massetto radiante da 200 m², evitando pendolazioni della PdC."
        )
        painter.drawText(QRectF(strat_box.left() + 8, strat_box.top() + 24, strat_box.width() - 16, 48), strat_text)

    # -------------------------------------------------------------
    # DRAWING PRIMITIVES & HELPERS
    # -------------------------------------------------------------
    def _draw_block(self, painter: QPainter, rect: QRectF, title: str, bg_color: str, border_color: str):
        painter.setBrush(QBrush(QColor(bg_color)))
        painter.setPen(QPen(QColor(border_color), 2))
        painter.drawRoundedRect(rect, 10, 10)

        # Title banner
        painter.setPen(QColor(border_color))
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        painter.drawText(QRectF(rect.left() + 14, rect.top() + 10, rect.width() - 28, 24), Qt.AlignmentFlag.AlignLeft, title)

    def _draw_tank(self, painter: QPainter, rect: QRectF, title: str, bg_color: str, border_color: str):
        # Cylinder look with gradient
        grad = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        grad.setColorAt(0.0, QColor("#1e293b"))
        grad.setColorAt(0.5, QColor("#161f30"))
        grad.setColorAt(1.0, QColor("#0f172a"))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(border_color), 2.5))
        painter.drawRoundedRect(rect, 28, 28)

        painter.setPen(QColor(border_color))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.drawText(QRectF(rect.left(), rect.top() + 16, rect.width(), 35), Qt.AlignmentFlag.AlignCenter, title)

    def _draw_badge(self, painter: QPainter, x: float, y: float, w: float, h: float, label: str, val: str, color_hex: str):
        b_rect = QRectF(x, y, w, h)
        painter.setBrush(QBrush(QColor("#0f172a")))
        painter.setPen(QPen(QColor("#2d3748"), 1))
        painter.drawRoundedRect(b_rect, 6, 6)

        painter.setPen(QColor("#94a3b8"))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Normal))
        painter.drawText(QRectF(x + 8, y + 4, w - 16, 16), Qt.AlignmentFlag.AlignLeft, label)

        painter.setPen(QColor(color_hex))
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        painter.drawText(QRectF(x + 8, y + 20, w - 16, 24), Qt.AlignmentFlag.AlignLeft, str(val))

    def _draw_pipe_sensor_tag(
        self,
        painter: QPainter,
        center_x: float,
        tag_y: float,
        label: str,
        val: str,
        color_hex: str,
        pipe_y: float,
        is_above: bool,
    ):
        """Draws a floating sensor badge with zero overlap and an indicator tick to the pipe."""
        tag_w = 110
        tag_h = 36
        tag_rect = QRectF(center_x - (tag_w / 2.0), tag_y, tag_w, tag_h)

        # Pointer line connecting tag to the pipe
        painter.setPen(QPen(QColor(color_hex), 1.5, Qt.PenStyle.DashLine))
        if is_above:
            painter.drawLine(QPointF(center_x, tag_rect.bottom()), QPointF(center_x, pipe_y - 3))
        else:
            painter.drawLine(QPointF(center_x, pipe_y + 3), QPointF(center_x, tag_rect.top()))

        # Tag Box
        painter.setBrush(QBrush(QColor("#0b1320")))
        painter.setPen(QPen(QColor(color_hex), 1.5))
        painter.drawRoundedRect(tag_rect, 5, 5)

        # Text
        painter.setPen(QColor("#94a3b8"))
        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Normal))
        painter.drawText(QRectF(tag_rect.left(), tag_rect.top() + 3, tag_w, 14), Qt.AlignmentFlag.AlignCenter, label)

        painter.setPen(QColor(color_hex))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.drawText(QRectF(tag_rect.left(), tag_rect.top() + 16, tag_w, 18), Qt.AlignmentFlag.AlignCenter, val)

    def _draw_arrow(self, painter: QPainter, x: float, y: float, dx: int, dy: int, color_hex: str):
        painter.setBrush(QBrush(QColor(color_hex)))
        painter.setPen(Qt.PenStyle.NoPen)
        arrow = QPainterPath()
        if dx > 0:
            arrow.moveTo(x + 8, y)
            arrow.lineTo(x - 6, y - 5)
            arrow.lineTo(x - 6, y + 5)
        elif dx < 0:
            arrow.moveTo(x - 8, y)
            arrow.lineTo(x + 6, y - 5)
            arrow.lineTo(x + 6, y + 5)
        arrow.closeSubpath()
        painter.drawPath(arrow)

    def _draw_radiant_floor_symbol(self, painter: QPainter, x: float, y: float, w: float, h: float):
        painter.setBrush(QBrush(QColor("#0f172a")))
        painter.setPen(QPen(QColor("#334155"), 1, Qt.PenStyle.DashLine))
        painter.drawRoundedRect(QRectF(x, y, w, h), 6, 6)

        # Serpentine pipe path
        painter.setPen(QPen(QColor("#f59e0b"), 1.8))
        path = QPainterPath()
        y1 = y + 16
        y2 = y + 36
        y3 = y + 56
        path.moveTo(x + 15, y1)
        path.lineTo(x + w - 15, y1)
        path.lineTo(x + w - 15, y2)
        path.lineTo(x + 15, y2)
        path.lineTo(x + 15, y3)
        path.lineTo(x + w - 15, y3)
        painter.drawPath(path)

        painter.setPen(QColor("#e2e8f0"))
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.drawText(QRectF(x + 15, y + 4, w - 30, 20), Qt.AlignmentFlag.AlignRight, "Massetto Radiante (200 m²)")


class PlantSynopticWidget(QWidget):
    """Container widget with explanation banner, live SCADA canvas, and thermodynamic legend."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Header Banner
        header = QLabel(
            "<b>SINOTTICO IDRAULICO IMPIANTO & MAPPATURA SONDE IN TEMPO REALE</b><br>"
            "<span style='color: #94a3b8; font-size: 11px;'>"
            "Visualizzazione SCADA della disposizione fisica delle sonde, dei circuiti primario e secondario, "
            "del disaccoppiatore Puffer 200L e del circuito frigorifero completo Viessmann."
            "</span>"
        )
        header.setStyleSheet("color: #38bdf8; background: #161f30; padding: 8px 14px; border-radius: 6px;")
        layout.addWidget(header)

        # Scroll Area holding the Canvas
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: #0c1322; border: 1px solid #1e293b; border-radius: 8px;")

        self.canvas = SynopticCanvas()
        scroll.setWidget(self.canvas)
        layout.addWidget(scroll, stretch=1)

        # Thermodynamic Insight Footer
        footer = QLabel(
            "⚙️ <b>Logica Idraulica Impianto di Bratto:</b> Il circuito primario alimenta esclusivamente il Puffer da 200L. "
            "Il rilancio verso il pavimento radiante è comandato dal termostato BTicino tramite la pompa Grundfos. "
            "Quando la Grundfos è spenta, la PdC satura rapidamente il solo puffer lavorando a cicli brevi."
        )
        footer.setStyleSheet("color: #cbd5e1; font-size: 11px; background: #161f30; padding: 6px 12px; border-radius: 6px;")
        layout.addWidget(footer)

    def update_telemetry(self, telemetry: dict[str, Any]):
        """Refreshes the canvas with fresh telemetry values."""
        self.canvas.update_telemetry(telemetry)
