#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

PKG_NAME="cachy-kernel-updater"
PKG_VER=$(grep -m1 '^APP_VERSION' main.py | sed -E 's/.*"([^"]+)".*/\1/')
DEB_DIR="deb_dist/${PKG_NAME}_${PKG_VER}_all"

echo "=== Cleaning previous deb staging directory ==="
rm -rf deb_dist
mkdir -p "${DEB_DIR}/DEBIAN"
mkdir -p "${DEB_DIR}/usr/bin"
mkdir -p "${DEB_DIR}/usr/share/cachy-kernel-updater"
mkdir -p "${DEB_DIR}/usr/share/applications"
mkdir -p "${DEB_DIR}/usr/share/metainfo"
mkdir -p "${DEB_DIR}/usr/share/icons/hicolor/scalable/apps"
mkdir -p "${DEB_DIR}/usr/share/icons/hicolor/48x48/apps"
mkdir -p "${DEB_DIR}/usr/share/icons/hicolor/128x128/apps"
mkdir -p "${DEB_DIR}/usr/share/icons/hicolor/256x256/apps"
mkdir -p "${DEB_DIR}/usr/share/icons/hicolor/512x512/apps"

echo "=== Creating Debian control file ==="
cat << EOF > "${DEB_DIR}/DEBIAN/control"
Package: ${PKG_NAME}
Version: ${PKG_VER}
Section: admin
Priority: optional
Architecture: all
Maintainer: Antonio <antonio@localhost>
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, python3-requests, gir1.2-gtk-4.0, gir1.2-adw-1, policykit-1 | polkitd, build-essential, bc, bison, flex, libssl-dev, libelf-dev, libncurses-dev, libdw-dev, libudev-dev, libpci-dev, libiberty-dev, autoconf, dwarves, pahole, zstd, xz-utils, lz4, cpio, rsync, kmod, fakeroot, dpkg-dev, debhelper, devscripts, clang, llvm, lld, sbsigntool, mokutil, openssl, linux-base, initramfs-tools
Recommends: podman | docker.io
Description: Debian CachyOS Kernel Installer & Updater (GTK4/Adwaita)
 A native GTK4/Libadwaita application to check, compile, install, and
 rollback CachyOS Linux kernels on Debian systems.
EOF

echo "===Copying application files ==="
cp -v main.py kernel_manager.py Containerfile sign-kernel.sh "${DEB_DIR}/usr/share/cachy-kernel-updater/"
cp -rv assets "${DEB_DIR}/usr/share/cachy-kernel-updater/"
chmod -R a+rX "${DEB_DIR}/usr/share/cachy-kernel-updater/assets"
chmod 644 "${DEB_DIR}/usr/share/cachy-kernel-updater/"*.*
chmod 755 "${DEB_DIR}/usr/share/cachy-kernel-updater/sign-kernel.sh"

echo "=== Creating launcher binary (/usr/bin/cachy-kernel-updater) ==="
cat << 'EOF' > "${DEB_DIR}/usr/bin/cachy-kernel-updater"
#!/usr/bin/env bash
exec /usr/bin/python3 /usr/share/cachy-kernel-updater/main.py "$@"
EOF
chmod 755 "${DEB_DIR}/usr/bin/cachy-kernel-updater"

echo "=== Installing Desktop launcher entry ==="
cp -v io.github.Antux912012.debian-cachy-os-kernel-updater.desktop "${DEB_DIR}/usr/share/applications/io.github.Antux912012.debian-cachy-os-kernel-updater.desktop"
chmod 644 "${DEB_DIR}/usr/share/applications/io.github.Antux912012.debian-cachy-os-kernel-updater.desktop"

echo "=== Installing AppStream metainfo ==="
cp -v io.github.Antux912012.debian-cachy-os-kernel-updater.metainfo.xml "${DEB_DIR}/usr/share/metainfo/"
chmod 644 "${DEB_DIR}/usr/share/metainfo/io.github.Antux912012.debian-cachy-os-kernel-updater.metainfo.xml"

echo "=== Installing application icons ==="
cp -v assets/io.github.Antux912012.debian-cachy-os-kernel-updater.svg "${DEB_DIR}/usr/share/icons/hicolor/scalable/apps/"
cp -v assets/logo_48.png "${DEB_DIR}/usr/share/icons/hicolor/48x48/apps/io.github.Antux912012.debian-cachy-os-kernel-updater.png"
cp -v assets/logo_128.png "${DEB_DIR}/usr/share/icons/hicolor/128x128/apps/io.github.Antux912012.debian-cachy-os-kernel-updater.png"
cp -v assets/logo_256.png "${DEB_DIR}/usr/share/icons/hicolor/256x256/apps/io.github.Antux912012.debian-cachy-os-kernel-updater.png"
cp -v assets/logo_512.png "${DEB_DIR}/usr/share/icons/hicolor/512x512/apps/io.github.Antux912012.debian-cachy-os-kernel-updater.png"

chmod 644 "${DEB_DIR}/usr/share/icons/hicolor/scalable/apps/"*.svg
chmod 644 "${DEB_DIR}/usr/share/icons/hicolor/"*/apps/*.png

echo "=== Building .deb package with dpkg-deb ==="
dpkg-deb --root-owner-group --build "${DEB_DIR}" "deb_dist/${PKG_NAME}_${PKG_VER}_all.deb"

echo "=== Debian Package Created Successfully ==="
ls -lh "deb_dist/${PKG_NAME}_${PKG_VER}_all.deb"
