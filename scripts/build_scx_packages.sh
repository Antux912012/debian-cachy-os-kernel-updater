#!/usr/bin/env bash
set -e

SCX_VERSION="1.1.4"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCX_SRC_DIR="${PROJECT_ROOT}/target/scx-src"
DIST_DIR="${PROJECT_ROOT}/dist/scx"
STAGE_DIR="${PROJECT_ROOT}/target/pkg-scx-stage"

SCHEDULERS=(
    "scx_bpfland"
    "scx_lavd"
    "scx_flash"
    "scx_rusty"
    "scx_cosmos"
    "scx_p2dq"
    "scx_beerland"
    "scx_rustland"
    "scx_layered"
    "scx_tickless"
    "scx_cake"
    "scx_eevdf"
    "scx_mitosis"
    "scx_rlfifo"
)

echo "==> Preparing sched-ext (scx v${SCX_VERSION}) source and binaries..."
if [ ! -d "${SCX_SRC_DIR}" ]; then
    git clone --branch "v${SCX_VERSION}" --depth 1 https://github.com/sched-ext/scx.git "${SCX_SRC_DIR}"
fi

MISSING_BIN=0
for s in "${SCHEDULERS[@]}"; do
    if [ ! -f "${SCX_SRC_DIR}/target/release-tiny/${s}" ]; then
        MISSING_BIN=1
        break
    fi
done

if [ "${MISSING_BIN}" -eq 1 ]; then
    echo "==> Compiling sched-ext schedulers with Cargo (release-tiny profile)..."
    PKG_ARGS=()
    for s in "${SCHEDULERS[@]}"; do
        PKG_ARGS+=("-p" "${s}")
    done
    (cd "${SCX_SRC_DIR}" && cargo build --profile=release-tiny "${PKG_ARGS[@]}")
fi

rm -rf "${STAGE_DIR}"
mkdir -p "${DIST_DIR}"
mkdir -p "${STAGE_DIR}/usr/bin"
mkdir -p "${STAGE_DIR}/etc/default"
mkdir -p "${STAGE_DIR}/lib/systemd/system"

echo "==> Staging compiled scx_* binaries..."
for s in "${SCHEDULERS[@]}"; do
    cp -f "${SCX_SRC_DIR}/target/release-tiny/${s}" "${STAGE_DIR}/usr/bin/${s}"
    strip "${STAGE_DIR}/usr/bin/${s}" 2>/dev/null || true
    chmod 0755 "${STAGE_DIR}/usr/bin/${s}"
done

# Create scxctl helper CLI for unified command-line and service control
cat << 'SCXCTL_EOF' > "${STAGE_DIR}/usr/bin/scxctl"
#!/usr/bin/env bash
set -e

ACTION="${1:-get}"
shift || true

SCHED=""
MODE="auto"

while [ $# -gt 0 ]; do
    case "$1" in
        --sched|-s)
            SCHED="$2"
            shift 2
            ;;
        --mode|-m)
            MODE="$2"
            shift 2
            ;;
        *)
            if [ -z "$SCHED" ]; then
                SCHED="$1"
            fi
            shift
            ;;
    esac
done

normalize_sched() {
    local raw="$1"
    if [[ "$raw" != scx_* ]]; then
        echo "scx_${raw}"
    else
        echo "$raw"
    fi
}

mode_flags() {
    local sched="$1"
    local m="$2"
    case "${m}:${sched}" in
        1:scx_bpfland|gaming:scx_bpfland) echo "-m performance" ;;
        1:scx_lavd|gaming:scx_lavd) echo "--performance" ;;
        1:scx_flash|gaming:scx_flash) echo "-m performance" ;;
        1:scx_p2dq|gaming:scx_p2dq) echo "--sched-mode performance" ;;
        2:scx_bpfland|powersave:scx_bpfland) echo "-m powersave" ;;
        2:scx_lavd|powersave:scx_lavd) echo "--powersave" ;;
        2:scx_flash|powersave:scx_flash) echo "-m powersave" ;;
        2:scx_p2dq|powersave:scx_p2dq) echo "--sched-mode efficiency" ;;
        3:scx_bpfland|lowlatency:scx_bpfland) echo "-s 5000 -S 500" ;;
        3:scx_lavd|lowlatency:scx_lavd) echo "--performance" ;;
        3:scx_flash|lowlatency:scx_flash) echo "-m all" ;;
        4:scx_bpfland|server:scx_bpfland) echo "-s 20000" ;;
        4:scx_cosmos|server:scx_cosmos) echo "-s 20000" ;;
        *) echo "" ;;
    esac
}

