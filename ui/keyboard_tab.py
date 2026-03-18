# SPDX-License-Identifier: GPL-3.0-or-later
"""
linuwu-sense-gui — keyboard_tab.py
Four-zone RGB keyboard control with live preview.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QSpinBox, QGridLayout, QComboBox, QSlider,
    QScrollArea, QFrame, QApplication, QStyle, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QFont

from controller.sysfs_controller import SysfsController
from config.constants import (
    KB_EFFECTS, KB_DIRECTIONS, KB_SPEED_MIN, KB_SPEED_MAX,
    DEFAULT_ZONE_COLORS, DEFAULT_KB_BRIGHTNESS,
)


# ── Keyboard preview widget ───────────────────────────────────────────────────

class _KeyboardPreview(QWidget):
    """
    Simplified top-view of the four RGB zones, roughly matching
    the Nitro keyboard layout: Z1 = left, Z2 = centre-left,
    Z3 = centre-right, Z4 = right (numpad area).
    Clicking a zone opens the colour picker for that zone.
    """
    zoneClicked = pyqtSignal(str)   # emits "zone1".."zone4"

    _ZONES = [
        ("zone1", "Left"),
        ("zone2", "Center L"),
        ("zone3", "Center R"),
        ("zone4", "Right"),
    ]
    # Proportional widths for the four zones (roughly matching a full keyboard)
    _WIDTHS = [0.30, 0.28, 0.22, 0.20]

    def __init__(self) -> None:
        super().__init__()
        self._colors: dict[str, str] = dict(DEFAULT_ZONE_COLORS)
        self._hovered: str | None = None
        self.setMinimumHeight(52)
        self.setMaximumHeight(72)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_colors(self, colors: dict[str, str]) -> None:
        self._colors = dict(colors)
        self.update()

    def _zone_rects(self) -> list[tuple[str, QRectF]]:
        w, h = self.width(), self.height()
        pad, gap = 4, 3
        x = pad
        rects = []
        inner_w = w - pad * 2
        for (zone, _), frac in zip(self._ZONES, self._WIDTHS):
            zw = int(inner_w * frac) - gap
            rects.append((zone, QRectF(x, pad, zw, h - pad * 2)))
            x += zw + gap
        return rects

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()

        for (zone, label), (_, rect) in zip(self._ZONES, self._zone_rects()):
            hex_c = self._colors.get(zone, "888888")
            fill  = QColor(f"#{hex_c}")

            # Slightly lighten hovered zone
            if zone == self._hovered:
                fill = fill.lighter(130)

            # Card background tinted with zone colour
            p.setBrush(fill)
            border_col = pal.color(pal.ColorRole.Window).lighter(160) \
                         if zone == self._hovered \
                         else pal.color(pal.ColorRole.Mid)
            p.setPen(QPen(border_col, 1.5))
            p.drawRoundedRect(rect, 6, 6)

            # Label text — white or black depending on luminance
            lum = 0.299 * fill.redF() + 0.587 * fill.greenF() + 0.114 * fill.blueF()
            text_col = QColor("#ffffff") if lum < 0.55 else QColor("#000000")
            f = QFont(); f.setPointSize(7); f.setBold(True)
            p.setFont(f); p.setPen(text_col)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

        p.end()

    def mouseMoveEvent(self, event) -> None:
        for zone, rect in self._zone_rects():
            if rect.contains(event.position()):
                if self._hovered != zone:
                    self._hovered = zone
                    self.update()
                return
        if self._hovered:
            self._hovered = None
            self.update()

    def leaveEvent(self, _) -> None:
        self._hovered = None
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            for zone, rect in self._zone_rects():
                if rect.contains(event.position()):
                    self.zoneClicked.emit(zone)
                    return


# ── Zone swatch button ────────────────────────────────────────────────────────

class ZoneButton(QPushButton):
    """Colour swatch that opens a colour picker on click."""
    colorChanged = pyqtSignal()

    def __init__(self, zone: str, hex_color: str = "FF0000") -> None:
        super().__init__()
        self.zone      = zone
        self.hex_color = hex_color.upper().zfill(6)
        self.setFixedSize(72, 48)
        self._apply()
        self.clicked.connect(self._pick)

    def _apply(self) -> None:
        self.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: #{self.hex_color};"
            f"  border: 2px solid palette(mid);"
            f"  border-radius: 6px;"
            f"}}"
            f"QPushButton:hover {{ border-color: palette(window-text); }}"
        )

    def _pick(self) -> None:
        from PyQt6.QtWidgets import QColorDialog
        colour = QColorDialog.getColor(
            QColor(f"#{self.hex_color}"), self, f"Zone colour — {self.zone}")
        if colour.isValid():
            self.hex_color = colour.name()[1:].upper()
            self._apply()
            self.colorChanged.emit()

    def get_hex(self) -> str:
        return self.hex_color


# ── Main tab ──────────────────────────────────────────────────────────────────

class KeyboardTab(QWidget):
    def __init__(self, controller: SysfsController) -> None:
        super().__init__()
        self._ctrl = controller
        # Debounce timer — batches rapid colour changes into one sysfs write
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(400)   # ms after last change
        self._apply_timer.timeout.connect(self._flush_zone_colors)
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        sp = QApplication.style().pixelMetric(QStyle.PixelMetric.PM_LayoutVerticalSpacing)
        m  = QApplication.style().pixelMetric(QStyle.PixelMetric.PM_LayoutLeftMargin)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner  = QWidget()
        inner.setMaximumWidth(1600)
        layout = QVBoxLayout(inner)
        layout.setSpacing(sp * 2)
        layout.setContentsMargins(m, m, m, m)

        # ── Live preview ──────────────────────────────────────────────────
        preview_grp = QGroupBox("Keyboard — Click a Zone to Customize")
        pv = QVBoxLayout(preview_grp)
        self._preview = _KeyboardPreview()
        self._preview.zoneClicked.connect(self._pick_zone)
        pv.addWidget(self._preview)
        layout.addWidget(preview_grp)

        # ── Zone swatches ─────────────────────────────────────────────────
        zones_grp = QGroupBox("Zone Configuration")
        zg = QHBoxLayout(zones_grp)
        zg.setSpacing(sp * 2)
        self._zone_btns: dict[str, ZoneButton] = {}
        for i, zone in enumerate(["zone1", "zone2", "zone3", "zone4"]):
            col_layout = QVBoxLayout()
            zone_names = ["Left", "Center L", "Center R", "Right"]
            lbl = QLabel(zone_names[i])
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setProperty("secondary", "true")
            col_layout.addWidget(lbl)
            btn = ZoneButton(zone, DEFAULT_ZONE_COLORS[zone])
            btn.colorChanged.connect(self._on_zone_changed)
            self._zone_btns[zone] = btn
            col_layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)
            zg.addLayout(col_layout)
        layout.addWidget(zones_grp)

        # ── Brightness ────────────────────────────────────────────────────
        bl = QHBoxLayout()
        bl.addWidget(QLabel("Brightness:"))
        self._brightness = QSlider(Qt.Orientation.Horizontal)
        self._brightness.setRange(0, 100)
        self._brightness.setValue(DEFAULT_KB_BRIGHTNESS)
        self._brightness.valueChanged.connect(self._on_brightness)
        bl.addWidget(self._brightness)
        self._brightness_lbl = QLabel(f"{DEFAULT_KB_BRIGHTNESS}%")
        bl.addWidget(self._brightness_lbl)
        layout.addLayout(bl)

        # ── Effects ───────────────────────────────────────────────────────
        fx_grp = QGroupBox("Lighting Effects")
        fxl = QGridLayout(fx_grp)

        fxl.addWidget(QLabel("Pattern:"), 0, 0)
        self._effect_combo = QComboBox()
        self._effect_combo.addItems(KB_EFFECTS.keys())
        fxl.addWidget(self._effect_combo, 0, 1)

        fxl.addWidget(QLabel("Direction:"), 1, 0)
        self._dir_combo = QComboBox()
        self._dir_combo.addItems(KB_DIRECTIONS.keys())
        fxl.addWidget(self._dir_combo, 1, 1)

        fxl.addWidget(QLabel("Speed:"), 2, 0)
        self._speed = QSpinBox()
        self._speed.setRange(KB_SPEED_MIN, KB_SPEED_MAX)
        self._speed.setValue(5)
        fxl.addWidget(self._speed, 2, 1)

        self._apply_fx_btn = QPushButton("Apply Lighting")
        self._apply_fx_btn.clicked.connect(self._apply_effect)
        fxl.addWidget(self._apply_fx_btn, 3, 0, 1, 2)
        layout.addWidget(fx_grp)

        # ── Colour presets ────────────────────────────────────────────────
        presets_grp = QGroupBox("Color Presets")
        pl = QHBoxLayout(presets_grp)
        for name, colors in [
            ("Rainbow",   {"zone1": "FF0000", "zone2": "FF7F00",
                           "zone3": "FFFF00", "zone4": "00FF00"}),
            ("Ocean",     {"zone1": "0000FF", "zone2": "0055FF",
                           "zone3": "00AAFF", "zone4": "00FFFF"}),
            ("Nitro Red", {"zone1": "FF0000", "zone2": "CC0000",
                           "zone3": "990000", "zone4": "660000"}),
            ("White",     {"zone1": "FFFFFF", "zone2": "FFFFFF",
                           "zone3": "FFFFFF", "zone4": "FFFFFF"}),
        ]:
            btn = QPushButton(name)
            btn.clicked.connect(lambda _, c=colors: self._apply_preset(c))
            pl.addWidget(btn)
        layout.addWidget(presets_grp)

        layout.addStretch()
        outer_w = QWidget()
        outer_l = QHBoxLayout(outer_w)
        outer_l.setContentsMargins(0, 0, 0, 0)
        outer_l.addStretch()
        outer_l.addWidget(inner, 1)
        outer_l.addStretch()
        scroll.setWidget(outer_w)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _load(self) -> None:
        colors = self._ctrl.get_per_zone_colors()
        for zone, btn in self._zone_btns.items():
            btn.hex_color = colors.get(zone, "FFFFFF")
            btn._apply()
        self._preview.set_colors(
            {z: b.hex_color for z, b in self._zone_btns.items()})

    def _pick_zone(self, zone: str) -> None:
        """Called when the preview is clicked — delegates to the ZoneButton."""
        self._zone_btns[zone]._pick()

    def _on_zone_changed(self) -> None:
        """Update preview immediately, debounce the sysfs write."""
        colors = {z: b.get_hex() for z, b in self._zone_btns.items()}
        self._preview.set_colors(colors)
        self._apply_timer.start()   # restarts on every change; fires once idle

    def _flush_zone_colors(self) -> None:
        """Write current colours to hardware — called after debounce settles."""
        colors = {z: b.get_hex() for z, b in self._zone_btns.items()}
        self._ctrl.set_per_zone_colors(colors, self._brightness.value())

    def _on_brightness(self, val: int) -> None:
        self._brightness_lbl.setText(f"{val}%")
        self._apply_timer.start()   # debounced

    def _apply_effect(self) -> None:
        mode      = KB_EFFECTS[self._effect_combo.currentText()]
        direction = KB_DIRECTIONS[self._dir_combo.currentText()]
        hex_c     = self._zone_btns["zone1"].get_hex()
        self._ctrl.set_four_zone_mode(
            mode,
            speed=self._speed.value(),
            brightness=self._brightness.value(),
            r=int(hex_c[0:2], 16),
            g=int(hex_c[2:4], 16),
            b=int(hex_c[4:6], 16),
            direction=direction,
        )
        self._apply_fx_btn.setText("✓  Applied")
        QApplication.instance().processEvents()
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2000, lambda: self._apply_fx_btn.setText("Apply Lighting"))

    def _apply_preset(self, colors: dict) -> None:
        for zone, hex_c in colors.items():
            if zone in self._zone_btns:
                self._zone_btns[zone].hex_color = hex_c
                self._zone_btns[zone]._apply()
        self._on_zone_changed()
