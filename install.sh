#!/usr/bin/env bash
# install.sh — Install linuwu sense on Arch Linux
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; exit 1; }

INSTALL_DIR="/usr/lib/linuwu-sense-gui"

[[ "$EUID" -ne 0 ]] && error "Please run as root: sudo ./install.sh"
command -v python3 &>/dev/null || error "python3 not found: sudo pacman -S python"

# ── Resolve the real user (not root) ──────────────────────────────────────
REAL_USER="${SUDO_USER:-}"
[[ -z "$REAL_USER" || "$REAL_USER" == "root" ]] && REAL_USER="$(logname 2>/dev/null || true)"
REAL_HOME="$(getent passwd "$REAL_USER" 2>/dev/null | cut -d: -f6 || true)"

# ── Dependencies ───────────────────────────────────────────────────────────
# Check PyQt6 (Arch ships 6.10.x which satisfies >=6.7 requirement)
python3 -c "import PyQt6" 2>/dev/null || {
    warn "python-pyqt6 not found — installing..."
    pacman -S --needed --noconfirm python-pyqt6 || error "Failed to install python-pyqt6"
}

# Optional: power-profiles-daemon for KDE power mode sync
if ! command -v powerprofilesctl &>/dev/null; then
    warn "powerprofilesctl not found — KDE power-mode sync disabled."
    warn "Install with: sudo pacman -S power-profiles-daemon"
fi

# ── acer-nitro group ───────────────────────────────────────────────────────
groupadd --system acer-nitro 2>/dev/null || true
if [[ -n "$REAL_USER" ]]; then
    usermod -aG acer-nitro "$REAL_USER"
fi

# ── App files ──────────────────────────────────────────────────────────────
info "Installing app..."
install -dm755 "$INSTALL_DIR"
# Copy app files including package markers
cp -r config controller ui main.py "$INSTALL_DIR/"
touch "$INSTALL_DIR/config/__init__.py" "$INSTALL_DIR/controller/__init__.py" "$INSTALL_DIR/ui/__init__.py"
install -Dm755 linuwu-sense-gui /usr/bin/linuwu-sense-gui

# ── .desktop + icon ────────────────────────────────────────────────────────
install -Dm644 linuwu-sense-gui.desktop \
    /usr/share/applications/linuwu-sense-gui.desktop
install -Dm644 assets/linuwu-sense-gui.svg \
    /usr/share/icons/hicolor/scalable/apps/linuwu-sense-gui.svg
gtk-update-icon-cache /usr/share/icons/hicolor 2>/dev/null || true
update-desktop-database /usr/share/applications 2>/dev/null || true

# ── udev — sysfs permissions ───────────────────────────────────────────────
info "Installing udev rules..."
install -Dm644 60-linuwu-sense.rules /etc/udev/rules.d/60-linuwu-sense.rules
install -Dm755 set-sysfs-perms.sh    "$INSTALL_DIR/set-sysfs-perms.sh"
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger --subsystem-match=platform 2>/dev/null || true
udevadm trigger --subsystem-match=cpu      2>/dev/null || true

# ── udev — Nitro hardware key ──────────────────────────────────────────────
install -Dm644 99-nitro-key.hwdb /etc/udev/hwdb.d/99-nitro-key.hwdb
systemd-hwdb update  2>/dev/null || true
udevadm trigger      2>/dev/null || true

# ── KDE global shortcut — write config directly, no qdbus needed ───────────
# Works on KDE 5 and KDE 6. The shortcut file is read at session start;
# kglobalaccel picks it up automatically on next login.
if [[ -n "$REAL_HOME" ]]; then
    KDE_CFG="$REAL_HOME/.config/kglobalshortcutsrc"
    # Remove any stale entry for this app first, then append a clean one.
    if [[ -f "$KDE_CFG" ]]; then
        # Strip the old block (between [linuwu-sense-gui.desktop] and the next [)
        python3 - "$KDE_CFG" << 'PYEOF'
import sys, re
path = sys.argv[1]
txt  = open(path).read()
txt  = re.sub(r'\[linuwu-sense-gui\.desktop\][^\[]*', '', txt, flags=re.S)
open(path, 'w').write(txt.strip() + '\n')
PYEOF
    fi
    # Append the new shortcut block
    # Launch1 = XF86Launch1 = the Nitro/PredatorSense hardware key
    cat >> "$KDE_CFG" << 'EOF'

[linuwu-sense-gui.desktop]
_k_friendly_name=linuwu sense
_launch=Launch1,none,linuwu sense
EOF
    chown "$REAL_USER:" "$KDE_CFG" 2>/dev/null || true
fi

# ── Done ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}✔  linuwu sense installed.${NC}"
echo ""
warn "Log out and back in for group permissions and the Nitro key to activate."
warn "Kernel module required:  sudo modprobe linuwu_sense"
