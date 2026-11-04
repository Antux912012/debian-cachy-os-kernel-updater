#!/usr/bin/env bash
# ==============================================================================
# CachyOS Debian Kernel Updater - Co-Located MOK Certificate & Signing Tool
# Modes:
#   sign-kernel.sh --status <output_dir>
#   sign-kernel.sh --install-and-sign <output_dir> [mok_password]
#   sign-kernel.sh --sign-only <output_dir> [kernel_version_or_auto] [mok_password]
#   sign-kernel.sh --reset-and-recreate <output_dir> [mok_password]
# ==============================================================================
set -euo pipefail

ACTION="${1:-}"
OUTPUT_DIR="${2:-}"
ARG3="${3:-}"
ARG4="${4:-}"

log_info()  { echo "[INFO] $*"; }
log_ok()    { echo "[SUCCESS] $*"; }
log_warn()  { echo "[WARN] $*"; }
log_err()   { echo "[ERROR] $*" >&2; }

# Resolve real non-root user ownership so the desktop app can always read/retrieve certificates
REAL_UID="${PKEXEC_UID:-${SUDO_UID:-$(id -u)}}"
REAL_GID=$(id -g "$REAL_UID" 2>/dev/null || echo "$REAL_UID")
REAL_USER_HOME=$(getent passwd "$REAL_UID" 2>/dev/null | cut -d: -f6 || echo "${HOME:-/root}")

# Active running kernel safety guard
RUNNING_KVER=$(uname -r)

if [[ -z "$OUTPUT_DIR" || "$OUTPUT_DIR" == "auto" ]]; then
    if [[ -d "${REAL_USER_HOME}/kernel-build-deb" ]]; then
        OUTPUT_DIR="${REAL_USER_HOME}/kernel-build-deb"
    else
        OUTPUT_DIR="${REAL_USER_HOME}/.cache/cachy-kernel-build"
    fi
fi

mkdir -p "$OUTPUT_DIR" 2>/dev/null || true
MOK_PRIV="${OUTPUT_DIR}/MOK.priv"
MOK_DER="${OUTPUT_DIR}/MOK.der"
MOK_PEM="${OUTPUT_DIR}/MOK.pem"

SYS_MOK_DIR="/var/lib/shim-signed/mok"

# --- MODE 1: Status Check (Reads directly without requiring root or exclusive lock) ---
if [[ "$ACTION" == "--status" ]]; then
    SB_STATE="disabled"
    # 1. Check kernel EFI variable directly (works in host, container, and Flatpak)
    for efivar in /sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c \
                  /run/host/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c \
                  /sys/firmware/efi/efivars/SecureBoot-* \
                  /run/host/sys/firmware/efi/efivars/SecureBoot-*; do
        if [[ -f "$efivar" ]]; then
            sb_byte=$(od -An -t u1 -j 4 -N 1 "$efivar" 2>/dev/null | tr -d '[:space:]' || true)
            if [[ "$sb_byte" == "1" ]]; then
                SB_STATE="enabled"
                break
            fi
        fi
    done

    # 2. Fallback to mokutil (direct or via flatpak-spawn --host)
    if [[ "$SB_STATE" != "enabled" ]]; then
        if command -v mokutil >/dev/null 2>&1 && mokutil --sb-state 2>/dev/null | grep -qi "SecureBoot enabled"; then
            SB_STATE="enabled"
        elif command -v flatpak-spawn >/dev/null 2>&1 && flatpak-spawn --host mokutil --sb-state 2>/dev/null | grep -qi "SecureBoot enabled"; then
            SB_STATE="enabled"
        fi
    fi

    KEY_EXISTS="no"
    KEY_ENROLLED="no"
    CHECK_DER=""
    if [[ -f "$MOK_DER" ]]; then
        CHECK_DER="$MOK_DER"
        if [[ -f "$MOK_PRIV" && -f "$MOK_PEM" ]]; then
            KEY_EXISTS="yes"
        fi
    elif [[ -f "${SYS_MOK_DIR}/MOK.der" ]]; then
        CHECK_DER="${SYS_MOK_DIR}/MOK.der"
        if [[ -f "${SYS_MOK_DIR}/MOK.priv" && -f "${SYS_MOK_DIR}/MOK.pem" ]]; then
            KEY_EXISTS="yes"
        fi
    fi

    if [[ -n "$CHECK_DER" ]]; then
        if command -v mokutil >/dev/null 2>&1 && mokutil --test-key "$CHECK_DER" 2>&1 | grep -qi "is already enrolled"; then
            KEY_ENROLLED="yes"
        elif command -v flatpak-spawn >/dev/null 2>&1 && flatpak-spawn --host mokutil --test-key "$CHECK_DER" 2>&1 | grep -qi "is already enrolled"; then
            KEY_ENROLLED="yes"
        fi
    fi

    echo "SB_STATE=${SB_STATE}"
    echo "KEY_EXISTS=${KEY_EXISTS}"
    echo "KEY_ENROLLED=${KEY_ENROLLED}"
    echo "CERT_DIR=${OUTPUT_DIR}"
    exit 0
