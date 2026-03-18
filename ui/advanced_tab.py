# SPDX-License-Identifier: GPL-3.0-or-later
"""
linuwu-sense-gui — advanced_tab.py
Advanced hardware settings:
  • USB charging threshold (while powered off)
  • Boot animation & sound toggle
  • LCD override (reduces latency / ghosting)

All sections are hidden via feature detection if the sysfs node
doesn't exist on the current hardware.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QGroupBox, QScrollArea, QFrame, QCheckBox,
    QApplication, QStyle,
)
from PyQt6.QtCore import Qt

from controller.sysfs_controller import SysfsController

_USB_OPTIONS = [
    ("Disabled",  0),
    ("10 %",     10),
    ("20 %",     20),
    ("30 %",     30),
]


class AdvancedTab(QWidget):
    def __init__(self, controller: SysfsController) -> None:
        super().__init__()
        self._ctrl = controller
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
        layout = QVBoxLayout(inner)
        layout.setSpacing(sp * 2)
        layout.setContentsMargins(m, m, m, m)

        # ── USB charging ──────────────────────────────────────────────────
        self._usb_grp = QGroupBox("USB Charging While Powered Off")
        ul = QVBoxLayout(self._usb_grp)
        ul.setSpacing(sp)

        row = QHBoxLayout()
        row.addWidget(QLabel("Charging Level:"))
        self._usb_combo = QComboBox()
        for label, _ in _USB_OPTIONS:
            self._usb_combo.addItem(label)
        self._usb_combo.setMinimumWidth(110)
        self._usb_combo.currentIndexChanged.connect(self._on_usb)
        row.addWidget(self._usb_combo)
        row.addStretch()
        ul.addLayout(row)

        hint = QLabel(
            "Controls power output on the USB port when the system is powered off.\n"
            "Set to Disabled when USB charging is not required."
        )
        hint.setWordWrap(True)
        hint.setProperty("secondary", "true")
        ul.addWidget(hint)
        layout.addWidget(self._usb_grp)

        # ── Boot animation & sound ────────────────────────────────────────
        self._boot_grp = QGroupBox("Startup Experience")
        bl = QVBoxLayout(self._boot_grp)
        self._boot_cb = QCheckBox("Show startup animation and play audio on power-on")
        self._boot_cb.stateChanged.connect(self._on_boot)
        bl.addWidget(self._boot_cb)
        boot_hint = QLabel(
            "Controls the custom Acer startup animation and sound that plays "
            "when the laptop powers on."
        )
        boot_hint.setWordWrap(True)
        boot_hint.setProperty("secondary", "true")
        bl.addWidget(boot_hint)
        layout.addWidget(self._boot_grp)

        # ── LCD override ──────────────────────────────────────────────────
        self._lcd_grp = QGroupBox("Display Overdrive")
        ll = QVBoxLayout(self._lcd_grp)
        self._lcd_cb = QCheckBox("Enable display overdrive to reduce pixel response time")
        self._lcd_cb.stateChanged.connect(self._on_lcd)
        ll.addWidget(self._lcd_cb)
        lcd_hint = QLabel(
            "Overrides the LCD timing to reduce input lag and screen ghosting. "
            "Useful for gaming. May increase power consumption slightly."
        )
        lcd_hint.setWordWrap(True)
        lcd_hint.setProperty("secondary", "true")
        ll.addWidget(lcd_hint)
        layout.addWidget(self._lcd_grp)

        layout.addStretch()
        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _load(self) -> None:
        # USB charging
        usb = self._ctrl.get_usb_charging()
        self._usb_combo.blockSignals(True)
        idx = 0
        if usb is not None:
            for i, (_, val) in enumerate(_USB_OPTIONS):
                if val == usb:
                    idx = i
                    break
        self._usb_combo.setCurrentIndex(idx)
        self._usb_combo.blockSignals(False)

        # Boot animation — hide group if sysfs node absent
        boot = self._ctrl.get_boot_animation_sound()
        if boot is None:
            self._boot_grp.setVisible(False)
        else:
            self._boot_cb.blockSignals(True)
            self._boot_cb.setChecked(boot)
            self._boot_cb.blockSignals(False)

        # LCD override — hide group if sysfs node absent
        lcd = self._ctrl.get_lcd_override()
        if lcd is None:
            self._lcd_grp.setVisible(False)
        else:
            self._lcd_cb.blockSignals(True)
            self._lcd_cb.setChecked(lcd)
            self._lcd_cb.blockSignals(False)

    def _on_usb(self, index: int) -> None:
        _, val = _USB_OPTIONS[index]
        self._ctrl.set_usb_charging(val)

    def _on_boot(self, state: int) -> None:
        self._ctrl.set_boot_animation_sound(
            state == Qt.CheckState.Checked.value)

    def _on_lcd(self, state: int) -> None:
        self._ctrl.set_lcd_override(
            state == Qt.CheckState.Checked.value)
