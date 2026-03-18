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
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSlider,
    QPushButton, QGroupBox, QGridLayout, QFrame, QScrollArea, QSizePolicy,
    QMenu, QToolButton, QApplication, QStyle,
)
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, QSettings
from PyQt6.QtGui import (QPainter, QColor, QPen, QLinearGradient,
                          QBrush, QPolygonF, QFont, QPalette, QIcon)
from controller.sysfs_controller import SysfsController
from ui.notifications import notify

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

class _Gauge(QWidget):
    ARC_W, START, SPAN = 8, 225, 270

    def __init__(self, label: str, unit: str, max_val: float,
                 fmt: str = "{:.0f}", base_color: QColor | None = None) -> None:
        super().__init__()
        self._label   = label
        self._unit    = unit
        self._max_val = max_val
        self._fmt     = fmt
        self._color         = base_color   # None → use palette highlight
        self._value         = 0.0
        self._override_text: str | None = None   # if set, shown instead of value
        # Square, expands to fill available space, min 90px
        self.setMinimumSize(90, 90)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return w  # always square

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(120, 120)

    def set_value(self, v: float, color: QColor | None = None) -> None:
        if v == self._value and color is self._color:
            return
        self._value = v
        if color is not None:
            self._color = color
        self.update()

    def set_text(self, text: str | None) -> None:
        """Override the displayed value with a fixed string (e.g. 'Auto')."""
        if text != self._override_text:
            self._override_text = text
            self.update()

    def paintEvent(self, _) -> None:  # noqa: N802
        pal    = self.palette()
        accent = self._color or pal.color(QPalette.ColorRole.Highlight)
        bg     = pal.color(QPalette.ColorRole.AlternateBase)
        track  = pal.color(QPalette.ColorRole.Mid)
        text   = pal.color(QPalette.ColorRole.WindowText)
        sub    = pal.color(QPalette.ColorRole.PlaceholderText)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Use actual widget dimensions (responsive)
        w, h = self.width(), min(self.width(), self.height())
        arc_w = max(5, int(w * 0.072))
        pad   = arc_w + 3
        rect  = QRectF(pad, pad, w - pad * 2, h - pad * 2)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(0, 0, w, h, 10, 10)

        p.setPen(QPen(track, arc_w,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(rect, int(self.START * 16), int(-self.SPAN * 16))

        frac = max(0.0, min(self._value / self._max_val, 1.0))
        if frac > 0.0:
            p.setPen(QPen(accent, arc_w,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(rect, int(self.START * 16), int(-frac * self.SPAN * 16))

        # Scale fonts proportionally to the actual widget size
        vf = QFont(); vf.setPointSizeF(max(9.0, w * 0.155)); vf.setBold(True)
        uf = QFont(); uf.setPointSizeF(max(7.0, w * 0.073))
        lf = QFont(); lf.setPointSizeF(max(7.0, w * 0.073)); lf.setBold(True)

        p.setPen(text)
        if self._override_text is not None:
            # Override text (e.g. "Auto") — smaller font so it fits nicely
            of = QFont(); of.setPointSizeF(max(7.0, w * 0.095)); of.setBold(True)
            p.setFont(of)
            p.drawText(QRectF(0, h * 0.20, w, h * 0.56),
                       Qt.AlignmentFlag.AlignCenter, self._override_text)
        else:
            p.setFont(vf)
            p.drawText(QRectF(0, h * 0.22, w, h * 0.36),
                       Qt.AlignmentFlag.AlignCenter,
                       self._fmt.format(self._value))
            p.setFont(uf)
            p.setPen(sub)
            p.drawText(QRectF(0, h * 0.54, w, h * 0.16),
                       Qt.AlignmentFlag.AlignCenter, self._unit)

        p.setFont(lf)
        p.setPen(text)
        p.drawText(QRectF(2, h * 0.70, w - 4, h * 0.22),
                   Qt.AlignmentFlag.AlignCenter, self._label)
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

    def push(self, values: list[float]) -> None:
        for i, v in enumerate(values):
            if i < len(self._history):
                self._history[i].append(float(v))
        self._dirty = True
        self.update()

    def paintEvent(self, _) -> None:  # noqa: N802
        pal    = self.palette()
        bg     = pal.color(QPalette.ColorRole.AlternateBase)
        grid   = pal.color(QPalette.ColorRole.Mid)
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
        "show_fan_graph":   True,
        "show_igpu":        True,
        "show_fan_control": True,
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

        inner  = QWidget()
        layout = QVBoxLayout(inner)
        sp = QApplication.style().pixelMetric(QStyle.PixelMetric.PM_LayoutVerticalSpacing)
        m  = QApplication.style().pixelMetric(QStyle.PixelMetric.PM_LayoutLeftMargin)
        layout.setSpacing(sp * 2)
        layout.setContentsMargins(m, m, m, m)

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

        # KDE-style configure button — icon-only tool button with instant popup menu
        self._cust_menu = QMenu(self)
        for key, label in [
            ("show_gauges",      "Live gauges"),
            ("show_temp_graph",  "Temperature graph"),
            ("show_fan_graph",   "Fan speed graph"),
            ("show_igpu",        "Intel iGPU gauge"),
            ("show_fan_control", "Manual fan sliders"),
        ]:
            act = self._cust_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self._prefs.get(key, True))
            act.setData(key)
            act.toggled.connect(self._on_cust_toggled)

        self._cust_menu.addSeparator()

        cust_btn = QToolButton()
        cust_btn.setIcon(QIcon.fromTheme("configure"))
        cust_btn.setToolTip("Customize Dashboard")
        cust_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        cust_btn.setMenu(self._cust_menu)
        cust_btn.setFixedHeight(28)
        row1.addWidget(cust_btn)

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

        # ── Gauge row ─────────────────────────────────────────────────────
        self._gauge_row = QWidget()
        gr = QHBoxLayout(self._gauge_row)
        gr.setContentsMargins(0, 0, 0, 0)
        gr.setSpacing(sp)
        self._g_cpu_t  = _Gauge("CPU Temp",      "°C",  100.0)
        self._g_dgpu_t = _Gauge(self._dgpu_label, "°C",  100.0)
        self._g_igpu_t = _Gauge("Intel iGPU",     "°C",  100.0)
        self._g_cpu_f  = _Gauge("CPU Fan",        "%",   100.0)
        self._g_gpu_f  = _Gauge("GPU Fan",        "%",   100.0)
        self._g_gpu_load = _Gauge("GPU Load",     "%",   100.0)
        for g in (self._g_cpu_t, self._g_dgpu_t, self._g_igpu_t,
                  self._g_cpu_f, self._g_gpu_f, self._g_gpu_load):
            gr.addWidget(g)
        layout.addWidget(self._gauge_row)

        # ── Temperature graph ─────────────────────────────────────────────
        # Pass pre-built QColor objects — no allocation per repaint
        self._temp_graph = _Graph(
            [("CPU Temp", _TRACE_CPU), (self._dgpu_label, _TRACE_GPU)],
            "°C", 100.0, height=120)
        layout.addWidget(self._temp_graph)

        # ── Fan speed graph ───────────────────────────────────────────────
        self._fan_graph = _Graph(
            [("CPU Fan %", _TRACE_FAN1), ("GPU Fan %", _TRACE_FAN2)],
            "%", 100.0, height=90)
        layout.addWidget(self._fan_graph)

        # ── Fan control ───────────────────────────────────────────────────
        self._fan_group = QGroupBox("Fan Control")
        fg = QGridLayout(self._fan_group)
        fg.setVerticalSpacing(10)
        fg.setHorizontalSpacing(12)
        fg.setColumnMinimumWidth(0, 80)
        fg.setColumnStretch(1, 1)
        fg.setColumnMinimumWidth(2, 48)

        fg.addWidget(QLabel("Fan Mode:"), 0, 0, Qt.AlignmentFlag.AlignVCenter)
        tr = QHBoxLayout()
        tr.setContentsMargins(0, 0, 0, 0)
        tr.setSpacing(10)
        self._fan_toggle = _FanModeToggle()
        self._fan_toggle.connect(self._on_mode_changed)
        tr.addWidget(self._fan_toggle)
        self._mode_hint = QLabel("Fan speeds are managed automatically by the system")
        self._mode_hint.setProperty("secondary", "true")
        tr.addWidget(self._mode_hint)
        tr.addStretch()
        fg.addLayout(tr, 0, 1, 1, 2)

        # Wrap slider rows in a container so QGridLayout row collapses on hide
        self._sliders_container = QWidget()
        sc = QVBoxLayout(self._sliders_container)
        sc.setContentsMargins(0, 4, 0, 0)
        sc.setSpacing(8)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sc.addWidget(sep)

        cpu_row = QHBoxLayout()
        cpu_row.addWidget(QLabel("CPU Fan Speed"))
        self._cpu_slider = QSlider(Qt.Orientation.Horizontal)
        self._cpu_slider.setRange(0, 100)
        self._cpu_pct = QLabel("0%")
        self._cpu_pct.setMinimumWidth(40)
        self._cpu_pct.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._cpu_slider.valueChanged.connect(
            lambda v: self._cpu_pct.setText(f"{v}%"))
        cpu_row.addWidget(self._cpu_slider, 1)
        cpu_row.addWidget(self._cpu_pct)
        sc.addLayout(cpu_row)

        gpu_row = QHBoxLayout()
        gpu_row.addWidget(QLabel("GPU Fan Speed"))
        self._gpu_slider = QSlider(Qt.Orientation.Horizontal)
        self._gpu_slider.setRange(0, 100)
        self._gpu_pct = QLabel("0%")
        self._gpu_pct.setMinimumWidth(40)
        self._gpu_pct.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._gpu_slider.valueChanged.connect(
            lambda v: self._gpu_pct.setText(f"{v}%"))
        gpu_row.addWidget(self._gpu_slider, 1)
        gpu_row.addWidget(self._gpu_pct)
        sc.addLayout(gpu_row)

        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setProperty("accent", "true")
        self._apply_btn.setMinimumHeight(32)
        self._apply_btn.clicked.connect(self._apply_fan)
        sc.addWidget(self._apply_btn)

        fg.addWidget(self._sliders_container, 1, 0, 1, 3)

        layout.addWidget(self._fan_group)
        layout.addStretch()

        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._profile_combo.currentTextChanged.connect(self._on_profile)
        self._set_sliders_enabled(False)
        self._apply_prefs()

    def _apply_prefs(self) -> None:
        p = self._prefs
        self._gauge_row.setVisible(p.get("show_gauges", True))
        self._g_igpu_t.setVisible(
            p.get("show_igpu", True) and bool(self._igpu_temp))
        self._temp_graph.setVisible(p.get("show_temp_graph", True))
        self._fan_graph.setVisible(p.get("show_fan_graph", True))
        self._fan_group.setVisible(p.get("show_fan_control", True))

    def _set_sliders_enabled(self, enabled: bool) -> None:
        # Hide the whole container — grid row collapses cleanly
        self._sliders_container.setVisible(enabled)
        self._mode_hint.setText(
            "Adjust fan speeds manually and click Apply to save" if enabled
            else "Fan speeds are managed automatically by the system"
        )

    # ── Customise (inline menu) ───────────────────────────────────────────────

    def _on_cust_toggled(self, checked: bool) -> None:
        act = self.sender()
        if act:
            key = act.data()
            self._prefs[key] = checked
            self._apply_prefs()
            # Persist immediately
            s = QSettings("linuwu-sense", "linuwu-sense-gui")
            s.setValue(f"dashboard/{key}", checked)

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

    def _on_mode_changed(self, is_auto: bool) -> None:
        if is_auto:
            self._set_sliders_enabled(False)
            self._cpu_slider.setValue(0)
            self._gpu_slider.setValue(0)
            self._ctrl.set_fan_speed(0, 0)
        else:
            cpu_hw, gpu_hw = self._ctrl.get_fan_speed()
            cpu_val = cpu_hw if (cpu_hw and cpu_hw > 0) else 50
            gpu_val = gpu_hw if (gpu_hw and gpu_hw > 0) else 50
            self._set_sliders_enabled(True)
            self._cpu_slider.setValue(cpu_val)
            self._gpu_slider.setValue(gpu_val)
            self._cpu_pct.setText(f"{cpu_val}%")
            self._gpu_pct.setText(f"{gpu_val}%")

    def _apply_fan(self) -> None:
        ok = self._ctrl.set_fan_speed(
            self._cpu_slider.value(), self._gpu_slider.value())
        if ok:
            self._apply_btn.setText("✓  Applied")
            QTimer.singleShot(2000,
                lambda: self._apply_btn.setText("Apply"))

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

        self._g_cpu_t.set_value(cpu_t,   _temp_color(cpu_t))
        self._g_dgpu_t.set_value(dgpu_t, _temp_color(dgpu_t))
        self._g_igpu_t.set_value(igpu_t, _temp_color(igpu_t))
        self._g_gpu_load.set_value(gpu_load)

        if self._fan_toggle.is_auto:
            self._g_cpu_f.set_text("Auto")
            self._g_gpu_f.set_text("Auto")
        else:
            self._g_cpu_f.set_text(None)
            self._g_gpu_f.set_text(None)
            self._g_cpu_f.set_value(float(cpu_f_pct))
            self._g_gpu_f.set_value(float(gpu_f_pct))

        self._temp_graph.push([cpu_t, dgpu_t])
        self._fan_graph.push([float(cpu_f_pct), float(gpu_f_pct)])

        # Desktop notifications for thermal events
        hot = max(cpu_t, dgpu_t)
        if hot >= 90 and not self._notified_critical:
            self._notified_critical = True
            notify("Thermal Warning — Critical",
                   f"CPU/GPU reached {hot:.0f} °C — consider switching to a lower profile.",
                   urgency=2)
        elif hot >= 75 and not self._notified_warning:
            self._notified_warning = True
            notify("Thermal Warning",
                   f"CPU/GPU at {hot:.0f} °C.", urgency=1)
        elif hot < 70:
            self._notified_warning  = False
            self._notified_critical = False

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

        cpu_hw, gpu_hw = self._ctrl.get_fan_speed()
        if cpu_hw and gpu_hw and (cpu_hw > 0 or gpu_hw > 0):
            self._fan_toggle.set_auto(False)
            self._set_sliders_enabled(True)
            self._cpu_slider.setValue(cpu_hw)
            self._gpu_slider.setValue(gpu_hw)
            self._cpu_pct.setText(f"{cpu_hw}%")
            self._gpu_pct.setText(f"{gpu_hw}%")
        else:
            self._fan_toggle.set_auto(True)
            self._set_sliders_enabled(False)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._poll()
        self._poll_timer.start(self.POLL_MS)
        if not self._kde_timer.isActive():
            self._kde_timer.start(3000)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._poll_timer.stop()   # stop sensor reads when tab not visible
