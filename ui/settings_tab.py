# SPDX-License-Identifier: GPL-3.0-or-later
"""
linuwu-sense-gui — settings_tab.py
Application preferences: sensor poll interval, temperature unit,
thermal notification thresholds.

Settings are persisted via QSettings and read by other tabs on startup.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QSpinBox, QGroupBox, QScrollArea, QFrame, QPushButton,
    QApplication, QStyle, QMessageBox,
)
from PyQt6.QtCore import Qt, QSettings


def get_settings() -> QSettings:
    return QSettings("linuwu-sense", "linuwu-sense-gui")


def poll_interval_ms() -> int:
    return get_settings().value("settings/poll_interval_ms", 2000, type=int)


def temp_unit() -> str:
    return get_settings().value("settings/temp_unit", "°C", type=str)


def warn_threshold() -> int:
    return get_settings().value("settings/warn_threshold", 75, type=int)


def critical_threshold() -> int:
    return get_settings().value("settings/critical_threshold", 90, type=int)


def celsius_to_unit(c: float) -> float:
    return c if temp_unit() == "°C" else c * 9 / 5 + 32


class SettingsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
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

        # ── Sensor polling ────────────────────────────────────────────────
        poll_grp = QGroupBox("Sensor Polling")
        pl = QVBoxLayout(poll_grp)
        pl.setSpacing(sp)

        row = QHBoxLayout()
        row.addWidget(QLabel("Update interval:"))
        self._poll_combo = QComboBox()
        for label, ms in [
            ("1 second",   1000),
            ("2 seconds",  2000),
            ("3 seconds",  3000),
            ("5 seconds",  5000),
            ("10 seconds", 10000),
        ]:
            self._poll_combo.addItem(label, ms)
        self._poll_combo.setMinimumWidth(130)
        row.addWidget(self._poll_combo)
        row.addStretch()
        pl.addLayout(row)

        hint = QLabel(
            "How often the app reads temperature and fan sensors.\n"
            "Lower values give more responsive graphs but use slightly more CPU."
        )
        hint.setWordWrap(True)
        hint.setProperty("secondary", "true")
        pl.addWidget(hint)
        layout.addWidget(poll_grp)

        # ── Temperature unit ──────────────────────────────────────────────
        unit_grp = QGroupBox("Temperature Unit")
        ul = QHBoxLayout(unit_grp)
        ul.addWidget(QLabel("Display temperatures in:"))
        self._unit_combo = QComboBox()
        self._unit_combo.addItems(["°C  (Celsius)", "°F  (Fahrenheit)"])
        self._unit_combo.setMinimumWidth(160)
        ul.addWidget(self._unit_combo)
        ul.addStretch()
        layout.addWidget(unit_grp)

        # ── Notification thresholds ───────────────────────────────────────
        notif_grp = QGroupBox("Thermal Notifications")
        nl = QVBoxLayout(notif_grp)
        nl.setSpacing(sp)

        warn_row = QHBoxLayout()
        warn_row.addWidget(QLabel("Warning threshold:"))
        self._warn_spin = QSpinBox()
        self._warn_spin.setRange(50, 95)
        self._warn_spin.setSuffix(" °C")
        self._warn_spin.setMinimumWidth(90)
        warn_row.addWidget(self._warn_spin)
        warn_row.addStretch()
        nl.addLayout(warn_row)

        crit_row = QHBoxLayout()
        crit_row.addWidget(QLabel("Critical threshold:"))
        self._crit_spin = QSpinBox()
        self._crit_spin.setRange(55, 105)
        self._crit_spin.setSuffix(" °C")
        self._crit_spin.setMinimumWidth(90)
        crit_row.addWidget(self._crit_spin)
        crit_row.addStretch()
        nl.addLayout(crit_row)

        notif_hint = QLabel(
            "Desktop notifications are sent when CPU or GPU temperature\n"
            "crosses these thresholds. Set higher to reduce notification frequency."
        )
        notif_hint.setWordWrap(True)
        notif_hint.setProperty("secondary", "true")
        nl.addWidget(notif_hint)
        layout.addWidget(notif_grp)

        # ── Apply ─────────────────────────────────────────────────────────
        apply_btn = QPushButton("Apply Settings")
        apply_btn.setProperty("accent", "true")
        apply_btn.setMinimumHeight(34)
        apply_btn.clicked.connect(self._apply)
        layout.addWidget(apply_btn)

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self._reset)
        layout.addWidget(reset_btn)

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
        s = get_settings()
        # Poll interval
        ms = s.value("settings/poll_interval_ms", 2000, type=int)
        for i in range(self._poll_combo.count()):
            if self._poll_combo.itemData(i) == ms:
                self._poll_combo.setCurrentIndex(i)
                break
        # Temp unit
        unit = s.value("settings/temp_unit", "°C", type=str)
        self._unit_combo.setCurrentIndex(0 if unit == "°C" else 1)
        # Thresholds
        self._warn_spin.setValue(s.value("settings/warn_threshold", 75, type=int))
        self._crit_spin.setValue(s.value("settings/critical_threshold", 90, type=int))

    def _apply(self) -> None:
        if self._warn_spin.value() >= self._crit_spin.value():
            QMessageBox.warning(self, "Invalid Thresholds",
                "Warning threshold must be lower than critical threshold.")
            return
        s = get_settings()
        s.setValue("settings/poll_interval_ms",
                   self._poll_combo.currentData())
        s.setValue("settings/temp_unit",
                   "°C" if self._unit_combo.currentIndex() == 0 else "°F")
        s.setValue("settings/warn_threshold", self._warn_spin.value())
        s.setValue("settings/critical_threshold", self._crit_spin.value())
        QMessageBox.information(self, "Settings",
            "Settings saved. Restart the app for poll interval changes to take effect.")

    def _reset(self) -> None:
        s = get_settings()
        s.remove("settings/poll_interval_ms")
        s.remove("settings/temp_unit")
        s.remove("settings/warn_threshold")
        s.remove("settings/critical_threshold")
        self._load()
