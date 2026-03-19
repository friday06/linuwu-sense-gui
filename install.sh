#!/usr/bin/env bash
# install.sh — Install linuwu-sense-gui
# Supports Arch Linux and most systemd-based distros.
set -euo pipefail

# ── Colours & helpers ─────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "  ${GREEN}✓${NC}  $*"; }
step()    { echo -e "\n${BOLD}${CYAN}▶  $*${NC}"; }
warn()    { echo -e "  ${YELLOW}⚠${NC}  $*"; }
error()   { echo -e "  ${RED}✗${NC}  $*"; exit 1; }
detail()  { echo -e "     ${NC}\033[2m$*\033[0m"; }

INSTALL_DIR="/usr/lib/linuwu-sense-gui"

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  linuwu-sense-gui — Installer${NC}"
echo -e "  \033[2mAcer Predator & Nitro hardware control\033[0m"
echo -e "  $(printf '─%.0s' {1..44})"

# ── Root check ────────────────────────────────────────────────────────────────
[[ "$EUID" -ne 0 ]] && error "Please run as root: sudo ./install.sh"

# ── Resolve the real user (not root) ─────────────────────────────────────────
REAL_USER="${SUDO_USER:-}"
[[ -z "$REAL_USER" || "$REAL_USER" == "root" ]] && \
    REAL_USER="$(logname 2>/dev/null || true)"
REAL_HOME="$(getent passwd "$REAL_USER" 2>/dev/null | cut -d: -f6 || true)"

# ── Step 1: Kernel module check ───────────────────────────────────────────────
step "Checking kernel module"

if lsmod | grep -q "^linuwu_sense"; then
    info "linuwu_sense module is loaded"
elif modinfo linuwu_sense &>/dev/null; then
    warn "linuwu_sense is installed but not loaded"
    detail "Run: sudo modprobe linuwu_sense"
    detail "To load on boot: echo linuwu_sense | sudo tee /etc/modules-load.d/linuwu_sense.conf"
else
    warn "linuwu_sense kernel module not found"
    detail "This app requires the linuwu_sense kernel module to control hardware."
    detail "Install it from: https://github.com/0x7375646F/Linuwu-Sense"
    detail "Then run: sudo modprobe linuwu_sense"
    detail ""
    detail "Continuing installation — you can install the module later."
fi

# ── Step 2: Python ────────────────────────────────────────────────────────────
step "Checking dependencies"

command -v python3 &>/dev/null || error "python3 not found — install it via your package manager"
info "python3 found — $(python3 --version)"

# PyQt6
_install_pyqt6() {
    echo ""
    echo -e "  ${YELLOW}PyQt6 is not installed.${NC}"
    echo -e "  Please choose how to install it:\n"
    echo -e "  ${BOLD}  1)${NC}  Arch / Manjaro          ${CYAN}pacman -S python-pyqt6${NC}"
    echo -e "  ${BOLD}  2)${NC}  Ubuntu / Debian / Mint  ${CYAN}apt install python3-pyqt6${NC}"
    echo -e "  ${BOLD}  3)${NC}  Fedora / RHEL           ${CYAN}dnf install python3-pyqt6${NC}"
    echo -e "  ${BOLD}  4)${NC}  openSUSE                ${CYAN}zypper install python3-qt6${NC}"
    echo -e "  ${BOLD}  5)${NC}  pip  (any distro)       ${CYAN}pip install PyQt6${NC}"
    echo -e "  ${BOLD}  6)${NC}  Skip — I'll install it myself"
    echo ""
    read -rp "  Enter choice [1-6]: " choice

    case "$choice" in
        1)
            command -v pacman &>/dev/null || error "pacman not found on this system"
            pacman -S --needed --noconfirm python-pyqt6 || error "pacman install failed"
            ;;
        2)
            command -v apt-get &>/dev/null || error "apt-get not found on this system"
            apt-get install -y python3-pyqt6 || error "apt install failed"
            ;;
        3)
            command -v dnf &>/dev/null || error "dnf not found on this system"
            dnf install -y python3-pyqt6 || error "dnf install failed"
            ;;
        4)
            command -v zypper &>/dev/null || error "zypper not found on this system"
            zypper install -y python3-qt6 || error "zypper install failed"
            ;;
        5)
            command -v pip3 &>/dev/null || error "pip3 not found — install python3-pip first"
            pip3 install PyQt6 --break-system-packages || pip3 install PyQt6 || error "pip install failed"
            ;;
        6)
            warn "Skipping PyQt6 install — the app will not launch until PyQt6 is available"
            return
            ;;
        *)
            error "Invalid choice '$choice' — aborting"
            ;;
    esac

    python3 -c "import PyQt6" 2>/dev/null || error "PyQt6 still not importable after install — check the output above"
    info "PyQt6 installed successfully"
}

