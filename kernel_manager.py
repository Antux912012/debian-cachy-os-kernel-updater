import subprocess
import requests
import os
import shutil
import re
import glob
import stat

APP_VERSION = "1.2.0"

class KernelManager:
    APP_VERSION = APP_VERSION
    def __init__(self):
        self.releases_api = "https://api.github.com/repos/CachyOS/linux/releases?per_page=30"
        self.pkgbuild_raw = "https://raw.githubusercontent.com/CachyOS/linux-cachyos/master/linux-cachyos/PKGBUILD"
        self.cachy_config_raw = "https://raw.githubusercontent.com/CachyOS/linux-cachyos/master/linux-cachyos/config"
        self._flatpak_spawn_available = None

        real_home = os.path.expanduser("~")
        if self.is_flatpak():
            cache_base = os.path.join(real_home, ".cache")
            config_base = os.path.join(real_home, ".config")
        else:
            cache_base = os.environ.get("XDG_CACHE_HOME", os.path.join(real_home, ".cache"))
            config_base = os.environ.get("XDG_CONFIG_HOME", os.path.join(real_home, ".config"))

        self.download_dir = os.path.join(cache_base, "cachy-kernel-build")
        self.config_dir = os.path.join(config_base, "cachy-kernel-updater")
        self.saved_config_path = os.path.join(self.config_dir, "kernel.config")
        self.saved_native_config_path = os.path.join(self.config_dir, "kernel-native.config")
        os.makedirs(self.config_dir, exist_ok=True)
        self._stage_host_helper_files()

        self.REQUIRED_BUILD_DEPS = [
            'build-essential',
            'bc',
            'bison',
            'flex',
            'libssl-dev',
            'libelf-dev',
            'libncurses-dev',
            'libdw-dev',
            'libudev-dev',
            'libpci-dev',
            'libiberty-dev',
            'autoconf',
            'dwarves',
            'pahole',
            'zstd',
            'xz-utils',
            'lz4',
            'cpio',
            'rsync',
            'kmod',
            'fakeroot',
            'dpkg-dev',
            'debhelper',
            'devscripts',
            'clang',
            'llvm',
            'lld',
            'sbsigntool',
            'mokutil',
            'openssl',
            'linux-base',
            'initramfs-tools'
        ]

        self.REQUIRED_SIGNING_DEPS = [
            'sbsigntool',
            'mokutil',
            'openssl',
            'linux-base',
            'initramfs-tools'
        ]

        self.latest_version = None
        self.latest_tag = None
        self.download_url = None

        self.output_base_dir = os.path.expanduser("~/kernel-build-deb")
        self.last_output_dir = None
        self.host_distro = self.detect_host_distro()
        self.os_tag = "ubuntu" if self.host_distro.get("id") == "ubuntu" else "debian"
        self.container_image_tag = f"cachyos-kernel-builder:{self.os_tag}"
        self._verified_container_images = set()

    def detect_host_distro(self) -> dict:
        """
        Detects the host OS distribution (Debian vs Ubuntu vs derivative) by inspecting
        /run/host/etc/os-release (when inside Flatpak) or /etc/os-release.
        Returns a dict with 'id', 'id_like', 'name', 'version_id', 'codename', 'is_ubuntu', 'is_debian_family'.
        """
        data = {
            "id": "debian",
            "id_like": "debian",
            "name": "Debian GNU/Linux",
            "version_id": "",
            "codename": "bookworm",
            "is_ubuntu": False,
            "is_debian_family": True,
        }
        os_release_paths = (
            "/run/host/etc/os-release",
            "/run/host/usr/lib/os-release",
            "/etc/os-release",
            "/usr/lib/os-release",
        )
        raw = {}
        for p in os_release_paths:
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            line = line.strip()
                            if "=" in line and not line.startswith("#"):
                                k, v = line.split("=", 1)
                                raw[k.strip()] = v.strip().strip('"').strip("'")
                    if raw.get("ID"):
                        break
                except Exception:
                    pass

        if raw:
            distro_id = raw.get("ID", "debian").lower()
            id_like = raw.get("ID_LIKE", "").lower()
            data["id"] = distro_id
            data["id_like"] = id_like
            data["name"] = raw.get("PRETTY_NAME", raw.get("NAME", distro_id.capitalize()))
            data["version_id"] = raw.get("VERSION_ID", "")
            data["codename"] = raw.get("VERSION_CODENAME", raw.get("UBUNTU_CODENAME", ""))
            data["is_ubuntu"] = (distro_id in ("ubuntu", "linuxmint", "pop", "neon", "elementary", "zorin") or "ubuntu" in id_like)
            data["is_debian_family"] = (
                data["is_ubuntu"]
                or distro_id in ("debian", "kali", "parrot", "raspbian", "lmde", "mx")
                or "debian" in id_like
            )
        return data

    def is_flatpak(self) -> bool:
        """Returns True when running inside a Flatpak sandbox."""
        return os.path.exists("/.flatpak-info") or bool(os.environ.get("FLATPAK_ID"))

    def _can_flatpak_spawn_host(self) -> bool:
        """Returns True if inside Flatpak and flatpak-spawn --host is operational."""
        if not self.is_flatpak():
            return False
        if self._flatpak_spawn_available is not None:
            return self._flatpak_spawn_available
        if not shutil.which("flatpak-spawn"):
            self._flatpak_spawn_available = False
            return False
        try:
            res = subprocess.run(
                ["flatpak-spawn", "--host", "true"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3
            )
            self._flatpak_spawn_available = (res.returncode == 0)
        except Exception:
            self._flatpak_spawn_available = False
        return self._flatpak_spawn_available

    def _host_cmd(self, cmd: list, cwd: str = None, env: dict = None) -> list:
        """Wraps a command list with 'flatpak-spawn --host' when running inside Flatpak."""
        if not self._can_flatpak_spawn_host():
            return list(cmd)
        spawn_cmd = ["flatpak-spawn", "--host"]
        if cwd:
            spawn_cmd.append(f"--directory={cwd}")
        if env:
            for k, v in env.items():
                spawn_cmd.append(f"--env={k}={v}")
        return spawn_cmd + list(cmd)

    def _run_host_subproc(self, cmd: list, **kwargs):
        """Runs a short subprocess on the host (via flatpak-spawn --host if in Flatpak)."""
        cwd = kwargs.get("cwd")
        if self._can_flatpak_spawn_host():
            actual_cmd = self._host_cmd(cmd, cwd=cwd)
            kwargs_copy = dict(kwargs)
            kwargs_copy.pop("cwd", None)
            return subprocess.run(actual_cmd, **kwargs_copy)
        return subprocess.run(cmd, **kwargs)

    def _which_host(self, binary: str):
        """Checks if an executable exists on the host (or locally)."""
        if self._can_flatpak_spawn_host():
            try:
                res = subprocess.run(
                    ["flatpak-spawn", "--host", "sh", "-c", 'command -v "$1"', "_", binary],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=5
                )
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception:
                pass
        return shutil.which(binary)

    def _stage_host_helper_files(self):
        """
        Copies sign-kernel.sh and Containerfile from the application bundle (/app/share/...)
        into ~/.config/cachy-kernel-updater/ so host processes (pkexec, podman, bash)
        invoked via flatpak-spawn --host can access them on the host filesystem.
        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            for fname, mode in (("sign-kernel.sh", 0o755), ("Containerfile", 0o644)):
                src = os.path.join(base_dir, fname)
                dst = os.path.join(self.config_dir, fname)
                if os.path.isfile(src) and os.path.abspath(src) != os.path.abspath(dst):
                    shutil.copy2(src, dst)
                    os.chmod(dst, mode)
        except Exception:
            pass

    def get_current_kernel_version(self):
        """Returns the currently running kernel version."""
        try:
            return subprocess.check_output(['uname', '-r'], text=True).strip()
        except Exception as e:
            return f"Error: {e}"

    def detect_hardware(self):
        """
        Detects system hardware: CPU model, vendor, thread count, laptop/chassis status,
        root filesystem, manufacturer, and loaded kernel modules.
        Returns a dict of detected hardware details.
        """
        info = {
            'cpu_model': 'Generic x86-64',
            'vendor': 'Unknown',
            'threads': os.cpu_count() or 4,
            'is_laptop': False,
            'manufacturer': 'Generic',
            'product_name': 'PC',
            'root_fs': 'ext4',
            'loaded_modules': []
        }

        # 1. CPU Info from /proc/cpuinfo
        try:
            with open('/proc/cpuinfo', 'r') as f:
                for line in f:
                    if ':' in line:
                        k, v = [x.strip() for x in line.split(':', 1)]
                        if k == 'model name' and info['cpu_model'] == 'Generic x86-64':
                            info['cpu_model'] = v
                        elif k == 'vendor_id' and info['vendor'] == 'Unknown':
                            info['vendor'] = v
        except Exception:
            pass

        # 2. Laptop detection via /sys/class/power_supply
        try:
            batteries = glob.glob('/sys/class/power_supply/BAT*')
            if batteries:
                info['is_laptop'] = True
        except Exception:
            pass

        # 3. DMI info (Manufacturer and Product)
        try:
            if os.path.exists('/sys/class/dmi/id/sys_vendor'):
                with open('/sys/class/dmi/id/sys_vendor', 'r') as f:
                    info['manufacturer'] = f.read().strip()
            if os.path.exists('/sys/class/dmi/id/product_name'):
                with open('/sys/class/dmi/id/product_name', 'r') as f:
                    info['product_name'] = f.read().strip()
        except Exception:
            pass

        # 4. Root Filesystem
        try:
            res = self._run_host_subproc(['df', '-T', '/'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5)
            df_out = res.stdout.splitlines() if res.returncode == 0 else []
            if len(df_out) > 1:
                info['root_fs'] = df_out[1].split()[1]
        except Exception:
            pass

        # 5. Loaded kernel modules from lsmod or /proc/modules
        try:
            modules = []
            if os.path.exists('/proc/modules'):
                with open('/proc/modules', 'r') as f:
                    for line in f:
                        parts = line.split()
                        if parts:
                            modules.append(parts[0])
            else:
                res = self._run_host_subproc(['lsmod'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5)
                if res.returncode == 0:
                    for line in res.stdout.splitlines()[1:]:
                        parts = line.split()
                        if parts:
                            modules.append(parts[0])
            info['loaded_modules'] = modules
        except Exception:
            pass

        # 6. Wi-Fi adapter detection
        info['wifi_adapter'] = None
        try:
            res = self._run_host_subproc(['lspci'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if any(w in line.lower() for w in ['wireless', 'wi-fi', 'network controller', '802.11']):
                        parts = line.split(':', 2)
                        info['wifi_adapter'] = parts[2].strip() if len(parts) >= 3 else line.strip()
                        break
        except Exception:
            pass

        # 7. Bluetooth adapter detection
        info['bluetooth_adapter'] = None
        try:
            res = self._run_host_subproc(['lsusb'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if 'bluetooth' in line.lower():
                        parts = line.split(':', 2)
                        info['bluetooth_adapter'] = parts[2].strip() if len(parts) >= 3 else line.strip()
                        break
            if not info['bluetooth_adapter'] and os.path.exists('/sys/class/bluetooth'):
                bt_nodes = os.listdir('/sys/class/bluetooth')
                if bt_nodes:
                    info['bluetooth_adapter'] = f"Bluetooth Adapter ({', '.join(bt_nodes)})"
        except Exception:
            pass

        return info

    def get_available_versions(self):
        """
        Fetches official CachyOS releases from GitHub.
        Returns a list of dicts:
        [{'version': '7.2.10-1', 'tag': 'cachyos-7.2.10-1', 'label': '7.2.10-1 (Stable)', 'is_experimental': False, 'download_url': '...'}, ...]
        """
        versions = []
        try:
            headers = {'User-Agent': 'Debian-CachyOS-Kernel-Updater'}
            response = requests.get(self.releases_api, headers=headers, timeout=12)
            if response.status_code == 200:
                releases = response.json()
                for rel in releases:
                    tag = rel.get('tag_name', '')
                    if not tag.startswith('cachyos-'):
                        continue
                    ver = tag.replace('cachyos-', '')
                    is_exp = ('-rc' in tag.lower() or rel.get('prerelease', False))
                    dl_url = None
                    for asset in rel.get('assets', []):
                        aname = asset.get('name', '')
                        if aname.endswith('.tar.gz') and not aname.endswith('.asc'):
                            dl_url = asset.get('browser_download_url')
                            break
                    if not dl_url:
                        dl_url = f"https://github.com/CachyOS/linux/releases/download/{tag}/{tag}.tar.gz"
                    
                    label = f"{ver} (Experimental)" if is_exp else f"{ver} (Stable)"
                    versions.append({
                        'version': ver,
                        'tag': tag,
                        'label': label,
                        'is_experimental': is_exp,
                        'download_url': dl_url
                    })
        except Exception as e:
            print(f"Error fetching releases API in get_available_versions: {e}")

        # Fallback if GitHub API failed or offline
        if not versions:
            fallback_ver = "7.2.10-1"
            fallback_tag = f"cachyos-{fallback_ver}"
            versions.append({
                'version': fallback_ver,
                'tag': fallback_tag,
                'label': f"{fallback_ver} (Stable)",
                'is_experimental': False,
                'download_url': f"https://github.com/CachyOS/linux/releases/download/{fallback_tag}/{fallback_tag}.tar.gz"
            })

        self.available_versions = versions
        return versions

    def get_latest_cachy_version(self, refresh=False):
        """Fetches the latest official stable CachyOS kernel version."""
        releases = self.get_available_versions() if (refresh or not getattr(self, 'available_versions', None)) else self.available_versions
        latest_stable = next((r for r in releases if not r['is_experimental']), None)
        
        if latest_stable:
            self.latest_version = latest_stable['version']
            self.latest_tag = latest_stable['tag']
            self.download_url = latest_stable['download_url']
            return self.latest_version

        # Fallback to PKGBUILD check if needed
        try:
            headers = {'User-Agent': 'Debian-CachyOS-Kernel-Updater'}
            r_pb = requests.get(self.pkgbuild_raw, headers=headers, timeout=10)
            if r_pb.status_code == 200:
                text = r_pb.text
                major = re.search(r'^\s*_major=([^\s#]+)', text, re.M)
                minor = re.search(r'^\s*_minor=([^\s#]+)', text, re.M)
                tagrel = re.search(r'^\s*_tagrel=([^\s#]+)', text, re.M)
                if major and minor:
                    rel_num = tagrel.group(1) if tagrel else '1'
                    pkg_ver = f"{major.group(1)}.{minor.group(1)}-{rel_num}"
                    pkg_tag = f"cachyos-{pkg_ver}"
                    self.latest_version = pkg_ver
                    self.latest_tag = pkg_tag
                    self.download_url = f"https://github.com/CachyOS/linux/releases/download/{pkg_tag}/{pkg_tag}.tar.gz"
                    return self.latest_version
        except Exception as e:
            print(f"Error checking PKGBUILD: {e}")

        if releases:
            self.latest_version = releases[0]['version']
            self.latest_tag = releases[0]['tag']
            self.download_url = releases[0]['download_url']
        else:
            self.latest_version = "7.2.10-1"
            self.latest_tag = "cachyos-7.2.10-1"
            self.download_url = f"https://github.com/CachyOS/linux/releases/download/{self.latest_tag}/{self.latest_tag}.tar.gz"

        return self.latest_version

    def is_matching_running_kernel(self):
        """Checks if the currently running kernel matches the latest CachyOS kernel."""
        current = self.get_current_kernel_version().lower()
        if not self.latest_version or self.latest_version == "Unknown":
            return False
        
        # Extract base version digits like 7.2.8 from 7.2.8-1
        base_ver = self.latest_version.split('-')[0]
        # Check if running kernel contains this version and cachyos
        if base_ver in current and 'cachy' in current:
            return True
        return False

    def _run_cmd(self, cmd, cwd=None, progress_callback=None, env=None, tee_log=True, host_exec=True):
        """Runs a command, logs output live, captures errors, and tees to ~/.cache/cachy-kernel-build/build.log."""
        exec_cmd = list(cmd)
        exec_cwd = cwd
        if host_exec and self._can_flatpak_spawn_host() and exec_cmd and exec_cmd[0] != "flatpak-spawn":
            exec_cmd = self._host_cmd(exec_cmd, cwd=cwd, env=env)
            exec_cwd = None

        if progress_callback:
            progress_callback(f"> {' '.join(cmd)}")

        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        os.makedirs(self.download_dir, exist_ok=True)
        build_log_path = os.path.join(self.download_dir, "build.log")

        log_file = None
        if tee_log:
            try:
                log_file = open(build_log_path, "a", encoding="utf-8", errors="replace")
                log_file.write(f"\n--- [Command: {' '.join(exec_cmd)}] ---\n")
                log_file.flush()
            except Exception:
                log_file = None

        error_regex = re.compile(r'(error:|fatal error:|undefined reference|No space left on device|Killed)', re.IGNORECASE)
        captured_errors = []

        process = subprocess.Popen(
            exec_cmd, cwd=exec_cwd, env=run_env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )

        try:
            if process.stdout:
                for line in iter(process.stdout.readline, ''):
                    stripped = line.rstrip()
                    if log_file:
                        try:
                            log_file.write(line)
                            log_file.flush()
                        except Exception:
                            pass

                    if error_regex.search(stripped):
                        if not re.search(r'0\s+errors', stripped, re.IGNORECASE):
                            captured_errors.append(stripped)

                    if progress_callback and line:
                        progress_callback(stripped)
        finally:
            if process.stdout:
                process.stdout.close()
            if log_file:
                try:
                    log_file.close()
                except Exception:
                    pass

        rc = process.wait()
        if rc != 0:
            err_msg_lines = [
                f"\n=======================================================",
                f"[!] BUILD FAILURE (Return code {rc})",
                f"    Command: {' '.join(cmd)}",
                f"======================================================="
            ]
            if captured_errors:
                err_msg_lines.append("[!] Root-cause compilation error(s) detected:")
                for err_line in captured_errors[-30:]:
                    err_msg_lines.append(f"    >>> {err_line}")
                err_msg_lines.append("-------------------------------------------------------")
            err_msg_lines.append(f"[!] Full build log available at:\n    {build_log_path}")
            err_msg_lines.append("=======================================================\n")

            full_error_text = "\n".join(err_msg_lines)
            if progress_callback:
                progress_callback(full_error_text)
            raise Exception(full_error_text)

    def _read_dpkg_installed_set(self, include_provides: bool = True) -> set:
        """Parses /var/lib/dpkg/status (or /run/host/var/lib/dpkg/status) and returns installed package names."""
        installed = set()
        for status_file in ("/run/host/var/lib/dpkg/status", "/var/lib/dpkg/status"):
            if os.path.isfile(status_file):
                try:
                    with open(status_file, "r", encoding="utf-8", errors="ignore") as f:
                        cur_pkg = None
                        cur_provides = []
                        cur_installed = False
                        for line in f:
                            if line.startswith("Package: "):
                                cur_pkg = line[9:].strip()
                            elif include_provides and line.startswith("Provides: "):
                                prov_raw = line[10:].strip()
                                cur_provides = [p.strip().split()[0] for p in prov_raw.split(",") if p.strip()]
                            elif line.startswith("Status: "):
                                cur_installed = ("install ok installed" in line)
                            elif line == "\n":
                                if cur_installed and cur_pkg:
                                    installed.add(cur_pkg)
                                    if include_provides:
                                        installed.update(cur_provides)
                                cur_pkg = None
                                cur_provides = []
                                cur_installed = False
                        if cur_installed and cur_pkg:
                            installed.add(cur_pkg)
                            if include_provides:
                                installed.update(cur_provides)
                    if installed:
                        return installed
                except Exception:
                    pass
        return installed

    def _check_dpkg_packages_missing(self, pkg_list: list) -> list:
        """Checks a list of Debian packages on the host (or container if running natively) in one batch."""
        if not pkg_list:
            return []
        installed = self._read_dpkg_installed_set(include_provides=True)
        if installed:
            return [p for p in pkg_list if p not in installed]

        # 2. Fallback to dpkg-query via host bridge
        missing = []
        for pkg in pkg_list:
            try:
                res = self._run_host_subproc(
                    ['dpkg-query', '-W', '-f=${Status}', pkg],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5
                )
                if 'install ok installed' not in res.stdout:
                    missing.append(pkg)
            except Exception:
                missing.append(pkg)
        return missing

    def check_build_dependencies(self, use_container=False):
        """Returns a list of missing build dependencies. Checks container engine and image only if use_container is True."""
        if use_container:
            missing = []
            engine = self.get_container_engine()
            if not engine:
                missing.append('podman')
            elif not self.has_container_image():
                missing.append(f"container-image:{self.container_image_tag}")
            return missing

        return self._check_dpkg_packages_missing(self.REQUIRED_BUILD_DEPS)

    def install_build_dependencies(self, progress_callback=None, use_container=False, force_rebuild=False):
        """
        Installs kernel build dependencies using pkexec apt-get.
        Installs container engine and prepares container image ONLY if use_container is True.
        """
        pkgs = [] if use_container else list(self.REQUIRED_BUILD_DEPS)
        if use_container:
            engine = self.get_container_engine()
            if not engine:
                pkgs.append('podman')

        if pkgs:
            if progress_callback:
                progress_callback("\n=======================================================")
                mode_desc = "container engine" if use_container else "host compiler"
                progress_callback(f"[*] Requesting root authorization via pkexec to install {mode_desc} dependencies...")
                progress_callback("=======================================================\n")
                progress_callback(f"Packages to install: {' '.join(pkgs)}\n")

            cmd = ['pkexec', 'apt-get', 'install', '-y'] + pkgs
            try:
                self._run_cmd(cmd, progress_callback=progress_callback)
                if progress_callback:
                    progress_callback("\n[✓] APT dependencies installed successfully!\n")
            except Exception as e:
                if progress_callback:
                    progress_callback(f"\n[!] APT dependency installation failed: {e}\n")
                return False

        # Build and verify container image ONLY if container build is selected
        if use_container:
            if progress_callback:
                progress_callback("=======================================================")
                progress_callback(f"[*] Setting up builder container image ({self.container_image_tag})...")
                progress_callback("=======================================================\n")
            try:
                self.ensure_container_image(progress_callback=progress_callback, force=force_rebuild)
                if progress_callback:
                    progress_callback(f"\n[✓] Container image verified and ready: {self.container_image_tag}\n")
            except Exception as e:
                if progress_callback:
                    progress_callback(f"\n[!] Container image setup failed: {e}\n")
                return False

        if progress_callback:
            mode_str = "Container-isolated" if use_container else "Host"
            progress_callback(f"\n[✓] All {mode_str} dependencies ready!\n")
        return True

    def check_signing_dependencies(self):
        """Returns a list of missing host packages required for Secure Boot kernel signing."""
        return self._check_dpkg_packages_missing(self.REQUIRED_SIGNING_DEPS)

    def ensure_signing_dependencies(self, progress_callback=None):
        """Verifies that host signing packages are installed, installing them via pkexec apt-get if missing."""
        missing = self.check_signing_dependencies()
        if not missing:
            return True
        if progress_callback:
            progress_callback(f"[*] Installing missing host signing dependencies via pkexec: {', '.join(missing)}")
        cmd = ['pkexec', 'apt-get', 'install', '-y'] + missing
        try:
            self._run_cmd(cmd, progress_callback=progress_callback)
            return True
        except Exception as e:
            if progress_callback:
                progress_callback(f"[!] Failed to install signing dependencies: {e}")
            return False

    def get_output_kernel_dir(self, is_native=False, version=None):
        """Returns the full path to the output kernel deb folder: ~/kernel-build-deb/Linux-kernel-CachyOS-(version)-[native-](debian|ubuntu)."""
        ver = version or self.latest_version or "latest"
        os_suffix = getattr(self, "os_tag", "debian")
        tag = f"native-{os_suffix}" if is_native else os_suffix
        folder_name = f"Linux-kernel-CachyOS-{ver}-{tag}"
        return os.path.join(self.output_base_dir, folder_name)

    def get_container_engine(self):
        """Returns 'podman' or 'docker' if available on host (or locally), otherwise None."""
        if self._which_host("podman"):
            return "podman"
        if self._which_host("docker"):
            return "docker"
        return None

    def has_container_image(self):
        """Checks if the Debian/Ubuntu builder container image is already available and has required tools."""
        engine = self.get_container_engine()
        if not engine:
            return False
        try:
            if engine == "podman":
                res = self._run_host_subproc([engine, "image", "exists", self.container_image_tag],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if res.returncode != 0:
                    self._verified_container_images.discard(self.container_image_tag)
                    return False
            else:
                res = self._run_host_subproc([engine, "inspect", "--type=image", self.container_image_tag],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if res.returncode != 0:
                    self._verified_container_images.discard(self.container_image_tag)
                    return False

            # Fast path: avoid spawning a container on repeated UI checks once verified
            if self.container_image_tag in self._verified_container_images:
                return True

            # Verify that essential build tools (such as libdw-dev) exist in the container image
            check_pkg = self._run_host_subproc(
                [engine, "run", "--rm", self.container_image_tag, "dpkg-query", "-W", "-f=${Status}", "libdw-dev"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=15
            )
            if "install ok installed" in check_pkg.stdout:
                self._verified_container_images.add(self.container_image_tag)
                return True
            return False
        except Exception:
            return False

    def ensure_container_image(self, progress_callback=None, force=False):
        """Ensures the Debian/Ubuntu builder image matching the host OS is built and ready."""
        engine = self.get_container_engine()
        if not engine:
            raise Exception("Neither podman nor docker was found. Please install podman or docker.")

        if force:
            self._verified_container_images.discard(self.container_image_tag)
        elif self.has_container_image():
            if progress_callback:
                progress_callback(f"[✓] Container image verified: {self.container_image_tag} ({engine})")
            return True

        is_ubuntu = bool(self.host_distro.get("is_ubuntu"))
        codename = (self.host_distro.get("codename") or "bookworm").lower()
        if is_ubuntu:
            base_img = "docker.io/library/ubuntu:24.04"
            base_label = "Ubuntu 24.04 LTS (Noble)"
        elif codename in ("trixie", "sid", "forky"):
            base_img = "docker.io/library/debian:trixie-slim"
            base_label = f"Debian {codename.capitalize()}"
        else:
            base_img = "docker.io/library/debian:bookworm-slim"
            base_label = "Debian Bookworm"

        if progress_callback:
            progress_callback(f"\n[*] Preparing {self.container_image_tag} using {engine}...")
            progress_callback(f"Base: {base_label} (detected host OS: {self.host_distro.get('name', 'Debian/Ubuntu')})")

        self._stage_host_helper_files()
        staged_cf = os.path.join(self.config_dir, "Containerfile")
        base_dir = os.path.dirname(os.path.abspath(__file__))
        local_cf = os.path.join(base_dir, "Containerfile")

        if not is_ubuntu and os.path.isfile(staged_cf):
            containerfile_path = staged_cf
        elif not is_ubuntu and not self.is_flatpak() and os.path.isfile(local_cf):
            containerfile_path = local_cf
        else:
            containerfile_path = os.path.join(self.download_dir, f"Containerfile.{self.os_tag}")
            os.makedirs(self.download_dir, exist_ok=True)
            with open(containerfile_path, "w") as cf:
                cf.write(f"""FROM {base_img}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \\
    build-essential \\
    bc \\
    bison \\
    flex \\
    libssl-dev \\
    libelf-dev \\
    libncurses-dev \\
    libdw-dev \\
    libudev-dev \\
    libpci-dev \\
    libiberty-dev \\
    autoconf \\
    dwarves \\
    pahole \\
    zstd \\
    xz-utils \\
    lz4 \\
    cpio \\
    rsync \\
    kmod \\
    fakeroot \\
    dpkg-dev \\
    debhelper \\
    devscripts \\
    git \\
    curl \\
    wget \\
    ca-certificates \\
    python3 \\
    python3-gi \\
    python3-requests \\
    clang \\
    llvm \\
    lld \\
    sbsigntool \\
    mokutil \\
    openssl \\
    linux-base \\
    initramfs-tools \\
    && rm -rf /var/lib/apt/lists/*

ENV DEBFULLNAME="CachyOS Kernel Builder"
ENV DEBEMAIL="builder@localhost"

WORKDIR /workspace
""")

        build_cmd = [engine, "build", "-t", self.container_image_tag, "-f", containerfile_path, os.path.dirname(containerfile_path)]
        self._run_cmd(build_cmd, progress_callback=progress_callback)
        if progress_callback:
            progress_callback(f"[✓] Successfully built container image: {self.container_image_tag}\n")
        return True

    def cleanup_cache_on_startup(self, progress_callback=None):
        """
        Checks ~/.cache for the kernel build directory on application launch.
        Preserves any generated .config to persistent storage before cleaning.
        """
        # First ensure persistent storage has an initial config from running CachyOS kernel if missing
        if not os.path.exists(self.saved_config_path):
            current_kernel = self.get_current_kernel_version()
            boot_cfg = f"/boot/config-{current_kernel}"
            if os.path.isfile(boot_cfg) and 'cachy' in current_kernel:
                try:
                    os.makedirs(os.path.dirname(self.saved_config_path), exist_ok=True)
                    shutil.copy(boot_cfg, self.saved_config_path)
                    if progress_callback:
                        progress_callback(f"[✓] Initialized configuration from running CachyOS kernel ({boot_cfg})")
                except Exception as e:
                    if progress_callback:
                        progress_callback(f"[!] Warning: could not seed initial config from {boot_cfg}: {e}")

        if not os.path.exists(self.download_dir):
            if progress_callback:
                progress_callback(f"[i] Cache check: {self.download_dir} is clean.")
            return

        # Do not clean if a build is actively running (lockfile check)
        lock_file = os.path.join(self.download_dir, ".building")
        if os.path.exists(lock_file):
            try:
                with open(lock_file, "r") as lf:
                    pid = int(lf.read().strip())
                # Check if process is still running
                os.kill(pid, 0)
                if progress_callback:
                    progress_callback(f"[i] Build process (PID {pid}) is currently running in cache; skipping cleanup.")
                return
            except (ProcessLookupError, ValueError, OSError):
                # Stale lockfile, proceed with cleanup
                pass

        if progress_callback:
            progress_callback(f"[*] Checking cache folder: {self.download_dir}...")

        # Search for any generated .config inside the download_dir tree to preserve it
        found_config = None
        for root, dirs, files in os.walk(self.download_dir):
            if ".config" in files:
                candidate = os.path.join(root, ".config")
                if os.path.isfile(candidate) and os.path.getsize(candidate) > 1000:
                    found_config = candidate
                    break

        # Save config if found and not yet saved or if found is newer
        if found_config:
            should_save = False
            if not os.path.exists(self.saved_config_path):
                should_save = True
            elif os.path.getmtime(found_config) > os.path.getmtime(self.saved_config_path):
                should_save = True

            if should_save:
                try:
                    os.makedirs(os.path.dirname(self.saved_config_path), exist_ok=True)
                    shutil.copy(found_config, self.saved_config_path)
                    if progress_callback:
                        progress_callback(f"[✓] Preserved generated kernel configuration to {self.saved_config_path}")
                except Exception as e:
                    if progress_callback:
                        progress_callback(f"[!] Warning: could not backup config: {e}")

        # Clean the cachy-kernel-build folder with robust permission handling
        try:
            for root, dirs, files in os.walk(self.download_dir, topdown=False):
                for name in files:
                    p = os.path.join(root, name)
                    try:
                        os.chmod(p, stat.S_IWUSR | stat.S_IRUSR)
                        os.unlink(p)
                    except Exception:
                        pass
                for name in dirs:
                    p = os.path.join(root, name)
                    try:
                        os.chmod(p, stat.S_IWUSR | stat.S_IRUSR | stat.S_IXUSR)
                        os.rmdir(p)
                    except Exception:
                        pass
            try:
                os.rmdir(self.download_dir)
            except Exception:
                shutil.rmtree(self.download_dir, ignore_errors=True)

            if progress_callback:
                progress_callback(f"[✓] Cleaned previous build artifacts from {self.download_dir}\n")
        except Exception as e:
            if progress_callback:
                progress_callback(f"[!] Warning: could not clean {self.download_dir}: {e}\n")

    def download_kernel(self, version=None, tag=None, download_url=None, progress_callback=None):
        """Downloads the official pre-patched CachyOS kernel source and configuration."""
        if version and tag and download_url:
            self.latest_version = version
            self.latest_tag = tag
            self.download_url = download_url
        elif tag:
            self.latest_tag = tag
            self.latest_version = version or tag.replace('cachyos-', '')
            self.download_url = download_url or f"https://github.com/CachyOS/linux/releases/download/{self.latest_tag}/{self.latest_tag}.tar.gz"
        elif version:
            self.latest_version = version
            self.latest_tag = f"cachyos-{version}"
            self.download_url = download_url or f"https://github.com/CachyOS/linux/releases/download/{self.latest_tag}/{self.latest_tag}.tar.gz"
        elif not self.latest_version or not self.download_url:
            self.get_latest_cachy_version()

        if not self.download_url:
            raise Exception("Unable to find download URL for CachyOS kernel.")

        os.makedirs(self.download_dir, exist_ok=True)

        # Write active build lockfile
        lock_file = os.path.join(self.download_dir, ".building")
        try:
            with open(lock_file, "w") as lf:
                lf.write(str(os.getpid()))
        except Exception:
            pass

        archive_name = f"{self.latest_tag}.tar.gz"
        archive_path = os.path.join(self.download_dir, archive_name)
        part_path = os.path.join(self.download_dir, f"{archive_name}.part")

        if progress_callback:
            progress_callback(f"Target: CachyOS Kernel {self.latest_version}")

        # Tarball integrity validator
        def is_tarball_valid(path):
            if not os.path.isfile(path) or os.path.getsize(path) < 10000000:
                return False
            try:
                with open(path, "rb") as tf:
                    magic = tf.read(2)
                return magic == b"\x1f\x8b"
            except Exception:
                return False

        # Download tarball with streaming progress indication and integrity check
        if not is_tarball_valid(archive_path):
            if os.path.exists(archive_path):
                try:
                    os.unlink(archive_path)
                except Exception:
                    pass

            if progress_callback:
                progress_callback(f"Downloading from {self.download_url}...")

            headers = {'User-Agent': 'Debian-CachyOS-Kernel-Updater'}
            with requests.get(self.download_url, headers=headers, stream=True, timeout=30) as resp:
                resp.raise_for_status()
                total_size = int(resp.headers.get('Content-Length', 0))
                downloaded = 0
                last_pct = -2
                with open(part_path, "wb") as out_f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            out_f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                percent = min(100, int(downloaded * 100 / total_size))
                                if percent >= last_pct + 2 or percent == 100:
                                    last_pct = percent
                                    mb_down = downloaded / (1024 * 1024)
                                    mb_total = total_size / (1024 * 1024)
                                    if progress_callback:
                                        progress_callback(f"Downloading: {percent}% ({mb_down:.1f} MB / {mb_total:.1f} MB)")

            if not is_tarball_valid(part_path):
                raise Exception("Downloaded kernel archive is incomplete or corrupted. Please check network connection.")

            os.replace(part_path, archive_path)
        else:
            if progress_callback:
                progress_callback(f"[✓] Verified existing archive: {archive_name}")

        extracted_dir = os.path.join(self.download_dir, self.latest_tag)

        # Validate extracted directory integrity
        def is_extracted_valid(path):
            if not os.path.isdir(path):
                return False
            makefile = os.path.join(path, "Makefile")
            compiler_h = os.path.join(path, "include/linux/compiler-version.h")
            return os.path.isfile(makefile) and os.path.isfile(compiler_h)

        if not is_extracted_valid(extracted_dir):
            if os.path.exists(extracted_dir):
                shutil.rmtree(extracted_dir, ignore_errors=True)

            if progress_callback:
                progress_callback(f"Extracting {archive_name}...")

            self._run_cmd(['tar', '-xf', archive_path], cwd=self.download_dir, progress_callback=progress_callback, host_exec=False)

        # Download official CachyOS config if needed
        config_path = os.path.join(self.download_dir, "config")
        if not os.path.exists(config_path) or os.path.getsize(config_path) < 1000:
            if progress_callback:
                progress_callback("Fetching official CachyOS kernel config...")
            try:
                r_cfg = requests.get(self.cachy_config_raw, headers={'User-Agent': 'Debian-CachyOS-Kernel-Updater'}, timeout=15)
                if r_cfg.status_code == 200 and len(r_cfg.content) > 1000:
                    with open(config_path, "wb") as cf:
                        cf.write(r_cfg.content)
            except Exception:
                pass

        if not os.path.exists(extracted_dir):
            # Fallback search if folder name differs
            candidates = [
                d for d in os.listdir(self.download_dir) 
                if os.path.isdir(os.path.join(self.download_dir, d)) and 'cachy' in d
            ]
            if candidates:
                extracted_dir = os.path.join(self.download_dir, candidates[0])
            else:
                raise Exception(f"Extracted directory not found in {self.download_dir}")

        if progress_callback:
            progress_callback(f"[✓] Kernel source verified and ready in {extracted_dir}")

        return extracted_dir

    def compile_kernel(
        self,
        kernel_dir,
        progress_callback=None,
        stage_callback=None,
        use_container=False,
        optimize_for_system=None,
        use_localmodconfig=True,
        strip_debug_symbols=True,
        cpu_scheduler='bore',
        compiler_lto='gcc_none',
        cpu_arch='generic',
        tick_rate='1000',
        tickless=True,
        threads=None
    ):
        """Prepares configuration and compiles the kernel into Debian packages."""
        # Handle backwards compatibility for optimize_for_system flag
        if optimize_for_system is True:
            cpu_arch = 'native'
            use_localmodconfig = True
        elif optimize_for_system is False and cpu_arch == 'generic':
            pass

        is_native = (cpu_arch == 'native')

        if stage_callback:
            stage_callback(3, "Sanitizing configuration for Debian stability...")
        elif progress_callback:
            progress_callback("Stage 3: Setting up and sanitizing kernel configuration for Debian...")

        config_dst = os.path.join(kernel_dir, ".config")

        # Recover saved config if available, otherwise use running CachyOS kernel or downloaded official config.
        # When building in container (Docker/Podman), always use the official CachyOS base config to build for ALL hardware.
        active_saved_cfg = self.saved_native_config_path if is_native else self.saved_config_path
        config_copied = False
        if not use_container and os.path.exists(active_saved_cfg) and os.path.getsize(active_saved_cfg) > 1000:
            if progress_callback:
                progress_callback(f"[✓] Recovering previously saved kernel configuration from {active_saved_cfg}...")
            shutil.copy(active_saved_cfg, config_dst)
            config_copied = True
        elif not use_container:
            current_kernel = self.get_current_kernel_version()
            boot_cfg = f"/boot/config-{current_kernel}"
            if os.path.isfile(boot_cfg) and 'cachy' in current_kernel:
                if progress_callback:
                    progress_callback(f"[✓] Recovering configuration from running kernel ({boot_cfg})...")
                shutil.copy(boot_cfg, config_dst)
                config_copied = True

        if not config_copied:
            if progress_callback:
                if use_container:
                    progress_callback("[*] Container build (Docker/Podman): Applying official CachyOS base kernel configuration with full generic driver support for all hardware...")
                else:
                    progress_callback("Applying official CachyOS base kernel configuration...")
            config_src = os.path.join(self.download_dir, "config")
            if os.path.exists(config_src):
                shutil.copy(config_src, config_dst)
            else:
                resp = self._http_get(self.cachy_config_raw, timeout=20)
                with open(config_dst, "wb") as f:
                    f.write(resp.content)

        if not use_container:
            missing_deps = self.check_build_dependencies(use_container=False)
            if missing_deps:
                raise Exception(
                    f"Missing required host compiler packages: {', '.join(missing_deps)}.\n"
                    f"Please install them by clicking 'Install Dependencies' or run:\n"
                    f"sudo apt-get install -y {' '.join(missing_deps)}"
                )

        # Apply necessary tweaks for Debian environment & sanitize .config in a single batched invocation
        # 1. Remove Debian/Canonical hardcoded certificate paths (Prevents Makefile:2207 crash)
        # 2. Bypass build-time module signing (avoids ephemeral key/cert failures in containers)
        # 3. Keep signature verification support compiled into the kernel for post-build user signing
        # 4. Disable heavy DWARF/BTF debug symbols if strip_debug_symbols is True (prevents 35GB disk exhaustion & OOM crashes)
        # 5. Disable strict -Werror and Rust (prevents compiler version mismatch failures on Debian)
        config_sanitize_cmd = [
            'scripts/config',
            '--set-str', 'SYSTEM_TRUSTED_KEYS', '',
            '--set-str', 'SYSTEM_REVOCATION_KEYS', '',
            '--set-str', 'MODULE_SIG_KEY', '',
            '--disable', 'MODULE_SIG_ALL',
            '--disable', 'MODULE_SIG_FORCE',
            '--enable', 'MODULE_SIG',
            '--enable', 'MODULE_SIG_SHA512',
            '--enable', 'KEXEC_SIG',
            '--disable', 'WERROR',
            '--disable', 'DRM_WERROR',
            '--disable', 'RUST',
            '--disable', 'INTEL_TDX_HOST',
            '--disable', 'KVM_INTEL_TDX',
        ]

        if strip_debug_symbols:
            config_sanitize_cmd.extend([
                '--enable', 'DEBUG_INFO_NONE',
                '--disable', 'DEBUG_INFO',
                '--disable', 'DEBUG_INFO_BTF',
                '--disable', 'DEBUG_INFO_BTF_MODULES',
                '--disable', 'DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT',
                '--disable', 'DEBUG_INFO_DWARF4',
                '--disable', 'DEBUG_INFO_DWARF5',
                '--disable', 'DEBUG_INFO_SPLIT',
            ])
        else:
            config_sanitize_cmd.extend([
                '--disable', 'DEBUG_INFO_NONE',
                '--enable', 'DEBUG_INFO_DWARF5',
                '--enable', 'DEBUG_INFO_BTF',
            ])

        # 2. CPU Scheduler Configuration (Default: BORE)
        if cpu_scheduler == 'bore':
            config_sanitize_cmd.extend(['--enable', 'CONFIG_SCHED_BORE'])
        else:
            config_sanitize_cmd.extend(['--disable', 'CONFIG_SCHED_BORE'])

        # 3. Compiler & LTO Selection
        use_llvm = compiler_lto.startswith('clang')
        if compiler_lto in ('gcc_none', 'clang_none'):
            config_sanitize_cmd.extend(['--disable', 'LTO_CLANG_THIN', '--disable', 'LTO_CLANG_FULL', '--enable', 'LTO_NONE'])
        elif compiler_lto == 'clang_thin':
            config_sanitize_cmd.extend(['--enable', 'LTO_CLANG', '--enable', 'LTO_CLANG_THIN', '--disable', 'LTO_NONE', '--disable', 'LTO_CLANG_FULL'])
        elif compiler_lto == 'clang_full':
            config_sanitize_cmd.extend(['--enable', 'LTO_CLANG', '--enable', 'LTO_CLANG_FULL', '--disable', 'LTO_NONE', '--disable', 'LTO_CLANG_THIN'])

        # 4. Tick Rate & Preemption (Default: 1000 Hz + Full Tickless Idle)
        hz_options = ('100', '250', '300', '500', '600', '750', '1000')
        if tick_rate in ('1000', '500', '300', '250'):
            for hz in hz_options:
                config_sanitize_cmd.extend(['--enable' if hz == tick_rate else '--disable', f'HZ_{hz}'])
            config_sanitize_cmd.extend(['--set-val', 'HZ', tick_rate])

        if tickless:
            config_sanitize_cmd.extend(['--enable', 'NO_HZ_IDLE', '--enable', 'NO_HZ', '--enable', 'NO_HZ_COMMON', '--disable', 'HZ_PERIODIC'])

        self._run_cmd(['bash'] + config_sanitize_cmd, cwd=kernel_dir, progress_callback=None, host_exec=False)

        # Prepare container runner prefix if container build is selected
        container_prefix = []
        if use_container:
            engine = self.get_container_engine()
            if not engine:
                raise Exception("Container build requested but neither podman nor docker is installed.")
            self.ensure_container_image(progress_callback=progress_callback)
            
            rel_kernel = os.path.relpath(kernel_dir, self.download_dir)
            container_prefix = [engine, "run", "--rm"]
            if engine == "podman":
                container_prefix += ["--userns=keep-id"]
            else:
                container_prefix += ["-u", f"{os.getuid()}:{os.getgid()}"]
            
            container_prefix += [
                "-v", f"{self.download_dir}:/workspace:z",
                "-w", f"/workspace/{rel_kernel}",
                "-e", "DEBFULLNAME=CachyOS Debian Builder",
                "-e", "DEBEMAIL=builder@localhost",
                "-e", "KBUILD_BUILD_USER=cachyos",
                "-e", "KBUILD_BUILD_HOST=debian",
                "-e", "DPKG_FLAGS=-d -uc -us",
                self.container_image_tag
            ]

        hw = self.detect_hardware()

        # 5. Hardware Drivers: When compiling in Container (Docker/Podman), compile for ALL hardware (no container-specific driver trimming)
        if use_container:
            if use_localmodconfig and progress_callback:
                progress_callback("\n=======================================================")
                progress_callback("[*] Container build detected (Docker/Podman):")
                progress_callback("    Compiling with full driver support for ALL hardware.")
                progress_callback("    Hardware driver trimming ('make localmodconfig') is bypassed to ensure universal hardware compatibility.")
                progress_callback("=======================================================\n")
            use_localmodconfig = False

        if use_localmodconfig:
            if progress_callback:
                progress_callback("\n=======================================================")
                progress_callback("[*] 'Current System Hardware Config' (localmodconfig):")
                progress_callback(f"    • CPU: {hw['cpu_model']} ({hw['threads']} threads)")
                progress_callback(f"    • Vendor: {hw['vendor']} | Chassis: {'Laptop (Battery)' if hw['is_laptop'] else 'Desktop/Workstation'}")
                if hw['manufacturer'] != 'Generic':
                    progress_callback(f"    • Machine: {hw['manufacturer']} {hw['product_name']}")
                progress_callback(f"    • Root Filesystem: {hw['root_fs']}")
                if hw.get('wifi_adapter'):
                    progress_callback(f"    • Wi-Fi Adapter: {hw['wifi_adapter']}")
                if hw.get('bluetooth_adapter'):
                    progress_callback(f"    • Bluetooth: {hw['bluetooth_adapter']}")
                progress_callback(f"    • Active Modules: {len(hw['loaded_modules'])} loaded hardware drivers detected")
                progress_callback("=======================================================\n")

            lsmod_host_file = os.path.join(self.download_dir, "host_lsmod.txt")
            try:
                if os.path.exists('/proc/modules'):
                    with open('/proc/modules', 'r') as pm:
                        mod_lines = ["Module                  Size  Used by"]
                        for line in pm:
                            parts = line.split()
                            if len(parts) >= 3:
                                mod_lines.append(f"{parts[0]} {parts[1]} {parts[2]}")
                        lsmod_raw = "\n".join(mod_lines) + "\n"
                else:
                    res = self._run_host_subproc(['lsmod'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5)
                    lsmod_raw = res.stdout if res.returncode == 0 else "Module                  Size  Used by\n"
            except Exception as e:
                lsmod_raw = "Module                  Size  Used by\n"
                if progress_callback:
                    progress_callback(f"[!] Warning: failed to export host lsmod: {e}")

            # Seed essential modules so streamline_config never drops Wi-Fi, Bluetooth, Crypto, or Storage
            essential_seed_modules = [
                # Wi-Fi stack & common drivers
                'cfg80211', 'mac80211', 'rfkill',
                'iwlwifi', 'iwlmvm', 'iwldvm',
                'rtw88_core', 'rtw88_pci', 'rtw88_8822ce', 'rtw88_8821ce', 'rtw88_8723de',
                'rtw89_core', 'rtw89_pci', 'rtw89_8852ae', 'rtw89_8852be', 'rtw89_8852ce',
                'ath9k', 'ath10k_core', 'ath10k_pci', 'ath11k', 'ath11k_pci',
                'mt76', 'mt7921e', 'mt7921_common', 'brcmfmac', 'brcmutil',
                # Bluetooth stack & drivers
                'bluetooth', 'btusb', 'btrtl', 'btbcm', 'btintel', 'btmtk', 'hci_uart', 'hidp', 'bnep', 'rfcomm',
                # Cryptography (Mandatory for iwd, wpa_supplicant, WPA2/WPA3 & Bluetooth)
                'cmac', 'ccm', 'gcm', 'ctr', 'cbc', 'ecb', 'sha256', 'sha512', 'sha1',
                'aes_generic', 'aesni_intel', 'crypto_user', 'af_alg', 'algif_hash', 'algif_skcipher', 'algif_aead', 'algif_rng',
                'ecdh_generic', 'ecc', 'crc16', 'arc4', 'michael_mic',
                # Core storage & input
                'nvme', 'nvme_core', 'ahci', 'libahci', 'sd_mod', 'usb_storage', 'uas',
                'hid', 'usbhid', 'hid_generic', 'ext4', 'btrfs', 'vfat', 'fat'
            ]
            existing_mods = set()
            for line in lsmod_raw.splitlines()[1:]:
                p = line.split()
                if p:
                    existing_mods.add(p[0])

            lsmod_lines = [lsmod_raw.rstrip()]
            for em in essential_seed_modules:
                if em not in existing_mods:
                    lsmod_lines.append(f"{em} 16384 0")

            try:
                with open(lsmod_host_file, "w") as f:
                    f.write("\n".join(lsmod_lines) + "\n")
            except Exception as e:
                if progress_callback:
                    progress_callback(f"[!] Warning: failed to write seeded lsmod: {e}")

            if progress_callback:
                progress_callback("[*] Applying 'make localmodconfig' to match machine hardware...")

            try:
                if use_container:
                    self._run_cmd(
                        container_prefix + ['sh', '-c', 'make localmodconfig LSMOD=/workspace/host_lsmod.txt < /dev/null'],
                        cwd=kernel_dir,
                        progress_callback=progress_callback
                    )
                else:
                    self._run_cmd(
                        ['sh', '-c', f'make localmodconfig LSMOD={lsmod_host_file} < /dev/null'],
                        cwd=kernel_dir,
                        progress_callback=progress_callback
                    )
                if progress_callback:
                    progress_callback("[✓] Hardware drivers tailored to current machine.")
            except Exception as e:
                if progress_callback:
                    progress_callback(f"[!] Warning: localmodconfig note: {e}")

        # Always enforce safety baselines for Storage, Filesystem, Input, RFKILL, Wi-Fi, Bluetooth & Crypto
        if progress_callback:
            progress_callback("[*] Enforcing hardware safety baselines for Wi-Fi, Bluetooth, crypto, storage, and filesystems...")

        safeties = [
            # Essential filesystems
            ('enable', 'CONFIG_BPF_SYSCALL'),
            ('enable', 'CONFIG_BPF_JIT'),
            ('enable', 'CONFIG_EXT4_FS'),
            ('module', 'CONFIG_BTRFS_FS'),
            ('enable', 'CONFIG_VFAT_FS'),
            ('enable', 'CONFIG_FAT_FS'),
            ('module', 'CONFIG_EXFAT_FS'),
            ('module', 'CONFIG_NTFS3_FS'),
            # Essential storage
            ('enable', 'CONFIG_BLK_DEV_SD'),
            ('enable', 'CONFIG_BLK_DEV_NVME'),
            ('enable', 'CONFIG_NVME_CORE'),
            ('enable', 'CONFIG_ATA'),
            ('enable', 'CONFIG_SATA_AHCI'),
            ('enable', 'CONFIG_USB_STORAGE'),
            ('module', 'CONFIG_USB_UAS'),
            # Essential input
            ('enable', 'CONFIG_HID'),
            ('enable', 'CONFIG_HID_GENERIC'),
            ('enable', 'CONFIG_USB_HID'),
            ('enable', 'CONFIG_INPUT_EVDEV'),

            # RFKILL & Wireless Core
            ('enable', 'CONFIG_RFKILL'),
            ('enable', 'CONFIG_RFKILL_LEDS'),
            ('enable', 'CONFIG_RFKILL_INPUT'),
            ('enable', 'CONFIG_WIRELESS'),
            ('module', 'CONFIG_CFG80211'),
            ('enable', 'CONFIG_CFG80211_DEFAULT_PS'),
            ('enable', 'CONFIG_CFG80211_CRDA_SUPPORT'),
            ('enable', 'CONFIG_CFG80211_WEXT'),
            ('module', 'CONFIG_MAC80211'),
            ('enable', 'CONFIG_MAC80211_HAS_RC'),
            ('enable', 'CONFIG_MAC80211_RC_MINSTREL'),
            ('enable', 'CONFIG_MAC80211_RC_DEFAULT_MINSTREL'),
            ('set-str', 'CONFIG_MAC80211_RC_DEFAULT', 'minstrel_ht'),
            ('enable', 'CONFIG_MAC80211_MESH'),
            ('enable', 'CONFIG_MAC80211_LEDS'),

            # Wireless & Bluetooth Cryptography (Mandatory for iwd, wpa_supplicant, WPA2/WPA3-SAE, 802.11w/PMF, BlueZ)
            ('enable', 'CONFIG_CRYPTO_AES'),
            ('module', 'CONFIG_CRYPTO_AES_NI_INTEL'),
            ('module', 'CONFIG_CRYPTO_AES_X86_64'),
            ('module', 'CONFIG_CRYPTO_CMAC'),
            ('module', 'CONFIG_CRYPTO_HMAC'),
            ('enable', 'CONFIG_CRYPTO_SHA256'),
            ('enable', 'CONFIG_CRYPTO_SHA512'),
            ('enable', 'CONFIG_CRYPTO_SHA1'),
            ('module', 'CONFIG_CRYPTO_CCM'),
            ('module', 'CONFIG_CRYPTO_GCM'),
            ('module', 'CONFIG_CRYPTO_CBC'),
            ('module', 'CONFIG_CRYPTO_CTR'),
            ('module', 'CONFIG_CRYPTO_ECB'),
            ('module', 'CONFIG_CRYPTO_MICHAEL_MIC'),
            ('module', 'CONFIG_CRYPTO_ARC4'),
            ('module', 'CONFIG_CRYPTO_LIB_ARC4'),
            ('enable', 'CONFIG_CRYPTO_LIB_AES'),
            ('module', 'CONFIG_CRYPTO_LIB_GF128MUL'),
            ('module', 'CONFIG_CRYPTO_ECDH'),
            ('module', 'CONFIG_CRYPTO_ECC'),
            ('module', 'CONFIG_CRYPTO_USER_API'),
            ('module', 'CONFIG_CRYPTO_USER_API_HASH'),
            ('module', 'CONFIG_CRYPTO_USER_API_SKCIPHER'),
            ('module', 'CONFIG_CRYPTO_USER_API_AEAD'),
            ('module', 'CONFIG_CRYPTO_USER_API_RNG'),
            ('enable', 'CONFIG_KEY_DH_OPERATIONS'),

            # Bluetooth Subsystem & Drivers
            ('module', 'CONFIG_BT'),
            ('enable', 'CONFIG_BT_BREDR'),
            ('module', 'CONFIG_BT_RFCOMM'),
            ('enable', 'CONFIG_BT_RFCOMM_TTY'),
            ('module', 'CONFIG_BT_BNEP'),
            ('enable', 'CONFIG_BT_BNEP_MC_FILTER'),
            ('enable', 'CONFIG_BT_BNEP_PROTO_FILTER'),
            ('module', 'CONFIG_BT_HIDP'),
            ('enable', 'CONFIG_BT_LE'),
            ('enable', 'CONFIG_BT_LEDS'),
            ('module', 'CONFIG_BT_HCIBTUSB'),
            ('enable', 'CONFIG_BT_HCIBTUSB_AUTOSUSPEND'),
            ('enable', 'CONFIG_BT_HCIBTUSB_BCM'),
            ('enable', 'CONFIG_BT_HCIBTUSB_MTK'),
            ('enable', 'CONFIG_BT_HCIBTUSB_RTL'),
            ('module', 'CONFIG_BT_HCIUART'),
            ('enable', 'CONFIG_BT_HCIUART_H4'),
            ('enable', 'CONFIG_BT_HCIUART_BCSP'),
            ('enable', 'CONFIG_BT_HCIUART_ATH3K'),
            ('enable', 'CONFIG_BT_HCIUART_LL'),
            ('enable', 'CONFIG_BT_HCIUART_3WIRE'),
            ('enable', 'CONFIG_BT_HCIUART_INTEL'),
            ('enable', 'CONFIG_BT_HCIUART_BCM'),
            ('enable', 'CONFIG_BT_HCIUART_QCA'),
            ('enable', 'CONFIG_BT_HCIUART_AG6XX'),
            ('enable', 'CONFIG_BT_HCIUART_MRVL'),
            ('enable', 'CONFIG_BT_HCIUART_RTL'),
            ('enable', 'CONFIG_BT_HCIUART_SERDEV'),
            ('module', 'CONFIG_BT_INTEL'),
            ('module', 'CONFIG_BT_INTEL_PCIE'),
            ('module', 'CONFIG_BT_BCM'),
            ('module', 'CONFIG_BT_RTL'),
            ('module', 'CONFIG_BT_MTK'),
            ('module', 'CONFIG_BT_MTKUART'),
            ('module', 'CONFIG_BT_QCA'),
            ('module', 'CONFIG_BT_ATH3K'),
            ('module', 'CONFIG_BT_MRVL'),
            ('module', 'CONFIG_BT_MRVL_SDIO'),
            ('module', 'CONFIG_BT_HCIVHCI'),

            # Wi-Fi Drivers: Major Vendor Families
            # Intel Wi-Fi
            ('enable', 'CONFIG_WLAN_VENDOR_INTEL'),
            ('module', 'CONFIG_IWLWIFI'),
            ('enable', 'CONFIG_IWLWIFI_LEDS'),
            ('module', 'CONFIG_IWLMVM'),
            ('module', 'CONFIG_IWLDVM'),
            ('enable', 'CONFIG_IWLWIFI_OPMODE_MODULAR'),
            # Realtek Wi-Fi
            ('enable', 'CONFIG_WLAN_VENDOR_REALTEK'),
            ('module', 'CONFIG_RTL_CARDS'),
            ('module', 'CONFIG_RTL8XXXU'),
            ('module', 'CONFIG_RTW88'),
            ('module', 'CONFIG_RTW88_CORE'),
            ('module', 'CONFIG_RTW88_PCI'),
            ('module', 'CONFIG_RTW88_USB'),
            ('module', 'CONFIG_RTW88_8822BE'),
            ('module', 'CONFIG_RTW88_8822CE'),
            ('module', 'CONFIG_RTW88_8723DE'),
            ('module', 'CONFIG_RTW88_8821CE'),
            ('module', 'CONFIG_RTW88_8822BU'),
            ('module', 'CONFIG_RTW88_8822CU'),
            ('module', 'CONFIG_RTW88_8723DU'),
            ('module', 'CONFIG_RTW88_8821CU'),
            ('module', 'CONFIG_RTW89'),
            ('module', 'CONFIG_RTW89_CORE'),
            ('module', 'CONFIG_RTW89_PCI'),
            ('module', 'CONFIG_RTW89_8852AE'),
            ('module', 'CONFIG_RTW89_8852BE'),
            ('module', 'CONFIG_RTW89_8852CE'),
            ('module', 'CONFIG_RTW89_8922AE'),
            # Qualcomm / Atheros Wi-Fi
            ('enable', 'CONFIG_WLAN_VENDOR_ATH'),
            ('module', 'CONFIG_ATH9K'),
            ('enable', 'CONFIG_ATH9K_PCI'),
            ('module', 'CONFIG_ATH9K_HTC'),
            ('module', 'CONFIG_ATH10K'),
            ('module', 'CONFIG_ATH10K_PCI'),
            ('module', 'CONFIG_ATH11K'),
            ('module', 'CONFIG_ATH11K_PCI'),
            ('module', 'CONFIG_ATH12K'),
            # MediaTek Wi-Fi
            ('enable', 'CONFIG_WLAN_VENDOR_MEDIATEK'),
            ('module', 'CONFIG_MT76_CORE'),
            ('module', 'CONFIG_MT76_USB'),
            ('module', 'CONFIG_MT76_SDIO'),
            ('module', 'CONFIG_MT76x0U'),
            ('module', 'CONFIG_MT76x2E'),
            ('module', 'CONFIG_MT76x2U'),
            ('module', 'CONFIG_MT7603E'),
            ('module', 'CONFIG_MT7615E'),
            ('module', 'CONFIG_MT7663U'),
            ('module', 'CONFIG_MT7663S'),
            ('module', 'CONFIG_MT7915E'),
            ('module', 'CONFIG_MT7921E'),
            ('module', 'CONFIG_MT7921U'),
            ('module', 'CONFIG_MT7921S'),
            ('module', 'CONFIG_MT7925E'),
            ('module', 'CONFIG_MT7925U'),
            # Broadcom Wi-Fi
            ('enable', 'CONFIG_WLAN_VENDOR_BROADCOM'),
            ('module', 'CONFIG_BRCMUTIL'),
            ('module', 'CONFIG_BRCMSMAC'),
            ('module', 'CONFIG_BRCMFMAC'),
            ('enable', 'CONFIG_BRCMFMAC_PROTO_BCDC'),
            ('enable', 'CONFIG_BRCMFMAC_SDIO'),
            ('enable', 'CONFIG_BRCMFMAC_USB'),
            ('enable', 'CONFIG_BRCMFMAC_PCIE'),
            ('module', 'CONFIG_B43'),
        ]

        # Laptop / Chassis tuning
        if hw['is_laptop']:
            safeties.extend([
                ('enable', 'CONFIG_CPU_FREQ_GOV_POWERSAVE'),
                ('enable', 'CONFIG_NO_HZ_IDLE'),
            ])

        # Manufacturer-specific ACPI modules
        mfg = hw['manufacturer'].lower()
        if 'lenovo' in mfg or 'thinkpad' in hw['product_name'].lower():
            safeties.append(('module', 'CONFIG_THINKPAD_ACPI'))
        elif 'dell' in mfg:
            safeties.append(('module', 'CONFIG_DELL_WMI'))
        elif 'asus' in mfg:
            safeties.append(('module', 'CONFIG_ASUS_WMI'))

        batched_safety_cmd = ['bash', 'scripts/config']
        for item in safeties:
            if len(item) == 2:
                action, opt = item
                batched_safety_cmd.extend([f'--{action}', opt])
            elif len(item) == 3:
                action, opt, val = item
                batched_safety_cmd.extend([f'--{action}', opt, str(val)])

        if use_localmodconfig:
            nr_cpus = max(16, min(128, hw['threads'] * 2))
            batched_safety_cmd.extend(['--set-val', 'CONFIG_NR_CPUS', str(nr_cpus)])

        self._run_cmd(batched_safety_cmd, cwd=kernel_dir, progress_callback=None, host_exec=False)

        # 6. CPU Microarchitecture Optimization
        os_suffix = getattr(self, "os_tag", "debian")
        if cpu_arch == 'native':
            arch_cmd = ['bash', 'scripts/config', '--disable', 'CONFIG_MGENERIC_CPU', '--enable', 'CONFIG_X86_NATIVE_CPU']
            if 'intel' in hw['vendor'].lower():
                arch_cmd.extend(['--enable', 'CONFIG_X86_INTEL_PSTATE', '--enable', 'CONFIG_INTEL_IDLE', '--enable', 'CONFIG_MNATIVE_INTEL'])
            elif 'amd' in hw['vendor'].lower():
                arch_cmd.extend(['--enable', 'CONFIG_X86_AMD_PSTATE', '--enable', 'CONFIG_MNATIVE_AMD'])
            arch_cmd.extend(['--set-str', 'CONFIG_LOCALVERSION', f'-cachyos-native-{os_suffix}'])
            self._run_cmd(arch_cmd, cwd=kernel_dir, progress_callback=None, host_exec=False)
            if progress_callback:
                progress_callback(f"[✓] CPU Architecture: Native (-march=native enabled, localversion=-cachyos-native-{os_suffix})")
        elif cpu_arch == 'x86-64-v3':
            self._run_cmd([
                'bash', 'scripts/config',
                '--enable', 'CONFIG_GENERIC_CPU',
                '--disable', 'CONFIG_X86_NATIVE_CPU',
                '--set-val', 'CONFIG_X86_64_VERSION', '3',
                '--set-str', 'CONFIG_LOCALVERSION', f'-cachyos-v3-{os_suffix}'
            ], cwd=kernel_dir, progress_callback=None, host_exec=False)
            if progress_callback:
                progress_callback(f"[✓] CPU Architecture: Generic x86-64-v3 (AVX2, localversion=-cachyos-v3-{os_suffix})")
        else: # generic (x86-64-v2 safe default)
            self._run_cmd([
                'bash', 'scripts/config',
                '--enable', 'CONFIG_GENERIC_CPU',
                '--disable', 'CONFIG_X86_NATIVE_CPU',
                '--set-val', 'CONFIG_X86_64_VERSION', '2',
                '--set-str', 'CONFIG_LOCALVERSION', f'-cachyos-{os_suffix}'
            ], cwd=kernel_dir, progress_callback=None, host_exec=False)
            if progress_callback:
                progress_callback(f"[✓] CPU Architecture: Generic x86-64 / x86-64-v2 (localversion=-cachyos-{os_suffix})")

        # 7. Update configuration for the new kernel version non-interactively
        toolchain_flags = ['LLVM=1', 'LLVM_IAS=1'] if use_llvm else []
        olddef_cmd = ['make'] + toolchain_flags + ['olddefconfig']
        if use_container:
            self._run_cmd(container_prefix + olddef_cmd, cwd=kernel_dir, progress_callback=progress_callback)
        else:
            self._run_cmd(olddef_cmd, cwd=kernel_dir, progress_callback=progress_callback)

        # 8. Save the generated configuration to persistent storage for future updates
        try:
            target_saved_cfg = self.saved_native_config_path if is_native else self.saved_config_path
            os.makedirs(os.path.dirname(target_saved_cfg), exist_ok=True)
            shutil.copy(config_dst, target_saved_cfg)
            if progress_callback:
                progress_callback(f"[✓] Preserved updated kernel configuration in {target_saved_cfg}")
        except Exception as e:
            if progress_callback:
                progress_callback(f"[!] Warning: could not save configuration: {e}")

        # 9. Clean stale packaging state
        debian_pkg_dir = os.path.join(kernel_dir, "debian")
        if os.path.exists(debian_pkg_dir):
            if progress_callback:
                progress_callback("[*] Cleaning stale debian/ packaging directory before build...")
            try:
                shutil.rmtree(debian_pkg_dir, ignore_errors=True)
            except Exception as e:
                if progress_callback:
                    progress_callback(f"[!] Warning: could not remove debian directory: {e}")

        # 10. Packaging environment variables and thread allocation
        packaging_env = {
            'DEBFULLNAME': 'CachyOS Debian Builder',
            'DEBEMAIL': 'builder@localhost',
            'KBUILD_BUILD_USER': 'cachyos',
            'KBUILD_BUILD_HOST': 'debian',
            'DPKG_FLAGS': '-d -uc -us',
        }

        # Default thread count: max(1, os.cpu_count() - 1)
        build_threads = int(threads) if threads else max(1, (os.cpu_count() or 4) - 1)
        
        if stage_callback:
            stage_callback(4, f"Compiling kernel packages ({build_threads} threads, 20–60 min)...")

        if progress_callback:
            mode_desc = f"inside Debian container ({self.get_container_engine()})" if use_container else "on host system"
            tc_desc = " (Clang/LLVM)" if use_llvm else " (GCC)"
            progress_callback(f"\n[*] Starting kernel compilation {mode_desc}{tc_desc} using {build_threads} CPU threads...")
            progress_callback(f"    Running 'make -j{build_threads} bindeb-pkg'...")

        bindeb_cmd = ['make', f'-j{build_threads}'] + toolchain_flags + ['bindeb-pkg', 'DPKG_FLAGS=-d -uc -us']

        try:
            # Compile and generate .deb packages
            if use_container:
                self._run_cmd(container_prefix + bindeb_cmd, cwd=kernel_dir, progress_callback=progress_callback)
            else:
                self._run_cmd(bindeb_cmd, cwd=kernel_dir, progress_callback=progress_callback, env=packaging_env)
        finally:
            # Clean up active build lockfile
            lock_file = os.path.join(self.download_dir, ".building")
            if os.path.exists(lock_file):
                try:
                    os.unlink(lock_file)
                except Exception:
                    pass

        # 11. Collect all generated deb packages and save to ~/kernel-build-deb/Linux-kernel-CachyOS-(version)-[native-]debian
        output_dir = self.get_output_kernel_dir(is_native=is_native)
        os.makedirs(output_dir, exist_ok=True)
        self.last_output_dir = output_dir

        if progress_callback:
            progress_callback(f"\n[*] Collecting generated Debian packages into:\n    {output_dir}")

        patterns = ["linux-image-*.deb", "linux-headers-*.deb", "linux-libc-dev-*.deb", "*.changes", "*.buildinfo"]
        found_files = []
        for pat in patterns:
            found_files.extend(glob.glob(os.path.join(self.download_dir, pat)))
        for pat in patterns:
            found_files.extend(glob.glob(os.path.join(kernel_dir, pat)))

        copied_count = 0
        for fpath in set(found_files):
            fname = os.path.basename(fpath)
            dst_path = os.path.join(output_dir, fname)
            try:
                shutil.copy2(fpath, dst_path)
                copied_count += 1
                if progress_callback:
                    progress_callback(f"    • Copied {fname}")
            except Exception as e:
                if progress_callback:
                    progress_callback(f"    [!] Warning: could not copy {fname}: {e}")

        # Also preserve .config in the output directory
        if os.path.exists(config_dst):
            try:
                shutil.copy2(config_dst, os.path.join(output_dir, "kernel.config"))
                if progress_callback:
                    progress_callback("    • Copied kernel.config")
            except Exception:
                pass

        # Generate standalone install.sh script in the output directory
        install_script_path = os.path.join(output_dir, "install.sh")
        try:
            ver = self.latest_version or "latest"
            kernel_brand = f"Linux-kernel-CachyOS-{ver}-{'native-' if optimize_for_system else ''}debian"
            with open(install_script_path, "w") as sf:
                sf.write(f"""#!/usr/bin/env bash
# CachyOS Kernel Debian Package Installer
# Kernel: {kernel_brand}
set -e

DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" >/dev/null 2>&1 && pwd)"
echo "=== Installing {kernel_brand} ==="
echo "Package directory: $DIR"

DEBS=()
for f in "$DIR"/linux-image-*.deb "$DIR"/linux-headers-*.deb; do
    if [ -f "$f" ] && [[ "$f" != *"-dbg"* ]]; then
        DEBS+=("$f")
    fi
done

if [ ${{#DEBS[@]}} -eq 0 ]; then
    echo "Error: No suitable kernel .deb packages found in $DIR"
    exit 1
fi

echo "Installing packages: ${{DEBS[@]}}"
if command -v pkexec >/dev/null 2>&1; then
    pkexec dpkg -i "${{DEBS[@]}}"
    pkexec update-grub
elif [ "$(id -u)" -eq 0 ]; then
    dpkg -i "${{DEBS[@]}}"
    update-grub
else
    sudo dpkg -i "${{DEBS[@]}}"
    sudo update-grub
fi

echo "=========================================================="
echo "Installation complete! Please reboot to boot the new kernel."
echo "=========================================================="
""")
            os.chmod(install_script_path, 0o755)
            if progress_callback:
                progress_callback("    • Generated install.sh helper script")
        except Exception as e:
            if progress_callback:
                progress_callback(f"    [!] Warning: could not create install.sh: {e}")

        if progress_callback:
            progress_callback(f"\n[✓] Compilation completed successfully! Saved {copied_count} artifact(s) to:\n    {output_dir}")

    def get_kernel_version_from_deb(self, deb_path: str) -> str:
        """
        Extracts the exact kernel version string from a linux-image-*.deb package.
        E.g. linux-image-7.2.10-cachyos-debian -> 7.2.10-cachyos-debian.
        """
        try:
            res = self._run_host_subproc(
                ['dpkg-deb', '-f', deb_path, 'Package'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10
            )
            pkg = res.stdout.strip()
            if pkg.startswith('linux-image-'):
                return pkg[len('linux-image-'):]
        except Exception:
            pass
        # Fallback to regex on filename
        fname = os.path.basename(deb_path)
        m = re.search(r'linux-image-([0-9]+\.[0-9]+\.[0-9]+-[^._]+)', fname)
        if m:
            return m.group(1)
        return ""

    def get_sign_script_path(self):
        """Locates the atomic root helper script sign-kernel.sh (prefers host-visible path when in Flatpak)."""
        self._stage_host_helper_files()
        staged_script = os.path.join(self.config_dir, "sign-kernel.sh")
        if self.is_flatpak() and os.path.isfile(staged_script):
            return staged_script
        candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "sign-kernel.sh"),
            staged_script,
            "/usr/share/cachy-kernel-updater/sign-kernel.sh",
            os.path.expanduser("~/Projects/debian-cachy-os-kernel-updater/sign-kernel.sh")
        ]
        for p in candidates:
            if os.path.isfile(p):
                return p
        return staged_script

    def get_mok_status(self, output_dir: str = None) -> dict:
        """
        Inspects UEFI Secure Boot state and MOK key existence in the designated output_dir.
        Checks kernel EFI variables directly, sign-kernel.sh --status, and mokutil.
        Returns a dict containing state flags and certificate paths.
        """
        target_dir = output_dir or self.find_deb_directory() or self.last_output_dir or self.get_output_kernel_dir(is_native=False)
        if not target_dir:
            target_dir = self.output_base_dir

        script_path = self.get_sign_script_path()
        sb_state = "disabled"
        key_exists = "no"
        key_enrolled = "no"

        # 1. Direct EFI variable check (/sys/firmware/efi/efivars/SecureBoot-*)
        for efivar_pattern in (
            "/sys/firmware/efi/efivars/SecureBoot-*",
            "/run/host/sys/firmware/efi/efivars/SecureBoot-*",
        ):
            for efivar_path in glob.glob(efivar_pattern):
                if "SecureBootMode" in efivar_path:
                    continue
                try:
                    with open(efivar_path, "rb") as ef:
                        data = ef.read()
                    if len(data) >= 5 and data[4] == 1:
                        sb_state = "enabled"
                        break
                except Exception:
                    pass

        # 1b. Host-bridged EFI variable check if inside Flatpak where /sys/firmware is hidden by bwrap
        if sb_state == "disabled" and self._can_flatpak_spawn_host():
            try:
                res = self._run_host_subproc(
                    ['od', '-An', '-t', 'u1', '-j', '4', '-N', '1', '/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c'],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=4
                )
                if res.returncode == 0 and res.stdout.strip() == "1":
                    sb_state = "enabled"
            except Exception:
                pass

        # 2. Check via sign-kernel.sh --status
        if os.path.isfile(script_path):
            try:
                res = self._run_host_subproc(
                    ['bash', script_path, '--status', target_dir],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=8
                )
                for line in res.stdout.splitlines():
                    if line.startswith("SB_STATE="):
                        val = line.split("=", 1)[1].strip()
                        if val == "enabled":
                            sb_state = "enabled"
                    elif line.startswith("KEY_EXISTS="):
                        key_exists = line.split("=", 1)[1].strip()
                    elif line.startswith("KEY_ENROLLED="):
                        key_enrolled = line.split("=", 1)[1].strip()
                    elif line.startswith("CERT_DIR="):
                        target_dir = line.split("=", 1)[1].strip()
            except Exception as e:
                print(f"Error checking status via sign-kernel.sh: {e}")

        # 3. Fallback check via mokutil (host or local)
        if sb_state == "disabled" and self._which_host("mokutil"):
            try:
                res = self._run_host_subproc(['mokutil', '--sb-state'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
                if 'SecureBoot enabled' in res.stdout:
                    sb_state = "enabled"
            except Exception:
                pass

        priv_path = os.path.join(target_dir, "MOK.priv")
        der_path = os.path.join(target_dir, "MOK.der")
        pem_path = os.path.join(target_dir, "MOK.pem")
        if os.path.isfile(der_path) and os.path.isfile(priv_path) and os.path.isfile(pem_path):
            key_exists = "yes"
            if key_enrolled != "yes" and self._which_host("mokutil"):
                try:
                    res = self._run_host_subproc(['mokutil', '--test-key', der_path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=5)
                    if 'is already enrolled' in res.stdout.lower():
                        key_enrolled = "yes"
                except Exception:
                    pass

        return {
            "secure_boot_enabled": (sb_state == "enabled"),
            "secure_boot": (sb_state == "enabled"),
            "state": sb_state,
            "key_exists": (key_exists == "yes"),
            "key_enrolled": (key_enrolled == "yes"),
            "cert_dir": target_dir,
            "priv_path": priv_path,
            "der_path": der_path,
            "pem_path": pem_path
        }

    def get_secure_boot_status(self, output_dir: str = None) -> bool:
        """Returns True if UEFI Secure Boot is active."""
        return self.get_mok_status(output_dir)["secure_boot_enabled"]

    def find_deb_directory(self):
        """Locates the directory containing compiled linux-image-*.deb packages."""
        search_dirs = []
        if self.last_output_dir and os.path.isdir(self.last_output_dir):
            search_dirs.append(self.last_output_dir)
        output_dir_native = self.get_output_kernel_dir(is_native=True)
        if os.path.isdir(output_dir_native) and output_dir_native not in search_dirs:
            search_dirs.append(output_dir_native)
        output_dir_generic = self.get_output_kernel_dir(is_native=False)
        if os.path.isdir(output_dir_generic) and output_dir_generic not in search_dirs:
            search_dirs.append(output_dir_generic)
        if os.path.isdir(self.download_dir) and self.download_dir not in search_dirs:
            search_dirs.append(self.download_dir)
        if os.path.isdir(self.output_base_dir):
            try:
                entries = sorted(
                    [os.path.join(self.output_base_dir, d) for d in os.listdir(self.output_base_dir)],
                    key=os.path.getmtime,
                    reverse=True
                )
                for full_p in entries:
                    if os.path.isdir(full_p) and full_p not in search_dirs:
                        search_dirs.append(full_p)
            except Exception:
                pass

        for sdir in search_dirs:
            candidates = glob.glob(os.path.join(sdir, "linux-image-*.deb"))
            candidates = [f for f in candidates if '-dbg' not in f]
            if candidates:
                return sdir
        return None

    def _create_mok_pass_file(self, mok_password: str):
        """Writes an optional MOK password to a 0600 temp file so it is never exposed in /proc/pid/cmdline."""
        if not mok_password:
            return None
        import tempfile
        fd, pass_path = tempfile.mkstemp(prefix=".mok-pass-", dir=self.config_dir)
        os.chmod(pass_path, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(mok_password)
        return pass_path

    def _run_sign_kernel_helper(self, cmd: list, cwd: str, success_msg: str, failure_prefix: str, log_callback=None, pass_file: str = None) -> tuple:
        """Executes sign-kernel.sh via pkexec and extracts MOK_STATUS from its output stream."""
        mok_status = "UNKNOWN"
        try:
            def stream_handler(line):
                nonlocal mok_status
                if "MOK_STATUS=" in line:
                    for token in line.split():
                        if token.startswith("MOK_STATUS="):
                            mok_status = token.split("=", 1)[1].strip()
                if log_callback:
                    log_callback(line)

            self._run_cmd(cmd, cwd=cwd, progress_callback=stream_handler)
            if log_callback and success_msg:
                log_callback(success_msg)
            return True, mok_status
        except Exception as e:
            if log_callback:
                log_callback(f"\n[!] {failure_prefix}: {e}\n")
            return False, f"FAILED: {e}"
        finally:
            if pass_file and os.path.exists(pass_file):
                try:
                    os.unlink(pass_file)
                except OSError:
                    pass

    def reset_and_recreate_mok_keys(self, output_dir: str = None, mok_password: str = "", log_callback=None) -> tuple:
        """
        Cancels any previous MOK enrollment (mokutil --revoke-import), deletes old MOK keys,
        generates a fresh 2048-bit RSA keypair in output_dir, re-signs the installed kernel in /boot,
        and queues the new MOK.der for enrollment in UEFI NVRAM.
        Invokes in a single atomic privileged transaction:
          pkexec bash sign-kernel.sh --reset-and-recreate <output_dir> [mok_password]
        Returns: (success: bool, mok_status: str)
        """
        target_dir = output_dir or self.find_deb_directory() or self.last_output_dir or self.get_output_kernel_dir(is_native=False)
        if not target_dir:
            target_dir = self.output_base_dir
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception:
            pass

        script_path = self.get_sign_script_path()
        if not os.path.isfile(script_path):
            if log_callback:
                log_callback(f"[!] Error: sign-kernel.sh not found at {script_path}")
            return False, "SCRIPT_NOT_FOUND"

        pass_file = self._create_mok_pass_file(mok_password)
        cmd = ["pkexec", "bash", script_path, "--reset-and-recreate", target_dir]
        if pass_file:
            cmd.extend(["--pass-file", pass_file])

        if log_callback:
            log_callback("\n=======================================================")
            log_callback("[*] Resetting & Recreating MOK Keys from Scratch...")
            log_callback(f"    Output & Certificate Directory: {target_dir}")
            log_callback(f"    Privileged Helper: {script_path}")
            log_callback("=======================================================\n")

        return self._run_sign_kernel_helper(
            cmd=cmd,
            cwd=target_dir,
            success_msg="\n[✓] MOK keys reset and recreated successfully in output folder!\n",
            failure_prefix="Reset and recreate MOK keys failed",
            log_callback=log_callback,
            pass_file=pass_file
        )

    def install_and_sign_kernel_debs(self, deb_dir: str = None, sign_enabled: bool = True, mok_password: str = "", log_callback=None) -> tuple:
        """
        Installs built Debian kernel packages and optionally signs them for UEFI Secure Boot.
        If sign_enabled is True, invokes:
          pkexec bash sign-kernel.sh --install-and-sign <deb_dir> [mok_password]
        in a single atomic privileged transaction.
        If sign_enabled is False, installs via pkexec dpkg -i without signing.
        Returns: (success: bool, mok_status: str)
        """
        target_dir = deb_dir or self.find_deb_directory() or self.last_output_dir or self.get_output_kernel_dir(is_native=False)
        if not target_dir or not os.path.isdir(target_dir):
            if log_callback:
                log_callback("Error: No linux-image-*.deb packages found in output or build directories.")
            return False, "NO_PACKAGES_FOUND"

        script_path = self.get_sign_script_path()
        if not os.path.isfile(script_path):
            if log_callback:
                log_callback(f"[!] Error: sign-kernel.sh not found at {script_path}")
            return False, "SCRIPT_NOT_FOUND"

        if sign_enabled:
            pass_file = self._create_mok_pass_file(mok_password)
            cmd = ["pkexec", "bash", script_path, "--install-and-sign", target_dir]
            if pass_file:
                cmd.extend(["--pass-file", pass_file])

            if log_callback:
                log_callback("\n=======================================================")
                log_callback("[*] Starting Single-Transaction Kernel Install & UEFI Secure Boot Signing...")
                log_callback(f"    Source Folder: {target_dir}")
                log_callback(f"    Privileged Helper: {script_path}")
                log_callback("=======================================================\n")

            return self._run_sign_kernel_helper(
                cmd=cmd,
                cwd=target_dir,
                success_msg="\n[✓] Package installation and Secure Boot signing completed successfully!\n",
                failure_prefix="Installation and signing failed",
                log_callback=log_callback,
                pass_file=pass_file
            )
        else:
            # Install without signing
            deb_files = glob.glob(os.path.join(target_dir, "linux-image-*.deb"))
            deb_files += glob.glob(os.path.join(target_dir, "linux-headers-*.deb"))
            deb_files = [f for f in deb_files if '-dbg' not in f]
            if not deb_files:
                if log_callback:
                    log_callback("Error: No .deb files found to install.")
                return False, "NO_DEBS"

            if log_callback:
                log_callback(f"[*] Installing packages without signing via pkexec dpkg -i: {[os.path.basename(f) for f in deb_files]}")

            cmd = ['pkexec', 'sh', '-c', 'dpkg -i "$@" && update-grub', '--'] + deb_files
            try:
                self._run_cmd(cmd, cwd=target_dir, progress_callback=log_callback)
                if log_callback:
                    log_callback("\n[✓] Packages installed successfully!\n")
                return True, "INSTALLED_NO_SIGN"
            except Exception as e:
                if log_callback:
                    log_callback(f"\n[!] Installation failed: {e}\n")
                return False, f"FAILED: {e}"

    def install_kernel(self, progress_callback=None, sign_after_install=True, mok_password=""):
        """Convenience wrapper for install_and_sign_kernel_debs returning bool."""
        success, _ = self.install_and_sign_kernel_debs(
            deb_dir=None,
            sign_enabled=sign_after_install,
            mok_password=mok_password,
            log_callback=progress_callback
        )
        return success

    def sign_existing_installed_kernel(self, kernel_version: str = "auto", mok_password: str = "", output_dir: str = None, log_callback=None) -> tuple:
        """
        Signs the currently installed /boot/vmlinuz-* and out-of-tree DKMS modules using MOK.
        Invokes in a single atomic privileged transaction:
          pkexec bash sign-kernel.sh --sign-only <output_dir> [kernel_version] [mok_password]
        Returns: (success: bool, mok_status: str)
        """
        script_path = self.get_sign_script_path()
        if not os.path.isfile(script_path):
            if log_callback:
                log_callback(f"[!] Error: sign-kernel.sh not found at {script_path}")
            return False, "SCRIPT_NOT_FOUND"

        target_dir = output_dir or self.find_deb_directory() or self.last_output_dir or self.get_output_kernel_dir(is_native=False)
        if not target_dir:
            target_dir = self.output_base_dir
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception:
            pass

        kver = kernel_version or "auto"
        pass_file = self._create_mok_pass_file(mok_password)
        cmd = ["pkexec", "bash", script_path, "--sign-only", target_dir, kver]
        if pass_file:
            cmd.extend(["--pass-file", pass_file])

        if log_callback:
            log_callback("\n=======================================================")
            log_callback(f"[*] Initiating Secure Boot Signing for installed kernel ({kver})...")
            log_callback(f"    Output & Certificate Directory: {target_dir}")
            log_callback(f"    Privileged Helper: {script_path}")
            log_callback("=======================================================\n")

        return self._run_sign_kernel_helper(
            cmd=cmd,
            cwd=target_dir,
            success_msg="\n[✓] Post-installation Secure Boot signing completed successfully!\n",
            failure_prefix="Secure Boot signing failed",
            log_callback=log_callback,
            pass_file=pass_file
        )

    def get_installed_kernels(self):
        """Returns a list of installed linux-image packages on the host."""
        installed_set = self._read_dpkg_installed_set(include_provides=False)
        packages = [pkg for pkg in installed_set if pkg.startswith("linux-image-") and "dbg" not in pkg]
        if packages:
            return sorted(packages)

        try:
            res = self._run_host_subproc(
                ['dpkg-query', '-W', '-f=${binary:Package}\\n', 'linux-image-*'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=8
            )
            if res.returncode == 0:
                packages = [line.strip() for line in res.stdout.split('\n') if line.strip() and 'dbg' not in line]
            return packages
        except Exception:
            return []

    def remove_kernel(self, package_name, progress_callback=None):
        """Removes a specific kernel package using pkexec."""
        if progress_callback:
            progress_callback(f"Removing {package_name} via pkexec...")
        cmd = ['pkexec', 'apt-get', 'purge', '-y', package_name]
        try:
            self._run_cmd(cmd, cwd='/tmp', progress_callback=progress_callback)
            if progress_callback:
                progress_callback(f"Successfully removed {package_name}. Updating GRUB...")
            try:
                self._run_cmd(['pkexec', 'update-grub'], cwd='/tmp', progress_callback=progress_callback)
            except Exception:
                pass
            return True
        except Exception as e:
            if progress_callback:
                progress_callback(f"Failed to remove {package_name}: {e}")
            return False

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Debian CachyOS Kernel Manager CLI")
    parser.add_argument('--check', action='store_true', help="Check for latest CachyOS kernel version")
    parser.add_argument('--status-sb', action='store_true', help="Check UEFI Secure Boot status")
    parser.add_argument('--install-deps', action='store_true', help="Install required build dependencies")
    parser.add_argument('--container', action='store_true', help="Use container environment (Podman/Docker)")
    parser.add_argument('--optimize', action='store_true', help="Optimize kernel compilation for local system (-march=native)")
    parser.add_argument('--build', action='store_true', help="Download and compile the latest CachyOS kernel")
    parser.add_argument('--install', action='store_true', help="Install compiled Debian packages")
    parser.add_argument('--no-sign', action='store_true', help="Skip Secure Boot MOK signing during installation")
    parser.add_argument('--rollback', nargs='?', const='', help="Purge/rollback an installed kernel package")
    parser.add_argument('--sign-mok', nargs='?', const='', help="Sign installed kernel in /boot for UEFI Secure Boot (MOK)")
    parser.add_argument('--sign-deb-mok', metavar='DIR', nargs='?', const='', help="Sign kernel using MOK certificates in target directory")
    parser.add_argument('--enroll-mok', action='store_true', help="Enroll MOK key into UEFI")
    parser.add_argument('--reset-mok', action='store_true', help="Cancel previous MOK enrollment, delete old certificates, generate fresh keypair in output folder, and re-sign kernel")

    args = parser.parse_args()
    km = KernelManager()

    def cli_log(msg):
        print(msg)

    if args.check:
        print(f"Current kernel: {km.get_current_kernel_version()}")
        print(f"Latest CachyOS: {km.get_latest_cachy_version()}")
        print(f"Running latest: {km.is_matching_running_kernel()}")
    elif args.status_sb:
        sb = km.get_secure_boot_status()
        print(f"UEFI Secure Boot: {'ENABLED' if sb else 'DISABLED'}")
    elif args.install_deps:
        km.install_build_dependencies(progress_callback=cli_log, use_container=args.container)
    elif args.build:
        src = km.download_kernel(progress_callback=cli_log)
        km.compile_kernel(src, progress_callback=cli_log, use_container=args.container, optimize_for_system=args.optimize)
    elif args.install:
        km.install_kernel(progress_callback=cli_log, sign_after_install=not args.no_sign)
    elif args.rollback is not None:
        if args.rollback:
            km.remove_kernel(args.rollback, progress_callback=cli_log)
        else:
            print("Installed kernels:", km.get_installed_kernels())
    elif args.sign_deb_mok is not None:
        target_dir = args.sign_deb_mok or km.last_output_dir or km.get_output_kernel_dir()
        km.sign_existing_installed_kernel(output_dir=target_dir, log_callback=cli_log)
    elif args.enroll_mok:
        import getpass
        pwd = getpass.getpass("Enter one-time MOK enrollment password (8-16 chars): ")
        success, msg = km.sign_existing_installed_kernel(kernel_version="auto", mok_password=pwd, log_callback=cli_log)
        print(f"Enrollment result: {success} ({msg})")
    elif args.reset_mok:
        import getpass
        pwd = getpass.getpass("Enter one-time MOK enrollment password (8-16 chars): ")
        success, msg = km.reset_and_recreate_mok_keys(mok_password=pwd, log_callback=cli_log)
        print(f"Reset result: {success} ({msg})")
    elif args.sign_mok is not None:
        km.sign_existing_installed_kernel(kernel_version=args.sign_mok or "auto", log_callback=cli_log)
    else:
        parser.print_help()