fi

# Concurrency lockfile protection via flock for privileged mutating operations
LOCK_FILE="/run/lock/cachy-kernel-updater.lock"
if [[ ! -d "/run/lock" || ! -w "/run/lock" ]]; then
    LOCK_FILE="/tmp/cachy-kernel-updater-${REAL_UID}.lock"
fi
exec 200>"$LOCK_FILE"
flock -n 200 || { log_err "Another kernel update or signing operation is already running. Aborting."; exit 1; }

if [[ $EUID -ne 0 ]]; then
    log_err "This operation requires root privileges (pkexec)."
    exit 1
fi

# --- Helper: Ensure Required Signing Packages ---
MISSING_PKGS=()
for cmd_pkg in "sbsign:sbsigntool" "sbverify:sbsigntool" "mokutil:mokutil" "openssl:openssl" "update-initramfs:initramfs-tools"; do
    cmd="${cmd_pkg%%:*}"
    pkg="${cmd_pkg##*:}"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        MISSING_PKGS+=("$pkg")
    fi
done
if [[ ${#MISSING_PKGS[@]} -gt 0 ]]; then
    log_info "Installing missing Secure Boot tools: ${MISSING_PKGS[*]}..."
    DEBIAN_FRONTEND=noninteractive apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends "${MISSING_PKGS[@]}"
fi

# --- Helper: Generate Fresh Certificates in <output_dir> ---
generate_certificates_in_output_dir() {
    local force_new="${1:-false}"
    mkdir -p "$OUTPUT_DIR"

    # If certificates exist in /var/lib/shim-signed/mok/ but not in OUTPUT_DIR, import them
    if [[ "$force_new" != "true" && (! -f "$MOK_PRIV" || ! -f "$MOK_DER" || ! -f "$MOK_PEM") && -f "${SYS_MOK_DIR}/MOK.priv" && -f "${SYS_MOK_DIR}/MOK.der" ]]; then
        log_info "Copying existing system MOK certificates into kernel output folder: ${OUTPUT_DIR}..."
        cp -f "${SYS_MOK_DIR}/MOK.priv" "$MOK_PRIV"
        cp -f "${SYS_MOK_DIR}/MOK.der"  "$MOK_DER"
        if [[ -f "${SYS_MOK_DIR}/MOK.pem" ]]; then
            cp -f "${SYS_MOK_DIR}/MOK.pem" "$MOK_PEM"
        else
            openssl x509 -inform DER -in "$MOK_DER" -out "$MOK_PEM"
        fi
    fi

    if [[ "$force_new" == "true" ]] || [[ ! -f "$MOK_PRIV" ]] || [[ ! -f "$MOK_DER" ]] || [[ ! -f "$MOK_PEM" ]]; then
        log_info "Generating fresh MOK certificates in kernel output folder: ${OUTPUT_DIR}..."
        rm -f "$MOK_PRIV" "$MOK_DER" "$MOK_PEM"

        openssl req -new -x509 -newkey rsa:2048 -nodes -days 3650 \
            -outform DER \
            -keyout "$MOK_PRIV" \
            -out "$MOK_DER" \
            -subj "/CN=CachyOS Kernel Signing Key ($(date +%Y-%m-%d))/" \
            -addext "extendedKeyUsage=codeSigning" 2>/dev/null || \
        openssl req -new -x509 -newkey rsa:2048 -nodes -days 3650 \
            -outform DER \
            -keyout "$MOK_PRIV" \
            -out "$MOK_DER" \
            -subj "/CN=CachyOS Kernel Signing Key ($(date +%Y-%m-%d))/"

        openssl x509 -inform DER -in "$MOK_DER" -out "$MOK_PEM"

        # Set ownership to the desktop user so the app and user can always read/retrieve them
        chown "$REAL_UID:$REAL_GID" "$MOK_PRIV" "$MOK_DER" "$MOK_PEM"
        chmod 600 "$MOK_PRIV"
        chmod 644 "$MOK_DER" "$MOK_PEM"
        log_ok "Saved MOK.priv, MOK.der, and MOK.pem in: ${OUTPUT_DIR}"
    else
        log_info "Using existing MOK certificates from: ${OUTPUT_DIR}"
        chown "$REAL_UID:$REAL_GID" "$MOK_PRIV" "$MOK_DER" "$MOK_PEM" 2>/dev/null || true
        chmod 600 "$MOK_PRIV"
        chmod 644 "$MOK_DER" "$MOK_PEM"
    fi

    # Mirror to /var/lib/shim-signed/mok for DKMS & system compatibility
    mkdir -p "$SYS_MOK_DIR"
    cp -f "$MOK_PRIV" "${SYS_MOK_DIR}/MOK.priv"
    cp -f "$MOK_DER"  "${SYS_MOK_DIR}/MOK.der"
    cp -f "$MOK_PEM"  "${SYS_MOK_DIR}/MOK.pem"
    chmod 600 "${SYS_MOK_DIR}/MOK.priv"
    chmod 644 "${SYS_MOK_DIR}/MOK.der" "${SYS_MOK_DIR}/MOK.pem"
}

# --- Helper: Install Persistent Kernel Postinst Hook ---
install_persistent_postinst_hook() {
    local hook_path="/etc/kernel/postinst.d/zz-cachyos-secureboot-sign"
    mkdir -p /etc/kernel/postinst.d
    cat << 'EOF' > "$hook_path"
#!/usr/bin/env bash
KVER="$1"
VMLINUZ="/boot/vmlinuz-${KVER}"
MOK_PRIV="/var/lib/shim-signed/mok/MOK.priv"
MOK_PEM="/var/lib/shim-signed/mok/MOK.pem"
if [[ "$KVER" == *cachy* ]] && [[ -f "$VMLINUZ" ]] && [[ -f "$MOK_PRIV" ]] && [[ -f "$MOK_PEM" ]] && command -v sbsign >/dev/null 2>&1; then
    if ! sbverify --cert "$MOK_PEM" "$VMLINUZ" >/dev/null 2>&1; then
        echo "[cachyos-sign] Auto-signing $VMLINUZ for UEFI Secure Boot..."
        sbsign --key "$MOK_PRIV" --cert "$MOK_PEM" --output "${VMLINUZ}.signed.tmp" "$VMLINUZ" && mv -f "${VMLINUZ}.signed.tmp" "$VMLINUZ"
        chmod 644 "$VMLINUZ"
    fi
fi
exit 0
EOF
    chmod 755 "$hook_path"
}

# --- Helper: Sign DKMS Modules ---
sign_dkms_modules() {
    local kver="$1"
    local mod_dir="/lib/modules/${kver}"
    local sign_file="${mod_dir}/build/scripts/sign-file"
    if [[ -x "$sign_file" && -d "${mod_dir}/updates" ]]; then
        log_info "Signing DKMS modules in ${mod_dir}/updates..."
        while IFS= read -r -d '' ko_file; do
            "$sign_file" sha512 "$MOK_PRIV" "$MOK_DER" "$ko_file" 2>/dev/null || true
        done < <(find "${mod_dir}/updates" -type f -name "*.ko" -print0)
        depmod -a "$kver" 2>/dev/null || true
        log_ok "DKMS modules signed for ${kver}."
    fi
}

# --- MODE 2: Cancel Previous Enrollment & Recreate Certificates from Scratch ---
if [[ "$ACTION" == "--reset-and-recreate" ]]; then
    MOK_PASS="$ARG3"
    log_info "Canceling any pending MOK enrollment requests in UEFI..."
    mokutil --revoke-import 2>/dev/null || true

    OLD_DER=""
    if [[ -f "$MOK_DER" ]]; then
        OLD_DER="$MOK_DER"
    elif [[ -f "${SYS_MOK_DIR}/MOK.der" ]]; then
        OLD_DER="${SYS_MOK_DIR}/MOK.der"
    fi

    # If an old MOK.der exists and was previously enrolled, request deletion if password provided
    if [[ -n "$OLD_DER" ]] && mokutil --test-key "$OLD_DER" 2>&1 | grep -qi "is already enrolled"; then
        if [[ -n "$MOK_PASS" ]]; then
            log_info "Scheduling removal of old enrolled MOK key..."
            printf "%s\n%s\n" "$MOK_PASS" "$MOK_PASS" | mokutil --delete "$OLD_DER" 2>/dev/null || true
        fi
    fi

    log_info "Deleting old certificates from ${OUTPUT_DIR} and ${SYS_MOK_DIR}..."
    rm -f "$MOK_PRIV" "$MOK_DER" "$MOK_PEM"
    rm -f "${SYS_MOK_DIR}/MOK.priv" "${SYS_MOK_DIR}/MOK.der" "${SYS_MOK_DIR}/MOK.pem"

    # Generate brand new certificates in OUTPUT_DIR
    generate_certificates_in_output_dir "true"
    install_persistent_postinst_hook

    # Queue the new MOK.der for enrollment if password was supplied
    if [[ -n "$MOK_PASS" ]]; then
        log_info "Queueing brand-new MOK.der for UEFI Secure Boot enrollment..."
        printf "%s\n%s\n" "$MOK_PASS" "$MOK_PASS" | mokutil --import "$MOK_DER"
        log_ok "MOK_STATUS=ENROLLMENT_QUEUED"
    else
        log_warn "MOK_STATUS=NEEDS_ENROLLMENT"
    fi

    # Also re-sign the latest installed CachyOS kernel in /boot if present so it matches the new key
    NEWEST_VMLINUZ=$(ls -t /boot/vmlinuz-*cachy* 2>/dev/null | grep -v '\.old$' | grep -v '\.signed$' | head -n1 || true)
    if [[ -n "$NEWEST_VMLINUZ" && -f "$NEWEST_VMLINUZ" ]]; then
        KVER="${NEWEST_VMLINUZ#/boot/vmlinuz-}"
        log_info "Re-signing installed kernel ${NEWEST_VMLINUZ} with the newly created MOK key..."
        sbsign --key "$MOK_PRIV" --cert "$MOK_PEM" --output "${NEWEST_VMLINUZ}.signed.tmp" "$NEWEST_VMLINUZ"
        mv -f "${NEWEST_VMLINUZ}.signed.tmp" "$NEWEST_VMLINUZ"
        chmod 644 "$NEWEST_VMLINUZ"
        sbverify --cert "$MOK_PEM" "$NEWEST_VMLINUZ"
        sign_dkms_modules "$KVER"
        update-initramfs -u -k "$KVER"
        command -v update-grub >/dev/null 2>&1 && update-grub
        log_ok "Re-signed ${NEWEST_VMLINUZ} with the new certificate!"
    fi

    log_ok "RESET_COMPLETE=${OUTPUT_DIR}"
    exit 0
fi

# --- MODE 3 & 4: Install & Sign OR Sign-Only ---
DETECTED_KVER=""
MOK_PASS=""

if [[ "$ACTION" == "--install-and-sign" ]]; then
    MOK_PASS="$ARG3"
    log_info "Searching for built .deb packages in ${OUTPUT_DIR}..."
    shopt -s nullglob
    IMAGE_DEBS=()
    HEADER_DEBS=()
    for deb in "$OUTPUT_DIR"/linux-image-*.deb; do
        [[ "$deb" == *-dbg_* ]] && continue
        IMAGE_DEBS+=("$deb")
    done
    for deb in "$OUTPUT_DIR"/linux-headers-*.deb; do
        HEADER_DEBS+=("$deb")
    done
    shopt -u nullglob

    if [[ ${#IMAGE_DEBS[@]} -eq 0 ]]; then
        log_err "No linux-image-*.deb packages found in ${OUTPUT_DIR}"
        exit 1
    fi

    LATEST_IMAGE_DEB=$(ls -t "${IMAGE_DEBS[@]}" | head -n1)
    VMLINUZ_IN_DEB=$(dpkg-deb -c "$LATEST_IMAGE_DEB" | awk '{print $6}' | grep -E '^\./boot/vmlinuz-' | head -n1 || true)
    if [[ -n "$VMLINUZ_IN_DEB" ]]; then
        DETECTED_KVER="${VMLINUZ_IN_DEB#./boot/vmlinuz-}"
        log_info "Detected kernel version from .deb payload: ${DETECTED_KVER}"
    fi

    # Verify package integrity and compute SHA256 hashes before installation
    ALL_INSTALL_DEBS=("$LATEST_IMAGE_DEB" "${HEADER_DEBS[@]}")
    for deb_pkg in "${ALL_INSTALL_DEBS[@]}"; do
        if ! dpkg-deb -I "$deb_pkg" >/dev/null 2>&1; then
            log_err "Integrity check failed: $deb_pkg is invalid or corrupt. Aborting install."
            exit 1
        fi
        deb_sha=$(sha256sum "$deb_pkg" | awk '{print $1}')
        log_info "Package verified: $(basename "$deb_pkg") [SHA256: ${deb_sha}]"
    done

    # Running kernel guard: ensure running kernel is not overwritten
    if [[ -n "$RUNNING_KVER" && -f "/boot/vmlinuz-${RUNNING_KVER}" ]]; then
        log_info "Preserving running kernel fallback: /boot/vmlinuz-${RUNNING_KVER}"
    fi

    log_info "Installing kernel .deb packages via dpkg -i..."
    DEBIAN_FRONTEND=noninteractive dpkg -i "$LATEST_IMAGE_DEB" "${HEADER_DEBS[@]}" || {
        log_warn "Resolving dependencies with apt-get install -f..."
        DEBIAN_FRONTEND=noninteractive apt-get install -f -y
    }
elif [[ "$ACTION" == "--sign-only" ]]; then
    TARGET_KVER="${ARG3:-auto}"
    MOK_PASS="$ARG4"
    if [[ "$TARGET_KVER" != "auto" && -f "/boot/vmlinuz-${TARGET_KVER}" ]]; then
        DETECTED_KVER="$TARGET_KVER"
    fi
else
    log_err "Unknown action: ${ACTION}"
    echo "Usage:"
    echo "  sign-kernel.sh --status <output_dir>"
    echo "  sign-kernel.sh --install-and-sign <output_dir> [mok_password]"
    echo "  sign-kernel.sh --sign-only <output_dir> [kernel_version_or_auto] [mok_password]"
    echo "  sign-kernel.sh --reset-and-recreate <output_dir> [mok_password]"
    exit 1
fi

# Auto-detect newest /boot/vmlinuz-*cachy* if not already set
if [[ -z "$DETECTED_KVER" ]]; then
    NEWEST_VMLINUZ=$(ls -t /boot/vmlinuz-*cachy* 2>/dev/null | grep -v '\.old$' | grep -v '\.signed$' | head -n1 || true)
    if [[ -z "$NEWEST_VMLINUZ" ]]; then
        NEWEST_VMLINUZ=$(ls -t /boot/vmlinuz-* 2>/dev/null | grep -v '\.old$' | grep -v '\.signed$' | head -n1 || true)
    fi
    if [[ -z "$NEWEST_VMLINUZ" ]]; then
        log_err "No /boot/vmlinuz-* kernel image found to sign!"
        exit 1
    fi
    DETECTED_KVER="${NEWEST_VMLINUZ#/boot/vmlinuz-}"
fi

VMLINUZ_PATH="/boot/vmlinuz-${DETECTED_KVER}"
if [[ ! -f "$VMLINUZ_PATH" ]]; then
    log_err "Target kernel image ${VMLINUZ_PATH} not found!"
    exit 1
fi

# 1. Ensure certificates exist in OUTPUT_DIR (and mirrored to SYS_MOK_DIR)
generate_certificates_in_output_dir "false"
install_persistent_postinst_hook

# 2. Sign /boot/vmlinuz-<version> using the certificate in OUTPUT_DIR
log_info "Signing ${VMLINUZ_PATH} using ${MOK_PEM}..."
TMP_SIGNED="${VMLINUZ_PATH}.signed.tmp"
rm -f "$TMP_SIGNED"
sbsign --key "$MOK_PRIV" --cert "$MOK_PEM" --output "$TMP_SIGNED" "$VMLINUZ_PATH"
mv -f "$TMP_SIGNED" "$VMLINUZ_PATH"
chmod 644 "$VMLINUZ_PATH"

# 3. Verify signature
log_info "Verifying signature on ${VMLINUZ_PATH}..."
sbverify --list "$VMLINUZ_PATH"
sbverify --cert "$MOK_PEM" "$VMLINUZ_PATH"
log_ok "Signature verified with ${MOK_PEM}!"

# 4. Sign DKMS / out-of-tree modules if present
sign_dkms_modules "$DETECTED_KVER"

# 5. Update initramfs and GRUB
log_info "Updating initramfs and GRUB for ${DETECTED_KVER}..."
update-initramfs -u -k "$DETECTED_KVER"
command -v update-grub >/dev/null 2>&1 && update-grub

# 6. Check / Queue MOK Enrollment
if command -v mokutil >/dev/null 2>&1; then
    if mokutil --test-key "$MOK_DER" 2>&1 | grep -qi "is already enrolled"; then
        log_ok "MOK_STATUS=ALREADY_ENROLLED"
    elif [[ -n "$MOK_PASS" ]]; then
        log_info "Queueing ${MOK_DER} for UEFI MOK enrollment..."
        mokutil --revoke-import 2>/dev/null || true
        printf "%s\n%s\n" "$MOK_PASS" "$MOK_PASS" | mokutil --import "$MOK_DER"
        log_ok "MOK_STATUS=ENROLLMENT_QUEUED"
    else
        log_warn "MOK_STATUS=NEEDS_ENROLLMENT"
    fi
fi

log_ok "ALL_DONE_KERNEL=${DETECTED_KVER}"
exit 0
