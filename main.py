import sys
import os
import subprocess
import threading
import re
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk, Gio, GObject

from kernel_manager import KernelManager

APP_VERSION = "1.2.0"


class KernelUpdaterWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="CachyOS Kernel Updater")
        self.set_default_size(880, 740)
        self.set_resizable(True)

        # Configure icon theme search paths for bundled & system symbolic icons
        display = Gdk.Display.get_default()
        if display:
            icon_theme = Gtk.IconTheme.get_for_display(display)
            appdir = os.environ.get("APPDIR")
            if appdir:
                icon_theme.add_search_path(os.path.join(appdir, "usr/share/icons"))
            icon_theme.add_search_path("/app/share/icons")
            icon_theme.add_search_path("/usr/share/icons")
            icon_theme.add_search_path("/usr/local/share/icons")
            icon_theme.add_search_path(os.path.expanduser("~/.local/share/icons"))
            local_assets = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
            if os.path.isdir(local_assets):
                icon_theme.add_search_path(local_assets)

        self.kernel_manager = KernelManager()
        self.versions_list = []
        self.is_secure_boot = False
        self._installed_kernel_rows = []

        self._apply_custom_css()
        self._register_window_actions()

        # Root ToolbarView (GNOME / Libadwaita HIG)
        self.toolbar_view = Adw.ToolbarView()
        self.set_content(self.toolbar_view)

        # ViewStack for 3 focused pages
        self.view_stack = Adw.ViewStack()

        # HeaderBar with centered ViewSwitcherTitle
        self.header = Adw.HeaderBar()
        self.view_switcher_title = Adw.ViewSwitcherTitle()
        self.view_switcher_title.set_stack(self.view_stack)
        self.view_switcher_title.set_title("CachyOS Kernel Updater")
        self.header.set_title_widget(self.view_switcher_title)

        # Left HeaderBar action: Check Updates
        self.check_button = Gtk.Button(icon_name="view-refresh-symbolic")
        self.check_button.set_tooltip_text("Check for CachyOS Kernel Updates")
        self.check_button.connect("clicked", self.on_check_updates_clicked)
        self.header.pack_start(self.check_button)

        # Right HeaderBar action: Primary Menu
        menu_model = Gio.Menu()
        menu_model.append("Install Build Dependencies", "win.install-deps")
        menu_model.append("Open Output Folder", "win.open-output")
        menu_model.append("About CachyOS Kernel Updater", "win.about")

        self.menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        self.menu_button.set_menu_model(menu_model)
        self.menu_button.set_tooltip_text("Main Menu")
        self.header.pack_end(self.menu_button)

        self.toolbar_view.add_top_bar(self.header)

        # Missing dependencies banner (hidden until startup check detects missing deps)
        self.deps_banner = Adw.Banner(
            title="Required kernel build dependencies are missing for the selected environment."
        )
        self.deps_banner.set_button_label("Install Dependencies")
        self.deps_banner.connect("button-clicked", lambda _b: self.on_install_deps_clicked(None))
        self.deps_banner.set_revealed(False)
        self.toolbar_view.add_top_bar(self.deps_banner)

        # Build the 3 ViewStack pages
        self.view_stack.add_titled_with_icon(
            self._build_update_page(), "build", "Update & Build", "system-software-install-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self._build_secure_boot_page(), "secureboot", "Secure Boot", "security-high-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self._build_kernels_logs_page(), "kernels", "Kernels & Logs", "utilities-terminal-symbolic"
        )
        self.toolbar_view.set_content(self.view_stack)

        # Bottom ViewSwitcherBar for narrow windows
        self.view_switcher_bar = Adw.ViewSwitcherBar()
        self.view_switcher_bar.set_stack(self.view_stack)
        self.view_switcher_title.bind_property(
            "title-visible", self.view_switcher_bar, "reveal", GObject.BindingFlags.SYNC_CREATE
        )
        self.toolbar_view.add_bottom_bar(self.view_switcher_bar)

        # Initialize adaptive terminal theme
        self.style_manager = Adw.StyleManager.get_default()
        self.invert_terminal_theme = False
        if self.style_manager:
            self.style_manager.connect("notify::dark", self._on_theme_changed)
        self._update_terminal_theme()

        # Defer all host/network/subprocess startup checks so the window opens instantaneously
        GLib.idle_add(self._schedule_startup_checks)

    def _register_window_actions(self):
        actions = [
            ("install-deps", lambda *_: self.on_install_deps_clicked(None)),
            ("open-output", lambda *_: self.on_open_output_clicked(None)),
            ("about", self.on_about_clicked),
        ]
        for name, cb in actions:
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)

    def _build_update_page(self) -> Gtk.Widget:
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        clamp = Adw.Clamp(maximum_size=680, tightening_threshold=520)
        clamp.set_margin_top(20)
        clamp.set_margin_bottom(24)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        clamp.set_child(content)
        scrolled.set_child(clamp)

        # 1. System Status Card
        status_group = Adw.PreferencesGroup(title="System Status")
        current_kernel = self.kernel_manager.get_current_kernel_version()
        host_os_name = self.kernel_manager.host_distro.get("name", "Debian/Ubuntu")

        running_row = Adw.ActionRow(title="Running Kernel", subtitle=f"{current_kernel} ({host_os_name})")
        self.match_status_pill = Gtk.Label(label="Checking...")
        self.match_status_pill.add_css_class("sb-pill-inactive")
        self.match_status_pill.set_valign(Gtk.Align.CENTER)
        running_row.add_suffix(self.match_status_pill)
        status_group.add(running_row)

        self.latest_row = Adw.ActionRow(title="Latest CachyOS Release", subtitle="Querying GitHub...")
        status_group.add(self.latest_row)

        self.sb_summary_row = Adw.ActionRow(title="UEFI Secure Boot & MOK", subtitle="Checking firmware state...")
        self.sb_banner_pill = Gtk.Label(label="Checking...")
        self.sb_banner_pill.add_css_class("sb-pill-inactive")
        self.sb_banner_pill.set_valign(Gtk.Align.CENTER)
        self.sb_summary_row.add_suffix(self.sb_banner_pill)
        status_group.add(self.sb_summary_row)

        content.append(status_group)

        # 2. Step 1: Kernel & Performance Profile
        step1_group = Adw.PreferencesGroup(
            title="1. Kernel & Performance Profile",
            description="Choose the kernel series, CPU scheduler, and target instruction set."
        )

        self.kernel_version_row = Adw.ComboRow(title="Kernel Series")
        self.version_string_list = Gtk.StringList.new(["Fetching available releases..."])
        self.kernel_version_row.set_model(self.version_string_list)
        self.kernel_version_row.connect("notify::selected", self.on_version_selected)
        step1_group.add(self.kernel_version_row)

        self.scheduler_row = Adw.ComboRow(
            title="CPU Scheduler",
            subtitle="BORE improves desktop responsiveness under heavy load"
        )
        self.scheduler_row.set_model(Gtk.StringList.new([
            "BORE (Recommended for Desktop)",
            "EEVDF (Standard Upstream)"
        ]))
        self.scheduler_row.set_selected(0)
        step1_group.add(self.scheduler_row)

        self.cpu_arch_row = Adw.ComboRow(
            title="CPU Optimization",
            subtitle="Choose Native for this PC or x86-64-v3 / Generic for portability"
        )
        self.cpu_arch_row.set_model(Gtk.StringList.new([
            "Generic x86-64 (Universal)",
            "Native (-march=native, This PC Only)",
            "Generic x86-64-v3 (Modern AVX2 CPUs)"
        ]))
        self.cpu_arch_row.set_selected(0)
        self.cpu_arch_row.connect("notify::selected", self.on_arch_selected)
        step1_group.add(self.cpu_arch_row)

        content.append(step1_group)

        # 3. Step 2: Advanced Kernel & Build Options (Progressive Disclosure)
        step2_group = Adw.PreferencesGroup()
        self.advanced_expander = Adw.ExpanderRow(
            title="2. Advanced Kernel & Build Options",
            subtitle="Build environment, Clang ThinLTO, timer tick rate, and packaging"
        )

        self.build_mode_row = Adw.ComboRow(
            title="Build Environment",
            subtitle="Native host build is fastest; container isolates build dependencies"
        )
        self.build_mode_row.set_model(Gtk.StringList.new([
            "Native Host Build (Fastest)",
            "Isolated Container (Podman / Docker)"
        ]))
        self.build_mode_row.set_selected(0)
        self.build_mode_row.connect("notify::selected", self.on_build_mode_selected)
        self.advanced_expander.add_row(self.build_mode_row)

        self.compiler_lto_row = Adw.ComboRow(
            title="Compiler & LTO",
            subtitle="Clang ThinLTO provides strong performance with fast link times"
        )
        self.compiler_lto_row.set_model(Gtk.StringList.new([
            "GCC (Standard)",
            "Clang (No LTO)",
            "Clang + ThinLTO (Recommended)",
            "Clang + Full LTO"
        ]))
        self.compiler_lto_row.set_selected(2)
        self.advanced_expander.add_row(self.compiler_lto_row)

        self.tick_rate_row = Adw.ComboRow(
            title="Timer Tick Rate",
            subtitle="Higher tick rates lower latency; 250 Hz maximizes battery life"
        )
        self.tick_rate_row.set_model(Gtk.StringList.new([
            "1000 Hz (Desktop / Gaming)",
            "500 Hz (Balanced)",
            "300 Hz",
            "250 Hz (Power Saving)"
        ]))
        self.tick_rate_row.set_selected(0)
        self.advanced_expander.add_row(self.tick_rate_row)

        cpu_count = os.cpu_count() or 4
        default_threads = max(1, cpu_count - 1)
        threads_row = Adw.ActionRow(
            title="Parallel Build Threads",
            subtitle=f"Leaves 1 CPU core free on your {cpu_count}-core system"
        )
        adj = Gtk.Adjustment(value=default_threads, lower=1, upper=max(1, cpu_count * 2), step_increment=1, page_increment=2)
        self.threads_spin = Gtk.SpinButton(adjustment=adj)
        self.threads_spin.set_valign(Gtk.Align.CENTER)
        threads_row.add_suffix(self.threads_spin)
        self.advanced_expander.add_row(threads_row)

        self.hw_config_row = Adw.ActionRow(
            title="Optimize Drivers for This Hardware",
            subtitle="Uses localmodconfig while preserving Wi-Fi, Bluetooth, NVMe & filesystem baselines"
        )
        self.hw_config_check = Gtk.Switch(active=True, valign=Gtk.Align.CENTER)
        self.hw_config_row.add_suffix(self.hw_config_check)
        self.hw_config_row.set_activatable_widget(self.hw_config_check)
        self.advanced_expander.add_row(self.hw_config_row)

        strip_row = Adw.ActionRow(
            title="Strip Debug Symbols",
            subtitle="Reduces .deb package size and speeds up installation"
        )
        self.strip_debug_check = Gtk.Switch(active=True, valign=Gtk.Align.CENTER)
        strip_row.add_suffix(self.strip_debug_check)
        strip_row.set_activatable_widget(self.strip_debug_check)
        self.advanced_expander.add_row(strip_row)

        auto_inst_row = Adw.ActionRow(
            title="Install Automatically After Build",
            subtitle="Installs built .deb packages via pkexec dpkg -i"
        )
        self.auto_install_check = Gtk.Switch(active=True, valign=Gtk.Align.CENTER)
        auto_inst_row.add_suffix(self.auto_install_check)
        auto_inst_row.set_activatable_widget(self.auto_install_check)
        self.advanced_expander.add_row(auto_inst_row)

        sign_row = Adw.ActionRow(
            title="Sign for UEFI Secure Boot (MOK)",
            subtitle="Signs vmlinuz and DKMS modules with your local Machine Owner Key"
        )
        self.sign_postinst_check = Gtk.Switch(active=True, valign=Gtk.Align.CENTER)
        sign_row.add_suffix(self.sign_postinst_check)
        sign_row.set_activatable_widget(self.sign_postinst_check)
        self.advanced_expander.add_row(sign_row)

        default_out = self.kernel_manager.get_output_kernel_dir(is_native=False)
        self.output_row = Adw.ActionRow(title="Output Packages Directory", subtitle=default_out)
        open_out_btn = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
        open_out_btn.add_css_class("flat")
        open_out_btn.set_tooltip_text("Open Output Directory")
        open_out_btn.connect("clicked", self.on_open_output_clicked)
        self.output_row.add_suffix(open_out_btn)
        self.advanced_expander.add_row(self.output_row)

        step2_group.add(self.advanced_expander)
        content.append(step2_group)

        # 4. Primary Action Area + Progress
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, halign=Gtk.Align.CENTER)
        action_box.set_margin_top(4)

        self.start_build_button = Gtk.Button()
        self.start_build_button.add_css_class("suggested-action")
        self.start_build_button.add_css_class("pill")
        start_content = Adw.ButtonContent(icon_name="system-run-symbolic", label="Start Kernel Build & Install")
        self.start_build_button.set_child(start_content)
        self.start_build_button.set_sensitive(False)
        self.start_build_button.connect("clicked", self.on_start_build_clicked)
        action_box.append(self.start_build_button)

        self.install_existing_button = Gtk.Button()
        self.install_existing_button.add_css_class("pill")
        inst_content = Adw.ButtonContent(icon_name="document-open-symbolic", label="Install Existing .deb")
        self.install_existing_button.set_child(inst_content)
        self.install_existing_button.connect("clicked", self.on_apply_clicked)
        action_box.append(self.install_existing_button)

        content.append(action_box)

        progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.stage_status_label = Gtk.Label(
            label="Ready to configure and compile CachyOS kernel.",
            halign=Gtk.Align.CENTER
        )
        self.stage_status_label.add_css_class("dim-label")
        self.stage_status_label.add_css_class("caption")
        progress_box.append(self.stage_status_label)

        self.stage_progress_bar = Gtk.ProgressBar()
        self.stage_progress_bar.set_fraction(0.0)
        progress_box.append(self.stage_progress_bar)
        content.append(progress_box)

        return scrolled

    def _build_secure_boot_page(self) -> Gtk.Widget:
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        clamp = Adw.Clamp(maximum_size=680, tightening_threshold=520)
        clamp.set_margin_top(20)
        clamp.set_margin_bottom(24)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        clamp.set_child(content)
        scrolled.set_child(clamp)

        # UEFI & MOK Status
        sb_group = Adw.PreferencesGroup(
            title="UEFI Secure Boot & MOK Status",
            description="Machine Owner Keys (MOK) allow your custom-compiled kernel and DKMS drivers to boot with Secure Boot enabled."
        )

        sb_fw_row = Adw.ActionRow(title="UEFI Secure Boot", subtitle="Hardware firmware enforcement state")
        self.sb_row_pill = Gtk.Label(label="Checking...")
        self.sb_row_pill.add_css_class("sb-pill-inactive")
        self.sb_row_pill.set_valign(Gtk.Align.CENTER)
        sb_fw_row.add_suffix(self.sb_row_pill)
        sb_group.add(sb_fw_row)

        mok_row = Adw.ActionRow(title="MOK Signing Key", subtitle="Enrollment status in motherboard UEFI NVRAM")
        self.mok_enroll_pill = Gtk.Label(label="Checking...")
        self.mok_enroll_pill.add_css_class("sb-pill-inactive")
        self.mok_enroll_pill.set_valign(Gtk.Align.CENTER)
        mok_row.add_suffix(self.mok_enroll_pill)
        sb_group.add(mok_row)

        default_out = self.kernel_manager.get_output_kernel_dir(is_native=False)
        self.cert_folder_row = Adw.ActionRow(
            title="Certificates Directory",
            subtitle=f"{default_out} (MOK.der, MOK.pem, MOK.priv)"
        )
        open_certs_btn = Gtk.Button(label="Open Folder", valign=Gtk.Align.CENTER)
        open_certs_btn.connect("clicked", self.on_open_certs_folder_clicked)
        self.cert_folder_row.add_suffix(open_certs_btn)
        sb_group.add(self.cert_folder_row)

        content.append(sb_group)

        # MOK Key Management
        mgmt_group = Adw.PreferencesGroup(title="MOK Key Management")

        sign_row = Adw.ActionRow(
            title="Sign & Enroll Installed Kernel",
            subtitle="Sign /boot/vmlinuz and out-of-tree DKMS modules, and queue MOK enrollment if needed"
        )
        self.sign_installed_action_button = Gtk.Button(label="Sign & Enroll", valign=Gtk.Align.CENTER)
        self.sign_installed_action_button.add_css_class("suggested-action")
        self.sign_installed_action_button.add_css_class("pill")
        self.sign_installed_action_button.connect("clicked", self.on_sign_installed_kernel_clicked)
        sign_row.add_suffix(self.sign_installed_action_button)
        mgmt_group.add(sign_row)

        reset_row = Adw.ActionRow(
            title="Reset & Recreate MOK Keys",
            subtitle="Revoke old UEFI enrollment, generate fresh RSA-2048 keys, and re-sign the installed kernel"
        )
        self.reset_mok_button = Gtk.Button(label="Reset Keys", valign=Gtk.Align.CENTER)
        self.reset_mok_button.add_css_class("destructive-action")
        self.reset_mok_button.add_css_class("pill")
        self.reset_mok_button.connect("clicked", self.on_reset_mok_clicked)
        reset_row.add_suffix(self.reset_mok_button)
        mgmt_group.add(reset_row)

        content.append(mgmt_group)
        return scrolled

    def _build_kernels_logs_page(self) -> Gtk.Widget:
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        clamp = Adw.Clamp(maximum_size=760, tightening_threshold=560)
        clamp.set_margin_top(20)
        clamp.set_margin_bottom(24)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        clamp.set_child(content)
        scrolled.set_child(clamp)

        # Installed Kernels Group
        self.kernels_group = Adw.PreferencesGroup(
            title="Installed Kernels",
            description="Inspect installed Linux kernel packages or remove an older kernel to reclaim /boot space."
        )
        self.rollback_button = Gtk.Button(label="Rollback Kernel...", valign=Gtk.Align.CENTER)
        self.rollback_button.add_css_class("destructive-action")
        self.rollback_button.connect("clicked", self.on_rollback_clicked)
        self.kernels_group.set_header_suffix(self.rollback_button)

        placeholder_row = Adw.ActionRow(title="Scanning installed kernel packages...")
        self._installed_kernel_rows.append(placeholder_row)
        self.kernels_group.add(placeholder_row)
        content.append(self.kernels_group)

        # Build & Installation Log Group
        log_group = Adw.PreferencesGroup(title="Build & Installation Log")
        log_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER)

        self.invert_log_button = Gtk.Button(icon_name="weather-clear-night-symbolic")
        self.invert_log_button.add_css_class("flat")
        self.invert_log_button.set_tooltip_text("Toggle Light / Dark Log Contrast")
        self.invert_log_button.connect("clicked", self.on_invert_log_clicked)
        log_actions.append(self.invert_log_button)

        self.copy_log_button = Gtk.Button(icon_name="edit-copy-symbolic")
        self.copy_log_button.add_css_class("flat")
        self.copy_log_button.set_tooltip_text("Copy Build / Error Log")
        self.copy_log_button.connect("clicked", self.on_copy_log_clicked)
        log_actions.append(self.copy_log_button)

        self.clear_log_button = Gtk.Button(icon_name="edit-clear-all-symbolic")
        self.clear_log_button.add_css_class("flat")
        self.clear_log_button.set_tooltip_text("Clear Log")
        self.clear_log_button.connect("clicked", self.on_clear_log_clicked)
        log_actions.append(self.clear_log_button)

        log_group.set_header_suffix(log_actions)

        self.terminal_scroller = Gtk.ScrolledWindow()
        self.terminal_scroller.set_min_content_height(300)
        self.terminal_scroller.set_vexpand(True)
        self.terminal_scroller.add_css_class("terminal-container")

        self.terminal_view = Gtk.TextView()
        self.terminal_view.set_editable(False)
        self.terminal_view.set_monospace(True)
        self.terminal_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.terminal_view.set_top_margin(10)
        self.terminal_view.set_bottom_margin(10)
        self.terminal_view.set_left_margin(12)
        self.terminal_view.set_right_margin(12)
        self.terminal_view.add_css_class("terminal-view")

        buf = self.terminal_view.get_buffer()
        self.terminal_theme_tag = buf.create_tag("theme_text", foreground="#ffffff", background="#000000")

        self.terminal_scroller.set_child(self.terminal_view)
        log_group.add(self.terminal_scroller)
        content.append(log_group)

        return scrolled

    def _schedule_startup_checks(self):
        """Runs initial host/cache/dependency/network checks in a background thread so UI paints immediately."""
        self.log(f"[*] CachyOS Kernel Updater v{APP_VERSION} initialized ({self.kernel_manager.host_distro.get('name', 'Debian/Ubuntu')}).")

        def worker():
            sb_status = self.kernel_manager.get_mok_status(self.get_current_output_dir())
            cleaned = self.kernel_manager.cleanup_cache_on_startup(progress_callback=self.log)
            missing_deps = self.kernel_manager.check_build_dependencies(use_container=False)
            installed_kernels = self.kernel_manager.get_installed_kernels()
            releases = self.kernel_manager.get_available_versions()
            latest = self.kernel_manager.get_latest_cachy_version()
            is_matching = self.kernel_manager.is_matching_running_kernel()
            GLib.idle_add(
                self._apply_startup_results,
                sb_status, cleaned, missing_deps, installed_kernels, releases, latest, is_matching
            )

        threading.Thread(target=worker, daemon=True).start()
        return False

    def _apply_startup_results(self, sb_status, cleaned, missing_deps, installed_kernels, releases, latest, is_matching):
        self._apply_mok_status_to_ui(sb_status)

        if cleaned:
            self.log(f"[*] Cleaned up {cleaned} stale build cache item(s) on startup.")

        self.deps_banner.set_revealed(bool(missing_deps))
        if missing_deps:
            self.log(f"[!] Missing {len(missing_deps)} host dependency item(s): {', '.join(missing_deps)}")
        else:
            self.log("[✓] Host compiler dependencies verified.")

        self._populate_installed_kernels_list(installed_kernels)
        self._update_version_ui(releases, latest, is_matching)
        return False

    def _populate_installed_kernels_list(self, installed_kernels):
        for row in self._installed_kernel_rows:
            self.kernels_group.remove(row)
        self._installed_kernel_rows.clear()

        current_kver = self.kernel_manager.get_current_kernel_version()
        if not installed_kernels:
            empty_row = Adw.ActionRow(title="No linux-image packages detected")
            self._installed_kernel_rows.append(empty_row)
            self.kernels_group.add(empty_row)
            return

        for pkg in installed_kernels:
            is_running = current_kver in pkg
            row = Adw.ActionRow(
                title=pkg,
                subtitle="Currently running kernel" if is_running else "Installed kernel package"
            )
            if is_running:
                pill = Gtk.Label(label="Running", valign=Gtk.Align.CENTER)
                pill.add_css_class("sb-pill-active")
                row.add_suffix(pill)
            else:
                rm_btn = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
                rm_btn.add_css_class("flat")
                rm_btn.set_tooltip_text(f"Remove {pkg}")
                rm_btn.connect("clicked", lambda _b, p=pkg: self._confirm_remove_single_kernel(p))
                row.add_suffix(rm_btn)
            self._installed_kernel_rows.append(row)
            self.kernels_group.add(row)

    def _confirm_remove_single_kernel(self, package_name: str):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Remove Kernel Package",
            body=f"Purge {package_name} from your system and update GRUB/initramfs?"
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_resp(_dlg, resp):
            if resp == "remove":
                self.log(f"[*] Requesting root authentication to purge {package_name}...")
                def remove_task():
                    success = self.kernel_manager.remove_kernel(package_name, progress_callback=self.log)
                    if success:
                        updated = self.kernel_manager.get_installed_kernels()
                        GLib.idle_add(self._populate_installed_kernels_list, updated)
                threading.Thread(target=remove_task, daemon=True).start()

        dialog.connect("response", on_resp)
        dialog.present()

    def on_about_clicked(self, action=None, param=None):
        """Shows a standard Libadwaita About dialog."""
        use_dialog = hasattr(Adw, "AboutDialog")
        about = Adw.AboutDialog() if use_dialog else Adw.AboutWindow(transient_for=self)
        about.set_application_name("CachyOS Kernel Updater")
        about.set_application_icon("io.github.Antux912012.debian-cachy-os-kernel-updater")
        about.set_version(APP_VERSION)
        about.set_developer_name("Antonio")
        about.set_comments("Compile, optimize, install, and UEFI Secure Boot sign CachyOS kernels on Debian & Ubuntu.")
        about.set_website("https://github.com/Antux912012/debian-cachy-os-kernel-updater")
        about.set_license_type(Gtk.License.GPL_3_0)
        if use_dialog:
            about.present(self)
        else:
            about.present()

    def _apply_custom_css(self):
        """Loads clean Adwaita-styled CSS for status pills and adaptive terminal log view."""
        provider = Gtk.CssProvider()
        css = b"""
            .sb-pill-active {
                background-color: #00A896;
                color: #ffffff;
                font-weight: bold;
                font-size: 8.5pt;
                padding: 4px 10px;
                border-radius: 12px;
            }
            .sb-pill-inactive {
                background-color: #5e5c64;
                color: #ffffff;
                font-weight: bold;
                font-size: 8.5pt;
                padding: 4px 10px;
                border-radius: 12px;
            }
            .terminal-container {
                border-radius: 10px;
                border: 1px solid rgba(0, 168, 150, 0.45);
            }
            scrolledwindow.terminal-container.terminal-dark,
            textview.terminal-view.terminal-dark,
            textview.terminal-view.terminal-dark text {
                font-family: monospace;
                font-size: 9.5pt;
                background-color: #0d1117;
                background-image: none;
                color: #e6edf3;
                caret-color: #e6edf3;
            }
            scrolledwindow.terminal-container.terminal-light,
            textview.terminal-view.terminal-light,
            textview.terminal-view.terminal-light text {
                font-family: monospace;
                font-size: 9.5pt;
                background-color: #ffffff;
                background-image: none;
                color: #1f2328;
                caret-color: #1f2328;
            }
        """
        provider.load_from_data(css)
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)

    def _is_dark_theme_active(self) -> bool:
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
        self._update_terminal_theme()

    def on_invert_log_clicked(self, button):
        self.invert_terminal_theme = not getattr(self, "invert_terminal_theme", False)
        self._update_terminal_theme()

    def _update_terminal_theme(self):
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
                self.terminal_theme_tag.set_property("foreground", "#e6edf3")
                self.terminal_theme_tag.set_property("background", "#0d1117")
                self.terminal_theme_tag.set_property("paragraph-background", "#0d1117")
            else:
                self.terminal_theme_tag.set_property("foreground", "#1f2328")
                self.terminal_theme_tag.set_property("background", "#ffffff")
                self.terminal_theme_tag.set_property("paragraph-background", "#ffffff")
            buf = self.terminal_view.get_buffer()
            buf.apply_tag(self.terminal_theme_tag, buf.get_start_iter(), buf.get_end_iter())

    def log(self, message):
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
        fraction = min(1.0, max(0.0, stage / total_stages))
        self.stage_progress_bar.set_fraction(fraction)
        self.stage_status_label.set_label(f"Stage {stage}/{total_stages}: {description}")
        return False

    def get_current_output_dir(self):
        sel_idx = self.kernel_version_row.get_selected()
        ver = None
        if self.versions_list and 0 <= sel_idx < len(self.versions_list):
            ver = self.versions_list[sel_idx]['version']
        is_native = (self.cpu_arch_row.get_selected() == 1)
        return self.kernel_manager.last_output_dir or self.kernel_manager.get_output_kernel_dir(is_native=is_native, version=ver)

    def update_output_path_display(self):
        target_dir = self.get_current_output_dir()
        if hasattr(self, "output_row"):
            self.output_row.set_subtitle(target_dir)
        if hasattr(self, "cert_folder_row"):
            self.cert_folder_row.set_subtitle(f"{target_dir} (MOK.der, MOK.pem, MOK.priv)")

    def _open_folder_in_file_manager(self, target_dir: str, label: str = "output folder"):
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception:
            pass
        self.log(f"[*] Opening {label}: {target_dir}")
        try:
            Gio.AppInfo.launch_default_for_uri(f"file://{target_dir}", None)
        except Exception:
            try:
                subprocess.Popen(self.kernel_manager._host_cmd(['xdg-open', target_dir]))
            except Exception as e:
                self.log(f"[!] Could not open folder: {e}")

    def _set_action_buttons_sensitive(self, sensitive: bool, include_aux: bool = False):
        for attr in ("start_build_button", "install_existing_button", "sign_installed_action_button", "reset_mok_button"):
            btn = getattr(self, attr, None)
            if btn is not None:
                btn.set_sensitive(sensitive)
        if include_aux:
            for attr in ("check_button", "rollback_button"):
                btn = getattr(self, attr, None)
                if btn is not None:
                    btn.set_sensitive(sensitive)

    def on_open_certs_folder_clicked(self, button=None):
        self._open_folder_in_file_manager(self.get_current_output_dir(), "certificates & output folder")

    def _apply_mok_status_to_ui(self, status: dict):
        target_dir = self.get_current_output_dir()
        self.is_secure_boot = status.get("secure_boot_enabled", False)
        enrolled = status.get("key_enrolled", False)

        pill_text = "Secure Boot: Active" if self.is_secure_boot else "Secure Boot: Off"
        pill_class = "sb-pill-active" if self.is_secure_boot else "sb-pill-inactive"

        self.sb_banner_pill.set_label(pill_text)
        self.sb_banner_pill.set_css_classes([pill_class])
        self.sb_row_pill.set_label("Active" if self.is_secure_boot else "Off")
        self.sb_row_pill.set_css_classes([pill_class])

        mok_text = "Enrolled" if enrolled else "Not Enrolled"
        self.mok_enroll_pill.set_label(mok_text)
        self.mok_enroll_pill.set_css_classes(["sb-pill-active" if enrolled else "sb-pill-inactive"])

        if self.is_secure_boot:
            self.sb_summary_row.set_subtitle("UEFI Secure Boot enforced • " + ("MOK enrolled" if enrolled else "MOK enrollment needed"))
        else:
            self.sb_summary_row.set_subtitle("UEFI Secure Boot disabled in firmware")

        self.cert_folder_row.set_subtitle(f"{target_dir} (MOK.der, MOK.pem, MOK.priv)")

    def refresh_secure_boot_ui(self):
        target_dir = self.get_current_output_dir()
        def worker():
            status = self.kernel_manager.get_mok_status(target_dir)
            GLib.idle_add(self._apply_mok_status_to_ui, status)
        threading.Thread(target=worker, daemon=True).start()

    def on_version_selected(self, row, param):
        self.update_output_path_display()

    def on_arch_selected(self, row, param):
        self.update_output_path_display()

    def on_build_mode_selected(self, row, param):
        use_container = (self.build_mode_row.get_selected() == 1)
        engine = self.kernel_manager.get_container_engine()
        if use_container:
            if engine:
                self.build_mode_row.set_subtitle(f"Detected engine: {engine.capitalize()} (isolated Debian builder)")
            else:
                self.build_mode_row.set_subtitle("Podman will be installed as a dependency (isolated Debian builder)")
            self.hw_config_check.set_active(False)
            self.hw_config_check.set_sensitive(False)
            self.hw_config_row.set_sensitive(False)
            self.hw_config_row.set_subtitle("Disabled in Container Mode: container builds universal hardware drivers.")
        else:
            self.build_mode_row.set_subtitle("Native host build is fastest; container isolates build dependencies")
            self.hw_config_check.set_sensitive(True)
            self.hw_config_check.set_active(True)
            self.hw_config_row.set_sensitive(True)
            self.hw_config_row.set_subtitle("Uses localmodconfig while preserving Wi-Fi, Bluetooth, NVMe & filesystem baselines")

        def dep_worker():
            missing = self.kernel_manager.check_build_dependencies(use_container=use_container)
            def _update():
                self.deps_banner.set_revealed(bool(missing))
                if missing:
                    self.log(f"[!] Missing {len(missing)} dependency item(s): {', '.join(missing)}.")
                else:
                    mode = "Container & build" if use_container else "Host compiler"
                    self.log(f"[✓] {mode} dependencies verified.")
                return False
            GLib.idle_add(_update)
        threading.Thread(target=dep_worker, daemon=True).start()

    def on_check_updates_clicked(self, button):
        self.log("[*] Checking official CachyOS GitHub repositories for available releases...")
        self.check_button.set_sensitive(False)
        self.latest_row.set_subtitle("Querying GitHub...")

        def check_task():
            releases = self.kernel_manager.get_available_versions()
            latest = self.kernel_manager.get_latest_cachy_version()
            is_matching = self.kernel_manager.is_matching_running_kernel()
            GLib.idle_add(self._update_version_ui, releases, latest, is_matching)

        threading.Thread(target=check_task, daemon=True).start()

    def _update_version_ui(self, releases, latest, is_matching):
        self.latest_row.set_subtitle(f"CachyOS {latest}")
        self.log(f"[✓] Official latest CachyOS kernel version: {latest}")

        self.versions_list = releases
        labels = [r['label'] for r in releases]
        self.version_string_list = Gtk.StringList.new(labels)
        self.kernel_version_row.set_model(self.version_string_list)

        stable_idx = 0
        for idx, r in enumerate(releases):
            if not r['is_experimental']:
                stable_idx = idx
                break
        self.kernel_version_row.set_selected(stable_idx)
        self.update_output_path_display()

        if is_matching:
            self.match_status_pill.set_label("Up to date")
            self.match_status_pill.set_css_classes(["sb-pill-active"])
            self.log("[i] Running kernel matches the latest CachyOS release.")
        else:
            self.match_status_pill.set_label("Update available")
            self.match_status_pill.set_css_classes(["sb-pill-inactive"])
            self.log("[i] Newer CachyOS release is ready to download and compile.")

        self.check_button.set_sensitive(True)
        self.start_build_button.set_sensitive(True)
        return False

    def on_open_output_clicked(self, button):
        sel_idx = self.kernel_version_row.get_selected()
        ver = self.versions_list[sel_idx]['version'] if (self.versions_list and 0 <= sel_idx < len(self.versions_list)) else None
        is_native = (self.cpu_arch_row.get_selected() == 1)
        out_dir = self.kernel_manager.last_output_dir or self.kernel_manager.get_output_kernel_dir(is_native=is_native, version=ver)
        if not os.path.exists(out_dir):
            out_dir = self.kernel_manager.output_base_dir
        self._open_folder_in_file_manager(out_dir, "output folder")

    def on_install_deps_clicked(self, button):
        use_container = (self.build_mode_row.get_selected() == 1)
        missing = self.kernel_manager.check_build_dependencies(use_container=use_container)
        if not missing:
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
            dialog.connect("response", lambda _d, r: self._start_deps_install(use_container=use_container, force_rebuild=True) if r == "reinstall" else None)
            dialog.present()
        else:
            self._start_deps_install(use_container=use_container, force_rebuild=False)

    def _start_deps_install(self, use_container=False, force_rebuild=False, and_build=False):
        self._set_action_buttons_sensitive(False, include_aux=True)

        def deps_task():
            success = self.kernel_manager.install_build_dependencies(
                progress_callback=self.log,
                use_container=use_container,
                force_rebuild=force_rebuild
            )
            GLib.idle_add(self._on_deps_complete, success, and_build, use_container)

        threading.Thread(target=deps_task, daemon=True).start()

    def _on_deps_complete(self, success, and_build=False, use_container=False):
        self._set_action_buttons_sensitive(True, include_aux=True)
        if success:
            self.deps_banner.set_revealed(False)
            self.log("[✓] Build dependencies setup complete.")
            if and_build:
                self._confirm_and_start_build()
        else:
            self.log("[!] Dependency installation was cancelled or encountered an error.")
        return False

    def on_start_build_clicked(self, button):
        use_container = (self.build_mode_row.get_selected() == 1)
        missing = self.kernel_manager.check_build_dependencies(use_container=use_container)
        if missing:
            dialog = Adw.MessageDialog(
                transient_for=self,
                heading="Dependencies Required",
                body=(
                    f"Missing required compilation packages:\n"
                    f"{', '.join(missing)}\n\n"
                    f"Install them now via pkexec apt-get?"
                )
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("install", "Install Dependencies")
            dialog.set_response_appearance("install", Adw.ResponseAppearance.SUGGESTED)
            dialog.connect("response", lambda _d, r: self._start_deps_install(use_container=use_container, force_rebuild=False, and_build=True) if r == "install" else None)
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
        opt_str = "Native (-march=native)" if cpu_arch == 'native' else ("Generic x86-64-v3" if cpu_arch == 'x86-64-v3' else "Generic x86-64")
        hw_str = "Universal Drivers (Container)" if use_container else ("Current Hardware (localmodconfig)" if use_localmodconfig else "Universal Drivers")

        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Start Kernel Build",
            body=(
                f"Kernel Version: {ver}\n"
                f"Build Environment: {mode_str}\n"
                f"Drivers: {hw_str}\n"
                f"CPU Architecture: {opt_str}\n"
                f"Scheduler: {cpu_scheduler.upper()} | Tick Rate: {tick_rate} Hz | Threads: {threads}\n\n"
                f"Output Directory:\n{output_dir}\n\n"
                f"Auto-Install: {'Yes' if auto_install else 'No'} | Secure Boot MOK Sign: {'Yes' if sign_after_install else 'No'}"
            )
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("proceed", "Start Build")
        dialog.set_response_appearance("proceed", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_dlg, response):
            if response == "proceed":
                def proceed(mok_password=""):
                    try:
                        os.makedirs(output_dir, exist_ok=True)
                    except Exception as e:
                        self.log(f"[!] Note on output directory: {e}")
                    self._start_kernel_build(
                        ver=ver, tag=tag, dl_url=dl_url,
                        use_container=use_container, use_localmodconfig=use_localmodconfig,
                        strip_debug_symbols=strip_debug_symbols, auto_install=auto_install,
                        sign_after_install=sign_after_install, cpu_arch=cpu_arch,
                        compiler_lto=compiler_lto, cpu_scheduler=cpu_scheduler,
                        tick_rate=tick_rate, threads=threads, mok_password=mok_password
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
        self, ver, tag, dl_url, use_container, use_localmodconfig,
        strip_debug_symbols, auto_install, sign_after_install, cpu_arch,
        compiler_lto, cpu_scheduler, tick_rate, threads, mok_password=""
    ):
        total_stages = 5 if auto_install else 4
        self._set_action_buttons_sensitive(False, include_aux=True)
        target_output_dir = self.get_current_output_dir()

        self.log("\n=======================================================")
        self.log("[*] Starting CachyOS Kernel Automated Build Pipeline...")
        self.log(f"    • Target Version: {ver} ({tag})")
        self.log(f"    • Build Mode: {'Container' if use_container else 'Native Host'}")
        self.log(f"    • CPU Architecture: {cpu_arch} | Scheduler: {cpu_scheduler} | -j{threads}")
        self.log(f"    • Output Directory: {target_output_dir}")
        self.log("=======================================================\n")

        self.update_stage_progress(1, total_stages, "Checking dependencies...")

        def build_task():
            try:
                GLib.idle_add(self.update_stage_progress, 1, total_stages, "Verifying build dependencies...")
                missing = self.kernel_manager.check_build_dependencies(use_container=use_container)
                if missing:
                    raise Exception(f"Missing required build dependencies: {', '.join(missing)}")

                GLib.idle_add(self.update_stage_progress, 2, total_stages, f"Downloading & patching CachyOS source ({ver})...")
                kernel_dir = self.kernel_manager.download_kernel(
                    version=ver, tag=tag, download_url=dl_url, progress_callback=self.log
                )

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
        self._set_action_buttons_sensitive(True, include_aux=True)
        self.refresh_secure_boot_ui()
        self._populate_installed_kernels_list(self.kernel_manager.get_installed_kernels())

        if success:
            self.stage_progress_bar.set_fraction(1.0)
            if auto_install:
                self.stage_status_label.set_label("Build, installation, and Secure Boot signing completed.")
                if sign_after_install:
                    if mok_status == "ENROLLMENT_QUEUED":
                        self.show_mok_enrolled_reboot_dialog()
                    elif mok_status == "ALREADY_ENROLLED":
                        self.show_mok_already_enrolled_dialog()
            else:
                self.stage_status_label.set_label("Build finished. Click 'Install Existing .deb' to install.")
        else:
            self.stage_status_label.set_label("Build failed. Switching to Kernels & Logs for details.")
            self.view_stack.set_visible_child_name("kernels")
        return False

    def on_apply_clicked(self, button):
        sign_after_install = self.sign_postinst_check.get_active()
        mode_desc = "Installation + UEFI Secure Boot Signing" if sign_after_install else "Installation"
        target_dir = self.get_current_output_dir()

        def start_install(mok_password=""):
            self.log(f"\n[*] Initiating package {mode_desc.lower()} via pkexec...")
            self._set_action_buttons_sensitive(False)

            def install_task():
                success, mok_status = self.kernel_manager.install_and_sign_kernel_debs(
                    deb_dir=target_dir, sign_enabled=sign_after_install,
                    mok_password=mok_password, log_callback=self.log
                )
                GLib.idle_add(self._on_install_complete, success, mok_status, sign_after_install)

            threading.Thread(target=install_task, daemon=True).start()

        if sign_after_install:
            self.request_mok_password_dialog(start_install)
        else:
            start_install("")

    def _on_install_complete(self, success, mok_status, sign_after_install=True):
        self._set_action_buttons_sensitive(True)
        self.refresh_secure_boot_ui()
        self._populate_installed_kernels_list(self.kernel_manager.get_installed_kernels())

        if success:
            self.log("\n[✓] CachyOS Kernel installed successfully. Please reboot to run the new kernel.")
            if sign_after_install:
                if mok_status == "ENROLLMENT_QUEUED":
                    self.show_mok_enrolled_reboot_dialog()
                elif mok_status == "ALREADY_ENROLLED":
                    self.show_mok_already_enrolled_dialog()
                elif mok_status == "NEEDS_ENROLLMENT":
                    self.log("[!] Notice: MOK key needs enrollment into UEFI NVRAM.")
        else:
            self.log(f"\n[!] Kernel installation failed: {mok_status}\n")
        return False

    def on_sign_installed_kernel_clicked(self, button):
        target_dir = self.get_current_output_dir()

        def start_signing(mok_password=""):
            current_kernel = self.kernel_manager.get_current_kernel_version()
            self._set_action_buttons_sensitive(False)
            self.log(f"\n[*] Starting Post-Installation Kernel & Module Signing for {current_kernel}...")

            def sign_task():
                try:
                    success, mok_status = self.kernel_manager.sign_existing_installed_kernel(
                        kernel_version="auto", mok_password=mok_password,
                        output_dir=target_dir, log_callback=self.log
                    )
                    GLib.idle_add(self._on_sign_installed_complete, success, mok_status)
                except Exception as e:
                    self.log(f"\n[!] Secure Boot signing failed: {e}\n")
                    GLib.idle_add(self._on_sign_installed_complete, False, str(e))

            threading.Thread(target=sign_task, daemon=True).start()

        self.request_mok_password_dialog(start_signing)

    def _on_sign_installed_complete(self, success, mok_status):
        self._set_action_buttons_sensitive(True)
        self.refresh_secure_boot_ui()

        if success:
            self.log(f"[✓] Post-installation signing completed (Status: {mok_status}).")
            if mok_status == "ENROLLMENT_QUEUED":
                self.show_mok_enrolled_reboot_dialog()
            elif mok_status == "ALREADY_ENROLLED":
                self.show_mok_already_enrolled_dialog()
            elif mok_status == "NEEDS_ENROLLMENT":
                self.log("[!] Notice: Kernel signed, but MOK key needs enrollment into UEFI NVRAM.")
        else:
            self.log(f"[!] Secure Boot signing failed: {mok_status}")
        return False

    def _present_mok_password_dialog(
        self, heading, body, action_id, action_label, appearance,
        pwd_prompt, confirm_prompt, on_confirmed, cancel_msg
    ):
        dialog = Adw.MessageDialog(transient_for=self, heading=heading, body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response(action_id, action_label)
        dialog.set_response_appearance(action_id, appearance)
        dialog.set_response_enabled(action_id, False)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        pwd_label = Gtk.Label(label=pwd_prompt, halign=Gtk.Align.START)
        pwd_label.add_css_class("caption")
        pwd_entry = Gtk.PasswordEntry(show_peek_icon=True)

        confirm_label = Gtk.Label(label=confirm_prompt, halign=Gtk.Align.START)
        confirm_label.add_css_class("caption")
        confirm_entry = Gtk.PasswordEntry(show_peek_icon=True)

        hint_label = Gtk.Label(label="Password must be between 8 and 16 characters.", halign=Gtk.Align.START)
        hint_label.add_css_class("dim-label")
        hint_label.add_css_class("caption")

        for child in (pwd_label, pwd_entry, confirm_label, confirm_entry, hint_label):
            box.append(child)

        def validate_passwords(*_):
            p1 = pwd_entry.get_text()
            p2 = confirm_entry.get_text()
            if len(p1) < 8 or len(p1) > 16:
                hint_label.set_label("Password must be between 8 and 16 characters.")
                dialog.set_response_enabled(action_id, False)
            elif p1 != p2:
                hint_label.set_label("Passwords do not match.")
                dialog.set_response_enabled(action_id, False)
            else:
                hint_label.set_label("Password valid and confirmed.")
                dialog.set_response_enabled(action_id, True)

        pwd_entry.connect("notify::text", validate_passwords)
        confirm_entry.connect("notify::text", validate_passwords)
        dialog.set_extra_child(box)

        def on_dialog_response(_dlg, response):
            if response == action_id:
                on_confirmed(pwd_entry.get_text())
            else:
                self.log(cancel_msg)

        dialog.connect("response", on_dialog_response)
        dialog.present()

    def request_mok_password_dialog(self, on_confirmed_callback):
        target_dir = self.get_current_output_dir()
        status = self.kernel_manager.get_mok_status(target_dir)
        if status.get("key_enrolled", False):
            self.log("[✓] MOK key is already enrolled in UEFI NVRAM. Skipping password prompt.")
            on_confirmed_callback("")
            return

        self._present_mok_password_dialog(
            heading="UEFI Secure Boot & MOK Setup",
            body=(
                "Your kernel and out-of-tree drivers will be signed with your local Machine Owner Key (MOK).\n\n"
                f"Certificates directory:\n{target_dir}\n\n"
                "Choose a one-time temporary password (8 to 16 characters) to authorize "
                "this key in MokManager during your next reboot:"
            ),
            action_id="enroll",
            action_label="Sign & Enroll Key",
            appearance=Adw.ResponseAppearance.SUGGESTED,
            pwd_prompt="One-Time MOK Password (8–16 characters):",
            confirm_prompt="Confirm Password:",
            on_confirmed=on_confirmed_callback,
            cancel_msg="[i] Operation cancelled by user."
        )

    def on_reset_mok_clicked(self, button=None):
        target_dir = self.get_current_output_dir()
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception:
            pass

        self._present_mok_password_dialog(
            heading="Reset & Recreate MOK Keys",
            body=(
                f"This cancels any previous UEFI MOK enrollment, deletes old certificates in:\n"
                f"{target_dir}\n\n"
                "It will generate a new RSA-2048 MOK keypair, re-sign the installed kernel in /boot, "
                "and queue the new key for enrollment on next reboot."
            ),
            action_id="reset",
            action_label="Reset & Recreate Keys",
            appearance=Adw.ResponseAppearance.DESTRUCTIVE,
            pwd_prompt="New MOK Password (8–16 characters):",
            confirm_prompt="Confirm New Password:",
            on_confirmed=lambda pwd: self._start_reset_and_recreate_mok(target_dir, pwd),
            cancel_msg="[i] MOK reset cancelled by user."
        )

    def _start_reset_and_recreate_mok(self, target_dir, password):
        self._set_action_buttons_sensitive(False)
        self.log(f"\n[*] Resetting & Recreating MOK Keys in {target_dir}...")

        def worker():
            try:
                success, mok_status = self.kernel_manager.reset_and_recreate_mok_keys(
                    output_dir=target_dir, mok_password=password, log_callback=self.log
                )
                GLib.idle_add(self._on_reset_mok_complete, success, mok_status, target_dir)
            except Exception as e:
                self.log(f"\n[!] Reset and recreation failed: {e}\n")
                GLib.idle_add(self._on_reset_mok_complete, False, str(e), target_dir)

        threading.Thread(target=worker, daemon=True).start()

    def _on_reset_mok_complete(self, success, mok_status, target_dir):
        self._set_action_buttons_sensitive(True)
        self.refresh_secure_boot_ui()

        if success:
            self.log(f"[✓] MOK keypair regenerated in {target_dir} and queued for UEFI enrollment.")
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
                "  5. Select 'Reboot'"
            )
        )
        dialog.add_response("ok", "Got It")
        dialog.present()

    def show_mok_already_enrolled_dialog(self):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Kernel Signed & Ready",
            body=(
                "The kernel and DKMS modules in /boot are cryptographically signed with your active MOK key.\n\n"
                "Your key is already enrolled in UEFI NVRAM, so you can reboot immediately."
            )
        )
        dialog.add_response("ok", "OK")
        dialog.present()

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
            display.get_clipboard().set(copy_text)
            self.log("[✓] Build log copied to clipboard.")

    def on_clear_log_clicked(self, button):
        self.terminal_view.get_buffer().set_text("")
        self.log("[i] Log buffer cleared.")

    def on_rollback_clicked(self, button):
        installed_kernels = self.kernel_manager.get_installed_kernels()
        if not installed_kernels:
            self.log("[!] No installed kernel packages found.")
            return

        current_kernel = self.kernel_manager.get_current_kernel_version()
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Rollback Kernel",
            body="Select an installed kernel package to remove.\n\nCaution: Do not remove the kernel you are currently running."
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

        def on_response(_dlg, response):
            if response == "remove":
                selected_item = dropdown.get_selected_item()
                if selected_item:
                    package_name = selected_item.get_string()
                    self.log(f"[*] Requesting root authentication to purge {package_name}...")
                    def remove_task():
                        success = self.kernel_manager.remove_kernel(package_name, progress_callback=self.log)
                        if success:
                            updated = self.kernel_manager.get_installed_kernels()
                            GLib.idle_add(self._populate_installed_kernels_list, updated)
                            GLib.idle_add(self.log, f"[✓] Removed {package_name}.")
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
        '--reset-mok'
    }
    if '--version' in sys.argv[1:]:
        print(f"Kernel Updater for CachyOS on Debian v{APP_VERSION}")
        sys.exit(0)
    if any(arg.split('=')[0] in cli_flags for arg in sys.argv[1:]):
        import runpy
        km_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kernel_manager.py')
        runpy.run_path(km_path, run_name='__main__')
        sys.exit(0)
    app = KernelUpdaterApp()
    sys.exit(app.run(sys.argv))
