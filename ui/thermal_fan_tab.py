# SPDX-License-Identifier: GPL-3.0-or-later
"""
linuwu-sense-gui — thermal_fan_tab.py
Main dashboard tab.

Layout (top → bottom):
  • Performance Mode selector — syncs KDE power mode bidirectionally
    via powerprofilesctl; auto-switches on AC plug/unplug and battery drain.
  • Live circular gauges — CPU temp, GPU temp, iGPU temp, CPU fan %,
    GPU fan %, GPU load %.
  • Temperature history graph (°C, 60-second scrolling).
  • Fan speed history graph (%, from the fan_speed sysfs node).
  • Fan Control — Auto / Manual toggle with collapsible sliders.
  • Customize button — KDE-style instant-popup menu to toggle sections.

Performance notes:
  • QFont / QColor / QPen objects are created once at module level and
    reused in every paintEvent — no per-frame heap allocation.
  • Power-supply sysfs paths are resolved once at import time and cached.
  • Sensor discovery runs once at construction, not on every tab switch.
  • nvidia-smi is called once per poll returning both temp and load.
"""

import os
import glob
import subprocess
import collections
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QGridLayout, QFrame, QScrollArea, QSizePolicy,
    QMenu, QToolButton, QApplication, QStyle,
)
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, QSettings, pyqtSignal
from PyQt6.QtGui import (QPainter, QColor, QPen, QLinearGradient,
                          QBrush, QPolygonF, QFont, QPalette, QIcon,
                          QDrag)
from PyQt6.QtCore import QMimeData
from controller.sysfs_controller import SysfsController
from ui.notifications import notify
from ui.settings_tab import warn_threshold, critical_threshold, poll_interval_ms, celsius_to_unit, temp_unit

# ── KDE power-profile maps ────────────────────────────────────────────────────

_TO_KDE: dict[str, str] = {
    "low-power":            "power-saver",
    "quiet":                "power-saver",
    "balanced":             "balanced",
    "balanced-performance": "performance",
}
_FROM_KDE: dict[str, str] = {
    "power-saver": "quiet",
    "balanced":    "balanced",
    "performance": "balanced-performance",
}


