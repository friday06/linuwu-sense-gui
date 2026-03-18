#!/usr/bin/env bash
# uninstall.sh — Remove linuwu-sense-gui
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; exit 1; }

[[ "$EUID" -ne 0 ]] && error "Please run as root: sudo ./uninstall.sh"

# Resolve the real user (not root)
REAL_USER="${SUDO_USER:-}"
[[ -z "$REAL_USER" || "$REAL_USER" == "root" ]] && \
    REAL_USER="$(logname 2>/dev/null || true)"
REAL_HOME="$(getent passwd "$REAL_USER" 2>/dev/null | cut -d: -f6 || true)"

info "Removing application files..."
rm -rf /usr/lib/linuwu-sense-gui
rm -f  /usr/bin/linuwu-sense-gui
rm -f  /usr/share/applications/linuwu-sense-gui.desktop
rm -f  /usr/share/icons/hicolor/scalable/apps/linuwu-sense-gui.svg
rm -f  /usr/share/polkit-1/actions/org.linuwu-sense.gui.policy
rm -f  /usr/share/doc/linuwu-sense-gui/README.md
rm -f  /usr/share/licenses/linuwu-sense-gui/LICENSE

info "Removing udev rules..."
rm -f /etc/udev/rules.d/60-linuwu-sense.rules
rm -f /etc/udev/hwdb.d/99-nitro-key.hwdb
udevadm control --reload-rules 2>/dev/null || true
systemd-hwdb update 2>/dev/null || true

info "Clearing user cache and config..."
if [[ -n "$REAL_HOME" ]]; then
    # QSettings config (Customise prefs, welcome shown state)
    rm -rf "$REAL_HOME/.config/linuwu-sense"
    rm -rf "$REAL_HOME/.config/linuwu-sense-gui"
    # Qt / application cache
    rm -rf "$REAL_HOME/.cache/linuwu-sense"
    rm -rf "$REAL_HOME/.cache/linuwu-sense-gui"
    # KDE global shortcut entry
    if [[ -f "$REAL_HOME/.config/kglobalshortcutsrc" ]]; then
        python3 - "$REAL_HOME/.config/kglobalshortcutsrc" << 'PYEOF'
import sys, re
path = sys.argv[1]
txt  = open(path).read()
txt  = re.sub(r'\[linuwu-sense-gui\.desktop\][^\[]*', '', txt, flags=re.S)
open(path, 'w').write(txt.strip() + '\n')
PYEOF
        warn "Removed KDE global shortcut entry."
    fi
fi

update-desktop-database /usr/share/applications 2>/dev/null || true
gtk-update-icon-cache /usr/share/icons/hicolor 2>/dev/null || true

echo ""
echo -e "${GREEN}✔  linuwu-sense-gui uninstalled successfully.${NC}"
warn "The acer-nitro group was not removed (other apps may use it)."
warn "To remove it manually: sudo groupdel acer-nitro"
