# Maintainer: friday06 <your@email.com>
# Kernel module by: 0x7375646F (sudo) <https://github.com/0x7375646F/Linuwu-Sense>

pkgname=linuwu-sense-gui
pkgver=1.0.0
pkgrel=1
pkgdesc="KDE/PyQt6 GUI for Acer Predator & Nitro laptops via the linuwu_sense kernel module"
arch=('any')
url="https://github.com/friday06/linuwu-sense-gui"
license=('GPL-3.0-or-later')
depends=('python' 'python-pyqt6')
optdepends=(
    'linuwu-sense-dkms: the kernel module this GUI controls'
    'power-profiles-daemon: KDE power-mode sync via powerprofilesctl'
    'nvidia-utils: nvidia-smi GPU temperature and load readout'
    'plasma-desktop: KDE global shortcut (Nitro key) registration'
)
source=("$pkgname-$pkgver.tar.gz::https://github.com/friday06/$pkgname/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')

package() {
    cd "$srcdir/$pkgname-$pkgver"

    local libdir="$pkgdir/usr/lib/$pkgname"

    # Python application files
    install -dm755 "$libdir"
    cp -r config controller ui main.py "$libdir/"
    touch "$libdir/config/__init__.py" "$libdir/controller/__init__.py" "$libdir/ui/__init__.py"

    # Launcher
    install -Dm755 linuwu-sense-gui       "$pkgdir/usr/bin/linuwu-sense-gui"

    # Desktop integration
    install -Dm644 linuwu-sense-gui.desktop \
        "$pkgdir/usr/share/applications/linuwu-sense-gui.desktop"
    install -Dm644 assets/linuwu-sense-gui.svg \
        "$pkgdir/usr/share/icons/hicolor/scalable/apps/linuwu-sense-gui.svg"

    # udev rules (sysfs permissions + Nitro key hwdb)
    install -Dm644 60-linuwu-sense.rules \
        "$pkgdir/etc/udev/rules.d/60-linuwu-sense.rules"
    install -Dm644 99-nitro-key.hwdb \
        "$pkgdir/etc/udev/hwdb.d/99-nitro-key.hwdb"
    install -Dm755 set-sysfs-perms.sh "$libdir/set-sysfs-perms.sh"

    # Documentation
    install -Dm644 README.md  "$pkgdir/usr/share/doc/$pkgname/README.md"
    install -Dm644 CREDITS    "$pkgdir/usr/share/doc/$pkgname/CREDITS"
    install -Dm644 LICENSE    "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}

post_install() {
    echo ""
    echo "  ──────────────────────────────────────────────"
    echo "  linuwu-sense-gui installed successfully"
    echo "  ──────────────────────────────────────────────"
    echo ""
    if ! lsmod 2>/dev/null | grep -q "^linuwu_sense"; then
        echo "  ⚠  linuwu_sense kernel module not detected."
        echo "     Install it from: https://github.com/0x7375646F/Linuwu-Sense"
        echo "     Then run: sudo modprobe linuwu_sense"
        echo ""
    fi
    echo "  ⚠  Log out and back in to activate hardware access permissions."
    echo "     Launch: linuwu-sense-gui"
    echo ""
}


post_remove() {
    # Clear user cache and config on pacman -R
    for dir in /home/*; do
        [[ -d "$dir" ]] || continue
        rm -rf "$dir/.config/linuwu-sense"
        rm -rf "$dir/.config/linuwu-sense-gui"
        rm -rf "$dir/.cache/linuwu-sense"
        rm -rf "$dir/.cache/linuwu-sense-gui"
    done
    update-desktop-database /usr/share/applications 2>/dev/null || true
    gtk-update-icon-cache /usr/share/icons/hicolor 2>/dev/null || true
    udevadm control --reload-rules 2>/dev/null || true
    systemd-hwdb update 2>/dev/null || true
}
