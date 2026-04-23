# SPDX-License-Identifier: GPL-3.0-or-later
"""
linuwu-sense-gui — notifications.py
KDE/freedesktop desktop notifications via D-Bus.

Sends a standard org.freedesktop.Notifications.Notify call so the
notification appears in KDE's notification popup (and notification history)
just like system battery warnings or network events.
"""

from __future__ import annotations

_notif_id: int = 0   # track last notification so we can replace it


def notify(
    summary: str,
    body: str = "",
    urgency: int = 1,       # 0=low, 1=normal, 2=critical
    timeout_ms: int = 6000, # -1 = persistent
) -> None:
    """
    Send a desktop notification via D-Bus.
    Silently does nothing if the notification daemon isn't available.
    """
    global _notif_id
    try:
        from PyQt6.QtDBus import QDBusConnection, QDBusMessage
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return

        msg = QDBusMessage.createMethodCall(
            "org.freedesktop.Notifications",
            "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications",
            "Notify",
        )

        # Build hints dict with urgency
        from PyQt6.QtDBus import QDBusArgument
        hints: dict = {"urgency": urgency}

        msg.setArguments([
            "linuwu-sense-gui",   # app_name
            _notif_id,            # replaces_id (replace previous)
            "cpu",                # app_icon (freedesktop icon name)
            summary,              # summary
            body,                 # body
            [],                   # actions
            hints,                # hints
            timeout_ms,           # expire_timeout
        ])

        reply = bus.call(msg)
        if reply.arguments():
            _notif_id = reply.arguments()[0]

    except Exception:
        pass   # notifications are optional — never crash the app
