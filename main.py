import sys
import os
import subprocess
import threading
import re
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk, Gio

from kernel_manager import KernelManager

APP_VERSION = "1.1.7"

class KernelUpdaterWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Debian CachyOS Kernel Updater")
        self.set_default_size(860, 720)
        self.set_decorated(True)
        self.set_resizable(True)

        # Ensure window decoration layout displays minimize, maximize, and close buttons
        settings = Gtk.Settings.get_default()
        if settings:
            settings.set_property("gtk-decoration-layout", ":minimize,maximize,close")

        # Configure icon theme search paths to guarantee symbolic window controls are found
        display = Gdk.Display.get_default()
        if display:
            icon_theme = Gtk.IconTheme.get_for_display(display)
            appdir = os.environ.get("APPDIR")
            if appdir:
                icon_theme.add_search_path(os.path.join(appdir, "usr/share/icons"))
                icon_theme.add_search_path(os.path.join(appdir, "usr/share/pixmaps"))
            # Standard host, Flatpak and local assets locations
            icon_theme.add_search_path("/app/share/icons")
            icon_theme.add_search_path("/app/share/pixmaps")
            icon_theme.add_search_path("/usr/share/icons")
            icon_theme.add_search_path("/usr/share/pixmaps")
            icon_theme.add_search_path("/usr/local/share/icons")
            icon_theme.add_search_path(os.path.expanduser("~/.local/share/icons"))
            local_assets = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
            if os.path.isdir(local_assets):
                icon_theme.add_search_path(local_assets)

        self.kernel_manager = KernelManager()
        self.versions_list = []
        self.is_secure_boot = self.kernel_manager.get_secure_boot_status()

        # Load custom CSS styling
        self._apply_custom_css()

        # Header Bar with explicit title buttons
        self.header = Adw.HeaderBar()
        self.header.set_show_start_title_buttons(True)
        self.header.set_show_end_title_buttons(True)

        self.set_icon_name("io.github.Antux912012.debian-cachy-os-kernel-updater")
        self.window_title = Adw.WindowTitle(
            title="Debian CachyOS Kernel Updater",
            subtitle=f"v{APP_VERSION} — Installer, Updater & Secure Boot Manager"
        )
        self.header.set_title_widget(self.window_title)

        # About button in header bar
        self.about_btn = Gtk.Button()
        self.about_btn.set_icon_name("help-about-symbolic")
        self.about_btn.set_tooltip_text("About Debian CachyOS Kernel Updater")
        self.about_btn.connect("clicked", self.on_about_clicked)
        self.header.pack_end(self.about_btn)

        # Scrolled content container to guarantee seamless navigation on all screen sizes
        self.scrolled_window = Gtk.ScrolledWindow()
        self.scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scrolled_window.set_vexpand(True)

        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.content_box.set_margin_top(16)
        self.content_box.set_margin_bottom(24)
        self.content_box.set_margin_start(20)
        self.content_box.set_margin_end(20)
        self.scrolled_window.set_child(self.content_box)

        # Main Layout using Adw.ToolbarView if available, fallback to Gtk.Box for older Libadwaita
        if hasattr(Adw, "ToolbarView"):
            self.toolbar_view = Adw.ToolbarView()
            self.set_content(self.toolbar_view)
            self.toolbar_view.add_top_bar(self.header)
            self.toolbar_view.set_content(self.scrolled_window)
        else:
            main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            main_box.append(self.header)
            main_box.append(self.scrolled_window)
            self.set_content(main_box)

        # =========================================================================
        # Top System Status Banner Card (With Branding Logo & Version Badge)
        # =========================================================================
        self.status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.status_box.add_css_class("card")
        self.status_box.add_css_class("status-card")
        self.status_box.set_margin_bottom(4)

        banner_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        banner_row.set_margin_top(12)
        banner_row.set_margin_bottom(12)
        banner_row.set_margin_start(16)
        banner_row.set_margin_end(16)

        # Application Logo Image in Banner
        logo_png_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo_128.png")
        if not os.path.exists(logo_png_path):
            logo_png_path = "/usr/share/pixmaps/io.github.Antux912012.debian-cachy-os-kernel-updater.png"
        if not os.path.exists(logo_png_path):
            logo_png_path = "/app/share/pixmaps/io.github.Antux912012.debian-cachy-os-kernel-updater.png"

        if os.path.exists(logo_png_path):
            self.banner_logo = Gtk.Image.new_from_file(logo_png_path)
        else:
            self.banner_logo = Gtk.Image.new_from_icon_name("io.github.Antux912012.debian-cachy-os-kernel-updater")
        self.banner_logo.set_pixel_size(56)
        self.banner_logo.set_valign(Gtk.Align.CENTER)
        banner_row.append(self.banner_logo)

        inner_status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        inner_status_box.set_hexpand(True)

        title_badge_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.app_brand_label = Gtk.Label(label="Debian CachyOS Kernel Updater", halign=Gtk.Align.START)
        self.app_brand_label.add_css_class("title-4")
        self.app_brand_label.add_css_class("brand-title")
        title_badge_row.append(self.app_brand_label)

        self.version_badge = Gtk.Label(label=f"v{APP_VERSION}")
        self.version_badge.add_css_class("version-badge")
        self.version_badge.set_valign(Gtk.Align.CENTER)
        title_badge_row.append(self.version_badge)
        inner_status_box.append(title_badge_row)

        current_kernel = self.kernel_manager.get_current_kernel_version()
        host_os_name = self.kernel_manager.host_distro.get("name", "Debian/Ubuntu")
        self.status_label = Gtk.Label(label=f"Current Kernel: {current_kernel}  •  Host OS: {host_os_name}", halign=Gtk.Align.START)
        self.status_label.add_css_class("body")
        inner_status_box.append(self.status_label)

        status_row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.latest_label = Gtk.Label(label="Latest CachyOS Kernel: Checking official GitHub...", halign=Gtk.Align.START)
        self.latest_label.add_css_class("caption")
        self.latest_label.set_hexpand(True)
        status_row_box.append(self.latest_label)

        # Live Secure Boot pill in top banner
        self.sb_banner_pill = Gtk.Label(label="[Secure Boot: Active]" if self.is_secure_boot else "[Secure Boot: Off]")
        self.sb_banner_pill.add_css_class("sb-pill-active" if self.is_secure_boot else "sb-pill-inactive")
        self.sb_banner_pill.set_valign(Gtk.Align.CENTER)
        status_row_box.append(self.sb_banner_pill)
        inner_status_box.append(status_row_box)

        self.match_status_label = Gtk.Label(label="", halign=Gtk.Align.START)
        self.match_status_label.add_css_class("caption")
        inner_status_box.append(self.match_status_label)

        banner_row.append(inner_status_box)
        self.status_box.append(banner_row)
        self.content_box.append(self.status_box)

        # =========================================================================
        # Section 1: "Step 1 — Choose Kernel Version & Build Environment"
        # =========================================================================
        self.step1_group = Adw.PreferencesGroup()
        self.step1_group.set_title("Step 1 — Choose Kernel Version &amp; Build Environment")
        self.step1_group.set_description("Select the CachyOS kernel release to download and how you want to compile it.")

        # 1. Kernel Version Dropdown
        self.kernel_version_row = Adw.ComboRow()
        self.kernel_version_row.set_title("Kernel Version")
        self.kernel_version_row.set_subtitle("Pre-selects latest Stable release; testing versions marked as (Experimental)")
        self.kernel_version_row.set_tooltip_text("Select the CachyOS kernel release to download and compile. Pre-selects the latest stable release.")
        initial_version = self.kernel_manager.latest_version or "7.3.0-4"
        self.version_string_list = Gtk.StringList.new([f"{initial_version} (Stable)"])
        self.kernel_version_row.set_model(self.version_string_list)
        self.kernel_version_row.set_selected(0)
        self.kernel_version_row.connect("notify::selected", self.on_version_selected)
        self.step1_group.add(self.kernel_version_row)

        # 2. Build Mode Dropdown (Native Host vs Isolated Container)
        self.build_mode_row = Adw.ComboRow()
        self.build_mode_row.set_title("Build Environment")
        self.build_mode_row.set_subtitle("Native Host Build (Recommended — Fastest) keeps build times lowest")
        self.build_mode_row.set_tooltip_text(
            "Native Host Build: Compiles directly on your system for maximum speed.\n"
            "Isolated Container Build: Uses Podman or Docker (Debian Bookworm container) to keep host packages clean."
        )
        build_mode_options = [
            "Native Host Build (Recommended — Fastest)",
            "Isolated Container Build (Podman / Docker — Keeps host system clean)"
        ]
        self.build_mode_row.set_model(Gtk.StringList.new(build_mode_options))
        self.build_mode_row.set_selected(0) # Default: Native Host Build
        self.build_mode_row.connect("notify::selected", self.on_build_mode_selected)
        self.step1_group.add(self.build_mode_row)

        self.content_box.append(self.step1_group)

        # =========================================================================
        # Section 2: "Step 2 — Recommended System & Boot Safety Options"
        # =========================================================================
        self.step2_group = Adw.PreferencesGroup()
        self.step2_group.set_title("Step 2 — Recommended System &amp; Boot Safety Options")
        self.step2_group.set_description("Safe defaults are already ticked for maximum stability and compatibility across systems.")

        # 1. Use Current System Hardware Config (localmodconfig / Host .config base)
        self.hw_config_row = Adw.ActionRow()
        self.hw_config_row.set_title("Use Current System Hardware Config (localmodconfig)")
        self.hw_config_row.set_subtitle("Tailors drivers to machine while preserving Wi-Fi, Bluetooth, storage &amp; filesystem baselines.")
        self.hw_config_row.set_tooltip_text("Scans active hardware drivers from the running system and trims unused drivers, while ensuring Wi-Fi, Bluetooth, crypto, storage, and filesystem drivers are always preserved.")
        self.hw_config_check = Gtk.CheckButton()
        self.hw_config_check.set_active(True)
        self.hw_config_check.set_tooltip_text("Scans active hardware drivers from the running system and trims unused drivers, while ensuring Wi-Fi, Bluetooth, crypto, storage, and filesystem drivers are always preserved.")
        self.hw_config_row.add_prefix(self.hw_config_check)
        self.hw_config_row.set_activatable_widget(self.hw_config_check)
        self.step2_group.add(self.hw_config_row)

        # 2. Optimize Build Size & RAM (Disable Debug Symbols)
        self.strip_debug_row = Adw.ActionRow()
        self.strip_debug_row.set_title("Optimize Build Size &amp; RAM (Disable Debug Symbols)")
        self.strip_debug_row.set_subtitle("Prevents disk space exhaustion and memory crashes during compilation.")
        self.strip_debug_row.set_tooltip_text("Enables DEBUG_INFO_NONE. Reduces required disk space from ~35 GB down to ~5 GB, prevents out-of-memory linker crashes, and speeds up compilation.")
        self.strip_debug_check = Gtk.CheckButton()
        self.strip_debug_check.set_active(True)
        self.strip_debug_check.set_tooltip_text("Enables DEBUG_INFO_NONE. Reduces required disk space from ~35 GB down to ~5 GB, prevents out-of-memory linker crashes, and speeds up compilation.")
        self.strip_debug_row.add_prefix(self.strip_debug_check)
        self.strip_debug_row.set_activatable_widget(self.strip_debug_check)
        self.step2_group.add(self.strip_debug_row)

        # 3. Auto-Install .deb Packages After Build
        self.auto_install_row = Adw.ActionRow()
        self.auto_install_row.set_title("Install Kernel Automatically When Build Finishes")
        self.auto_install_row.set_subtitle("Installs the generated linux-image and linux-headers .deb packages.")
        self.auto_install_row.set_tooltip_text("Automatically prompts to install the compiled Debian packages using pkexec when compilation completes.")
        self.auto_install_check = Gtk.CheckButton()
        self.auto_install_check.set_active(True)
        self.auto_install_check.set_tooltip_text("Automatically prompts to install the compiled Debian packages using pkexec when compilation completes.")
        self.auto_install_row.add_prefix(self.auto_install_check)
        self.auto_install_row.set_activatable_widget(self.auto_install_check)
        self.step2_group.add(self.auto_install_row)

        # 4. Sign Kernel in /boot After Installation (UEFI Secure Boot)
        self.sign_postinst_row = Adw.ActionRow()
        self.sign_postinst_row.set_title("Sign Kernel for UEFI Secure Boot After Installation")
        self.sign_postinst_row.set_subtitle("Signs /boot/vmlinuz with your Machine Owner Key (MOK) so your PC boots safely with Secure Boot on.")
        self.sign_postinst_row.set_tooltip_text("Cryptographically signs the installed kernel image and DKMS modules with your local Machine Owner Key for UEFI Secure Boot.")
        self.sign_postinst_check = Gtk.CheckButton()
        # Pre-ticked as safe default across systems
        self.sign_postinst_check.set_active(True)
        self.sign_postinst_check.set_tooltip_text("Cryptographically signs the installed kernel image and DKMS modules with your local Machine Owner Key for UEFI Secure Boot.")
        self.sign_postinst_row.add_prefix(self.sign_postinst_check)
        self.sign_postinst_row.set_activatable_widget(self.sign_postinst_check)

        # Live status pill next to Secure Boot option
        self.sb_row_pill = Gtk.Label(label="[Secure Boot: Active]" if self.is_secure_boot else "[Secure Boot: Off]")
        self.sb_row_pill.add_css_class("sb-pill-active" if self.is_secure_boot else "sb-pill-inactive")
        self.sb_row_pill.set_valign(Gtk.Align.CENTER)
        self.sign_postinst_row.add_suffix(self.sb_row_pill)
        self.step2_group.add(self.sign_postinst_row)

        # 4b. Pluggable sched-ext (SCX v1.1.4) BPF Schedulers Row
        scx_st = self.kernel_manager.get_scx_status()
        self.scx_row = Adw.ActionRow()
        self.scx_row.set_title("sched-ext (SCX v1.1.4) Userspace BPF Schedulers")
        self.scx_row.set_subtitle(
            "Bundles & installs scx_bpfland, scx_lavd, scx_flash, scx_rusty, scx_cosmos, scx_p2dq, scx_cake, and scxctl."
        )
        self.scx_row.set_tooltip_text(
            "Installs precompiled sched-ext (scx v1.1.4) BPF schedulers (.deb) and enables CONFIG_SCHED_CLASS_EXT=y in compiled kernels."
        )
        scx_count = scx_st.get("installed_count", 0)
        self.scx_pill = Gtk.Label(
            label=f"[SCX: {scx_count} Installed]" if scx_count > 0 else "[SCX: Not Installed]"
        )
        self.scx_pill.add_css_class("sb-pill-active" if scx_count > 0 else "sb-pill-inactive")
        self.scx_pill.set_valign(Gtk.Align.CENTER)
        self.scx_row.add_suffix(self.scx_pill)

        self.install_scx_button = Gtk.Button(
            label="🔄 Update SCX" if scx_count > 0 else "⚡ Install SCX (.deb)"
        )
        self.install_scx_button.set_valign(Gtk.Align.CENTER)
        if scx_count == 0:
            self.install_scx_button.add_css_class("suggested-action")
        self.install_scx_button.set_tooltip_text(
            "Install or update precompiled sched-ext (scx-scheds_1.1.4_amd64.deb) userspace BPF schedulers on your system."
        )
        self.install_scx_button.connect("clicked", self.on_install_scx_clicked)
        self.scx_row.add_suffix(self.install_scx_button)
        self.step2_group.add(self.scx_row)

        # 5. Certificates & Packages Location Row
        self.cert_folder_row = Adw.ActionRow()
        self.cert_folder_row.set_title("MOK Certificates &amp; Packages Location")
        initial_target_dir = self.kernel_manager.get_output_kernel_dir(is_native=False)
        self.cert_folder_row.set_subtitle(f"{initial_target_dir} (MOK.der, MOK.pem, MOK.priv)")
        self.cert_folder_row.set_tooltip_text("Directory where local Machine Owner Keys (MOK) and compiled .deb packages are stored.")

        self.open_cert_button = Gtk.Button(label="📂 Open Folder")
        self.open_cert_button.set_valign(Gtk.Align.CENTER)
        self.open_cert_button.connect("clicked", self.on_open_certs_folder_clicked)
        self.open_cert_button.set_tooltip_text("Open the folder containing MOK certificates and Debian packages in your file manager.")
        self.cert_folder_row.add_suffix(self.open_cert_button)

        self.reset_mok_row_button = Gtk.Button(label="🔄 Reset MOK Keys")
        self.reset_mok_row_button.set_valign(Gtk.Align.CENTER)
        self.reset_mok_row_button.add_css_class("flat")
        self.reset_mok_row_button.connect("clicked", self.on_reset_mok_clicked)
        self.reset_mok_row_button.set_tooltip_text("Cancels any previous MOK enrollment, deletes old certificates, generates brand-new MOK keys in the output folder, and re-signs your kernel.")
        self.cert_folder_row.add_suffix(self.reset_mok_row_button)
        self.step2_group.add(self.cert_folder_row)

        self.content_box.append(self.step2_group)

        # =========================================================================
        # Collapsible Expander: "▸ Advanced Kernel & CPU Tuning (Optional)"
        # =========================================================================
        self.tuning_expander = Gtk.Expander(label="▸ Advanced Kernel & CPU Tuning (Optional)")
        self.tuning_expander.set_expanded(False) # Collapsed by default
        self.tuning_expander.add_css_class("card")
        self.tuning_expander.set_margin_top(4)
        self.tuning_expander.set_margin_bottom(4)

        tuning_group = Adw.PreferencesGroup()
        tuning_group.set_title("Fine-Grained Compiler &amp; Hardware Tweaks")
        tuning_group.set_description("Optional tweaks for power users. Safe defaults are already active.")

        # 1. CPU Architecture Target
        self.cpu_arch_row = Adw.ComboRow()
        self.cpu_arch_row.set_title("CPU Architecture Target")
        self.cpu_arch_row.set_subtitle("Instruction set optimization level")
        self.cpu_arch_row.set_tooltip_text(
            "Generic: Safe for all modern CPUs; avoids illegal instruction boot panics across machines.\n"
            "Native: Enables -march=native tailored specifically for this machine's CPU model.\n"
            "x86-64-v3: Optimizes for modern CPUs supporting AVX2 instructions."
        )
        arch_options = [
            "Generic x86-64 / x86-64-v2 (Safe for all modern CPUs) [Default]",
            "Native (Current CPU only — march=native)",
            "x86-64-v3 (Modern CPUs with AVX2)"
        ]
        self.cpu_arch_row.set_model(Gtk.StringList.new(arch_options))
        self.cpu_arch_row.set_selected(0) # Default: Generic
        self.cpu_arch_row.connect("notify::selected", self.on_arch_selected)
        tuning_group.add(self.cpu_arch_row)

        # 2. Compiler & LTO Mode
        self.compiler_lto_row = Adw.ComboRow()
        self.compiler_lto_row.set_title("Compiler &amp; LTO Mode")
        self.compiler_lto_row.set_subtitle("Toolchain and Link-Time Optimization")
        self.compiler_lto_row.set_tooltip_text(
            "GCC (No LTO): Standard compilation; safest, lowest-memory choice across varied Debian hardware.\n"
            "Clang (ThinLTO Disabled): Compiles kernel with LLVM/Clang without LTO overhead.\n"
            "Clang + ThinLTO: Faster binary with moderate RAM consumption during link phase.\n"
            "Clang + Full LTO: Aggressive whole-program optimization; requires high system RAM."
        )
        lto_options = [
            "GCC (Standard - No LTO — Fastest & Safest) [Default]",
            "Clang (ThinLTO Disabled)",
            "Clang + ThinLTO (Optimized)",
            "Clang + Full LTO (Aggressive — High RAM)"
        ]
        self.compiler_lto_row.set_model(Gtk.StringList.new(lto_options))
        self.compiler_lto_row.set_selected(0) # Default: GCC
        tuning_group.add(self.compiler_lto_row)

        # 3. CPU Scheduler
        self.scheduler_row = Adw.ComboRow()
        self.scheduler_row.set_title("CPU Scheduler")
        self.scheduler_row.set_subtitle("Process scheduling algorithm")
        self.scheduler_row.set_tooltip_text(
            "BORE: Burst-Oriented Response Enhancer. Default CachyOS scheduler; stable and responsive for desktop & gaming.\n"
            "EEVDF: Earliest Eligible Virtual Deadline First. Standard upstream Linux kernel scheduler."
        )
        scheduler_options = [
            "BORE + sched-ext (SCX) BPF Support [Default]",
            "EEVDF + sched-ext (SCX) BPF Support"
        ]
        self.scheduler_row.set_model(Gtk.StringList.new(scheduler_options))
        self.scheduler_row.set_selected(0) # Default: BORE
        tuning_group.add(self.scheduler_row)

        # 4. Tick Rate & Preemption
        self.tick_rate_row = Adw.ComboRow()
        self.tick_rate_row.set_title("Tick Rate &amp; Preemption")
        self.tick_rate_row.set_subtitle("Timer interrupt frequency and idle power saving")
        self.tick_rate_row.set_tooltip_text(
            "1000 Hz + Full Tickless Idle: Optimal balance of low latency and laptop battery efficiency.\n"
            "500 Hz / 300 Hz: Lower timer interrupt overhead for specialized server/virtualized workloads."
        )
        tick_options = [
            "1000 Hz + Full Tickless Idle [Default]",
            "500 Hz + Full Tickless Idle",
            "300 Hz + Full Tickless Idle",
            "250 Hz + Full Tickless Idle"
        ]
        self.tick_rate_row.set_model(Gtk.StringList.new(tick_options))
        self.tick_rate_row.set_selected(0) # Default: 1000 Hz
        tuning_group.add(self.tick_rate_row)

        # 5. Parallel Build Threads (-j)
        cpu_count = os.cpu_count() or 4
        safe_default_threads = max(1, cpu_count - 1)

        self.threads_row = Adw.ActionRow()
        self.threads_row.set_title("Parallel Build Threads (-j)")
        self.threads_row.set_subtitle(f"Default: {safe_default_threads} (leaves 1 CPU core free to prevent UI lockup)")
        self.threads_row.set_tooltip_text("Controls make -j concurrency. Default leaves one CPU core free so your desktop never stutters during compilation.")
        
        threads_adj = Gtk.Adjustment(
            value=safe_default_threads,
            lower=1,
            upper=cpu_count,
            step_increment=1,
            page_increment=2
        )
        self.threads_spin = Gtk.SpinButton(adjustment=threads_adj, numeric=True)
        self.threads_spin.set_valign(Gtk.Align.CENTER)
        self.threads_spin.set_tooltip_text("Controls make -j concurrency. Default leaves one CPU core free so your desktop never stutters during compilation.")
        self.threads_row.add_suffix(self.threads_spin)
        tuning_group.add(self.threads_row)

        # 6. Output Package Folder Row
        self.output_row = Adw.ActionRow()
        self.output_row.set_title("Output Package Folder")
        self.output_row.set_subtitle(self.kernel_manager.get_output_kernel_dir(is_native=False))
        self.output_row.set_tooltip_text("Directory where compiled Debian (.deb) packages and configuration files are stored.")

        self.open_output_button = Gtk.Button(label="Open Folder")
        self.open_output_button.set_valign(Gtk.Align.CENTER)
        self.open_output_button.connect("clicked", self.on_open_output_clicked)
        self.open_output_button.set_tooltip_text("Open the output Debian packages folder in your file manager.")
        self.output_row.add_suffix(self.open_output_button)
        tuning_group.add(self.output_row)

        self.tuning_expander.set_child(tuning_group)
        self.content_box.append(self.tuning_expander)

        # =========================================================================
        # Section 3: "Step 3 — Build, Install & Sign"
        # =========================================================================
        self.step3_group = Adw.PreferencesGroup()
        self.step3_group.set_title("Step 3 — Build, Install &amp; Sign")
        self.step3_group.set_description("Click 'Start Kernel Build &amp; Install' below. The app will download, configure, compile, install, and sign your kernel automatically.")

        # Primary Action Bar
        self.action_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.action_card.add_css_class("card")
        self.action_card.set_margin_top(4)

        action_card_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        action_card_inner.set_margin_top(16)
        action_card_inner.set_margin_bottom(16)
        action_card_inner.set_margin_start(16)
        action_card_inner.set_margin_end(16)

        # Primary Button (Prominent & Suggested)
        self.start_build_button = Gtk.Button(label="🚀 Start Kernel Build & Install")
        self.start_build_button.add_css_class("suggested-action")
        self.start_build_button.add_css_class("pill")
        self.start_build_button.set_halign(Gtk.Align.CENTER)
        self.start_build_button.set_size_request(320, 48)
        self.start_build_button.set_tooltip_text("Starts automated download, configuration, compilation, installation, and Secure Boot signing.")
        self.start_build_button.connect("clicked", self.on_start_build_clicked)
        action_card_inner.append(self.start_build_button)

        # Secondary Utility Buttons Box
        self.secondary_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.secondary_box.set_halign(Gtk.Align.CENTER)

        self.install_existing_button = Gtk.Button(label="Install Existing .deb")
        self.install_existing_button.set_tooltip_text("Install existing compiled linux-image and linux-headers Debian packages.")
        self.install_existing_button.connect("clicked", self.on_apply_clicked)
        self.secondary_box.append(self.install_existing_button)

        self.sign_installed_action_button = Gtk.Button(label="🔒 Sign Installed Kernel (Secure Boot)")
        self.sign_installed_action_button.set_tooltip_text("Sign currently installed /boot/vmlinuz and DKMS modules with MOK, and stage UEFI enrollment in a single atomic transaction.")
        self.sign_installed_action_button.connect("clicked", self.on_sign_installed_kernel_clicked)
        self.secondary_box.append(self.sign_installed_action_button)

        self.reset_mok_button = Gtk.Button(label="🔄 Reset MOK Keys")
        self.reset_mok_button.set_tooltip_text("Cancels any previous MOK enrollment, deletes old keys, generates fresh MOK keypair in output folder, and re-signs kernel.")
        self.reset_mok_button.connect("clicked", self.on_reset_mok_clicked)
        self.secondary_box.append(self.reset_mok_button)

        self.check_button = Gtk.Button(label="Check Updates")
        self.check_button.set_tooltip_text("Query official CachyOS repositories for newly released kernel versions.")
        self.check_button.connect("clicked", self.on_check_updates_clicked)
        self.secondary_box.append(self.check_button)

        self.deps_button = Gtk.Button(label="Install Dependencies")
        self.deps_button.set_tooltip_text("Verify and install required build or container dependencies via pkexec apt-get.")
        self.deps_button.connect("clicked", self.on_install_deps_clicked)
        self.secondary_box.append(self.deps_button)

        self.rollback_button = Gtk.Button(label="Rollback Kernel")
        self.rollback_button.add_css_class("destructive-action")
        self.rollback_button.set_tooltip_text("Safely remove an installed kernel package and restore previous kernel.")
        self.rollback_button.connect("clicked", self.on_rollback_clicked)
        self.secondary_box.append(self.rollback_button)

        action_card_inner.append(self.secondary_box)

        # Progress Indicator & Step Status Label
        progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        progress_box.set_margin_top(4)

        self.stage_status_label = Gtk.Label(
            label="Ready to build. Click '🚀 Start Kernel Build & Install' to begin.",
            halign=Gtk.Align.START
        )
        self.stage_status_label.add_css_class("stage-label")
        self.stage_status_label.set_wrap(True)
        progress_box.append(self.stage_status_label)

        self.stage_progress_bar = Gtk.ProgressBar()
        self.stage_progress_bar.set_fraction(0.0)
        self.stage_progress_bar.set_show_text(False)
        progress_box.append(self.stage_progress_bar)

        action_card_inner.append(progress_box)
        self.action_card.append(action_card_inner)
        self.content_box.append(self.action_card)

        # =========================================================================
        # Collapsible Detailed Build Log Expander
        # =========================================================================
        self.log_expander = Gtk.Expander(label="Show Detailed Build Log")
        self.log_expander.set_expanded(False) # Collapsed by default so users aren't overwhelmed
        self.log_expander.add_css_class("card")
        self.log_expander.set_margin_top(4)

        log_expander_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        log_expander_box.set_margin_top(10)
        log_expander_box.set_margin_bottom(12)
        log_expander_box.set_margin_start(12)
        log_expander_box.set_margin_end(12)

        # Log toolbar with Copy Error Log button
        log_toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        log_desc_label = Gtk.Label(label="Compiler terminal stream & execution history:", halign=Gtk.Align.START)
        log_desc_label.add_css_class("caption")
        log_desc_label.set_hexpand(True)
        log_toolbar.append(log_desc_label)

        self.invert_terminal_theme = False
        self.invert_log_button = Gtk.Button(label="🌗 Invert Colors")
        self.invert_log_button.set_tooltip_text("Switch terminal between White-on-Black and Black-on-White (auto-adapts to Adwaita Light/Dark by default).")
        self.invert_log_button.connect("clicked", self.on_invert_log_clicked)
        log_toolbar.append(self.invert_log_button)

        self.copy_log_button = Gtk.Button(label="📋 Copy Error Log")
        self.copy_log_button.set_tooltip_text("Copy build errors and recent terminal output to system clipboard.")
        self.copy_log_button.connect("clicked", self.on_copy_log_clicked)
        log_toolbar.append(self.copy_log_button)

        self.clear_log_button = Gtk.Button(label="Clear Log")
        self.clear_log_button.set_tooltip_text("Clear current log buffer.")
        self.clear_log_button.connect("clicked", self.on_clear_log_clicked)
        log_toolbar.append(self.clear_log_button)

        log_expander_box.append(log_toolbar)

        # Scrolled terminal view
        self.terminal_view = Gtk.TextView()
        self.terminal_view.set_editable(False)
        self.terminal_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.terminal_view.set_monospace(True)
        self.terminal_view.set_left_margin(12)
        self.terminal_view.set_right_margin(12)
        self.terminal_view.set_top_margin(10)
        self.terminal_view.set_bottom_margin(10)
        self.terminal_view.add_css_class("terminal-view")

        self.terminal_scroller = Gtk.ScrolledWindow()
        self.terminal_scroller.set_child(self.terminal_view)
        self.terminal_scroller.set_min_content_height(260)
        self.terminal_scroller.set_vexpand(True)
        self.terminal_scroller.add_css_class("terminal-container")
        log_expander_box.append(self.terminal_scroller)

        # Configure adaptive Light/Dark theme tag & Adw.StyleManager listener for terminal view
        buf = self.terminal_view.get_buffer()
        self.terminal_theme_tag = buf.create_tag("terminal_theme")
        self.style_manager = Adw.StyleManager.get_default()
        if self.style_manager:
            self.style_manager.connect("notify::dark", self._on_theme_changed)
        settings = Gtk.Settings.get_default()
        if settings:
            settings.connect("notify::gtk-application-prefer-dark-theme", self._on_theme_changed)
            settings.connect("notify::gtk-theme-name", self._on_theme_changed)
        self._update_terminal_theme()

        self.log_expander.set_child(log_expander_box)
        self.content_box.append(self.log_expander)

        # Startup initialization
        self.kernel_manager.cleanup_cache_on_startup(progress_callback=self.log)
        sb_status = "ENABLED (MOK signing recommended)" if self.is_secure_boot else "DISABLED / INACTIVE"
        self.log(f"[i] Host UEFI Secure Boot: {sb_status}")

        # Check build dependencies on startup
        use_container = (self.build_mode_row.get_selected() == 1)
        missing_deps = self.kernel_manager.check_build_dependencies(use_container=use_container)
        if missing_deps:
            self.log(f"[!] Notice: Missing {len(missing_deps)} build dependency item(s): {', '.join(missing_deps)}. Click 'Install Dependencies' to install.")
        else:
            mode = "Container & build" if use_container else "Host compiler"
            self.log(f"[✓] {mode} dependencies are verified and installed.")

        # Automatically check for available CachyOS releases on startup
        self.on_check_updates_clicked(None)

    def on_about_clicked(self, button):
        """Displays modern Libadwaita About dialog with the new logo and version."""
        if hasattr(Adw, "AboutDialog"):
            about = Adw.AboutDialog()
            about.set_application_name("Debian CachyOS Kernel Updater")
            about.set_application_icon("io.github.Antux912012.debian-cachy-os-kernel-updater")
            about.set_version(APP_VERSION)
            about.set_developer_name("Antonio")
            about.set_comments("Modern GTK4/Adwaita tool to compile, install, optimize, and sign CachyOS kernels on Debian systems.")
            about.set_website("https://github.com/Antux912012/debian-cachy-kernel-updater")
            about.set_license_type(Gtk.License.GPL_3_0)
            about.present(self)
        elif hasattr(Adw, "AboutWindow"):
            about = Adw.AboutWindow(transient_for=self)
            about.set_application_name("Debian CachyOS Kernel Updater")
            about.set_application_icon("io.github.Antux912012.debian-cachy-os-kernel-updater")
            about.set_version(APP_VERSION)
            about.set_developer_name("Antonio")
            about.set_comments("Modern GTK4/Adwaita tool to compile, install, optimize, and sign CachyOS kernels on Debian systems.")
            about.set_website("https://github.com/Antux912012/debian-cachy-kernel-updater")
            about.set_license_type(Gtk.License.GPL_3_0)
            about.present()

    def _apply_custom_css(self):
        """Loads clean, modern Adwaita-styled CSS for status badges, branding colors, and terminal log view."""
        provider = Gtk.CssProvider()
        css = b"""
            /* Brand Title & Headings */
            .brand-title {
                color: #00A896;
                font-weight: 800;
            }
            .status-card {
                border-left: 4px solid #00A896;
                background-color: rgba(0, 168, 150, 0.05);
            }
            .version-badge {
                background-color: rgba(0, 168, 150, 0.15);
                color: #00A896;
                font-weight: bold;
                font-size: 8pt;
                padding: 2px 8px;
                border-radius: 10px;
                border: 1px solid rgba(0, 168, 150, 0.4);
            }
            .sb-pill-active {
                background-color: #00A896;
                color: #ffffff;
                font-weight: bold;
                font-size: 8.5pt;
                padding: 4px 10px;
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 0.2);
            }
            .sb-pill-inactive {
                background-color: #5e5c64;
                color: #ffffff;
                font-weight: bold;
                font-size: 8.5pt;
                padding: 4px 10px;
                border-radius: 12px;
            }
            .stage-label {
                font-weight: bold;
                font-size: 11pt;
                color: #00A896;
            }
            /* Suggested action button (Teal Brand Gradient) */
            button.suggested-action {
                background: linear-gradient(135deg, #00A896 0%, #028090 100%);
                color: #ffffff;
                font-weight: bold;
                border: none;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0, 168, 150, 0.25);
            }
            button.suggested-action:hover {
                background: linear-gradient(135deg, #02bda8 0%, #0393a5 100%);
                box-shadow: 0 4px 8px rgba(0, 168, 150, 0.35);
            }
            button.suggested-action:active {
                background: linear-gradient(135deg, #017569 0%, #015e6a 100%);
            }
            /* Destructive action button (Crimson Brand Gradient) */
            button.destructive-action {
                background: linear-gradient(135deg, #D82655 0%, #C01C46 100%);
                color: #ffffff;
                font-weight: bold;
                border: none;
                border-radius: 8px;
            }
            button.destructive-action:hover {
                background: linear-gradient(135deg, #e83765 0%, #d82655 100%);
            }
            /* Progress Bar with Teal to Crimson Gradient */
            progressbar > trough > progress {
                background: linear-gradient(90deg, #00A896 0%, #028090 55%, #D82655 100%);
                border-radius: 6px;
            }
            progressbar > trough {
                background-color: rgba(0, 168, 150, 0.15);
                border-radius: 6px;
            }
            /* Modern Adaptive Terminal View (Light & Dark Adwaita Theme Support) */
            .terminal-container {
                border-radius: 8px;
                border: 1px solid rgba(0, 168, 150, 0.45);
            }
            scrolledwindow.terminal-container.terminal-dark,
            textview.terminal-view.terminal-dark,
            textview.terminal-view.terminal-dark text {
                font-family: monospace;
                font-size: 9.5pt;
                background-color: #000000;
                background-image: none;
                color: #ffffff;
                caret-color: #ffffff;
            }
            scrolledwindow.terminal-container.terminal-light,
            textview.terminal-view.terminal-light,
            textview.terminal-view.terminal-light text {
                font-family: monospace;
                font-size: 9.5pt;
                background-color: #ffffff;
                background-image: none;
                color: #000000;
                caret-color: #000000;
            }
        """
        provider.load_from_data(css)
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)

    def _is_dark_theme_active(self) -> bool:
        """Detects whether Adwaita / GTK is currently using a dark color scheme."""
        is_dark = False
        if hasattr(self, "style_manager") and self.style_manager:
            is_dark = bool(self.style_manager.get_dark())
        else:
            settings = Gtk.Settings.get_default()
            if settings:
                prefer_dark = settings.get_property("gtk-application-prefer-dark-theme")
                theme_name = (settings.get_property("gtk-theme-name") or "").lower()
                is_dark = bool(prefer_dark or "dark" in theme_name)
        if getattr(self, "invert_terminal_theme", False):
            is_dark = not is_dark
        return is_dark

    def _on_theme_changed(self, *args):
        """Callback when Adwaita Light/Dark mode changes."""
        self._update_terminal_theme()

    def on_invert_log_clicked(self, button):
        """Allows toggling White-on-Black vs Black-on-White manually in addition to auto Adwaita theme adaptation."""
        self.invert_terminal_theme = not getattr(self, "invert_terminal_theme", False)
        self._update_terminal_theme()

    def _update_terminal_theme(self):
        """Applies high-contrast White-on-Black (Dark mode) or Black-on-White (Light mode) to the build log terminal."""
        use_dark_terminal = self._is_dark_theme_active()
        for widget in (getattr(self, "terminal_view", None), getattr(self, "terminal_scroller", None)):
            if widget is None:
                continue
            if use_dark_terminal:
                widget.remove_css_class("terminal-light")
                widget.add_css_class("terminal-dark")
            else:
                widget.remove_css_class("terminal-dark")
                widget.add_css_class("terminal-light")

        if hasattr(self, "terminal_theme_tag") and self.terminal_theme_tag:
            if use_dark_terminal:
                self.terminal_theme_tag.set_property("foreground", "#ffffff")
                self.terminal_theme_tag.set_property("background", "#000000")
                self.terminal_theme_tag.set_property("paragraph-background", "#000000")
            else:
                self.terminal_theme_tag.set_property("foreground", "#000000")
                self.terminal_theme_tag.set_property("background", "#ffffff")
                self.terminal_theme_tag.set_property("paragraph-background", "#ffffff")
            buf = self.terminal_view.get_buffer()
            buf.apply_tag(self.terminal_theme_tag, buf.get_start_iter(), buf.get_end_iter())

    def log(self, message):
        """Thread-safe logging to the textview terminal."""
        GLib.idle_add(self._log_idle, message)

    def _log_idle(self, message):
        buffer = self.terminal_view.get_buffer()
        end_iter = buffer.get_end_iter()
        if hasattr(self, "terminal_theme_tag") and self.terminal_theme_tag:
            buffer.insert_with_tags(end_iter, message + "\n", self.terminal_theme_tag)
        else:
            buffer.insert(end_iter, message + "\n")
        mark = buffer.create_mark(None, buffer.get_end_iter(), False)
        self.terminal_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)
        return False

    def update_stage_progress(self, stage: int, total_stages: int, description: str):
        """Updates the high-level step progress bar and stage label."""
        fraction = min(1.0, max(0.0, stage / total_stages))
        self.stage_progress_bar.set_fraction(fraction)
        self.stage_status_label.set_label(f"Stage {stage}/{total_stages}: {description}")
        return False

    def get_current_output_dir(self):
        """Returns the current output directory where packages and MOK certificates are saved."""
        sel_idx = self.kernel_version_row.get_selected()
        ver = None
        if self.versions_list and 0 <= sel_idx < len(self.versions_list):
            ver = self.versions_list[sel_idx]['version']
        is_native = (self.cpu_arch_row.get_selected() == 1)
        return self.kernel_manager.last_output_dir or self.kernel_manager.get_output_kernel_dir(is_native=is_native, version=ver)

    def update_output_path_display(self):
        """Updates output package directory and certificate path displays."""
        target_dir = self.get_current_output_dir()
        if hasattr(self, "output_row"):
            self.output_row.set_subtitle(target_dir)
        if hasattr(self, "cert_folder_row"):
            self.cert_folder_row.set_subtitle(f"{target_dir} (MOK.der, MOK.pem, MOK.priv)")

    def on_open_certs_folder_clicked(self, button=None):
        target_dir = self.get_current_output_dir()
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception:
            pass
        self.log(f"[*] Opening certificates & output folder: {target_dir}")
        try:
            Gio.AppInfo.launch_default_for_uri(f"file://{target_dir}", None)
        except Exception:
            try:
                subprocess.Popen(self.kernel_manager._host_cmd(['xdg-open', target_dir]))
            except Exception as e:
                self.log(f"[!] Could not open folder: {e}")

    def refresh_secure_boot_ui(self):
        """Refreshes live Secure Boot pills and certificate status."""
        target_dir = self.get_current_output_dir()
        status = self.kernel_manager.get_mok_status(target_dir)
        self.is_secure_boot = status.get("secure_boot_enabled", False)

        pill_text = "[Secure Boot: Active]" if self.is_secure_boot else "[Secure Boot: Off]"
        pill_class = "sb-pill-active" if self.is_secure_boot else "sb-pill-inactive"

        if hasattr(self, "sb_banner_pill"):
            self.sb_banner_pill.set_label(pill_text)
            self.sb_banner_pill.set_css_classes([pill_class])
        if hasattr(self, "sb_row_pill"):
            self.sb_row_pill.set_label(pill_text)
            self.sb_row_pill.set_css_classes([pill_class])
        if hasattr(self, "cert_folder_row"):
            self.cert_folder_row.set_subtitle(f"{target_dir} (MOK.der, MOK.pem, MOK.priv)")

    def on_version_selected(self, row, param):
        self.update_output_path_display()

    def on_arch_selected(self, row, param):
        self.update_output_path_display()

    def on_build_mode_selected(self, row, param):
        use_container = (self.build_mode_row.get_selected() == 1)
        engine = self.kernel_manager.get_container_engine()
        if use_container:
            if engine:
                self.build_mode_row.set_subtitle(f"Detected engine: {engine.capitalize()} (Debian Bookworm isolated environment)")
            else:
                self.build_mode_row.set_subtitle("Podman will be installed as a dependency (Debian Bookworm isolated environment)")
            self.hw_config_check.set_active(False)
            self.hw_config_check.set_sensitive(False)
            self.hw_config_row.set_sensitive(False)
            self.hw_config_row.set_subtitle("Disabled in Container Mode: Container compilation builds for all hardware.")
            self.log("[i] Container build selected: compiling for all hardware inside an isolated builder image.")
        else:
            self.build_mode_row.set_subtitle("Native Host Build (Recommended — Fastest) compiles directly on host")
            self.hw_config_check.set_sensitive(True)
            self.hw_config_check.set_active(True)
            self.hw_config_row.set_sensitive(True)
            self.hw_config_row.set_subtitle("Tailors drivers to machine while preserving Wi-Fi, Bluetooth, storage &amp; filesystem baselines.")
            self.log("[i] Native Host Build selected: compiling directly on host.")

        # Re-check dependencies dynamically for the newly selected environment
        missing = self.kernel_manager.check_build_dependencies(use_container=use_container)
        if missing:
            self.log(f"[!] Notice: Missing {len(missing)} dependency item(s): {', '.join(missing)}. Click 'Install Dependencies' to install.")
        else:
            mode = "Container & build" if use_container else "Host compiler"
            self.log(f"[✓] {mode} dependencies are verified and installed.")

    def on_check_updates_clicked(self, button):
        self.log("[*] Checking official CachyOS GitHub repositories for available releases...")
        if hasattr(self, "check_button"):
            self.check_button.set_sensitive(False)
        self.latest_label.set_label("Latest CachyOS Kernel: Querying GitHub...")

        def check_task():
            releases = self.kernel_manager.get_available_versions()
            latest = self.kernel_manager.get_latest_cachy_version()
            is_matching = self.kernel_manager.is_matching_running_kernel()
            GLib.idle_add(self._update_version_ui, releases, latest, is_matching)

        threading.Thread(target=check_task, daemon=True).start()

    def _update_version_ui(self, releases, latest, is_matching):
        self.latest_label.set_label(f"Latest CachyOS Kernel: {latest}")
        self.log(f"[✓] Official latest CachyOS kernel version: {latest}")

        self.versions_list = releases
        labels = [r['label'] for r in releases]
        self.version_string_list = Gtk.StringList.new(labels)
        self.kernel_version_row.set_model(self.version_string_list)

        # Pre-select latest Stable release
        stable_idx = 0
        for idx, r in enumerate(releases):
            if not r['is_experimental']:
                stable_idx = idx
                break
        self.kernel_version_row.set_selected(stable_idx)
        self.update_output_path_display()

        if is_matching:
            self.match_status_label.set_label("✅ You are currently running the latest CachyOS kernel.")
            self.log("[i] Running kernel matches the latest CachyOS release.")
        else:
            self.match_status_label.set_label("⚡ A newer or different CachyOS kernel version is available for compilation.")
            self.log("[i] Newer CachyOS release is ready to download and compile.")

        if hasattr(self, "check_button"):
            self.check_button.set_sensitive(True)
        if hasattr(self, "start_build_button"):
            self.start_build_button.set_sensitive(True)
        if hasattr(self, "deps_button"):
            self.deps_button.set_sensitive(True)
        return False

    def on_open_output_clicked(self, button):
        sel_idx = self.kernel_version_row.get_selected()
        ver = self.versions_list[sel_idx]['version'] if (self.versions_list and 0 <= sel_idx < len(self.versions_list)) else None
        is_native = (self.cpu_arch_row.get_selected() == 1)
        out_dir = self.kernel_manager.last_output_dir or self.kernel_manager.get_output_kernel_dir(is_native=is_native, version=ver)
        if not os.path.exists(out_dir):
            out_dir = self.kernel_manager.output_base_dir
        if not os.path.exists(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception:
                pass
        self.log(f"[*] Opening output folder: {out_dir}")
        try:
            Gio.AppInfo.launch_default_for_uri(f"file://{out_dir}", None)
        except Exception:
            try:
                subprocess.Popen(self.kernel_manager._host_cmd(['xdg-open', out_dir]))
            except Exception as e:
                self.log(f"[!] Could not open folder: {e}")

    def on_install_scx_clicked(self, button):
        self.set_buttons_sensitive(False)
        self.install_scx_button.set_sensitive(False)
        self.status_label.set_text("Installing sched-ext (SCX v1.1.4) BPF schedulers...")
        self.progress_bar.set_fraction(0.2)
        self.log_expander.set_expanded(True)

        def run():
            try:
                self.kernel_manager.install_scx_schedulers(progress_callback=self.log)
                GLib.idle_add(self.on_install_scx_complete, True, "sched-ext (SCX v1.1.4) BPF schedulers installed successfully!")
            except Exception as e:
                GLib.idle_add(self.on_install_scx_complete, False, str(e))

        threading.Thread(target=run, daemon=True).start()

    def on_install_scx_complete(self, success, message):
        self.set_buttons_sensitive(True)
        self.install_scx_button.set_sensitive(True)
        scx_st = self.kernel_manager.get_scx_status()
        scx_count = scx_st.get("installed_count", 0)
        self.scx_pill.set_label(f"[SCX: {scx_count} Installed]" if scx_count > 0 else "[SCX: Not Installed]")
        if scx_count > 0:
            self.scx_pill.remove_css_class("sb-pill-inactive")
            self.scx_pill.add_css_class("sb-pill-active")
            self.install_scx_button.set_label("🔄 Update SCX")
            self.install_scx_button.remove_css_class("suggested-action")
        if success:
            self.progress_bar.set_fraction(1.0)
            self.status_label.set_text(message)
        else:
            self.progress_bar.set_fraction(0.0)
            self.status_label.set_text("SCX installation failed (see build log)")
            self.log(f"[!] SCX installation error: {message}")
        return False

    def on_install_deps_clicked(self, button):
        use_container = (self.build_mode_row.get_selected() == 1)
        missing = self.kernel_manager.check_build_dependencies(use_container=use_container)
        if not missing:
            self.log("\n=======================================================")
            if use_container:
                self.log("[✓] All required kernel build dependencies and container environment are already installed:")
                engine = self.kernel_manager.get_container_engine() or "podman"
                self.log(f"    • Container Engine: {engine}")
                self.log(f"    • Container Image: {self.kernel_manager.container_image_tag} (verified)")
            else:
                self.log("[✓] All required host kernel compiler dependencies are already installed:")
            for dep in self.kernel_manager.REQUIRED_BUILD_DEPS:
                self.log(f"    • {dep} (installed)")
            self.log("=======================================================\n")

            dialog = Adw.MessageDialog(
                transient_for=self,
                heading="Dependencies Installed",
                body=(
                    "All required dependencies "
                    + ("and container builder image " if use_container else "")
                    + "are already installed on your system.\n\nWould you like to run verification/reinstallation anyway?"
                )
            )
            dialog.add_response("cancel", "Keep Current")
            dialog.add_response("reinstall", "Update / Reinstall")
            dialog.set_response_appearance("reinstall", Adw.ResponseAppearance.SUGGESTED)

            def on_dialog_response(dlg, response):
                if response == "reinstall":
                    self._start_deps_install(use_container=use_container, force_rebuild=True)

            dialog.connect("response", on_dialog_response)
            dialog.present()
        else:
            self.log("\n=======================================================")
            mode_desc = "Container & Build" if use_container else "Host Compiler"
            self.log(f"[*] Missing {len(missing)} {mode_desc} dependency item(s): {', '.join(missing)}")
            self.log("=======================================================\n")
            self._start_deps_install(use_container=use_container, force_rebuild=False)

    def _start_deps_install(self, use_container=False, force_rebuild=False, and_build=False):
        self.deps_button.set_sensitive(False)
        self.start_build_button.set_sensitive(False)
        self.check_button.set_sensitive(False)
        if hasattr(self, "reset_mok_button"):
            self.reset_mok_button.set_sensitive(False)
        if hasattr(self, "reset_mok_row_button"):
            self.reset_mok_row_button.set_sensitive(False)

        def deps_task():
            success = self.kernel_manager.install_build_dependencies(
                progress_callback=self.log,
                use_container=use_container,
                force_rebuild=force_rebuild
            )
            GLib.idle_add(self._on_deps_complete, success, and_build)

        threading.Thread(target=deps_task, daemon=True).start()

    def _on_deps_complete(self, success, and_build=False):
        self.deps_button.set_sensitive(True)
        self.check_button.set_sensitive(True)
        self.start_build_button.set_sensitive(True)
        if hasattr(self, "reset_mok_button"):
            self.reset_mok_button.set_sensitive(True)
        if hasattr(self, "reset_mok_row_button"):
            self.reset_mok_row_button.set_sensitive(True)
        if success:
            self.log("[✓] Build dependencies setup complete.")
            if and_build:
                self._confirm_and_start_build()
        else:
            self.log("[!] Dependency installation was cancelled or encountered an error.")
        return False

    def on_start_build_clicked(self, button):
        use_container = (self.build_mode_row.get_selected() == 1)

        # Check dependencies before build
        missing = self.kernel_manager.check_build_dependencies(use_container=use_container)
        if missing:
            mode_desc = "container environment" if use_container else "host compiler"
            self.log(f"[!] Cannot start build: missing {len(missing)} {mode_desc} package(s): {', '.join(missing)}")
            dialog = Adw.MessageDialog(
                transient_for=self,
                heading="Dependencies Required",
                body=(
                    f"Your system is missing required compilation packages:\n"
                    f"{', '.join(missing)}\n\n"
                    f"Would you like to install them now using pkexec apt-get?"
                )
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("install", "Install Dependencies")
            dialog.set_response_appearance("install", Adw.ResponseAppearance.SUGGESTED)

            def on_missing_resp(dlg, resp):
                if resp == "install":
                    self._start_deps_install(use_container=use_container, force_rebuild=False, and_build=True)

            dialog.connect("response", on_missing_resp)
            dialog.present()
            return

        self._confirm_and_start_build()

    def _confirm_and_start_build(self):
        sel_idx = self.kernel_version_row.get_selected()
        target_rel = self.versions_list[sel_idx] if (self.versions_list and 0 <= sel_idx < len(self.versions_list)) else None
        ver = target_rel['version'] if target_rel else self.kernel_manager.latest_version
        tag = target_rel['tag'] if target_rel else self.kernel_manager.latest_tag
        dl_url = target_rel['download_url'] if target_rel else self.kernel_manager.download_url

        use_container = (self.build_mode_row.get_selected() == 1)
        use_localmodconfig = False if use_container else self.hw_config_check.get_active()
        strip_debug_symbols = self.strip_debug_check.get_active()
        auto_install = self.auto_install_check.get_active()
        sign_after_install = self.sign_postinst_check.get_active()

        arch_idx = self.cpu_arch_row.get_selected()
        cpu_arch = ['generic', 'native', 'x86-64-v3'][arch_idx]

        lto_idx = self.compiler_lto_row.get_selected()
        compiler_lto = ['gcc_none', 'clang_none', 'clang_thin', 'clang_full'][lto_idx]

        sched_idx = self.scheduler_row.get_selected()
        cpu_scheduler = ['bore', 'eevdf'][sched_idx]

        tick_idx = self.tick_rate_row.get_selected()
        tick_rate = ['1000', '500', '300', '250'][tick_idx]

        threads = int(self.threads_spin.get_value())

        output_dir = self.kernel_manager.get_output_kernel_dir(is_native=(cpu_arch == 'native'), version=ver)
        mode_str = f"Container ({self.kernel_manager.get_container_engine() or 'Podman'})" if use_container else "Native Host System"
        opt_str = "Native (-march=native)" if cpu_arch == 'native' else ("Generic x86-64-v3" if cpu_arch == 'x86-64-v3' else "Generic x86-64 (Safe for all modern CPUs)")
        hw_str = "All Hardware (Universal Generic Drivers — Container Mode)" if use_container else ("Current System Hardware (localmodconfig)" if use_localmodconfig else "All Hardware (Universal Generic Drivers)")

        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Start Kernel Build",
            body=(
                f"Kernel Version: {ver}\n"
                f"Build Environment: {mode_str}\n"
                f"Hardware Drivers: {hw_str}\n"
                f"CPU Architecture: {opt_str}\n"
                f"CPU Scheduler: {cpu_scheduler.upper()} | Tick Rate: {tick_rate} Hz\n"
                f"Parallel Threads: {threads} (1 core kept free)\n\n"
                f"Output Package Folder:\n📂 {output_dir}\n\n"
                f"Auto-Install after build: {'Yes (pkexec dpkg -i)' if auto_install else 'No'}\n"
                f"UEFI Secure Boot signing: {'Yes (MOK)' if sign_after_install else 'No'}"
            )
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("proceed", "🚀 Start Build")
        dialog.set_response_appearance("proceed", Adw.ResponseAppearance.SUGGESTED)

        def on_response(dlg, response):
            if response == "proceed":
                def proceed(mok_password=""):
                    try:
                        os.makedirs(output_dir, exist_ok=True)
                    except Exception as e:
                        self.log(f"[!] Note on output directory: {e}")
                    self._start_kernel_build(
                        ver=ver,
                        tag=tag,
                        dl_url=dl_url,
                        use_container=use_container,
                        use_localmodconfig=use_localmodconfig,
                        strip_debug_symbols=strip_debug_symbols,
                        auto_install=auto_install,
                        sign_after_install=sign_after_install,
                        cpu_arch=cpu_arch,
                        compiler_lto=compiler_lto,
                        cpu_scheduler=cpu_scheduler,
                        tick_rate=tick_rate,
                        threads=threads,
                        mok_password=mok_password
                    )

                if auto_install and sign_after_install:
                    self.request_mok_password_dialog(proceed)
                else:
                    proceed("")
            else:
                self.log("[i] Build cancelled by user.")

        dialog.connect("response", on_response)
        dialog.present()

    def _start_kernel_build(
        self,
        ver,
        tag,
        dl_url,
        use_container,
        use_localmodconfig,
        strip_debug_symbols,
        auto_install,
        sign_after_install,
        cpu_arch,
        compiler_lto,
        cpu_scheduler,
        tick_rate,
        threads,
        mok_password=""
    ):
        total_stages = 5 if auto_install else 4

        self.start_build_button.set_sensitive(False)
        self.install_existing_button.set_sensitive(False)
        self.sign_installed_action_button.set_sensitive(False)
        if hasattr(self, "reset_mok_button"):
            self.reset_mok_button.set_sensitive(False)
        if hasattr(self, "reset_mok_row_button"):
            self.reset_mok_row_button.set_sensitive(False)
        self.deps_button.set_sensitive(False)
        self.check_button.set_sensitive(False)
        self.rollback_button.set_sensitive(False)

        target_output_dir = self.get_current_output_dir()

        self.log("\n=======================================================")
        self.log("[*] Starting CachyOS Kernel Automated Build Pipeline...")
        self.log(f"    • Target Version: {ver} ({tag})")
        self.log(f"    • Build Mode: {'Container' if use_container else 'Native Host'}")
        self.log(f"    • CPU Architecture: {cpu_arch}")
        self.log(f"    • Scheduler: {cpu_scheduler} | Concurrency: -j{threads}")
        self.log(f"    • Auto-Install: {'Enabled' if auto_install else 'Disabled'}")
        self.log(f"    • Secure Boot Signing: {'Enabled (MOK)' if sign_after_install else 'Disabled'}")
        self.log(f"    • Output & Certs Directory: {target_output_dir}")
        self.log("=======================================================\n")

        self.update_stage_progress(1, total_stages, "Checking dependencies...")

        def build_task():
            try:
                # Stage 1: Verification
                GLib.idle_add(self.update_stage_progress, 1, total_stages, "Verifying build dependencies and environment...")
                missing = self.kernel_manager.check_build_dependencies(use_container=use_container)
                if missing:
                    raise Exception(f"Missing required build dependencies: {', '.join(missing)}")

                # Stage 2: Download & patch CachyOS source
                GLib.idle_add(self.update_stage_progress, 2, total_stages, f"Downloading & patching CachyOS source ({ver})...")
                kernel_dir = self.kernel_manager.download_kernel(
                    version=ver,
                    tag=tag,
                    download_url=dl_url,
                    progress_callback=self.log
                )

                # Stage 3 & 4: Sanitizing configuration & compiling
                def stage_cb(stage_num, desc):
                    GLib.idle_add(self.update_stage_progress, stage_num, total_stages, desc)

                self.kernel_manager.compile_kernel(
                    kernel_dir,
                    progress_callback=self.log,
                    stage_callback=stage_cb,
                    use_container=use_container,
                    use_localmodconfig=use_localmodconfig,
                    strip_debug_symbols=strip_debug_symbols,
                    cpu_scheduler=cpu_scheduler,
                    compiler_lto=compiler_lto,
                    cpu_arch=cpu_arch,
                    tick_rate=tick_rate,
                    tickless=True,
                    threads=threads
                )

                # Stage 5 (if auto_install): Install & Sign in a single privileged transaction
                mok_status = "NONE"
                if auto_install:
                    GLib.idle_add(self.update_stage_progress, 5, total_stages, "Installing .deb packages & signing for Secure Boot...")
                    inst_ok, mok_status = self.kernel_manager.install_and_sign_kernel_debs(
                        deb_dir=target_output_dir,
                        sign_enabled=sign_after_install,
                        mok_password=mok_password,
                        log_callback=self.log
                    )
                    if not inst_ok:
                        raise Exception(f"Debian package installation encountered an error: {mok_status}")

                GLib.idle_add(self._on_build_complete, True, auto_install, sign_after_install, mok_status)
            except Exception as e:
                self.log(f"\n[!] Build task failed: {str(e)}")
                GLib.idle_add(self._on_build_complete, False, auto_install, sign_after_install, "ERROR", str(e))

        threading.Thread(target=build_task, daemon=True).start()

    def _on_build_complete(self, success, auto_install=True, sign_after_install=True, mok_status=None, error_msg=None):
        self.start_build_button.set_sensitive(True)
        self.install_existing_button.set_sensitive(True)
        self.sign_installed_action_button.set_sensitive(True)
        if hasattr(self, "reset_mok_button"):
            self.reset_mok_button.set_sensitive(True)
        if hasattr(self, "reset_mok_row_button"):
            self.reset_mok_row_button.set_sensitive(True)
        self.deps_button.set_sensitive(True)
        self.check_button.set_sensitive(True)
        self.rollback_button.set_sensitive(True)

        self.refresh_secure_boot_ui()

        if success:
            self.stage_progress_bar.set_fraction(1.0)
            if auto_install:
                self.stage_status_label.set_label("✓ Build, installation, and Secure Boot signing completed successfully!")
                self.log("\n=======================================================")
                self.log("[✓] Pipeline Finished! CachyOS kernel is installed and ready.")
                if sign_after_install:
                    if mok_status == "ENROLLMENT_QUEUED":
                        self.log("    • Machine Owner Key (MOK) queued for UEFI enrollment on reboot.")
                        self.show_mok_enrolled_reboot_dialog()
                    elif mok_status == "ALREADY_ENROLLED":
                        self.log("    • Kernel signed with active MOK key; no enrollment needed.")
                        self.show_mok_already_enrolled_dialog()
                    else:
                        self.log("    Please reboot your computer to boot the new kernel.")
                else:
                    self.log("    Please reboot your computer to boot the new kernel.")
                self.log("=======================================================\n")
            else:
                self.stage_status_label.set_label("✓ Build finished! Kernel packages are ready to install.")
                self.log("\n=======================================================")
                self.log("[✓] Kernel compilation finished! Click 'Install Existing .deb' to install.")
                self.log("=======================================================\n")
        else:
            self.stage_status_label.set_label("❌ Build task failed. Click 'Show Detailed Build Log' or 'Copy Error Log'.")
            self.log_expander.set_expanded(True)
        return False

    def on_apply_clicked(self, button):
        sign_after_install = self.sign_postinst_check.get_active()
        mode_desc = "Installation + UEFI Secure Boot Signing" if sign_after_install else "Installation"
        target_dir = self.get_current_output_dir()

        def start_install(mok_password=""):
            self.log(f"\n[*] Initiating package {mode_desc.lower()} via pkexec...")
            self.install_existing_button.set_sensitive(False)
            self.start_build_button.set_sensitive(False)
            self.sign_installed_action_button.set_sensitive(False)
            if hasattr(self, "reset_mok_button"):
                self.reset_mok_button.set_sensitive(False)
            if hasattr(self, "reset_mok_row_button"):
                self.reset_mok_row_button.set_sensitive(False)

            def install_task():
                success, mok_status = self.kernel_manager.install_and_sign_kernel_debs(
                    deb_dir=target_dir,
                    sign_enabled=sign_after_install,
                    mok_password=mok_password,
                    log_callback=self.log
                )
                GLib.idle_add(self._on_install_complete, success, mok_status, sign_after_install)

            threading.Thread(target=install_task, daemon=True).start()

        if sign_after_install:
            self.request_mok_password_dialog(start_install)
        else:
            start_install("")

    def _on_install_complete(self, success, mok_status, sign_after_install=True):
        self.install_existing_button.set_sensitive(True)
        self.start_build_button.set_sensitive(True)
        self.sign_installed_action_button.set_sensitive(True)
        if hasattr(self, "reset_mok_button"):
            self.reset_mok_button.set_sensitive(True)
        if hasattr(self, "reset_mok_row_button"):
            self.reset_mok_row_button.set_sensitive(True)

        self.refresh_secure_boot_ui()

        if success:
            self.log("\n[✓] CachyOS Kernel installed successfully! Please reboot to run the new kernel.")
            if sign_after_install:
                if mok_status == "ENROLLMENT_QUEUED":
                    self.show_mok_enrolled_reboot_dialog()
                elif mok_status == "ALREADY_ENROLLED":
                    self.show_mok_already_enrolled_dialog()
                elif mok_status == "NEEDS_ENROLLMENT":
                    self.log("[!] Notice: MOK key needs enrollment into UEFI NVRAM.")
            else:
                self.log("[i] If your system uses UEFI Secure Boot, click '🔒 Sign Installed Kernel (Secure Boot)' to authorize the kernel.")
        else:
            self.log(f"\n[!] Kernel installation failed: {mok_status}\n")
        return False

    def on_sign_installed_kernel_clicked(self, button):
        target_dir = self.get_current_output_dir()
        def start_signing(mok_password=""):
            current_kernel = self.kernel_manager.get_current_kernel_version()
            self.sign_installed_action_button.set_sensitive(False)
            self.start_build_button.set_sensitive(False)
            self.install_existing_button.set_sensitive(False)
            if hasattr(self, "reset_mok_button"):
                self.reset_mok_button.set_sensitive(False)
            if hasattr(self, "reset_mok_row_button"):
                self.reset_mok_row_button.set_sensitive(False)

            self.log("\n=======================================================")
            self.log("[*] Starting Post-Installation Kernel & Module Signing (MOK)...")
            self.log(f"    Target/Running Kernel: {current_kernel}")
            self.log(f"    Certificates & Output: {target_dir}")
            self.log("=======================================================\n")

            def sign_task():
                try:
                    success, mok_status = self.kernel_manager.sign_existing_installed_kernel(
                        kernel_version="auto",
                        mok_password=mok_password,
                        output_dir=target_dir,
                        log_callback=self.log
                    )
                    GLib.idle_add(self._on_sign_installed_complete, success, mok_status)
                except Exception as e:
                    self.log(f"\n[!] Secure Boot signing failed: {e}\n")
                    GLib.idle_add(self._on_sign_installed_complete, False, str(e))

            threading.Thread(target=sign_task, daemon=True).start()

        self.request_mok_password_dialog(start_signing)

    def _on_sign_installed_complete(self, success, mok_status):
        self.sign_installed_action_button.set_sensitive(True)
        self.start_build_button.set_sensitive(True)
        self.install_existing_button.set_sensitive(True)
        if hasattr(self, "reset_mok_button"):
            self.reset_mok_button.set_sensitive(True)
        if hasattr(self, "reset_mok_row_button"):
            self.reset_mok_row_button.set_sensitive(True)

        self.refresh_secure_boot_ui()

        if success:
            self.log(f"[✓] Post-installation signing and initramfs/GRUB update completed successfully! (Status: {mok_status})")
            if mok_status == "ENROLLMENT_QUEUED":
                self.show_mok_enrolled_reboot_dialog()
            elif mok_status == "ALREADY_ENROLLED":
                self.show_mok_already_enrolled_dialog()
            elif mok_status == "NEEDS_ENROLLMENT":
                self.log("[!] Notice: Kernel signed, but MOK key needs enrollment into UEFI NVRAM.")
        else:
            self.log(f"[!] Secure Boot signing failed: {mok_status}")
        return False

    def request_mok_password_dialog(self, on_confirmed_callback):
        """
        Checks UEFI Secure Boot and MOK enrollment status in the current output folder.
        If MOK is already enrolled into UEFI NVRAM, invokes on_confirmed_callback("") immediately.
        If MOK key is NOT enrolled, prompts the user for a one-time 8-16 character password
        before running any pkexec operations so that only ONE Polkit prompt appears.
        """
        target_dir = self.get_current_output_dir()
        status = self.kernel_manager.get_mok_status(target_dir)
        if status.get("key_enrolled", False):
            self.log("[✓] MOK key is already enrolled in UEFI NVRAM. Skipping password prompt.")
            on_confirmed_callback("")
            return

        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="UEFI Secure Boot & MOK Setup",
            body=(
                "Your kernel and out-of-tree drivers will be signed with your local Machine Owner Key (MOK).\n\n"
                f"Certificates will be stored in:\n📂 {target_dir}\n\n"
                "Because this MOK key is not yet enrolled in your motherboard's UEFI NVRAM, "
                "please choose a one-time temporary password (8 to 16 characters) to authorize "
                "it during your next reboot in the MokManager screen:"
            )
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("enroll", "Sign & Enroll Key")
        dialog.set_response_appearance("enroll", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_enabled("enroll", False)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        pwd_label = Gtk.Label(label="One-Time MOK Password (8–16 characters):", halign=Gtk.Align.START)
        pwd_label.add_css_class("caption")
        pwd_entry = Gtk.PasswordEntry()
        pwd_entry.set_show_peek_icon(True)

        confirm_label = Gtk.Label(label="Confirm Password:", halign=Gtk.Align.START)
        confirm_label.add_css_class("caption")
        confirm_entry = Gtk.PasswordEntry()
        confirm_entry.set_show_peek_icon(True)

        hint_label = Gtk.Label(label="Password must be between 8 and 16 characters.", halign=Gtk.Align.START)
        hint_label.add_css_class("dim-label")
        hint_label.add_css_class("caption")

        box.append(pwd_label)
        box.append(pwd_entry)
        box.append(confirm_label)
        box.append(confirm_entry)
        box.append(hint_label)

        def validate_passwords(*_):
            p1 = pwd_entry.get_text()
            p2 = confirm_entry.get_text()
            if len(p1) < 8 or len(p1) > 16:
                hint_label.set_label("Password must be between 8 and 16 characters.")
                dialog.set_response_enabled("enroll", False)
            elif p1 != p2:
                hint_label.set_label("Passwords do not match.")
                dialog.set_response_enabled("enroll", False)
            else:
                hint_label.set_label("✓ Password valid and confirmed.")
                dialog.set_response_enabled("enroll", True)

        pwd_entry.connect("notify::text", validate_passwords)
        confirm_entry.connect("notify::text", validate_passwords)

        dialog.set_extra_child(box)

        def on_dialog_response(dlg, response):
            if response == "enroll":
                pwd = pwd_entry.get_text()
                on_confirmed_callback(pwd)
            else:
                self.log("[i] Operation cancelled by user.")

        dialog.connect("response", on_dialog_response)
        dialog.present()

    def on_reset_mok_clicked(self, button=None):
        target_dir = self.get_current_output_dir()
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception:
            pass

        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Reset & Recreate MOK Keys",
            body=(
                f"This will cancel your previous UEFI MOK enrollment, delete old certificates in:\n"
                f"📂 {target_dir}\n\n"
                f"It will generate a brand-new RSA-2048 MOK keypair from scratch, re-sign your currently installed "
                f"kernel in /boot, and queue the new key for enrollment on next reboot.\n\n"
                f"Enter a new one-time enrollment password (8 to 16 characters):"
            )
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("reset", "Reset & Recreate Keys")
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_enabled("reset", False)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        pwd_label = Gtk.Label(label="New MOK Password (8–16 characters):", halign=Gtk.Align.START)
        pwd_label.add_css_class("caption")
        pwd_entry = Gtk.PasswordEntry()
        pwd_entry.set_show_peek_icon(True)

        confirm_label = Gtk.Label(label="Confirm New Password:", halign=Gtk.Align.START)
        confirm_label.add_css_class("caption")
        confirm_entry = Gtk.PasswordEntry()
        confirm_entry.set_show_peek_icon(True)

        hint_label = Gtk.Label(label="Password must be between 8 and 16 characters.", halign=Gtk.Align.START)
        hint_label.add_css_class("dim-label")
        hint_label.add_css_class("caption")

        box.append(pwd_label)
        box.append(pwd_entry)
        box.append(confirm_label)
        box.append(confirm_entry)
        box.append(hint_label)

        def validate_passwords(*_):
            p1 = pwd_entry.get_text()
            p2 = confirm_entry.get_text()
            if len(p1) < 8 or len(p1) > 16:
                hint_label.set_label("Password must be between 8 and 16 characters.")
                dialog.set_response_enabled("reset", False)
            elif p1 != p2:
                hint_label.set_label("Passwords do not match.")
                dialog.set_response_enabled("reset", False)
            else:
                hint_label.set_label("✓ Password valid and confirmed.")
                dialog.set_response_enabled("reset", True)

        pwd_entry.connect("notify::text", validate_passwords)
        confirm_entry.connect("notify::text", validate_passwords)

        dialog.set_extra_child(box)

        def on_dialog_response(dlg, response):
            if response == "reset":
                pwd = pwd_entry.get_text()
                self._start_reset_and_recreate_mok(target_dir, pwd)
            else:
                self.log("[i] MOK reset cancelled by user.")

        dialog.connect("response", on_dialog_response)
        dialog.present()

    def _start_reset_and_recreate_mok(self, target_dir, password):
        self.start_build_button.set_sensitive(False)
        self.install_existing_button.set_sensitive(False)
        self.sign_installed_action_button.set_sensitive(False)
        if hasattr(self, "reset_mok_button"):
            self.reset_mok_button.set_sensitive(False)
        if hasattr(self, "reset_mok_row_button"):
            self.reset_mok_row_button.set_sensitive(False)

        self.log("\n=======================================================")
        self.log("[*] Resetting & Recreating MOK Keys from Scratch...")
        self.log(f"    Target Folder: {target_dir}")
        self.log("=======================================================\n")

        def worker():
            try:
                success, mok_status = self.kernel_manager.reset_and_recreate_mok_keys(
                    output_dir=target_dir,
                    mok_password=password,
                    log_callback=self.log
                )
                GLib.idle_add(self._on_reset_mok_complete, success, mok_status, target_dir)
            except Exception as e:
                self.log(f"\n[!] Reset and recreation failed: {e}\n")
                GLib.idle_add(self._on_reset_mok_complete, False, str(e), target_dir)

        threading.Thread(target=worker, daemon=True).start()

    def _on_reset_mok_complete(self, success, mok_status, target_dir):
        self.start_build_button.set_sensitive(True)
        self.install_existing_button.set_sensitive(True)
        self.sign_installed_action_button.set_sensitive(True)
        if hasattr(self, "reset_mok_button"):
            self.reset_mok_button.set_sensitive(True)
        if hasattr(self, "reset_mok_row_button"):
            self.reset_mok_row_button.set_sensitive(True)

        self.refresh_secure_boot_ui()

        if success:
            self.log(f"[✓] MOK keypair regenerated in {target_dir} and queued for UEFI enrollment!")
            self.show_mok_enrolled_reboot_dialog()
        else:
            self.log(f"[!] MOK reset failed: {mok_status}")
            dialog = Adw.MessageDialog(
                transient_for=self,
                heading="MOK Reset Failed",
                body=f"Failed to reset and recreate MOK keys:\n\n{mok_status}"
            )
            dialog.add_response("ok", "Close")
            dialog.present()
        return False

    def show_mok_enrolled_reboot_dialog(self):
        """Displays instructions for MokManager on the next reboot."""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="MOK Enrollment Queued for Next Reboot",
            body=(
                "Your kernel has been signed and the Machine Owner Key (MOK) is queued for enrollment.\n\n"
                "When you restart your computer, the blue MokManager screen will appear:\n\n"
                "  1. Press any key to enter MokManager\n"
                "  2. Select 'Enroll MOK'\n"
                "  3. Select 'Continue' and 'Yes' to confirm\n"
                "  4. Enter the one-time password you just created\n"
                "  5. Select 'Reboot'\n\n"
                "After these steps, your signed CachyOS kernel will boot securely!"
            )
        )
        dialog.add_response("ok", "Got It")
        dialog.present()

    def show_mok_already_enrolled_dialog(self):
        """Displays confirmation when MOK key is already enrolled in UEFI."""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Kernel Signed & Ready",
            body=(
                "The kernel and DKMS modules in /boot are cryptographically signed with your active MOK key.\n\n"
                "Your key is already enrolled in UEFI NVRAM, so you can reboot immediately!"
            )
        )
        dialog.add_response("ok", "OK")
        dialog.present()

    def show_mok_enrollment_dialog(self, der_path=None):
        """Compatibility helper redirecting to request_mok_password_dialog."""
        self.request_mok_password_dialog(lambda pwd: self.on_sign_installed_kernel_clicked(None))

    def on_enroll_mok_clicked(self, button=None):
        def _do_enroll(pwd):
            self.log("[*] Queueing MOK enrollment...")
            success, mok_status = self.kernel_manager.sign_existing_installed_kernel(kernel_version="auto", mok_password=pwd, log_callback=self.log)
            if success:
                if mok_status == "ENROLLMENT_QUEUED":
                    self.show_mok_enrolled_reboot_dialog()
                else:
                    self.show_mok_already_enrolled_dialog()

        self.request_mok_password_dialog(_do_enroll)

    def on_copy_log_clicked(self, button):
        buffer = self.terminal_view.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        if not text.strip():
            self.log("[i] Log buffer is empty.")
            return

        lines = text.splitlines()
        error_lines = [l for l in lines if re.search(r'(error:|fatal error:|BUILD FAILURE|undefined reference|No space left)', l, re.I)]
        if error_lines:
            copy_text = "=== CACHYOS BUILD ERROR LOG SUMMARY ===\n" + "\n".join(error_lines[-40:]) + "\n\n=== RECENT LOG ===\n" + "\n".join(lines[-100:])
        else:
            copy_text = text

        display = Gdk.Display.get_default()
        if display:
            clipboard = display.get_clipboard()
            clipboard.set(copy_text)
            self.log("[✓] Build log copied to system clipboard.")

    def on_clear_log_clicked(self, button):
        buffer = self.terminal_view.get_buffer()
        buffer.set_text("")
        self.log("[i] Terminal log buffer cleared.")

    def on_rollback_clicked(self, button):
        installed_kernels = self.kernel_manager.get_installed_kernels()
        if not installed_kernels:
            self.log("[!] No installed kernel packages found.")
            return

        current_kernel = self.kernel_manager.get_current_kernel_version()

        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Rollback Kernel",
            body="Select an installed kernel package to remove.\n\n⚠️ Caution: Do not remove the kernel you are currently running!"
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove Package")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)

        dropdown = Gtk.DropDown.new_from_strings(installed_kernels)

        for i, pkg in enumerate(installed_kernels):
            if current_kernel not in pkg:
                dropdown.set_selected(i)
                break

        dialog.set_extra_child(dropdown)

        def on_response(dlg, response):
            if response == "remove":
                selected_item = dropdown.get_selected_item()
                if selected_item:
                    package_name = selected_item.get_string()
                    self.log(f"[*] Requesting root authentication to purge {package_name}...")

                    def remove_task():
                        success = self.kernel_manager.remove_kernel(package_name, progress_callback=self.log)
                        if success:
                            GLib.idle_add(self.log, f"[✓] Removed {package_name}. Reboot your computer to boot the previous kernel.")

                    threading.Thread(target=remove_task, daemon=True).start()

        dialog.connect("response", on_response)
        dialog.present()


class KernelUpdaterApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='io.github.Antux912012.debian-cachy-os-kernel-updater')

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = KernelUpdaterWindow(self)
        win.present()


if __name__ == '__main__':
    cli_flags = {
        '--check', '--status-sb', '--install-deps', '--build', '--install',
        '--rollback', '--sign-mok', '--sign-deb-mok', '--enroll-mok',
        '--reset-mok', '--sign-debs'
    }
    if '--version' in sys.argv[1:]:
        print(f"Debian CachyOS Kernel Updater v{APP_VERSION}")
        sys.exit(0)
    if any(arg.split('=')[0] in cli_flags for arg in sys.argv[1:]):
        import runpy
        km_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kernel_manager.py')
        runpy.run_path(km_path, run_name='__main__')
        sys.exit(0)
    app = KernelUpdaterApp()
    sys.exit(app.run(sys.argv))
