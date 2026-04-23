# SPDX-License-Identifier: GPL-3.0-or-later
"""
linuwu-sense-gui — tray_icon.py

KDE-style monochrome system tray icon.

The icon is a small circular temperature gauge rendered at runtime as a
QPixmap so it automatically matches the system icon size and looks correct
on both light and dark panels.  Like KDE's own indicators (Plasma System
Monitor, KSysGuard) the icon:
  • Is monochrome — uses windowText colour so it inverts correctly on any panel
  • Shows the current CPU temperature as a number inside a thin arc
  • Changes arc colour at warning (≥75 °C) and critical (≥90 °C) thresholds
    using the standard Breeze warning/error palette colours

Right-click menu follows KDE convention:
  • Checkable profile actions (radio group)
  • Separator
  • Show/Hide window
  • Quit
"""

from __future__ import annotations

import math
from PyQt6.QtWidgets import (
    QSystemTrayIcon, QMenu, QApplication,
)
from PyQt6.QtCore import Qt, QRectF, QSize
from PyQt6.QtGui import (
    QIcon, QPainter, QPixmap, QColor, QPen, QFont,
    QPalette, QAction, QActionGroup,
)

from config.constants import APP_NAME

# Temperature threshold colours (Breeze semantic)
_COL_NORMAL   = None          # None → use windowText (monochrome)
_COL_WARNING  = QColor("#f67400")   # warm orange
_COL_CRITICAL = QColor("#ff3a3a")   # logo red


def _make_icon(temp: float, size: int = 22) -> QIcon:
    """
    Render a monochrome circular temperature gauge as a QIcon.

    The arc sweeps 270° starting from bottom-left, proportional to
    temp/100.  Text is the integer temperature.  The arc colour shifts
    to warning/critical colours above the thresholds.
    """
    px = QPixmap(QSize(size, size))
    px.fill(Qt.GlobalColor.transparent)

    pal   = QApplication.palette()
    fg    = pal.color(QPalette.ColorRole.WindowText)   # monochrome base

    if temp >= 90:
        arc_col = _COL_CRITICAL
    elif temp >= 75:
        arc_col = _COL_WARNING
    else:
        arc_col = QColor('#a78bfa')   # logo purple — matches brand

    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    stroke = max(1, size // 11)
    pad    = stroke + 1
    rect   = QRectF(pad, pad, size - pad * 2, size - pad * 2)

    # Track arc (dim)
    track = QColor(fg); track.setAlpha(45)
    p.setPen(QPen(track, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(rect, 225 * 16, -270 * 16)

    # Value arc
    frac = max(0.0, min(temp / 100.0, 1.0))
    if frac > 0.0:
        p.setPen(QPen(arc_col, stroke,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, 225 * 16, int(-frac * 270 * 16))

    # Temperature text
    f = QFont()
    f.setPointSizeF(size * 0.30)
    f.setBold(True)
    p.setFont(f)
    p.setPen(fg)
    p.drawText(QRectF(0, size * 0.15, size, size * 0.70),
               Qt.AlignmentFlag.AlignCenter, f"{int(temp)}")

    p.end()
    return QIcon(px)


class TrayIcon(QSystemTrayIcon):
    """
    Monochrome KDE-style tray icon for linuwu-sense-gui.

    Usage::
        tray = TrayIcon(main_window, ctrl)
        tray.show()

    Call ``update(cpu_temp, profile)`` from the poll loop to refresh the icon
    and tooltip without rebuilding the menu.
    """

    def __init__(self, window, ctrl) -> None:
        super().__init__(window)
        self._window  = window
        self._ctrl    = ctrl
        self._temp    = 0.0
        self._profile = ""
        self._profiles: list[str] = []

        self._build_menu()
        self.setIcon(_make_icon(0))
        self.setToolTip(APP_NAME)

        # Single-click shows/hides window (KDE convention)
        self.activated.connect(self._on_activated)

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        menu = QMenu()

        # Profile submenu
        self._profile_menu = menu.addMenu(
            QIcon.fromTheme("cpu"), "Performance Mode")
        self._profile_group = QActionGroup(self)
        self._profile_group.setExclusive(True)
        self._profile_group.triggered.connect(self._on_profile_action)

        self._refresh_profiles()

        menu.addSeparator()

        # Show / Hide
        self._toggle_act = QAction(
            QIcon.fromTheme("window-restore"), "Show linuwu sense", self)
        self._toggle_act.triggered.connect(self._toggle_window)
        menu.addAction(self._toggle_act)

        menu.addSeparator()

        quit_act = QAction(QIcon.fromTheme("application-exit"), "Quit", self)
        quit_act.triggered.connect(QApplication.quit)
        menu.addAction(quit_act)

        self.setContextMenu(menu)

    def _refresh_profiles(self) -> None:
        """Populate (or repopulate) the profile submenu from sysfs."""
        # Clear old actions
        for act in self._profile_group.actions():
            self._profile_menu.removeAction(act)
            self._profile_group.removeAction(act)

        self._profiles = self._ctrl.get_available_profiles()
        for prof in self._profiles:
            act = QAction(prof.replace("-", " ").title(), self)
            act.setCheckable(True)
            act.setData(prof)
            act.setChecked(prof == self._profile)
            self._profile_group.addAction(act)
            self._profile_menu.addAction(act)

    # ── Public update API ─────────────────────────────────────────────────────

    def update(self, cpu_temp: float, profile: str) -> None:
        """Called from the main poll loop — refreshes icon and tooltip."""
        temp_changed    = abs(cpu_temp - self._temp) >= 1.0
        profile_changed = profile != self._profile

        if temp_changed:
            self._temp = cpu_temp
            self.setIcon(_make_icon(cpu_temp))

        if profile_changed:
            self._profile = profile
            for act in self._profile_group.actions():
                act.setChecked(act.data() == profile)

        if temp_changed or profile_changed:
            prof_display = profile.replace("-", " ").title() if profile else "—"
            self.setToolTip(
                f"{APP_NAME}\n"
                f"CPU  {cpu_temp:.0f} °C\n"
                f"Profile  {prof_display}"
            )

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_window()

    def _toggle_window(self) -> None:
        if self._window.isVisible():
            self._window.hide()
            self._toggle_act.setText("Open")
            self._toggle_act.setIcon(QIcon.fromTheme("window-restore"))
        else:
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()
            self._toggle_act.setText("Minimise to Tray")
            self._toggle_act.setIcon(QIcon.fromTheme("window-minimize"))

    def _on_profile_action(self, act: QAction) -> None:
        self._ctrl.set_thermal_profile(act.data())
        # Also sync KDE power mode
        from ui.thermal_fan_tab import _set_kde_profile, _TO_KDE
        kde = _TO_KDE.get(act.data(), "")
        if kde:
            _set_kde_profile(kde)