if python3 -c "import PyQt6" 2>/dev/null; then
    VER=$(python3 -c "import PyQt6.QtCore; print(PyQt6.QtCore.PYQT_VERSION_STR)" 2>/dev/null || echo "unknown")
    info "PyQt6 found — v$VER"
else
    _install_pyqt6
fi

# power-profiles-daemon (optional)
if command -v powerprofilesctl &>/dev/null; then
    info "powerprofilesctl found — KDE power-mode sync enabled"
else
    warn "powerprofilesctl not found — KDE power-mode sync will be disabled"
    detail "Install power-profiles-daemon and enable the service to enable this feature"
fi

# ── Step 3: Group & permissions ───────────────────────────────────────────────
step "Setting up hardware access"

groupadd --system acer-nitro 2>/dev/null && \
    info "Created acer-nitro group" || \
    info "acer-nitro group already exists"

if [[ -n "$REAL_USER" ]]; then
    usermod -aG acer-nitro "$REAL_USER"
    info "Added $REAL_USER to acer-nitro group"
fi

# ── Step 4: Application files ─────────────────────────────────────────────────
step "Installing application"

install -dm755 "$INSTALL_DIR"
cp -r config controller ui main.py "$INSTALL_DIR/"
touch "$INSTALL_DIR/config/__init__.py" \
      "$INSTALL_DIR/controller/__init__.py" \
      "$INSTALL_DIR/ui/__init__.py"
install -Dm755 linuwu-sense-gui /usr/bin/linuwu-sense-gui
info "Application files installed to $INSTALL_DIR"

# ── Step 5: Desktop integration ───────────────────────────────────────────────
step "Registering with desktop environment"

install -Dm644 linuwu-sense-gui.desktop \
    /usr/share/applications/linuwu-sense-gui.desktop
info "App menu entry registered"

install -Dm644 assets/linuwu-sense-gui.svg \
    /usr/share/icons/hicolor/scalable/apps/linuwu-sense-gui.svg
gtk-update-icon-cache /usr/share/icons/hicolor 2>/dev/null || true
update-desktop-database /usr/share/applications 2>/dev/null || true
info "Icon installed"

install -Dm644 org.linuwu-sense.gui.policy \
    /usr/share/polkit-1/actions/org.linuwu-sense.gui.policy
info "Polkit policy installed"

# ── Step 6: udev rules ────────────────────────────────────────────────────────
step "Installing udev rules"

install -Dm644 60-linuwu-sense.rules /etc/udev/rules.d/60-linuwu-sense.rules
install -Dm755 set-sysfs-perms.sh    "$INSTALL_DIR/set-sysfs-perms.sh"
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger --subsystem-match=platform 2>/dev/null || true
info "Sysfs permission rules installed"

install -Dm644 99-nitro-key.hwdb /etc/udev/hwdb.d/99-nitro-key.hwdb
systemd-hwdb update 2>/dev/null || true
udevadm trigger 2>/dev/null || true
info "Nitro key mapping installed"

# ── Step 7: KDE shortcut ──────────────────────────────────────────────────────
step "Configuring KDE shortcut"

if [[ -n "$REAL_HOME" ]]; then
    KDE_CFG="$REAL_HOME/.config/kglobalshortcutsrc"
    if [[ -f "$KDE_CFG" ]]; then
        python3 - "$KDE_CFG" << 'PYEOF'
import sys, re
path = sys.argv[1]
txt  = open(path).read()
txt  = re.sub(r'\[linuwu-sense-gui\.desktop\][^\[]*', '', txt, flags=re.S)
open(path, 'w').write(txt.strip() + '\n')
PYEOF
    fi
    cat >> "$KDE_CFG" << 'KEOF'

[linuwu-sense-gui.desktop]
_k_friendly_name=linuwu sense
_launch=Launch1,none,linuwu sense
KEOF
    chown "$REAL_USER:" "$KDE_CFG" 2>/dev/null || true
    info "Nitro key shortcut registered (takes effect after re-login)"
else
    warn "Could not detect user home — KDE shortcut not configured"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "  $(printf '─%.0s' {1..44})"
echo -e "  ${BOLD}${GREEN}Installation complete!${NC}"
echo ""
echo -e "  ${BOLD}Next steps:${NC}"

if ! lsmod | grep -q "^linuwu_sense"; then
    echo -e "  ${YELLOW}1.${NC} Install the kernel module:"
    echo -e "     ${CYAN}https://github.com/0x7375646F/Linuwu-Sense${NC}"
    echo -e "     then run: ${BOLD}sudo modprobe linuwu_sense${NC}"
    echo ""
    echo -e "  ${YELLOW}2.${NC} Log out and back in to activate group permissions"
    echo -e "     and the NitroSense hardware key shortcut."
else
    echo -e "  ${YELLOW}1.${NC} Log out and back in to activate group permissions"
    echo -e "     and the NitroSense hardware key shortcut."
fi
echo ""
echo -e "  Launch: ${BOLD}linuwu-sense-gui${NC}"
echo ""