case "$ACTION" in
    get|status)
        if [ -f /sys/kernel/sched_ext/state ]; then
            STATE=$(cat /sys/kernel/sched_ext/state 2>/dev/null || echo "disabled")
            OPS=$(cat /sys/kernel/sched_ext/root/ops 2>/dev/null || echo "none")
            echo "state: ${STATE} (active: ${OPS})"
        else
            echo "sched_ext not supported by running kernel"
        fi
        ;;
    list)
        for b in /usr/bin/scx_* /usr/local/bin/scx_*; do
            [ -x "$b" ] && basename "$b"
        done | sort -u
        ;;
    stop)
        pkill -TERM -x 'scx_[a-z0-9_]+' 2>/dev/null || true
        sleep 0.2
        pkill -KILL -x 'scx_[a-z0-9_]+' 2>/dev/null || true
        ;;
    switch|start)
        if [ -z "$SCHED" ] || [ "$SCHED" = "none" ]; then
            "$0" stop
            exit 0
        fi
        TARGET=$(normalize_sched "$SCHED")
        BIN=$(command -v "$TARGET" || true)
        if [ -z "$BIN" ]; then
            echo "Error: scheduler binary '$TARGET' not found" >&2
            exit 127
        fi
        "$0" stop
        FLAGS=$(mode_flags "$TARGET" "$MODE")
        if [ -n "$FLAGS" ]; then
            nohup "$BIN" $FLAGS >/tmp/mithrandir-${TARGET}.log 2>&1 &
            sleep 0.3
            if ! kill -0 $! 2>/dev/null; then
                nohup "$BIN" >/tmp/mithrandir-${TARGET}.log 2>&1 &
                sleep 0.3
            fi
        else
            nohup "$BIN" >/tmp/mithrandir-${TARGET}.log 2>&1 &
            sleep 0.3
        fi
        ;;
    *)
        echo "Usage: scxctl [get|list|start|switch|stop] [--sched <name>] [--mode <mode>]"
        exit 1
        ;;
esac
SCXCTL_EOF
chmod 0755 "${STAGE_DIR}/usr/bin/scxctl"

cat << 'DEFAULT_EOF' > "${STAGE_DIR}/etc/default/scx"
# Default configuration for sched-ext (scx) service
SCX_SCHEDULER=scx_bpfland
SCX_FLAGS=""
DEFAULT_EOF

cat << 'SERVICE_EOF' > "${STAGE_DIR}/lib/systemd/system/scx.service"
[Unit]
Description=sched-ext (SCX) Pluggable BPF Kernel Scheduler
After=multi-user.target
ConditionPathExists=/sys/kernel/sched_ext/state

[Service]
Type=simple
EnvironmentFile=-/etc/default/scx
ExecStart=/bin/sh -c 'exec /usr/bin/${SCX_SCHEDULER:-scx_bpfland} ${SCX_FLAGS}'
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
SERVICE_EOF

# 1. Build Portable Tarball (.tar.gz)
TARBALL_PATH="${DIST_DIR}/scx-scheds-${SCX_VERSION}-x86_64.tar.gz"
echo "==> Building portable tarball: ${TARBALL_PATH}"
tar -C "${STAGE_DIR}" -czf "${TARBALL_PATH}" usr etc lib

# 2. Build Debian Package (.deb)
DEB_ROOT="${PROJECT_ROOT}/target/pkg-scx-deb"
rm -rf "${DEB_ROOT}"
mkdir -p "${DEB_ROOT}/DEBIAN"
cp -a "${STAGE_DIR}/usr" "${DEB_ROOT}/"
cp -a "${STAGE_DIR}/etc" "${DEB_ROOT}/"
cp -a "${STAGE_DIR}/lib" "${DEB_ROOT}/"

