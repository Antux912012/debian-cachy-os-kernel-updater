#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

echo "=== Preparing staging environment in AppDir ==="
mkdir -p AppDir/usr/share/cachy-kernel-updater
mkdir -p AppDir/usr/share/applications
mkdir -p AppDir/usr/share/icons/hicolor/scalable/apps
mkdir -p AppDir/usr/share/icons/hicolor/256x256/apps
mkdir -p AppDir/usr/share/icons/hicolor/512x512/apps

cp -v main.py kernel_manager.py sign-kernel.sh AppDir/usr/share/cachy-kernel-updater/
chmod 755 AppDir/usr/share/cachy-kernel-updater/sign-kernel.sh

# Copy official icons into AppDir
cp -v assets/io.github.Antux912012.debian-cachy-os-kernel-updater.svg AppDir/usr/share/icons/hicolor/scalable/apps/
cp -v assets/logo_256.png AppDir/usr/share/icons/hicolor/256x256/apps/io.github.Antux912012.debian-cachy-os-kernel-updater.png
cp -v assets/logo_512.png AppDir/usr/share/icons/hicolor/512x512/apps/io.github.Antux912012.debian-cachy-os-kernel-updater.png
cp -v assets/logo_256.png AppDir/io.github.Antux912012.debian-cachy-os-kernel-updater.png
cp -v assets/io.github.Antux912012.debian-cachy-os-kernel-updater.svg AppDir/io.github.Antux912012.debian-cachy-os-kernel-updater.svg

# Create desktop file in AppDir
cat << 'EOF' > AppDir/usr/share/applications/io.github.Antux912012.debian-cachy-os-kernel-updater.desktop
[Desktop Entry]
Name=CachyOS Kernel Updater
GenericName=Kernel Updater
Comment=Check, compile, install, and rollback CachyOS kernels on Debian
Exec=usr/bin/python3 usr/share/cachy-kernel-updater/main.py
Icon=io.github.Antux912012.debian-cachy-os-kernel-updater
Terminal=false
Type=Application
Categories=System;Settings;GTK;
StartupNotify=true
EOF
cp -v AppDir/usr/share/applications/io.github.Antux912012.debian-cachy-os-kernel-updater.desktop AppDir/io.github.Antux912012.debian-cachy-os-kernel-updater.desktop

# Ensure fake apt-key exists to bypass deprecated Debian 12 check in appimage-builder
if [ ! -f "apt-key" ]; then
    echo -e '#!/bin/bash\nexit 0' > apt-key
    chmod +x apt-key
fi

echo "=== Building AppImage ==="
PATH="$PWD:$PATH" appimage-builder --recipe AppImageBuilder.yml --skip-test

echo "=== Build Complete ==="
ls -lh *.AppImage