def _set_kde_profile(kde: str) -> None:
    try:
        subprocess.run(
            ["powerprofilesctl", "set", kde],
            check=False, timeout=3,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _get_kde_profile() -> str:
    try:
        return subprocess.check_output(
            ["powerprofilesctl", "get"],
            timeout=2, stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return ""


# ── Sysfs helpers ─────────────────────────────────────────────────────────────

def _sread(path: str) -> str:
    """Read a sysfs file and return its stripped text, or '' on any error."""
    try:
        with open(path) as fh:
            return fh.read().strip()
    except Exception:
        return ""


def _hwmon_name(base: str) -> str:
    real = os.path.realpath(base)
    return (
        _sread(os.path.join(real, "name")) or
        _sread(os.path.join(base, "name")) or ""
    ).lower()


def _hwmon_inputs(base: str, kind: str):
    real = os.path.realpath(base)
    seen: set[str] = set()
    for p in sorted(
        glob.glob(os.path.join(real, f"{kind}*_input")) +
        glob.glob(os.path.join(base, f"{kind}*_input"))
    ):
        rp = os.path.realpath(p)
        if rp not in seen:
            seen.add(rp)
            yield rp


def _find_sensor(
    keywords: list[str],
    kind: str = "temp",
    exclude: list[str] | None = None,
) -> str | None:
    exclude = exclude or []
    for base in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        name = _hwmon_name(base)
        if any(ex in name for ex in exclude):
            continue
        matched = any(k in name for k in keywords)
        for p in _hwmon_inputs(base, kind):
            lbl = _sread(p.replace("_input", "_label")).lower()
            if matched or any(k in lbl for k in keywords):
                return p
    return None


def _nvidia_smi_query() -> tuple[float, float]:
    """
    Single nvidia-smi call returning (temp_°C, load_%).
    Combining both queries halves subprocess overhead.
    """
    try:
        out = subprocess.check_output(
            ["nvidia-smi",
             "--query-gpu=temperature.gpu,utilization.gpu",
             "--format=csv,noheader,nounits"],
            timeout=2, stderr=subprocess.DEVNULL,
        ).decode().strip()
        parts = out.splitlines()[0].split(",")
        return float(parts[0].strip()), float(parts[1].strip())
    except Exception:
        return 0.0, 0.0


def _amd_gpu_load() -> float:
    """Return AMD GPU busy % from DRM sysfs, or 0."""
    for p in glob.glob("/sys/class/drm/card*/device/gpu_busy_percent"):
        try:
            return float(_sread(p))
        except Exception:
            pass
    return 0.0


def _find_dgpu() -> tuple[str | None, bool]:
    """Returns (sysfs_path_or_None, use_nvidia_smi)."""
    # AMD — prefer 'edge' label (die temperature)
    for base in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        if "amdgpu" not in _hwmon_name(base):
            continue
        for p in _hwmon_inputs(base, "temp"):
            lbl = _sread(p.replace("_input", "_label")).lower()
            if "edge" in lbl or "junction" in lbl:
                return p, False
        for p in _hwmon_inputs(base, "temp"):
            return p, False

    # Nvidia via hwmon (newer proprietary drivers)
    p = _find_sensor(["nvidia"], "temp", exclude=["coretemp", "i915"])
    if p:
        return p, False

    # Nvidia via nvidia-smi fallback
    try:
        subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader,nounits"],
            check=True, timeout=2,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return None, True
    except Exception:
        pass

    # Nouveau
    return _find_sensor(["nouveau"], "temp"), False


def _find_igpu() -> str | None:
    p = _find_sensor(["i915"], "temp",
                     exclude=["amdgpu", "radeon", "nouveau", "nvidia"])
    if p:
        return p
    for base in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        if "coretemp" not in _hwmon_name(base):
            continue
        for inp in _hwmon_inputs(base, "temp"):
            lbl = _sread(inp.replace("_input", "_label")).lower()
            if "package" in lbl:
                return inp
    return None


def _read_temp(path: str | None) -> float:
    if not path:
        return 0.0
    try:
        return int(_sread(path)) / 1000.0
    except Exception:
        return 0.0


# ── Power-supply path cache (resolved once at import time) ───────────────────
# Avoids glob.glob on every 5-second AC poll.

def _resolve_power_paths() -> tuple[list[str], list[str]]:
    ac_paths = (
        glob.glob("/sys/class/power_supply/AC*/online") +
        glob.glob("/sys/class/power_supply/ADP*/online") +
        glob.glob("/sys/class/power_supply/ACAD/online")
    )
    bat_paths = glob.glob("/sys/class/power_supply/BAT*/capacity")
    return ac_paths, bat_paths


_AC_PATHS, _BAT_PATHS = _resolve_power_paths()


def _ac_online() -> bool:
    return any(_sread(p) == "1" for p in _AC_PATHS)


def _battery_pct() -> int | None:
    for p in _BAT_PATHS:
        try:
            return int(_sread(p))
        except Exception:
            pass
    return None


# ── Memory / swap helpers ────────────────────────────────────────────────────

def _read_meminfo() -> dict[str, int]:
    """Parse /proc/meminfo and return values in MB."""
    vals: dict[str, int] = {}
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                k, v = line.split(":", 1)
                vals[k.strip()] = int(v.split()[0]) // 1024  # kB → MB
    except Exception:
        pass
    return vals


# ── Pre-built paint objects ────────────────────────────────────────────────────
# Created once at class/module level; never re-allocated per repaint.

# Temperature threshold colours
_COL_HOT    = QColor("#da4453")
_COL_WARM   = QColor("#f67400")
_COL_MILD   = QColor("#f6c543")

# Graph trace colours
_TRACE_CPU  = QColor("#3daee9")
_TRACE_GPU  = QColor("#da4453")
_TRACE_FAN1 = QColor("#3daee9")
_TRACE_FAN2 = QColor("#27ae60")

# Reusable font objects
_FONT_VALUE  = QFont(); _FONT_VALUE.setPointSize(17); _FONT_VALUE.setBold(True)
_FONT_UNIT   = QFont(); _FONT_UNIT.setPointSize(8)
_FONT_LABEL  = QFont(); _FONT_LABEL.setPointSize(8);  _FONT_LABEL.setBold(True)
_FONT_GRAPH  = QFont(); _FONT_GRAPH.setPointSize(7)


def _temp_color(t: float) -> QColor | None:
    """Return a colour override for a given temperature, or None for 'cool'."""
    if t >= 90: return _COL_HOT
    if t >= 75: return _COL_WARM
    if t >= 60: return _COL_MILD
    return None


# ── Circular gauge ────────────────────────────────────────────────────────────


class _CardWrapper(QWidget):
    """
    Wraps a _Gauge with KDE System Monitor-style edit-mode chrome:
      • Drag handle bar at the top  (≡) — drag to reorder
      • Resize grip at bottom-right — drag to expand/shrink column span
      • Highlight border when edit mode is active
    In normal mode it is completely transparent.
    """
    # Signals
    dragStarted  = pyqtSignal(object)   # emits self
    dropOn       = pyqtSignal(object)   # emits self
    spanChanged  = pyqtSignal(object, int)  # emits (self, new_span)

    HANDLE_H = 22
    GRIP_SZ  = 20
    GRIP_PAD = 18   # bottom margin reserved for grip

    def __init__(self, gauge: "_Gauge") -> None:
        super().__init__()
        self.gauge      = gauge
        self._edit_mode = False
        self._dragging  = False
        self._drag_origin = None
        self._col_span  = 1

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(gauge)

        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)
        self.setAcceptDrops(True)

    def set_edit_mode(self, on: bool) -> None:
        self._edit_mode = on
        top = self.HANDLE_H if on else 0
        bot = self.GRIP_PAD if on else 0
        self.setContentsMargins(0, top, 0, bot)
        self.update()

    def get_col_span(self) -> int:
        return self._col_span

    def set_col_span(self, span: int) -> None:
        self._col_span = span

    # ── painting ─────────────────────────────────────────────────────────────

    def paintEvent(self, _) -> None:
        if not self._edit_mode:
            return
        pal = self.palette()
        p   = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        # Highlight border
        accent = pal.color(QPalette.ColorRole.Highlight)
        p.setPen(QPen(accent, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, W - 2, H - 2, 10, 10)

        # Drag handle bar
        handle_col = QColor(accent); handle_col.setAlpha(200)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(handle_col)
        p.drawRoundedRect(1, 1, W - 2, self.HANDLE_H - 2, 6, 6)

        # Drag handle dots (≡)
        dot_col = pal.color(QPalette.ColorRole.HighlightedText)
        p.setBrush(dot_col); p.setPen(Qt.PenStyle.NoPen)
        cx, cy = W // 2, self.HANDLE_H // 2
        for dx in (-10, -4, 2, 8):
            for dy in (-3, 3):
                p.drawEllipse(cx + dx - 2, cy + dy - 2, 4, 4)

        # Update cursor based on position (resize = ↔, drag handle = ✋)
        # (done in mouseMoveEvent instead to avoid per-paint overhead)

        # Resize grip — diagonal lines in bottom-right corner (like KDE)
        grip_col = QColor(accent); grip_col.setAlpha(180)
        p.setPen(QPen(grip_col, 2, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        gs = self.GRIP_SZ
        for offset in (4, 8, 12):
            p.drawLine(W - 2, H - 2 - offset,
                       W - 2 - offset, H - 2)
        # Arrow hint ▶ on right side
        p.setBrush(grip_col)
        p.setPen(Qt.PenStyle.NoPen)
        arrow = QPolygonF([
            QPointF(W - 6, H - self.GRIP_PAD // 2 - 5),
            QPointF(W - 6, H - self.GRIP_PAD // 2 + 5),
            QPointF(W - 2, H - self.GRIP_PAD // 2),
        ])
        p.drawPolygon(arrow)
        p.end()

    # ── mouse events — drag handle & resize grip ──────────────────────────────

    def mousePressEvent(self, ev) -> None:
        if not self._edit_mode:
            return
        pos = ev.position()
        # Drag handle area
        if pos.y() <= self.HANDLE_H:
            self._dragging   = True
            self._drag_origin = ev.position().toPoint()
        # Resize grip area
        elif (pos.x() >= self.width()  - self.GRIP_SZ and
              pos.y() >= self.height() - self.GRIP_PAD):
            self._resizing = True
            self._resize_origin_x = ev.position().x()
            self._span_at_start   = self._col_span

    def mouseMoveEvent(self, ev) -> None:
        if not self._edit_mode:
            return
        # Update cursor to give visual feedback
        pos = ev.position()
        if (pos.x() >= self.width() - self.GRIP_SZ and
                pos.y() >= self.height() - self.GRIP_PAD):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif pos.y() <= self.HANDLE_H:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        if self._dragging:
            if (ev.position().toPoint() - self._drag_origin).manhattanLength() > 8:
                drag = QDrag(self)
                mime = QMimeData()
                mime.setData("application/x-gauge-card", b"1")
                drag.setMimeData(mime)
                # Pixmap preview
                px = self.grab()
                px = px.scaled(px.width() // 2, px.height() // 2,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                drag.setPixmap(px)
                drag.setHotSpot(px.rect().center())
                self._dragging = False
                drag.exec(Qt.DropAction.MoveAction)
        elif self._resizing:
            dx       = ev.position().x() - self._resize_origin_x
            new_span = max(1, min(4, self._span_at_start + int(dx / 60)))
            if new_span != self._col_span:
                self._col_span = new_span   # update before emit
                self.spanChanged.emit(self, new_span)

    def mouseReleaseEvent(self, ev) -> None:
        self._dragging  = False
        self._resizing  = False

    # ── drop target ───────────────────────────────────────────────────────────

    def dragEnterEvent(self, ev) -> None:
        if ev.mimeData().hasFormat("application/x-gauge-card"):
            ev.acceptProposedAction()
            self.update()

    def dragLeaveEvent(self, ev) -> None:
        self.update()

    def dropEvent(self, ev) -> None:
        if ev.mimeData().hasFormat("application/x-gauge-card"):
            ev.acceptProposedAction()
            self.dropOn.emit(self)


class _Gauge(QWidget):
    """
    GNOME System Monitor style card:
    - Title at top
    - Thin ring arc (270° span)
    - Value/text centred inside ring
    - For memory mode: "Used", amount, total, "Total" stacked inside
    - White card background, subtle border
    """
    START, SPAN = 225, 270

    def __init__(self, label: str, unit: str, max_val: float,
                 fmt: str = "{:.0f}", base_color: QColor | None = None) -> None:
        super().__init__()
        self._label   = label
        self._unit    = unit
        self._max_val = max_val
        self._fmt     = fmt
        self._color   = base_color
        self._value   = 0.0
        self._override_text: str | None = None
        self._detail_l1: str = ""
        self._detail_l2: str = ""
        self._hwf_enabled = True
        self.setMinimumSize(100, 120)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

    def hasHeightForWidth(self) -> bool:
        return self._hwf_enabled

    def heightForWidth(self, w: int) -> int:
        return int(w * 1.18)   # slightly taller than wide for title + ring

    def setHwfDisabled(self, disabled: bool) -> None:
        """Disable hasHeightForWidth for wide-span cards."""
        self._hwf_enabled = not disabled
        self.updateGeometry()

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(150, 177)

    def set_value(self, v: float, color: QColor | None = None) -> None:
        if v == self._value and color is self._color:
            return
        self._value = v
        if color is not None:
            self._color = color
        self.update()

    def set_text(self, text: str | None) -> None:
        if text != self._override_text:
            self._override_text = text
            self.update()

    def set_detail(self, line1: str, line2: str) -> None:
        self._detail_l1 = line1
        self._detail_l2 = line2
        self.update()

    def set_unit(self, unit: str, max_val: float) -> None:
        """Update the unit label and arc maximum (e.g. switch °C↔°F)."""
        if self._unit != unit or self._max_val != max_val:
            self._unit    = unit
            self._max_val = max_val
            self.update()

    def paintEvent(self, _) -> None:  # noqa: N802
        pal    = self.palette()
        accent = self._color or pal.color(QPalette.ColorRole.Highlight)
        # Use Base for card — adapts to light/dark theme automatically
        card   = pal.color(QPalette.ColorRole.Base)
        # Border: slightly more contrast than Mid in dark mode
        border = pal.color(QPalette.ColorRole.Button)
        # Arc track: needs to be visible in both themes
        track  = pal.color(QPalette.ColorRole.Midlight)
        text   = pal.color(QPalette.ColorRole.WindowText)
        sub    = pal.color(QPalette.ColorRole.PlaceholderText)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        # ── Card background ──────────────────────────────────────────────
        p.setPen(QPen(border, 1))
        p.setBrush(card)
        p.drawRoundedRect(1, 1, W - 2, H - 2, 12, 12)

        # ── Title at top ─────────────────────────────────────────────────
        title_h = max(20, min(int(H * 0.16), 32))
        tf = QFont()
        tf.setPointSizeF(max(8.0, min(W, H) * 0.075))
        p.setFont(tf)
        p.setPen(text)
        p.drawText(QRectF(4, 6, W - 8, title_h),
                   Qt.AlignmentFlag.AlignCenter, self._label)

        # ── Ring arc — size to fit, centred horizontally ─────────────────
        ring_top = title_h + 6
        avail_h  = H - ring_top - 8
        ring_sz  = max(40, min(W - 20, avail_h))
        ring_x   = (W - ring_sz) // 2
        arc_w    = max(5, int(ring_sz * 0.085))
        pad      = arc_w // 2 + 2
        rect     = QRectF(ring_x + pad, ring_top + pad,
                          ring_sz - pad * 2, ring_sz - pad * 2)

        p.setPen(QPen(track, arc_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(rect, int(self.START * 16), int(-self.SPAN * 16))

        frac = max(0.0, min(self._value / self._max_val, 1.0))
        if frac > 0.0:
            p.setPen(QPen(accent, arc_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(rect, int(self.START * 16), int(-frac * self.SPAN * 16))

        # ── Inside-ring text ──────────────────────────────────────────────
        cx   = ring_x + ring_sz / 2
        cy   = ring_top + ring_sz / 2
        ir   = (ring_sz / 2) - arc_w - 4   # inner radius

        if self._detail_l1:
            # Memory mode: Used label, used amount, total amount, Total label
            lf = QFont(); lf.setPointSizeF(max(6.0, ir * 0.18))
            vf = QFont(); vf.setPointSizeF(max(7.5, ir * 0.28)); vf.setBold(True)
            sf = QFont(); sf.setPointSizeF(max(6.5, ir * 0.22))
            tl = QFont(); tl.setPointSizeF(max(6.0, ir * 0.18))

            p.setFont(lf); p.setPen(sub)
            p.drawText(QRectF(cx - ir, cy - ir * 0.82, ir * 2, ir * 0.38),
                       Qt.AlignmentFlag.AlignCenter, "Used")
            p.setFont(vf); p.setPen(text)
            p.drawText(QRectF(cx - ir, cy - ir * 0.46, ir * 2, ir * 0.46),
                       Qt.AlignmentFlag.AlignCenter, self._detail_l1)
            p.setFont(sf); p.setPen(text)
            p.drawText(QRectF(cx - ir, cy + ir * 0.02, ir * 2, ir * 0.40),
                       Qt.AlignmentFlag.AlignCenter, self._detail_l2)
            p.setFont(tl); p.setPen(sub)
            p.drawText(QRectF(cx - ir, cy + ir * 0.42, ir * 2, ir * 0.38),
                       Qt.AlignmentFlag.AlignCenter, "Total")

        elif self._override_text is not None:
            of = QFont(); of.setPointSizeF(max(7.0, ir * 0.30)); of.setBold(True)
            p.setFont(of); p.setPen(text)
            p.drawText(QRectF(cx - ir, cy - ir * 0.40, ir * 2, ir * 0.80),
                       Qt.AlignmentFlag.AlignCenter, self._override_text)
        else:
            vf = QFont(); vf.setPointSizeF(max(9.0, ir * 0.38)); vf.setBold(True)
            uf = QFont(); uf.setPointSizeF(max(7.0, ir * 0.22))
            p.setFont(vf); p.setPen(text)
            p.drawText(QRectF(cx - ir, cy - ir * 0.50, ir * 2, ir * 0.55),
                       Qt.AlignmentFlag.AlignCenter, self._fmt.format(self._value))
            p.setFont(uf); p.setPen(sub)
            p.drawText(QRectF(cx - ir, cy + ir * 0.08, ir * 2, ir * 0.38),
                       Qt.AlignmentFlag.AlignCenter, self._unit)

        p.end()


# ── History graph ─────────────────────────────────────────────────────────────

class _Graph(QWidget):
    """
    Scrolling multi-trace graph with gradient fills.

    ``traces`` is a list of ``(label, QColor)`` pairs.
    Pre-built QColor objects are passed in so paintEvent never allocates new ones.
    """
    HISTORY = 60

    def __init__(
        self,
        traces: list[tuple[str, QColor]],
        unit: str,
        max_val: float,
        height: int = 90,
    ) -> None:
        super().__init__()
        self._traces   = traces
        self._unit     = unit
        self._max_val  = max_val
        self._history  = [
            collections.deque([0.0] * self.HISTORY, maxlen=self.HISTORY)
            for _ in traces
        ]
        self._dirty    = False
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_unit(self, unit: str, max_val: float) -> None:
        """Update unit label and y-axis maximum."""
        self._unit    = unit
        self._max_val = max_val
        self.update()

    def push(self, values: list[float]) -> None:
        for i, v in enumerate(values):
            if i < len(self._history):
                self._history[i].append(float(v))
        self._dirty = True
        self.update()

    def paintEvent(self, _) -> None:  # noqa: N802
        pal    = self.palette()
        bg     = pal.color(QPalette.ColorRole.Base)
        grid   = pal.color(QPalette.ColorRole.Button)
        labels = pal.color(QPalette.ColorRole.PlaceholderText)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        PL, PR, PT, PB = 36, 8, 8, 18

        p.fillRect(0, 0, w, h, bg)

        p.setFont(_FONT_GRAPH)
        for i in range(5):
            frac = i / 4
            y    = int(PT + frac * (h - PT - PB))
            val  = self._max_val * (1 - frac)
            gc   = QColor(grid); gc.setAlpha(40)
            p.setPen(QPen(gc, 1))
            p.drawLine(PL, y, w - PR, y)
            p.setPen(labels)
            p.drawText(0, y - 6, PL - 3, 14,
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{val:.0f}")

        gw = w - PL - PR
        gh = h - PT - PB
        n  = self.HISTORY

        for idx in range(len(self._traces) - 1, -1, -1):
            lbl, color = self._traces[idx]
            pts = list(self._history[idx])
            xs  = [PL + i * gw / (n - 1) for i in range(n)]
            ys  = [PT + (1 - min(pts[i], self._max_val) / self._max_val) * gh
                   for i in range(n)]

            grad = QLinearGradient(0, PT, 0, PT + gh)
            fc   = QColor(color); fc.setAlpha(55);  grad.setColorAt(0, fc)
            fc2  = QColor(color); fc2.setAlpha(0);  grad.setColorAt(1, fc2)

            poly = QPolygonF()
            poly.append(QPointF(xs[0], PT + gh))
            for i in range(n):
                poly.append(QPointF(xs[i], ys[i]))
            poly.append(QPointF(xs[-1], PT + gh))

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawPolygon(poly)

            p.setPen(QPen(color, 1.5, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(1, n):
                p.drawLine(int(xs[i - 1]), int(ys[i - 1]),
                           int(xs[i]),     int(ys[i]))

        # Legend
        lx = PL + 4
        for lbl, color in self._traces:
            p.setPen(QPen(color, 2))
            p.drawLine(lx, 11, lx + 12, 11)
            p.setPen(labels)
            p.drawText(lx + 15, 5, 90, 12,
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       lbl)
            lx += 100

        p.setPen(labels)
        p.drawText(w - PR - 46, h - 3, 46, 10,
                   Qt.AlignmentFlag.AlignRight, "← 60 s")
        p.end()
        self._dirty = False


# ── Fan mode toggle ───────────────────────────────────────────────────────────

class _FanModeToggle(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._is_auto = True
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.auto_btn   = QPushButton("Auto")
        self.manual_btn = QPushButton("Manual")
        for btn in (self.auto_btn, self.manual_btn):
            btn.setCheckable(False)
            btn.setFixedHeight(28)
            btn.setMinimumWidth(80)
        self.auto_btn.setStyleSheet(
            "QPushButton{border-top-right-radius:0;border-bottom-right-radius:0;}")
        self.manual_btn.setStyleSheet(
            "QPushButton{border-top-left-radius:0;border-bottom-left-radius:0;"
            "border-left:none;}")
        layout.addWidget(self.auto_btn)
        layout.addWidget(self.manual_btn)
        self.auto_btn.clicked.connect(lambda: self._set(True))
        self.manual_btn.clicked.connect(lambda: self._set(False))
        self._refresh()

    def _set(self, auto: bool) -> None:
        self._is_auto = auto
        self._refresh()

    def _refresh(self) -> None:
        self.auto_btn.setProperty(
            "role", "toggle-on" if self._is_auto else "toggle-off")
        self.manual_btn.setProperty(
            "role", "toggle-off" if self._is_auto else "toggle-on")
        for btn in (self.auto_btn, self.manual_btn):
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    @property
    def is_auto(self) -> bool:
        return self._is_auto

    def set_auto(self, v: bool) -> None:
        self._set(v)

    def connect(self, cb) -> None:
        self.auto_btn.clicked.connect(lambda: cb(True))
        self.manual_btn.clicked.connect(lambda: cb(False))


# ── Main tab ──────────────────────────────────────────────────────────────────

class ThermalFanTab(QWidget):
    POLL_MS = 2000   # sensor read interval

    _DEFAULT_PREFS: dict[str, bool] = {
        "show_gauges":      True,
        "show_temp_graph":  True,
        "show_igpu":        True,
        "show_memory":      True,
    }

    def __init__(self, controller: SysfsController) -> None:
        super().__init__()
        self._ctrl  = controller
        # Restore user's visibility preferences
        s = QSettings("linuwu-sense", "linuwu-sense-gui")
        self._prefs = {
            k: s.value(f"dashboard/{k}", default, type=bool)
            for k, default in self._DEFAULT_PREFS.items()
        }

        # Sensor discovery — runs once at construction
        self._cpu_temp = _find_sensor(
            ["tdie", "tctl", "k10temp", "coretemp", "package"], "temp",
            exclude=["amdgpu", "radeon", "nouveau", "nvidia", "i915"])
        self._dgpu_temp, self._dgpu_smi = _find_dgpu()
        self._igpu_temp = _find_igpu()

        # Determine GPU display name once
        self._dgpu_label = (
            "Nvidia GPU" if (self._dgpu_smi or _find_sensor(["nvidia"], "temp"))
            else ("AMD GPU" if _find_sensor(["amdgpu"], "temp") else "GPU")
        )

        # Timers
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)

        self._ac_timer = QTimer(self)
        self._ac_timer.timeout.connect(self._check_ac)
        self._ac_timer.start(5000)
        self._was_ac = _ac_online()
        self._last_bat_pct: int | None = None
        self._notified_warning  = False   # avoid repeat notifications
        self._notified_critical = False
        self._bat_timer = QTimer(self)
        self._bat_timer.timeout.connect(self._check_battery_level)
        self._bat_timer.start(60_000)  # check every 60 s while on battery

        self._kde_timer = QTimer(self)
        self._kde_timer.timeout.connect(self._sync_kde)
        self._kde_timer.start(3000)
        self._last_kde = ""

        self._build_ui()
        self._load_settings()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        sp = QApplication.style().pixelMetric(QStyle.PixelMetric.PM_LayoutVerticalSpacing)
        m  = QApplication.style().pixelMetric(QStyle.PixelMetric.PM_LayoutLeftMargin)

        # Max-width centred container — keeps layout sane on ultrawide / fullscreen
        inner  = QWidget()
        inner.setMaximumWidth(1600)
        layout = QVBoxLayout(inner)
        layout.setSpacing(sp * 2)
        layout.setContentsMargins(m, m, m, m)

        # Outer container centres inner horizontally
        outer_widget = QWidget()
        outer_layout = QHBoxLayout(outer_widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addStretch()
        outer_layout.addWidget(inner, 1)
        outer_layout.addStretch()

        # ── Profile row ───────────────────────────────────────────────────
        prof_grp = QGroupBox("Performance Mode")
        pl = QVBoxLayout(prof_grp)
        pl.setSpacing(sp)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Mode:"))
        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(200)
        row1.addWidget(self._profile_combo)
        self._kde_badge = QLabel()
        self._kde_badge.setProperty("secondary", "true")
        row1.addWidget(self._kde_badge)
        row1.addStretch()
        # Manual lock toggle — prevents auto-switching this session
        self._manual_lock = False

        # Edit-mode button — toggles the edit toolbar below the profile row
        self._edit_btn = QToolButton()
        self._edit_btn.setIcon(QIcon.fromTheme("configure"))
        self._edit_btn.setToolTip("Customize Dashboard")
        self._edit_btn.setCheckable(True)
        self._edit_btn.setFixedHeight(28)
        self._edit_btn.toggled.connect(self._toggle_edit_mode)
        row1.addWidget(self._edit_btn)

        self._lock_btn = QToolButton()
        self._lock_btn.setIcon(QIcon.fromTheme("object-unlocked"))
        self._lock_btn.setCheckable(True)
        self._lock_btn.setFixedSize(28, 28)
        self._lock_btn.setToolTip("Hold current mode — prevent automatic switching")
        self._lock_btn.toggled.connect(self._on_lock_toggled)
        row1.addWidget(self._lock_btn)
        pl.addLayout(row1)
        self._profile_desc = QLabel()
        self._profile_desc.setProperty("secondary", "true")
        self._profile_desc.setWordWrap(True)
        pl.addWidget(self._profile_desc)
        layout.addWidget(prof_grp)

        # ── Edit toolbar — KDE System Monitor style ──────────────────
        self._edit_bar = QWidget()
        self._edit_bar.setObjectName("edit-bar")
        self._edit_bar.setStyleSheet("""
            #edit-bar {
                background: palette(alternate-base);
                border: 1px solid palette(mid);
                border-radius: 6px;
            }
        """)
        eb = QHBoxLayout(self._edit_bar)
        eb.setContentsMargins(8, 6, 8, 6)
        eb.setSpacing(4)

        # Save / Discard — left side
        self._save_btn = QPushButton(
            QIcon.fromTheme("document-save"), "Save Changes")
        self._save_btn.setProperty("accent", "true")
        self._save_btn.clicked.connect(self._save_layout)
        eb.addWidget(self._save_btn)

        discard_btn = QPushButton(
            QIcon.fromTheme("edit-undo"), "Discard Changes")
        discard_btn.clicked.connect(self._discard_layout)
        eb.addWidget(discard_btn)

        sep1 = QFrame(); sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setStyleSheet("color: palette(mid);")
        eb.addWidget(sep1)

        # Section toggles — middle
        self._edit_actions: dict[str, QPushButton] = {}
        self._prefs_backup: dict = {}
        for key, label, icon in [
            ("show_gauges",      "Gauges",      "cpu"),
            ("show_temp_graph",  "Temp Graph",  "office-chart-line"),
            ("show_igpu",        "iGPU",        "cpu"),
                ("show_memory",      "Memory",      "media-flash"),
        ]:
            btn = QPushButton(QIcon.fromTheme(icon), label)
            btn.setCheckable(True)
            btn.setChecked(self._prefs.get(key, True))
            btn.setProperty("edit-toggle", "true")
            btn.toggled.connect(
                lambda checked, k=key: self._on_cust_toggled_key(k, checked))
            eb.addWidget(btn)
            self._edit_actions[key] = btn

        eb.addStretch()

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet("color: palette(mid);")
        eb.addWidget(sep2)

        # Done — right side
        done_btn = QPushButton(
            QIcon.fromTheme("dialog-ok-apply"), "Done")
        done_btn.clicked.connect(lambda: self._edit_btn.setChecked(False))
        eb.addWidget(done_btn)

        self._edit_bar.setVisible(False)
        layout.addWidget(self._edit_bar)

        # ── Gauge grid — GNOME System Monitor card style ──────────────
        # ── Equal 4-column grid — KDE System Monitor style ───────────────
        self._gauge_row = QWidget()
        self._gauge_row.setMaximumHeight(560)
        gg = QGridLayout(self._gauge_row)
        gg.setContentsMargins(0, 0, 0, 0)
        gg.setSpacing(sp)
        for col in range(4):
            gg.setColumnStretch(col, 1)
        # Equal row heights — both rows same stretch, min-height set per row
        gg.setRowStretch(0, 1)
        gg.setRowStretch(1, 1)
        gg.setRowMinimumHeight(0, 140)
        gg.setRowMinimumHeight(1, 140)

        self._g_cpu_t    = _Gauge("CPU Temp",          "°C",  100.0)
        self._g_dgpu_t   = _Gauge(self._dgpu_label,    "°C",  100.0)
        self._g_igpu_t   = _Gauge("Intel iGPU",        "°C",  100.0)
        self._g_gpu_load = _Gauge("GPU Load",          "%",   100.0)
        self._g_ram      = _Gauge("Memory",            "%",   100.0)
        self._g_swap     = _Gauge("Swap",              "%",   100.0)

        # Wrap each gauge in a _CardWrapper for edit-mode chrome
        def _wrap(g: _Gauge) -> _CardWrapper:
            w = _CardWrapper(g)
            w.dropOn.connect(self._on_card_drop)
            w.spanChanged.connect(self._on_span_changed)
            return w

        self._c_cpu_t    = _wrap(self._g_cpu_t)
        self._c_dgpu_t   = _wrap(self._g_dgpu_t)
        self._c_igpu_t   = _wrap(self._g_igpu_t)
        self._c_gpu_load = _wrap(self._g_gpu_load)
        self._c_ram      = _wrap(self._g_ram)
        self._c_swap     = _wrap(self._g_swap)

        # 6 gauges in 4-column grid — fan gauges removed (in Fan Control tab)
        # Row 0: CPU Temp | GPU Temp | iGPU Temp | GPU Load
        # Row 1: Memory (span 2)     | Swap (span 2)
        self._c_ram.set_col_span(2)
        self._c_swap.set_col_span(2)
        # Disable hasHeightForWidth on all gauges so the grid controls row height
        for g in (self._g_cpu_t, self._g_dgpu_t, self._g_igpu_t,
                  self._g_gpu_load, self._g_ram, self._g_swap):
            g.setHwfDisabled(True)
        self._grid_layout = gg
        self._card_grid: list[list[_CardWrapper | None]] = [
            [self._c_cpu_t, self._c_dgpu_t, self._c_igpu_t, self._c_gpu_load],
            [self._c_ram,   self._c_swap],
        ]
        self._rebuild_grid()

        layout.addWidget(self._gauge_row)

        # ── Temperature graph ─────────────────────────────────────────────
        # Pass pre-built QColor objects — no allocation per repaint
        self._temp_graph = _Graph(
            [("CPU Temp", _TRACE_CPU), (self._dgpu_label, _TRACE_GPU)],
            "°C", 100.0, height=90)
        layout.addWidget(self._temp_graph)

        # Expanding spacer fills remaining space naturally
        layout.addStretch(1)

        scroll.setWidget(outer_widget)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

        self._profile_combo.currentTextChanged.connect(self._on_profile)
        self._apply_prefs()

    def _apply_prefs(self) -> None:
        p = self._prefs
        # Section-level visibility
        self._gauge_row.setVisible(p.get("show_gauges", True))
        self._temp_graph.setVisible(p.get("show_temp_graph", True))
        # GPU Load gauge follows gauges pref
        self._c_gpu_load.setVisible(p.get("show_gauges", True))
        # Memory gauges
        show_mem = p.get("show_memory", True)
        self._c_ram.setVisible(show_mem)
        self._c_swap.setVisible(show_mem)
        # iGPU — only show if hardware present and pref enabled
        igpu_on = p.get("show_igpu", True) and bool(self._igpu_temp)
        self._c_igpu_t.setVisible(igpu_on)


    # ── Customise (inline menu) ───────────────────────────────────────────────

    # ── Grid management ──────────────────────────────────────────────────

    def _all_cards(self) -> list["_CardWrapper"]:
        return [c for row in self._card_grid for c in row if c is not None]

    def _rebuild_grid(self) -> None:
        """Remove all widgets from the grid and re-add from _card_grid."""
        gg = self._grid_layout
        # Remove all
        for i in reversed(range(gg.count())):
            gg.takeAt(i)
        # Re-add with stored spans
        for row, cols in enumerate(self._card_grid):
            col_idx = 0
            for card in cols:
                if card is None:
                    col_idx += 1
                    continue
                span = card.get_col_span()
                gg.addWidget(card, row, col_idx, 1, span)
                col_idx += span

    def _on_card_drop(self, target: "_CardWrapper") -> None:
        """Swap the dragged card with the drop target."""
        source = self.sender()
        if source is target:
            return
        # Find positions
        src_pos = tgt_pos = None
        for r, row in enumerate(self._card_grid):
            for c, card in enumerate(row):
                if card is source: src_pos = (r, c)
                if card is target: tgt_pos = (r, c)
        if src_pos and tgt_pos:
            sr, sc = src_pos; tr, tc = tgt_pos
            self._card_grid[sr][sc], self._card_grid[tr][tc] = \
                self._card_grid[tr][tc], self._card_grid[sr][sc]
            self._rebuild_grid()

    def _on_span_changed(self, card: "_CardWrapper", new_span: int) -> None:
        """Rebuild the grid after a card span change (span already set on card)."""
        self._rebuild_grid()

    def _toggle_edit_mode(self, on: bool) -> None:
        if on:
            self._prefs_backup = dict(self._prefs)
        self._edit_bar.setVisible(on)
        tip = "Exit customize mode" if on else "Customize Dashboard"
        self._edit_btn.setToolTip(tip)
        # Toggle edit chrome on every card
        for card in self._all_cards():
            card.set_edit_mode(on)

    def _save_layout(self) -> None:
        """Persist current prefs and exit edit mode."""
        s = QSettings("linuwu-sense", "linuwu-sense-gui")
        for k, v in self._prefs.items():
            s.setValue(f"dashboard/{k}", v)
        self._edit_btn.setChecked(False)

    def _discard_layout(self) -> None:
        """Restore prefs to what they were when edit mode opened."""
        self._prefs = dict(self._prefs_backup)
        self._apply_prefs()
        # Sync toggle button states
        for k, btn in self._edit_actions.items():
            btn.blockSignals(True)
            btn.setChecked(self._prefs.get(k, True))
            btn.blockSignals(False)
        self._edit_btn.setChecked(False)

    def _on_cust_toggled_key(self, key: str, checked: bool) -> None:
        self._prefs[key] = checked
        self._apply_prefs()
        s = QSettings("linuwu-sense", "linuwu-sense-gui")
        s.setValue(f"dashboard/{key}", checked)

    def _on_cust_toggled(self, checked: bool) -> None:
        """Legacy slot kept for safety — delegates to key-based version."""
        act = self.sender()
        if act:
            self._on_cust_toggled_key(act.data(), checked)

    # ── Profile / KDE sync ────────────────────────────────────────────────────

    def _update_kde_badge(self, nitro: str) -> None:
        kde   = _TO_KDE.get(nitro, "")
        icons = {"power-saver": "🔋", "balanced": "⚖️", "performance": "⚡"}
        self._kde_badge.setText(
            f"{icons.get(kde, '')} System: {kde}" if kde else "")

    def _sync_kde(self) -> None:
        """Reflect external KDE power-profile changes into the combo."""
        kde = _get_kde_profile()
        if not kde or kde == self._last_kde:
            return
        self._last_kde = kde
        nitro = _FROM_KDE.get(kde, "")
        if not nitro or self._profile_combo.currentText() == nitro:
            return
        idx = self._profile_combo.findText(nitro)
        if idx >= 0:
            self._profile_combo.blockSignals(True)
            self._profile_combo.setCurrentIndex(idx)
            self._profile_combo.blockSignals(False)
            self._ctrl.set_thermal_profile(nitro)
            self._update_kde_badge(nitro)

    def _on_lock_toggled(self, locked: bool) -> None:
        self._manual_lock = locked
        tip = "Performance mode is held — automatic switching disabled" if locked \
              else "Hold current mode — prevent automatic switching"
        self._lock_btn.setToolTip(tip)
        self._lock_btn.setIcon(
            QIcon.fromTheme("object-locked" if locked else "object-unlocked"))

    def _on_profile(self, profile: str) -> None:
        self._ctrl.set_thermal_profile(profile)
        kde = _TO_KDE.get(profile, "")
        if kde:
            _set_kde_profile(kde)
            self._last_kde = kde
        self._update_kde_badge(profile)
        desc = {
            "low-power":            "Optimized for extended battery life with reduced performance.",
            "quiet":                "Balanced acoustics with moderate performance for everyday tasks.",
            "balanced":             "Balanced performance and thermal output for daily use.",
            "balanced-performance": "Maximum sustained performance for demanding applications.",
        }.get(profile, "")
        self._profile_desc.setText(desc)

    # ── Fan control ───────────────────────────────────────────────────────────


    # ── Live sensor poll ──────────────────────────────────────────────────────

    def _poll(self) -> None:
        cpu_t  = _read_temp(self._cpu_temp)
        if self._dgpu_smi:
            dgpu_t, gpu_load = _nvidia_smi_query()   # one subprocess, two values
        else:
            dgpu_t   = _read_temp(self._dgpu_temp)
            gpu_load = _amd_gpu_load()
        igpu_t = _read_temp(self._igpu_temp)

        cpu_f_pct, gpu_f_pct = self._ctrl.get_fan_speed()
        cpu_f_pct = cpu_f_pct or 0
        gpu_f_pct = gpu_f_pct or 0

        # Convert temps to display unit
        unit    = temp_unit()
        is_f    = unit == "°F"
        max_t   = 212.0 if is_f else 100.0
        cpu_d   = celsius_to_unit(cpu_t)
        dgpu_d  = celsius_to_unit(dgpu_t)
        igpu_d  = celsius_to_unit(igpu_t)

        # Update gauge units if settings changed
        for g in (self._g_cpu_t, self._g_dgpu_t, self._g_igpu_t):
            g.set_unit(unit, max_t)
        self._temp_graph.set_unit(unit, max_t)

        self._g_cpu_t.set_value(cpu_d,   _temp_color(cpu_t))  # color uses raw °C
        self._g_dgpu_t.set_value(dgpu_d, _temp_color(dgpu_t))
        self._g_igpu_t.set_value(igpu_d, _temp_color(igpu_t))
        self._g_gpu_load.set_value(gpu_load)

        self._temp_graph.push([cpu_d, dgpu_d])

        # Desktop notifications for thermal events
        hot  = max(cpu_t, dgpu_t)
        wcrit = critical_threshold()
        wwarn = warn_threshold()
        unit  = temp_unit()
        hot_d = celsius_to_unit(hot)
        if hot >= wcrit and not self._notified_critical:
            self._notified_critical = True
            notify("Thermal Warning — Critical",
                   f"CPU/GPU reached {hot_d:.0f}{unit} — consider switching to a lower profile.",
                   urgency=2)
        elif hot >= wwarn and not self._notified_warning:
            self._notified_warning = True
            notify("Thermal Warning",
                   f"CPU/GPU at {hot_d:.0f}{unit}.", urgency=1)
        elif hot < (wwarn - 5):
            self._notified_warning  = False
            self._notified_critical = False

        # Memory & swap
        mem = _read_meminfo()
        if mem:
            total_ram  = mem.get("MemTotal",  1)
            avail_ram  = mem.get("MemAvailable", 0)
            used_ram   = total_ram - avail_ram
            ram_pct    = min(100.0, used_ram / total_ram * 100) if total_ram else 0.0
            total_swap = mem.get("SwapTotal", 0)
            free_swap  = mem.get("SwapFree",  0)
            used_swap  = total_swap - free_swap
            swap_pct   = min(100.0, used_swap / total_swap * 100) if total_swap else 0.0
            self._g_ram.set_value(ram_pct)
            self._g_swap.set_value(swap_pct)
            # Tooltip shows actual MB values
            def _gb(mb: int) -> str:
                return f"{mb/1024:.1f} GiB" if mb >= 1024 else f"{mb} MiB"
            # RAM gauge: "Used" line1, total line2
            self._g_ram.set_detail(_gb(used_ram), _gb(total_ram))
            self._g_ram.setToolTip(
                f"RAM: {used_ram} MiB used / {total_ram} MiB total")
            # Swap gauge
            if total_swap:
                self._g_swap.set_detail(_gb(used_swap), _gb(total_swap))
                self._g_swap.setToolTip(
                    f"Swap: {used_swap} MiB used / {total_swap} MiB total")
            else:
                self._g_swap.set_detail("No", "swap")

        # Update tray icon — walk up to MainWindow
        win = self.window()
        if hasattr(win, "update_tray"):
            win.update_tray(cpu_t, self._profile_combo.currentText())

    def _switch_profile(self, target: str) -> None:
        """Switch the thermal profile if not locked and not already active."""
        if self._manual_lock:
            return   # user has locked the profile this session
        if self._profile_combo.currentText() == target:
            return
        idx = self._profile_combo.findText(target)
        if idx >= 0:
            self._profile_combo.setCurrentIndex(idx)

    def _check_ac(self) -> None:
        ac = _ac_online()
        if ac == self._was_ac:
            return
        self._was_ac = ac
        if ac:
            # Charger reconnected → performance
            self._switch_profile("balanced-performance")
        else:
            # Just unplugged — set based on current charge
            pct = _battery_pct() or 100
            self._switch_profile("low-power" if pct <= 20 else "balanced")

    def _check_battery_level(self) -> None:
        """Progressively lower the profile as battery drains while unplugged."""
        if _ac_online():
            return   # on AC — nothing to do
        pct = _battery_pct()
        if pct is None:
            return
        prev = self._last_bat_pct
        self._last_bat_pct = pct
        if prev is None:
            return   # first reading — no transition yet
        # Only switch downward when crossing a threshold
        if prev > 20 >= pct:
            self._switch_profile("low-power")
        elif prev > 40 >= pct:
            self._switch_profile("quiet")

    # ── Load ──────────────────────────────────────────────────────────────────

    def _load_settings(self) -> None:
        profiles = self._ctrl.get_available_profiles()
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        if profiles:
            self._profile_combo.addItems(profiles)
            self._profile_combo.setEnabled(True)
            current = self._ctrl.get_thermal_profile()
            if current:
                idx = self._profile_combo.findText(current)
                if idx >= 0:
                    self._profile_combo.setCurrentIndex(idx)
                self._update_kde_badge(current)
        else:
            self._profile_combo.addItem("Not available")
            self._profile_combo.setEnabled(False)
        self._profile_combo.blockSignals(False)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._poll()
        self._poll_timer.start(self.POLL_MS)
        if not self._kde_timer.isActive():
            self._kde_timer.start(3000)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._poll_timer.stop()   # stop sensor reads when tab not visible
