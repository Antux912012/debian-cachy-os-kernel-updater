#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

PKG_NAME="cachy-kernel-updater"
PKG_VER=$(grep -m1 '^APP_VERSION' main.py | sed -E 's/.*"([^"]+)".*/\1/')
APP_ID="io.github.Antux912012.debian-cachy-os-kernel-updater"
RPM_NAME="${PKG_NAME}-${PKG_VER}-1.noarch.rpm"

echo "==> Building ${PKG_NAME} RPM package (${RPM_NAME})..."

RPM_TOP="${DIR}/rpm_dist"
rm -rf "${RPM_TOP}"
mkdir -p "${RPM_TOP}"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

cat > "${RPM_TOP}/SPECS/${PKG_NAME}.spec" << EOF
%global debug_package %{nil}
Name:           ${PKG_NAME}
Version:        ${PKG_VER}
Release:        1%{?dist}
Summary:        Debian CachyOS Kernel Installer & Updater (GTK4/Libadwaita)
License:        GPL-3.0-or-later
URL:            https://github.com/Antux912012/debian-cachy-os-kernel-updater
BuildArch:      noarch
Requires:       python3 python3-gobject python3-requests gtk4 libadwaita polkit hicolor-icon-theme

%description
A native GTK4/Libadwaita application to check, compile, install, and
rollback CachyOS Linux kernels on Debian-based distributions, including
containerized kernel compilation and UEFI Secure Boot MOK signing.

%install
mkdir -p %{buildroot}%{_bindir}
mkdir -p %{buildroot}%{_datadir}/${PKG_NAME}
mkdir -p %{buildroot}%{_datadir}/applications
mkdir -p %{buildroot}%{_datadir}/metainfo
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/scalable/apps
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/48x48/apps
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/128x128/apps
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/256x256/apps
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/512x512/apps

cp -a /workspace/main.py /workspace/kernel_manager.py /workspace/Containerfile /workspace/sign-kernel.sh %{buildroot}%{_datadir}/${PKG_NAME}/
cp -r /workspace/assets %{buildroot}%{_datadir}/${PKG_NAME}/
chmod 755 %{buildroot}%{_datadir}/${PKG_NAME}/sign-kernel.sh

cat > %{buildroot}%{_bindir}/${PKG_NAME} << 'LAUNCHER'
#!/usr/bin/env bash
exec /usr/bin/python3 /usr/share/cachy-kernel-updater/main.py "\$@"
LAUNCHER
chmod 755 %{buildroot}%{_bindir}/${PKG_NAME}

install -m 644 /workspace/${APP_ID}.desktop %{buildroot}%{_datadir}/applications/${APP_ID}.desktop
install -m 644 /workspace/${APP_ID}.metainfo.xml %{buildroot}%{_datadir}/metainfo/${APP_ID}.metainfo.xml
install -m 644 /workspace/assets/${APP_ID}.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/${APP_ID}.svg
install -m 644 /workspace/assets/logo_48.png %{buildroot}%{_datadir}/icons/hicolor/48x48/apps/${APP_ID}.png
install -m 644 /workspace/assets/logo_128.png %{buildroot}%{_datadir}/icons/hicolor/128x128/apps/${APP_ID}.png
install -m 644 /workspace/assets/logo_256.png %{buildroot}%{_datadir}/icons/hicolor/256x256/apps/${APP_ID}.png
install -m 644 /workspace/assets/logo_512.png %{buildroot}%{_datadir}/icons/hicolor/512x512/apps/${APP_ID}.png

%files
%{_bindir}/${PKG_NAME}
%{_datadir}/${PKG_NAME}/*
%{_datadir}/applications/${APP_ID}.desktop
%{_datadir}/metainfo/${APP_ID}.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/${APP_ID}.svg
%{_datadir}/icons/hicolor/48x48/apps/${APP_ID}.png
%{_datadir}/icons/hicolor/128x128/apps/${APP_ID}.png
%{_datadir}/icons/hicolor/256x256/apps/${APP_ID}.png
%{_datadir}/icons/hicolor/512x512/apps/${APP_ID}.png
EOF

podman run --rm --userns=keep-id \
  -v "${DIR}:/workspace:Z" -w /workspace localhost/dev-fedora \
  rpmbuild -bb --define "_topdir /workspace/rpm_dist" "/workspace/rpm_dist/SPECS/${PKG_NAME}.spec"

BUILT_RPM=$(find "${RPM_TOP}/RPMS" -name "${PKG_NAME}-*.rpm" | head -n1)
cp "${BUILT_RPM}" "${DIR}/${RPM_NAME}"
echo "==> RPM package generated successfully: ${DIR}/${RPM_NAME}"
