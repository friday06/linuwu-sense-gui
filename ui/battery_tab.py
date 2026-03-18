# SPDX-License-Identifier: GPL-3.0-or-later
"""
linuwu-sense-gui — battery_tab.py
Battery limiter, backlight timeout, calibration, and Gaming/Office presets.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QPushButton, QGroupBox, QMessageBox, QScrollArea, QFrame,
    QApplication, QStyle,
)
from PyQt6.QtCore import Qt, QTimer

from controller.sysfs_controller import SysfsController


class BatteryTab(QWidget):
    def __init__(self, controller: SysfsController) -> None:
        super().__init__()
        self._ctrl = controller
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_toast)
        self._build_ui()
        self._load()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner  = QWidget()
        layout = QVBoxLayout(inner)
        sp = QApplication.style().pixelMetric(QStyle.PixelMetric.PM_LayoutVerticalSpacing)
        m  = QApplication.style().pixelMetric(QStyle.PixelMetric.PM_LayoutLeftMargin)
        layout.setSpacing(sp * 2)
        layout.setContentsMargins(m, m, m, m)

        # ── Battery limiter ───────────────────────────────────────────────
        limiter_grp = QGroupBox("Battery Protection")
        ll = QVBoxLayout(limiter_grp)
        self._limiter_cb = QCheckBox("Limit maximum charge to 80%")
        self._limiter_cb.stateChanged.connect(self._on_limiter)
        ll.addWidget(self._limiter_cb)
        info = QLabel(
            "When enabled, charging stops at 80% to reduce long-term wear.\n"
            "Recommended when the laptop is mostly used on AC power."
        )
        info.setWordWrap(True)
        info.setProperty("secondary", "true")
        ll.addWidget(info)
        layout.addWidget(limiter_grp)

        # ── Keyboard backlight timeout ────────────────────────────────────
        bl_grp = QGroupBox("Keyboard Backlight")
        bl = QVBoxLayout(bl_grp)
        self._backlight_cb = QCheckBox("Turn off keyboard backlight after 30 seconds of inactivity")
        self._backlight_cb.stateChanged.connect(self._on_backlight)
        bl.addWidget(self._backlight_cb)
        layout.addWidget(bl_grp)

        # ── Battery calibration ───────────────────────────────────────────
        cal_grp = QGroupBox("Battery Recalibration")
        cl = QVBoxLayout(cal_grp)
        cal_info = QLabel(
            "Performs a complete discharge and recharge cycle to restore battery gauge accuracy.\n"
            "Keep the AC adapter connected throughout. This process may take several hours."
        )
        cal_info.setWordWrap(True)
        cal_info.setProperty("secondary", "true")
        cl.addWidget(cal_info)
        cal_btn = QPushButton("Start Recalibration")
        cal_btn.setProperty("danger", "true")
        cal_btn.clicked.connect(self._start_calibration)
        cl.addWidget(cal_btn)
        layout.addWidget(cal_grp)

        # ── Quick presets ─────────────────────────────────────────────────
        preset_grp = QGroupBox("Performance Presets")
        pl = QVBoxLayout(preset_grp)
        pl.setSpacing(sp)

        info_lbl = QLabel(
            "Apply a preset configuration for performance and power management."
        )
        info_lbl.setProperty("secondary", "true")
        pl.addWidget(info_lbl)
        pl.addWidget(_hline())

        for btn_label, desc, slot in [
            ("Gaming",
             "High-performance mode  ·  Unrestricted CPU  ·  Backlight enabled",
             self._preset_gaming),
            ("Office",
             "Power-saving mode  ·  CPU limited to 2.5 GHz  ·  Battery protection on",
             self._preset_office),
        ]:
            row = QHBoxLayout()
            btn = QPushButton(btn_label)
            btn.setMinimumHeight(32)
            btn.setMinimumWidth(130)
            if "Gaming" in btn_label:
                btn.setProperty("accent", "true")
            btn.clicked.connect(slot)
            row.addWidget(btn)
            d = QLabel(desc)
            d.setProperty("secondary", "true")
            d.setWordWrap(True)
            row.addWidget(d, 1)
            pl.addLayout(row)

        self._toast = QLabel("")
        self._toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._toast.setProperty("toast", "true")
        self._toast.hide()
        pl.addWidget(self._toast)
        layout.addWidget(preset_grp)

        layout.addStretch()
        scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Load ──────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        for cb, getter in (
            (self._limiter_cb,   self._ctrl.get_battery_limiter),
            (self._backlight_cb, self._ctrl.get_backlight_timeout),
        ):
            val = getter()
            if val is not None:
                cb.blockSignals(True)
                cb.setChecked(val)
                cb.blockSignals(False)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_limiter(self, state: int) -> None:
        self._ctrl.set_battery_limiter(state == Qt.CheckState.Checked.value)

    def _on_backlight(self, state: int) -> None:
        self._ctrl.set_backlight_timeout(state == Qt.CheckState.Checked.value)

    def _start_calibration(self) -> None:
        if QMessageBox.question(
            self, "Confirm Recalibration",
            "This will perform a full battery discharge and recharge cycle.\n"
            "Keep the AC adapter connected at all times.\n\nProceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            if self._ctrl.start_battery_calibration():
                QMessageBox.information(self, "Calibration", "Recalibration started. Keep the AC adapter connected.")

    def _preset_gaming(self) -> None:
        self._backlight_cb.setChecked(True)
        ok_cpu  = self._ctrl.set_cpu_freq_limit(0)
        ok_prof = self._ctrl.set_thermal_profile("balanced-performance")
        if ok_cpu and ok_prof:
            self._toast_show("Gaming preset applied successfully")
        else:
            self._toast_show("Preset applied — CPU frequency limit requires re-login to take full effect")

    def _preset_office(self) -> None:
        self._limiter_cb.setChecked(True)
        self._backlight_cb.setChecked(True)
        ok_cpu  = self._ctrl.set_cpu_freq_limit(2500)
        ok_prof = self._ctrl.set_thermal_profile("low-power")
        if ok_cpu and ok_prof:
            self._toast_show("Office preset applied — CPU limited to 2.5 GHz")
        else:
            self._toast_show("Preset applied — CPU frequency limit requires re-login to take full effect")

    # ── Toast helper ──────────────────────────────────────────────────────────

    def _toast_show(self, msg: str, ms: int = 3500) -> None:
        self._toast.setText(msg)
        self._toast.show()
        self._toast_timer.start(ms)

    def _hide_toast(self) -> None:
        self._toast.hide()
        self._toast.setText("")


def _hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    return f
