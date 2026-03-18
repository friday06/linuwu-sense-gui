# SPDX-License-Identifier: GPL-3.0-or-later
"""
linuwu-sense-gui — fan_tab.py
Dedicated Fan Control tab.

Features:
  • Auto / Manual mode toggle
  • CPU and GPU fan speed sliders (hidden in auto mode)
  • Live fan speed gauges (reuses the _Gauge / _Graph from thermal_fan_tab)
  • Fan speed history graph
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QPushButton, QGroupBox, QFrame, QScrollArea,
    QApplication, QStyle, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer

from controller.sysfs_controller import SysfsController


class FanTab(QWidget):
    def __init__(self, controller: SysfsController) -> None:
        super().__init__()
        self._ctrl = controller
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._build_ui()
        self._load()

    # ── UI ────────────────────────────────────────────────────────────────────

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

        outer_widget = QWidget()
        outer_layout = QHBoxLayout(outer_widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addStretch()
        outer_layout.addWidget(inner, 1)
        outer_layout.addStretch()

        # ── Mode group ────────────────────────────────────────────────────
        mode_grp = QGroupBox("Fan Control Mode")
        mg = QVBoxLayout(mode_grp)
        mg.setSpacing(sp)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Fan Mode:"))

        from ui.thermal_fan_tab import _FanModeToggle
        self._fan_toggle = _FanModeToggle()
        self._fan_toggle.connect(self._on_mode_changed)
        mode_row.addWidget(self._fan_toggle)

        self._mode_hint = QLabel("Fan speeds are managed automatically by the system")
        self._mode_hint.setProperty("secondary", "true")
        mode_row.addWidget(self._mode_hint)
        mode_row.addStretch()
        mg.addLayout(mode_row)
        layout.addWidget(mode_grp)

        # ── Live gauges — 2-column equal grid, square aspect ratio ──────
        from ui.thermal_fan_tab import _Gauge, _Graph, _TRACE_FAN1, _TRACE_FAN2
        from PyQt6.QtWidgets import QGridLayout

        gauge_grp = QGroupBox("Current Fan Speed")
        gauge_grp.setMaximumHeight(320)
        gg_layout = QGridLayout(gauge_grp)
        gg_layout.setSpacing(sp)
        gg_layout.setColumnStretch(0, 1)
        gg_layout.setColumnStretch(1, 1)
        gg_layout.setRowMinimumHeight(0, 180)

        self._g_cpu_f = _Gauge("CPU Fan", "%", 100.0)
        self._g_gpu_f = _Gauge("GPU Fan", "%", 100.0)
        self._g_cpu_f.setHwfDisabled(True)
        self._g_gpu_f.setHwfDisabled(True)
        gg_layout.addWidget(self._g_cpu_f, 0, 0)
        gg_layout.addWidget(self._g_gpu_f, 0, 1)
        layout.addWidget(gauge_grp)

        # ── History graph ─────────────────────────────────────────────────
        self._fan_graph = _Graph(
            [("CPU Fan %", _TRACE_FAN1), ("GPU Fan %", _TRACE_FAN2)],
            "%", 100.0, height=120)
        layout.addWidget(self._fan_graph)

        # ── Manual sliders ────────────────────────────────────────────────
        self._sliders_grp = QGroupBox("Manual Speed Control")
        sg = QVBoxLayout(self._sliders_grp)
        sg.setSpacing(sp)

        info = QLabel(
            "Set fan speeds manually. Values apply immediately on clicking Apply.\n"
            "Switch back to Auto to return control to the firmware."
        )
        info.setWordWrap(True)
        info.setProperty("secondary", "true")
        sg.addWidget(info)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sg.addWidget(sep)

        cpu_row = QHBoxLayout()
        cpu_row.addWidget(QLabel("CPU Fan Speed:"))
        self._cpu_slider = QSlider(Qt.Orientation.Horizontal)
        self._cpu_slider.setRange(0, 100)
        self._cpu_pct = QLabel("0%")
        self._cpu_pct.setMinimumWidth(44)
        self._cpu_pct.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._cpu_slider.valueChanged.connect(
            lambda v: self._cpu_pct.setText(f"{v}%"))
        cpu_row.addWidget(self._cpu_slider, 1)
        cpu_row.addWidget(self._cpu_pct)
        sg.addLayout(cpu_row)

        gpu_row = QHBoxLayout()
        gpu_row.addWidget(QLabel("GPU Fan Speed:"))
        self._gpu_slider = QSlider(Qt.Orientation.Horizontal)
        self._gpu_slider.setRange(0, 100)
        self._gpu_pct = QLabel("0%")
        self._gpu_pct.setMinimumWidth(44)
        self._gpu_pct.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._gpu_slider.valueChanged.connect(
            lambda v: self._gpu_pct.setText(f"{v}%"))
        gpu_row.addWidget(self._gpu_slider, 1)
        gpu_row.addWidget(self._gpu_pct)
        sg.addLayout(gpu_row)

        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setProperty("accent", "true")
        self._apply_btn.setMinimumHeight(34)
        self._apply_btn.clicked.connect(self._apply_fan)
        sg.addWidget(self._apply_btn)
        layout.addWidget(self._sliders_grp)

        layout.addStretch(1)
        scroll.setWidget(outer_widget)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    # ── Load ──────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        cpu_hw, gpu_hw = self._ctrl.get_fan_speed()
        if cpu_hw and gpu_hw and (cpu_hw > 0 or gpu_hw > 0):
            self._fan_toggle.set_auto(False)
            self._sliders_grp.setVisible(True)
            self._cpu_slider.setValue(cpu_hw)
            self._gpu_slider.setValue(gpu_hw)
            self._cpu_pct.setText(f"{cpu_hw}%")
            self._gpu_pct.setText(f"{gpu_hw}%")
        else:
            self._fan_toggle.set_auto(True)
            self._sliders_grp.setVisible(False)
        self._update_hint()

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_mode_changed(self, is_auto: bool) -> None:
        if is_auto:
            self._sliders_grp.setVisible(False)
            self._ctrl.set_fan_speed(0, 0)
        else:
            cpu_hw, gpu_hw = self._ctrl.get_fan_speed()
            cpu_val = cpu_hw if (cpu_hw and cpu_hw > 0) else 50
            gpu_val = gpu_hw if (gpu_hw and gpu_hw > 0) else 50
            self._sliders_grp.setVisible(True)
            self._cpu_slider.setValue(cpu_val)
            self._gpu_slider.setValue(gpu_val)
            self._cpu_pct.setText(f"{cpu_val}%")
            self._gpu_pct.setText(f"{gpu_val}%")
        self._update_hint()

    def _update_hint(self) -> None:
        if self._fan_toggle.is_auto:
            self._mode_hint.setText(
                "Fan speeds are managed automatically by the system")
        else:
            self._mode_hint.setText(
                "Adjust fan speeds manually and click Apply to save")

    def _apply_fan(self) -> None:
        ok = self._ctrl.set_fan_speed(
            self._cpu_slider.value(), self._gpu_slider.value())
        if ok:
            self._apply_btn.setText("✓  Applied")
            QTimer.singleShot(2000,
                lambda: self._apply_btn.setText("Apply"))

    # ── Live poll ─────────────────────────────────────────────────────────────

    def _poll(self) -> None:
        cpu_f, gpu_f = self._ctrl.get_fan_speed()
        cpu_f = cpu_f or 0
        gpu_f = gpu_f or 0
        if self._fan_toggle.is_auto:
            self._g_cpu_f.set_text("Auto")
            self._g_gpu_f.set_text("Auto")
        else:
            self._g_cpu_f.set_text(None)
            self._g_gpu_f.set_text(None)
            self._g_cpu_f.set_value(float(cpu_f))
            self._g_gpu_f.set_value(float(gpu_f))
        self._fan_graph.push([float(cpu_f), float(gpu_f)])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._poll()
        self._poll_timer.start(2000)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._poll_timer.stop()