INSTALLED_KB=$(du -sk "${DEB_ROOT}/usr" | awk '{print $1}')
cat << DEB_CTRL_EOF > "${DEB_ROOT}/DEBIAN/control"
Package: scx-scheds
Version: ${SCX_VERSION}-1
Section: kernel
Priority: optional
Architecture: amd64
Provides: scx, scx-tools
Replaces: scx, scx-tools
Depends: libc6, libelf1 | libelf1t64, zlib1g, libzstd1
Installed-Size: ${INSTALLED_KB}
Maintainer: Antonio <https://github.com/Antux912012>
Homepage: https://github.com/sched-ext/scx
Description: Pluggable BPF CPU schedulers (sched-ext / scx) built for Mithrandir & CachyOS
 Official sched-ext (scx v${SCX_VERSION}) userspace BPF CPU schedulers including
 scx_bpfland, scx_lavd, scx_flash, scx_rusty, scx_cosmos, scx_p2dq, scx_beerland,
 scx_rustland, scx_layered, scx_tickless, scx_cake, scx_eevdf, scx_mitosis,
 scx_rlfifo, and scxctl management utility.
DEB_CTRL_EOF

cat << 'POSTINST_EOF' > "${DEB_ROOT}/DEBIAN/postinst"
#!/bin/sh
set -e
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl daemon-reload >/dev/null 2>&1 || true
fi
exit 0
POSTINST_EOF
chmod 0755 "${DEB_ROOT}/DEBIAN/postinst"

DEB_PATH="${DIST_DIR}/scx-scheds_${SCX_VERSION}_amd64.deb"
echo "==> Building Debian package: ${DEB_PATH}"
dpkg-deb --root-owner-group --build -Zxz "${DEB_ROOT}" "${DEB_PATH}"

# 3. Build RPM Package (.rpm) if rpmbuild is available
if command -v rpmbuild >/dev/null 2>&1; then
    RPM_TOPDIR="${PROJECT_ROOT}/target/pkg-scx-rpm"
    rm -rf "${RPM_TOPDIR}"
    mkdir -p "${RPM_TOPDIR}"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

    cat << RPM_SPEC_EOF > "${RPM_TOPDIR}/SPECS/scx-scheds.spec"
Name:           scx-scheds
Version:        ${SCX_VERSION}
Release:        1
Summary:        Pluggable BPF CPU schedulers (sched-ext / scx) for Mithrandir
License:        GPL-2.0-only
URL:            https://github.com/sched-ext/scx
BuildArch:      x86_64
Provides:       scx = ${SCX_VERSION}
Provides:       scx-tools = ${SCX_VERSION}
AutoReqProv:    no
Requires:       glibc, elfutils-libelf, zlib, libzstd

%define _binary_payload w9.xzdio
%define _build_id_links none

%description
Official sched-ext (scx v${SCX_VERSION}) userspace BPF CPU schedulers including
scx_bpfland, scx_lavd, scx_flash, scx_rusty, scx_cosmos, scx_p2dq, scx_beerland,
scx_rustland, scx_layered, scx_tickless, scx_cake, scx_eevdf, scx_mitosis,
scx_rlfifo, and scxctl management utility.

%install
mkdir -p %{buildroot}/usr/bin
mkdir -p %{buildroot}/etc/default
mkdir -p %{buildroot}/usr/lib/systemd/system
cp -a ${STAGE_DIR}/usr/bin/* %{buildroot}/usr/bin/
cp -a ${STAGE_DIR}/etc/default/scx %{buildroot}/etc/default/scx
cp -a ${STAGE_DIR}/lib/systemd/system/scx.service %{buildroot}/usr/lib/systemd/system/scx.service

%files
/usr/bin/scx_*
/usr/bin/scxctl
%config(noreplace) /etc/default/scx
/usr/lib/systemd/system/scx.service
RPM_SPEC_EOF

    echo "==> Building Fedora/openSUSE RPM package..."
    rpmbuild -bb --define "_topdir ${RPM_TOPDIR}" "${RPM_TOPDIR}/SPECS/scx-scheds.spec"
    cp -f "${RPM_TOPDIR}"/RPMS/x86_64/scx-scheds-*.rpm "${DIST_DIR}/scx-scheds-${SCX_VERSION}-1.x86_64.rpm"
fi

echo "==> Built sched-ext redistributable packages in ${DIST_DIR}:"
ls -lh "${DIST_DIR}"
