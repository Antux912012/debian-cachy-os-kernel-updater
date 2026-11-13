# Kernel Updater for CachyOS on Debian (Unofficial)

An independent, community-driven **GTK4 / Libadwaita** application designed for Debian systems to check, download, compile, install, and rollback performance-optimized **CachyOS Linux Kernels**.

> [!NOTE]
> **Trademark & Non-Affiliation Notice (Flathub Policy Compliance):**
> **Kernel Updater for CachyOS on Debian** (`io.github.Antux912012.debian-cachy-os-kernel-updater`) is an independent, unofficial third-party tool developed by Antonio (`Antux912012`) and is **not** affiliated with, endorsed by, or maintained by the official **CachyOS Project** or the **Debian Project**. All product names, logos, and brands are property of their respective owners.

![Debian](https://img.shields.io/badge/Debian-Bookworm%20%2B-A81D33?logo=debian&logoColor=white)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20LTS%20%2B-E95420?logo=ubuntu&logoColor=white)
![GTK4](https://img.shields.io/badge/GUI-GTK4%20%2F%20Libadwaita-00A896?logo=gnome&logoColor=white)
![Python](https://img.shields.io/badge/Language-Python%203-3776AB?logo=python&logoColor=white)
![Flatpak](https://img.shields.io/badge/Flatpak-io.github.Antux912012.debian--cachy--os--kernel--updater-4A90D9?logo=flathub&logoColor=white)
![Version](https://img.shields.io/badge/version-1.2.0-00A896.svg)
![License](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg)

<p align="center">
  <img src="assets/logo_256.png" alt="Kernel Updater for CachyOS on Debian Logo" width="180">
</p>

## Application Screenshots

### 1. Update & Build — System Status, Kernel Selection & Progressive Options
<p align="center">
  <img src="assets/screenshots/screenshot-1-main.png" alt="Update & Build - Kernel Selection and Progressive Advanced Options" width="860">
</p>

### 2. Secure Boot & MOK — Firmware Status & Key Management
<p align="center">
  <img src="assets/screenshots/screenshot-2-secureboot.png" alt="Secure Boot and MOK Key Management" width="860">
</p>

### 3. Kernels & Logs — Installed Kernel Management & Build Terminal
<p align="center">
  <img src="assets/screenshots/screenshot-3-kernels.png" alt="Installed Kernels, Rollback, and Build Log Terminal" width="860">
</p>

> [!CAUTION]
> ### ⚠️ EXPERIMENTAL TOOL & LIMITATION OF LIABILITY
>
> - **Experimental Software:** This software is an independent community project provided strictly as an **EXPERIMENTAL TOOL**.
> - **No Assumption of Responsibility:** The developers, maintainers, and contributors **DO NOT ASSUME ANY RESPONSIBILITY OR LIABILITY WHATSOEVER** for any direct, indirect, incidental, or consequential damages, hardware malfunction, boot failures, unbootable system states, data loss, downtime, or system mis-use resulting from the use or inability to use this software.
> - **Inherent System Risks:** Compiling Linux kernels, tailoring hardware drivers, modifying `/boot`, configuring GRUB bootloader entries, and enrolling Machine Owner Keys (MOK) into motherboard UEFI NVRAM are low-level operations that carry inherent risks. You use this software **ENTIRELY AT YOUR OWN RISK**.
> - **Mandatory Fallback Kernel:** Users must **always maintain a proven, working stock Debian kernel** installed on their system to guarantee system recovery should an experimental kernel fail to boot.
> - **Open Source Standard & License:** This tool is free software licensed under the standard **GNU General Public License v3.0 (GPLv3)**. See [LICENSE](LICENSE) for the full terms, conditions, and standard disclaimer of warranty (GPLv3 Sections 15 & 16).

---

## Features

1. **Official CachyOS Version Checking:** Queries the official [CachyOS GitHub repository](https://github.com/CachyOS/linux/releases) and [PKGBUILD](https://github.com/CachyOS/linux-cachyos) to detect the latest stable CachyOS kernel release (e.g. 7.2.10).
2. **System Comparison:** Automatically verifies whether your currently running kernel matches the latest CachyOS release.
3. **Automated Source & Config Download:** Downloads the pre-patched official CachyOS kernel tree and the official CachyOS `.config`.
4. **Containerized Compilation & Host OS Auto-Detection (Debian & Ubuntu):**
   * Automatically inspects `/run/host/etc/os-release` (inside Flatpak) and `/etc/os-release` to detect whether the host is **Debian** (Bookworm, Trixie, Sid, LMDE, MX) or **Ubuntu** (24.04 LTS+, Pop!_OS, Linux Mint, KDE neon, Zorin).
   * Dynamically selects `debian:bookworm-slim` (`cachyos-kernel-builder:debian`) on Debian hosts or `ubuntu:24.04` (`cachyos-kernel-builder:ubuntu`) on Ubuntu hosts when compiling inside an isolated **Podman** or **Docker** container, tagging built kernels (`-cachyos-debian` vs `-cachyos-ubuntu`) and output directories accordingly.
5. **⚡ Compile for My System (Experimental):**
   * **Hardware Auto-Detection:** Automatically scans your machine's CPU vendor (Intel/AMD), CPU model, thread count, form-factor (laptop battery vs desktop), root filesystem, and active hardware modules.
   * **Native CPU Optimization (`-march=native`):** Directs the compiler to utilize your exact CPU microarchitecture instructions (AVX2, AVX-512, BMI2, modern cache line sizes) for maximum responsiveness.
   * **Hardware-Tailored Drivers (`make localmodconfig`):** Scans active hardware modules and trims thousands of unused drivers for hardware not present on your system, reducing compile times from 45–90 minutes down to ~10–20 minutes!
   * **Baseline Safeguards:** Enforces essential storage controllers (NVMe, SATA), filesystems (ext4, btrfs, vfat, ntfs3), and USB input/storage classes so your system always boots reliably.
6. **🔐 In-App UEFI Secure Boot (MOK) Signing & Enrollment Wizard:**
   * **Automatic Post-Build Signing:** Automatically unpacks built `.deb` packages, signs `/boot/vmlinuz-*` with `sbsign`, verifies signature integrity with `sbverify`, and repacks `.deb` packages in-place.
   * **In-App MOK Enrollment:** Prompts for a one-time enrollment password directly inside the GUI and stages the key into NVRAM via `pkexec mokutil --import` for approval on next reboot.
   * **Standalone Signing Tools:** Sign existing packages on demand, enroll MOK keys, or sign `/boot/vmlinuz-*` directly.
7. **Organized Output in `~/kernel-build-deb/`:**
   * Prompts the user to grant permission to create the output folder in their home directory.
   * Collects all generated `.deb` packages (`linux-image`, `linux-headers`), `kernel.config`, and a self-contained `install.sh` helper into `/home/$USER/kernel-build-deb/Linux-kernel-CachyOS-(version)-debian/` (or `-native-debian/`).
8. **Optimized Compilation (`make bindeb-pkg`):**
   * Configures the kernel with CachyOS scheduler and performance optimizations.
   * Sanitizes Debian certificate traps (`SYSTEM_TRUSTED_KEYS=""`, `SYSTEM_REVOCATION_KEYS=""`) and module keys to ensure failure-free builds on both host and containers.
   * Compiles the kernel into native `.deb` packages using all available CPU threads.
9. **Polkit Privilege Escalation:** Safely invokes `pkexec` for native password prompts when installing or purging packages, importing MOK keys, and updating GRUB.
10. **Kernel Rollback:** Lists installed `linux-image-*` packages in a safety-first UI dialog, allowing you to purge previous kernels and automatically restore older kernel entries in GRUB.
11. **Cache Cleanup & Persistent Config Recovery:** Checks and cleans `~/.cache/cachy-kernel-build` every time the app opens, preventing disk bloat while automatically saving and recovering your generated kernel `.config` across kernel updates.
12. **One-Click Build Dependencies Installer:** Built-in "Install Dependencies" button to verify and install all required kernel compiler tools directly from the GUI.
13. **Modern Native UI:** Built with **GTK4** and **Libadwaita**, providing dark mode support, titlebar controls, and live terminal logging.

---

## ⚡ Experimental Feature: "Compile for My System"

The **"Compile for my system"** switch enables automated hardware auto-detection to build an optimized, machine-tailored CachyOS kernel rather than a generic one-size-fits-all build:

### What It Does:
* **Silicon-Level Optimization (`-march=native`):** Configures the kernel with `CONFIG_X86_NATIVE_CPU=y` (and CachyOS native compiler flags), instructing GCC to utilize all instruction sets supported by your exact processor (e.g. AVX2, AVX-512, BMI2, AES-NI, FMA, and modern cache-line tuning).
* **Hardware-Tailored Driver Stripping (`make localmodconfig`):** Generic distribution kernels compile over 5,000 drivers for thousands of ancient or obscure controllers. The app snapshots your running hardware via `lsmod` and trims away drivers for hardware not physically present on your machine.
* **Dramatically Faster Builds:** Cuts compilation time from **45–90 minutes down to ~10–20 minutes** on typical multi-core CPUs, while also reducing kernel image and initramfs size.
* **Form-Factor & Power Management:** Detects whether you are running on a laptop (battery detected) or desktop, configuring optimal CPU frequency governors (`AMD P-State EPP` / `Intel P-State`), timer tick behavior, and vendor-specific ACPI modules (e.g., ThinkPad, Dell, ASUS).
* **Baseline Safeguards:** Enforces core storage drivers (NVMe, AHCI/SATA), vital filesystems (`ext4`, `btrfs`, `vfat`, `ntfs3`), and USB HID input devices so your system boots reliably and external drives continue to work.
* **Isolated Output:** System-tailored builds are labeled with the `-cachyos-native-debian` localversion and organized into `~/kernel-build-deb/Linux-kernel-CachyOS-(version)-native-debian/`.

> [!IMPORTANT]
> **Portability Notice:**
> A kernel compiled with "Compile for my system" is tailored specifically for the machine on which it was built. The resulting `.deb` packages should not be installed on another PC with different hardware or a different CPU generation.

---

## Installation

### Method 1: Official Debian APT Repository (Recommended)

Installing via our official APT repository enables automatic updates alongside your system packages (`sudo apt upgrade`):

```bash
# 1. Download and install the repository GPG signing key
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://antux912012.github.io/debian-cachy-os-kernel-updater/KEY.gpg | sudo gpg --dearmor -o /etc/apt/keyrings/cachy-kernel-updater.gpg

# 2. Add the repository to your APT sources
echo "deb [signed-by=/etc/apt/keyrings/cachy-kernel-updater.gpg] https://antux912012.github.io/debian-cachy-os-kernel-updater stable main" | sudo tee /etc/apt/sources.list.d/cachy-kernel-updater.list

# 3. Update package index and install
sudo apt update
sudo apt install cachy-kernel-updater
```

> [!TIP]
> Compatible with **Debian 12 (Bookworm)**, **Debian 13 (Trixie)**, **Debian Sid (Unstable)**, and Debian-based distributions. You can also visit the [APT Repository Web Page](https://antux912012.github.io/debian-cachy-os-kernel-updater/).

---

### Method 2: Direct `.deb` Package Download

Download the pre-compiled `.deb` package from the [v1.2.0 Release Page](https://github.com/Antux912012/debian-cachy-os-kernel-updater/releases/tag/v1.2.0):

* 📦 **[cachy-kernel-updater_1.2.0_all.deb](https://github.com/Antux912012/debian-cachy-os-kernel-updater/releases/download/v1.2.0/cachy-kernel-updater_1.2.0_all.deb)**

Install it using `apt` (which automatically installs any missing dependencies):
```bash
sudo apt install -y ./cachy-kernel-updater_1.2.0_all.deb
```

---

### Method 2b: AppImage, RPM & AUR (`PKGBUILD`)

* **AppImage** (runs across Debian/Ubuntu/Linux distributions with GTK4/Libadwaita):
```bash
chmod +x ./Debian-CachyOS-Kernel-Updater-1.2.0-x86_64.AppImage
./Debian-CachyOS-Kernel-Updater-1.2.0-x86_64.AppImage
```
* **RPM Package (`.rpm`)**:
```bash
sudo dnf install ./cachy-kernel-updater-1.2.0-1.noarch.rpm
```
* **Arch Linux / AUR (`packaging/aur/PKGBUILD`)**:
```bash
cd packaging/aur && makepkg -si
```

---

### Method 3: Flathub & Flatpak Bundle

Install the Flatpak (`io.github.Antux912012.debian-cachy-os-kernel-updater`):
```bash
# From Flathub (once published)
flatpak install flathub io.github.Antux912012.debian-cachy-os-kernel-updater

# Or from the standalone release bundle (.flatpak)
flatpak install --user io.github.Antux912012.debian-cachy-os-kernel-updater.flatpak
```
Run the application:
```bash
flatpak run io.github.Antux912012.debian-cachy-os-kernel-updater
```

#### Flatpak Sandbox & Host Permissions Disclosure
In accordance with [Flathub Requirements](https://docs.flathub.org/docs/for-app-authors/requirements), this utility declares the following sandbox permissions in its manifest (`io.github.Antux912012.debian-cachy-os-kernel-updater.yml`):
- **`--filesystem=host` & `--talk-name=org.freedesktop.Flatpak` (`flatpak-spawn --host`)**: Required because compiling Linux kernels (via host toolchain or Podman/Docker), inspecting `/boot`, `/var/lib/dpkg`, and `/sys/firmware/efi/efivars`, signing kernel modules with MOK keys (`sbsign` / `mokutil`), and installing `.deb` kernel images (`pkexec dpkg -i`) operate directly on the host operating system.
- **`--talk-name=org.freedesktop.Notifications` & `--system-talk-name=org.freedesktop.PolicyKit1`**: Used for build completion notifications and Polkit privilege elevation prompts.
- **Architecture (`x86_64`)**: Targets `x86_64` systems matching CachyOS `x86-64-v3` / `x86-64-v4` and native microarchitecture tuning.

---

### Method 4: Running Directly from Source (Python)
If running from source code (`python3 main.py`), you must ensure the following Debian packages and GTK4 libraries are installed:

| Library Package | Purpose |
| :--- | :--- |
| `python3` | Python runtime |
| `python3-gi` | Python GObject introspection bindings |
| `python3-gi-cairo` | Cairo vector graphics bindings for Python |
| `python3-requests` | HTTP library for querying the official CachyOS GitHub API |
| `gir1.2-gtk-4.0` | GTK 4.0 graphical toolkit |
| `gir1.2-adw-1` | Libadwaita 1.0 widget library (GNOME modern styling) |
| `libadwaita-1-0` | Libadwaita shared C libraries |
| `policykit-1` or `polkitd` | Provides `pkexec` for secure root privilege prompts |

Install all of them with a single command:
```bash
sudo apt update
sudo apt install -y python3 python3-gi python3-gi-cairo python3-requests \
    gir1.2-gtk-4.0 gir1.2-adw-1 libadwaita-1-0 policykit-1
```

---

### 4. Kernel Compilation Dependencies
To compile the CachyOS kernel (`make bindeb-pkg`), your system requires standard Linux kernel compilation build tools:

```bash
sudo apt install -y build-essential libncurses-dev bison flex libssl-dev \
    libelf-dev bc rsync debhelper pahole dwarves sbsigntool mokutil openssl
```

> [!NOTE]
> **Compilation Duration Notice:**
> Compiling a full Linux kernel is an intensive task that utilizes all available CPU threads. The compilation process can take a while (typically anywhere from 15 to 45+ minutes) depending on the processing power, CPU core count, and cooling capabilities of your system.

---

## 🔐 Secure Boot & Kernel Signing

> [!WARNING]
> **Crucial for Systems with Secure Boot Enabled:**
> Custom compiled Linux kernels are not signed by Debian's official Microsoft-trusted EFI key. If your computer has **UEFI Secure Boot enabled**, your motherboard firmware will refuse to boot the newly compiled CachyOS kernel unless it is signed with a **Machine Owner Key (MOK)**.

### Option A: Atomic Post-Installation Kernel & DKMS Signing (Recommended)
The application provides integrated **Single-Transaction Privileged Helper Architecture**:
1. When **"Sign Kernel for UEFI Secure Boot After Installation"** is checked (safe default, pre-ticked across systems):
   - MOK certificates (`MOK.priv`, `MOK.der`, `MOK.pem`) are generated directly inside the **kernel output directory** alongside the compiled `.deb` packages (and mirrored to `/var/lib/shim-signed/mok/` for system/DKMS compatibility).
   - Certificates in the output folder are owned by the desktop user (`600` for `MOK.priv`, `644` for `MOK.der`/`pem`) so they can be retrieved or backed up without root permissions.
   - The app prompts for a one-time MOK enrollment password *only* if your key is not already enrolled in UEFI NVRAM.
   - A single `pkexec` authorization executes the atomic helper `sign-kernel.sh --install-and-sign <output_dir> [mok_pass]`.
   - The helper installs missing signing packages (`sbsigntool`, `mokutil`), extracts the exact kernel image from the `.deb`, installs via `dpkg -i`, signs `/boot/vmlinuz-*` via `sbsign`, signs DKMS modules, updates `initramfs` and `update-grub`, and stages MOK enrollment non-interactively via `mokutil --import`.
   - Installs a persistent Debian hook at `/etc/kernel/postinst.d/zz-cachyos-secureboot-sign` (chmod 0755) so future CachyOS kernel updates are signed automatically.
2. If the MOK key is enrolled on reboot, a clear MokManager walkthrough is displayed:
   - Select **Enroll MOK** -> **Continue** -> **Yes**.
   - Enter your chosen temporary password.
   - Select **Reboot** to boot into your newly signed kernel!
3. Standalone Actions:
   - Click **"🔒 Sign Installed Kernel (Secure Boot)"** to sign already-installed kernels and DKMS modules in `/boot` in a single transaction.
   - Click **"🔄 Reset MOK Keys"** (or `"🔄 Reset & Recreate MOK Keys"`) to cancel pending enrollments (`mokutil --revoke-import`), delete old keys, generate brand-new RSA-2048 MOK keys from scratch in the output folder, and re-sign your kernel.
   - Click **"📂 Open Folder"** next to *MOK Certificates & Packages Location* to directly inspect your `.deb` packages and `MOK.der`/`pem` files.

### Option B: CLI Signing with `sign-kernel.sh`
For headless systems or command-line workflows, use [`sign-kernel.sh`](sign-kernel.sh):
```bash
# Atomic install, sign, DKMS, initramfs, GRUB, and MOK enrollment:
sudo ./sign-kernel.sh --install-and-sign ~/kernel-build-deb/Linux-kernel-CachyOS-.../ [mok_password]

# Sign existing installed kernel in /boot and queue MOK:
sudo ./sign-kernel.sh --sign-only ~/kernel-build-deb/Linux-kernel-CachyOS-.../ auto [mok_password]

# Reset MOK keys from scratch, re-sign installed kernel, and queue new enrollment:
sudo ./sign-kernel.sh --reset-and-recreate ~/kernel-build-deb/Linux-kernel-CachyOS-.../ [mok_password]

# Check Secure Boot and MOK enrollment status without root:
./sign-kernel.sh --status [output_dir]
```

---

## Building from Source

### Build the Native Debian Package (`.deb`)
```bash
./build_deb.sh
```
This generates the ready-to-install package at `deb_dist/cachy-kernel-updater_1.1.8_all.deb`.

### Build the Standalone Flatpak Bundle (`.flatpak`)
```bash
./build_flatpak.sh
```
This compiles the application in an isolated Flatpak environment and produces `deb_dist/io.github.Antux912012.debian-cachy-os-kernel-updater.flatpak`.

---

## Project Structure

```
├── assets/                                      # Official CachyOS emblem logo & screenshot assets
│   ├── screenshots/                             # Official AppStream & GitHub UI screenshots
│   │   ├── screenshot-1-main.png                # Main dashboard & Secure Boot status
│   │   ├── screenshot-2-tuning.png              # Advanced Kernel & CPU tuning options
│   │   └── screenshot-3-compiling.png           # Live compilation progress & terminal log
│   ├── logo_48.png                              # 48x48 icon
│   ├── logo_128.png                             # 128x128 icon
│   ├── logo_256.png                             # 256x256 icon
│   ├── logo_512.png                             # 512x512 icon
│   ├── logo_master.png                          # High-resolution master icon
│   └── io.github.Antux912012.debian-cachy-os-kernel-updater.svg     # Scalable SVG application emblem
├── flatpak/
│   └── wheels/                                  # Offline Python wheels for Flatpak
├── main.py                                      # GTK4 / Libadwaita User Interface
├── kernel_manager.py                            # Backend engine: version checking, compilation, install & rollback
├── sign-kernel.sh                               # Atomic UEFI Secure Boot MOK signing & enrollment tool
├── build_deb.sh                                 # Debian package (.deb) generator script
├── build_flatpak.sh                             # Flatpak bundle (.flatpak) packaging script
├── io.github.Antux912012.debian-cachy-os-kernel-updater.yml         # Flatpak application manifest
├── io.github.Antux912012.debian-cachy-os-kernel-updater.desktop     # Desktop application launcher
├── io.github.Antux912012.debian-cachy-os-kernel-updater.metainfo.xml# AppStream metadata specification
├── Containerfile                                # Containerized isolated compiler definition
├── requirements.txt                             # Python requirements
├── LICENSE                                      # GNU General Public License v3.0 (GPLv3)
└── README.md                                    # Documentation & instructions
```

---

## 🙏 Acknowledgements & Support CachyOS

This project would not be possible without the remarkable, groundbreaking work of the **[CachyOS Team](https://cachyos.org/)**. 

We express our sincerest gratitude to the CachyOS developers for their continuous innovation in the Linux ecosystem, including their performance-optimized kernel patches, advanced CPU schedulers (BORE, EEVDF, etc.), and fine-tuned configurations that make high-performance desktop responsiveness and gaming accessible to everyone.

* 🌐 **Official Website:** [https://cachyos.org](https://cachyos.org)
* 🐙 **Official GitHub:** [https://github.com/CachyOS](https://github.com/CachyOS)
* 🐧 **CachyOS Kernel Source & Patches:** [CachyOS/linux-cachyos](https://github.com/CachyOS/linux-cachyos) & [CachyOS/CachyOS-PKGBUILDS](https://github.com/CachyOS/CachyOS-PKGBUILDS)
* 🎨 **GNOME / Libadwaita & PyGObject:** [GNOME/libadwaita](https://gitlab.gnome.org/GNOME/libadwaita) & [GNOME/pygobject](https://gitlab.gnome.org/GNOME/pygobject)
* 💖 **Support & Donate to CachyOS:** If you enjoy the performance benefits of CachyOS kernels, please consider supporting their project directly through the **[CachyOS Donation Page](https://cachyos.org/donate/)** or their **[Patreon](https://www.patreon.com/CachyOS)**.

*(Note: This updater is an independent, community-driven tool for Debian and is not officially affiliated with or maintained by the CachyOS core team).*

---

## 📜 Changelog

### v1.1.8
- **Removed `sched-ext` (SCX) Integration**: Removed SCX userspace BPF scheduler installation, bundled SCX `.deb` archives, and `CONFIG_SCHED_CLASS_EXT` overrides to focus cleanly on CachyOS's native **BORE** and **EEVDF** kernel schedulers.
- **Restored True `DEBUG_INFO_NONE` Stripping**: Restored `--enable DEBUG_INFO_NONE` (disabling DWARF/BTF debug info) when "Strip Debug Symbols" is active, significantly lowering disk usage and build time.
- **Codebase Audit & Optimization**: Consolidated multiple `scripts/config` subprocess invocations into a single batched execution, unified `/var/lib/dpkg/status` parsing and MOK `sign-kernel.sh` stream handling, deduplicated GTK4/Libadwaita dialog and action helpers, and removed legacy `/app/share/pixmaps` icon paths and dormant methods.

### v1.1.6
- **Automatic Debian & Ubuntu Host OS Detection (`/etc/os-release` & `/run/host/etc/os-release`)**: Added [`KernelManager.detect_host_distro()`](kernel_manager.py) to automatically detect whether the host system (or build environment) is running Debian or Ubuntu/derivatives, dynamically selecting `debian:bookworm-slim` (`cachyos-kernel-builder:debian`) or `ubuntu:24.04` (`cachyos-kernel-builder:ubuntu`), matching `-cachyos-debian` / `-cachyos-ubuntu` localversion tags, and displaying the active Host OS in the top status banner.
- **Flathub Policy & Linter Compliance**: Aligned application display name (`Kernel Updater for CachyOS on Debian`), trademark/non-affiliation notices, and Flatpak sandbox permission disclosures in `README.md`, `.metainfo.xml`, and `.desktop`; bumped GNOME Flatpak runtime to `51`; and added automated [`scripts/release-flathub.sh`](scripts/release-flathub.sh) release pipeline.

### v1.1.5
- **Standardized Flatpak & Freedesktop Application ID (`io.github.Antux912012.debian-cachy-os-kernel-updater`)**: Migrated application ID, AppStream catalog metadata, desktop launcher, and icon assets to the canonical `io.github.Antux912012.debian-cachy-os-kernel-updater` reverse-DNS namespace.
- **Containerized Podman Packaging**: Rebuilt `cachy-kernel-updater_1.1.5_all.deb` and `io.github.Antux912012.debian-cachy-os-kernel-updater.flatpak` inside the dedicated Podman development environment.

### v1.1.4
- **Official Application Screenshots & AppStream Catalog Metadata**: Added 3 high-resolution UI screenshots (`screenshot-1-main.png`, `screenshot-2-tuning.png`, `screenshot-3-compiling.png`) to the GitHub documentation and embedded AppStream `<screenshots>` metadata + composed `app-info` catalog inside the Flatpak bundle and `.deb` package for GNOME Software Center, KDE Discover, and Bazaar.
- **Updated Debian & Flatpak Releases**: Rebuilt `cachy-kernel-updater_1.1.4_all.deb` and `cachy-kernel-updater_1.1.4.flatpak` inside the isolated `dev-debian` Podman container environment.

### v1.1.3
- **Fixed Flatpak UEFI Secure Boot Recognition**: Added direct kernel EFI variable inspection (`/sys/firmware/efi/efivars/SecureBoot-*`, `/run/host/sys/firmware/efi/efivars/SecureBoot-*`, and host `od`/`mokutil` bridge) and fixed `sign-kernel.sh --status` to run without requiring `/run/lock` exclusive locks.
- **Fixed Flatpak Sandbox Host Execution (`flatpak-spawn --host`)**: Bridged all host operations (`dpkg`, `pkexec`, `make`, `podman`, `mokutil`, `sbsign`, `lspci`, `lsusb`), staged `sign-kernel.sh` and `Containerfile` to `~/.config/cachy-kernel-updater/` for host visibility, and exposed `/var/lib/dpkg:ro`, `/boot:ro`, and `/sys/firmware/efi/efivars:ro` to the Flatpak runtime.
- **Fixed Kernel Download & Config Sanitization Performance**: Switched kernel source downloads to streaming `requests.get()` with live MB/percentage progress reporting and gzip header verification; batched the ~180 `scripts/config` safety baseline flags into a single fast invocation.
- **Adaptive Light/Dark Build Log Terminal**: Fixed the build log terminal view so it dynamically adapts to Adwaita Light Mode (black text `#000000` on white background `#ffffff`) and Dark Mode (white text `#ffffff` on black background `#000000`) with a manual `🌗 Invert Colors` toggle button.

### v1.1.2
- **Fixed Missing Wi-Fi & Bluetooth Drivers (Safety Baseline Overhaul)**: Resolved issue where `make localmodconfig` stripped Wi-Fi and Bluetooth drivers and crypto algorithms that were not actively loaded into memory at compile-time.
- **Mandatory Wireless Cryptography Support**: Enforced kernel configs for `CONFIG_CRYPTO_CMAC`, `CONFIG_CRYPTO_USER_API_HASH`, `CONFIG_CRYPTO_AES_NI_INTEL`, `CONFIG_CRYPTO_USER_API_SKCIPHER`, and related crypto ciphers, fixing daemon crashes with modern connection managers (`iwd`, `wpa_supplicant`, WPA2/WPA3-SAE, 802.11w/PMF).
- **Comprehensive Bluetooth Subsystem**: Enforced `CONFIG_BT_HIDP` (Bluetooth Human Interface Devices / input), `CONFIG_BT_HCIUART` (laptop serial UART Bluetooth), `CONFIG_BT_HCIBTUSB`, and vendor drivers (`CONFIG_BT_INTEL`, `BCM`, `RTL`, `MTK`).
- **Universal Wi-Fi Driver Preservation**: Enforced kernel modules for major Wi-Fi families (Intel `iwlwifi`/`iwlmvm`/`iwldvm`, Realtek `rtw88`/`rtw89`/`rtl8xxxu`, Qualcomm/Atheros `ath9k`/`ath10k`/`ath11k`/`ath12k`, MediaTek `mt76`/`mt7921`/`mt7925`, and Broadcom `brcmfmac`).
- **Seeded `host_lsmod.txt` Generation**: Seeded the `lsmod` snapshot with essential network, Bluetooth, and crypto modules so `streamline_config.pl` never removes dormant, unassociated, or rfkill-blocked wireless controllers.
- **Hardware Detection Reporting**: Added automatic detection and live reporting of system Wi-Fi adapters and Bluetooth controllers.
- **Updated Package Releases & APT Repository**: Bumped version to `1.1.2`, generated new Debian and Flatpak packages, and updated APT repository metadata.

### v1.1.1
- **New Vibrant Emblem Logo & Branding Palette**: Adopted modern low-poly CachyOS "C" rocket emblem with rich crimson (`#D82655`) and vibrant teal (`#00A896`), including matching GTK4/Adwaita custom CSS themes, status badges, and gradient progress bars.
- **Top System Status Card**: Enhanced top banner with app icon, version badge (`v1.1.1`), and integrated About dialog.
- **Guided 1-2-3 Step UI Workflow**: Streamlined the user interface into 3 clear cards with safe cross-system defaults pre-selected out-of-the-box (`localmodconfig`, stripped debug symbols, automated `.deb` installation, and post-install UEFI signing).
- **Dual Package Distribution**: Added standalone Flatpak bundle (`.flatpak`) alongside official Debian package (`.deb`).
- **Co-Located MOK Certificates**: Generated MOK certificates are stored directly in the kernel build output directory with user permissions.
- **Resolved `bindeb-pkg` Error 2**: Sanitized Debian/Canonical `.pem` certificate traps (`SYSTEM_TRUSTED_KEYS=""`, `SYSTEM_REVOCATION_KEYS=""`, `MODULE_SIG_KEY=""`) and decoupled module signing from the compilation phase, enabling robust failure-free kernel builds natively and inside Podman/Docker containers.
- **Added Full Kernel 7.x & Packaging Dependencies**: Added `pahole`, `dwarves`, `sbsigntool`, `mokutil`, `openssl`, `fakeroot`, and `dpkg-dev` to `Containerfile`, `build_deb.sh`, and `kernel_manager.py`.
- **In-App Post-Build UEFI Secure Boot (MOK) Signing**: Automatically unpacks `linux-image-*.deb` packages post-compilation, signs internal `/boot/vmlinuz-*` binaries with `sbsign`, verifies cryptographic signatures via `sbverify`, and repacks `.deb` packages in-place.
- **In-App MOK Key Enrollment Wizard**: Integrated interactive dialog to stage MOK certificate enrollment into UEFI NVRAM (`pkexec mokutil --import`) with password validation and step-by-step reboot guidance for MokManager.
- **Standalone Security Signing Tools**: Added UI rows and CLI arguments (`--sign-deb-mok`, `--status-sb`, `--enroll-mok`) for on-demand package signing and MOK management.

### v1.0.6
- Added experimental "Compile for my system" hardware-tailored kernel build with CPU detection and `make localmodconfig`.

---

## ⚖️ Standard & License

This software is an open-source community project distributed under the **[GNU General Public License v3.0 (GPLv3)](LICENSE)** standard.

```text
Debian CachyOS Kernel Installer & Updater
Copyright (C) 2026 Antonio and Contributors.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.
```

See the full [LICENSE](LICENSE) file for complete licensing terms, warranty disclaimer, and conditions.

