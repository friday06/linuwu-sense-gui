#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
linuwu-sense-gui — main.py
Application entry point.  Applies the native KDE Breeze style and injects
only the minimal QSS needed for role-based custom widgets.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QStyleFactory
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow

# Only things the native QStyle cannot handle on its own:
#   • Segmented Auto/Manual toggle  (role="toggle-on/off")
#   • Accent primary-action button  (accent="true")
#   • Destructive button            (danger="true")
#   • De-emphasised helper text     (secondary="true")
#
# Everything else — colours, fonts, borders, spacing, hover states,
# focus rings, shadows — is left entirely to Breeze / the user's theme.
_ROLE_QSS = """
/* ═══════════════════════════════════════════════════════════════════════
   linuwu-sense-gui  —  KDE Breeze companion stylesheet
   Only overrides what the native Breeze QStyle cannot do on its own.
   Everything else (colours, borders, hover, focus rings, animations)
   is left to the user's installed theme.
   ═══════════════════════════════════════════════════════════════════════ */

/* ── QGroupBox — Breeze 6: normal weight title, standard secondary colour ─ */
QGroupBox {
    margin-top: 1.3em;
    padding-top: 0.3em;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 4px;
    color: palette(windowtext);
    font-size: 11px;
    font-weight: 500;
}


/* ── Segmented Auto / Manual toggle ──────────────────────────────────── */
QPushButton[role="toggle-on"] {
    background-color: palette(highlight);
    color: palette(highlighted-text);
    border: 1px solid palette(highlight);
    border-radius: 4px;
    font-weight: 700;
    padding: 4px 18px;
}
QPushButton[role="toggle-off"] {
    background-color: palette(button);
    color: palette(button-text);
    border: 1px solid palette(mid);
    border-radius: 4px;
    padding: 4px 18px;
}
QPushButton[role="toggle-off"]:hover {
    border-color: palette(highlight);
    color: palette(highlight);
}

/* ── Accent / primary action button ──────────────────────────────────── */
QPushButton[accent="true"] {
    background-color: palette(highlight);
    color: palette(highlighted-text);
    border: 1px solid palette(highlight);
    font-weight: 600;
}
QPushButton[accent="true"]:hover   { background-color: palette(highlight); filter: brightness(1.1); }
QPushButton[accent="true"]:pressed { background-color: palette(highlight); filter: brightness(0.85); }
QPushButton[accent="true"]:disabled {
    background-color: palette(mid);
    color: palette(shadow);
    border-color: palette(mid);
}

/* ── Destructive / danger action button ──────────────────────────────── */
QPushButton[danger="true"] {
    background-color: #da4453;
    color: #ffffff;
    border: 1px solid #da4453;
    font-weight: 600;
}
QPushButton[danger="true"]:hover   { background-color: #e05060; border-color: #e05060; }
QPushButton[danger="true"]:pressed { background-color: #c0394a; border-color: #c0394a; }

/* ── Secondary / de-emphasised text ──────────────────────────────────── */
QLabel[secondary="true"] {
    color: palette(placeholdertext);
    font-size: 11px;
}

/* ── KDE badge / pill label ───────────────────────────────────────────── */
QLabel[badge="true"] {
    background-color: palette(highlight);
    color: palette(highlighted-text);
    border-radius: 8px;
    padding: 1px 7px;
    font-size: 10px;
    font-weight: 600;
}

/* ── Toast notification label ────────────────────────────────────────── */
QLabel[toast="true"] {
    color: palette(highlight);
    font-size: 12px;
    font-weight: 600;
    padding: 4px 0;
}
"""


def main() -> None:
    # HiDPI — must be set before QApplication is created
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("linuwu-sense-gui")
    app.setApplicationDisplayName("linuwu sense")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("linuwu-sense")
    # Links the running process to the .desktop entry so Plasma shows
    # the correct icon and groups windows / taskbar entries correctly.
    app.setDesktopFileName("linuwu-sense-gui")

    # Prefer Breeze (KDE's native style) → Kvantum → Fusion fallback.
    # On any KDE system Breeze will be present.  Fusion is the safe
    # cross-platform fallback for non-KDE desktops.
    available = QStyleFactory.keys()
    for name in ("breeze", "Breeze", "kvantum", "Kvantum", "Fusion"):
        if name in available:
            app.setStyle(name)
            break

    app.setStyleSheet(_ROLE_QSS + """
    QPushButton[edit-toggle="true"] {
        border: 1px solid palette(mid);
        border-radius: 4px;
        padding: 3px 8px;
    }
    QPushButton[edit-toggle="true"]:checked {
        background-color: palette(highlight);
        color: palette(highlighted-text);
        border-color: palette(highlight);
    }
""")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
