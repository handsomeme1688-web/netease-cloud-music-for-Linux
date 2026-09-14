#!/usr/bin/python3
"""An independent GTK/WebKitGTK window for NetEase Cloud Music."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

APP_ID = "io.github.neteasecloudmusic.WebPlayer"
APP_NAME = "网易云音乐"
VERSION = "1.0.2"
HOME_URL = "https://music.163.com/st/webplayer"
STORAGE_NAME = "netease-cloud-music"

if sys.version_info < (3, 8):
    print("需要 Python 3.8 或更新版本。", file=sys.stderr)
    sys.exit(1)

# Choose the display backend before GTK is imported. The parent process may
# force GDK_BACKEND=x11 even on a Wayland desktop; that adds an XWayland path.
# This override is local to this application, with X11 as an automatic fallback.
display_backend = os.environ.get("NETEASE_MUSIC_BACKEND", "")
if display_backend in ("wayland", "x11"):
    os.environ["GDK_BACKEND"] = display_backend
elif os.environ.get("XDG_SESSION_TYPE") == "wayland" and os.environ.get("WAYLAND_DISPLAY"):
    os.environ["GDK_BACKEND"] = "wayland,x11"

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    WEBKIT_API = None
    for api in ("4.1", "4.0"):
        try:
            gi.require_version("WebKit2", api)
        except ValueError:
            continue
        WEBKIT_API = api
        break
    if WEBKIT_API is None:
        raise ValueError("未安装 WebKit2 4.1 或 4.0 的运行组件")
    # Choose one ABI before importing it; Soup 2 and Soup 3 cannot share a process.
    from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2
except (ImportError, ValueError) as exc:
    print("缺少运行组件。请通过 sudo apt install ./软件包.deb 安装完整依赖，\n"
          "或在源码目录运行 bash install-dependencies.sh。\n"
          "WebKit 组件优先使用 gir1.2-webkit2-4.1；较旧软件源可使用 gir1.2-webkit2-4.0。\n"
          f"详细信息：{exc}", file=sys.stderr)
    sys.exit(1)

if (Gtk.MAJOR_VERSION, Gtk.MINOR_VERSION) < (3, 24):
    print("需要 GTK 3.24 或更新的 GTK 3 版本。", file=sys.stderr)
    sys.exit(1)
if (WebKit2.get_major_version(), WebKit2.get_minor_version()) < (2, 28):
    print("需要 WebKitGTK 2.28 或更新版本。", file=sys.stderr)
    sys.exit(1)


def private_directory(base, fallback):
    candidate = Path(os.environ.get(base) or Path.home() / fallback)
    if not candidate.is_absolute():
        candidate = Path.home() / fallback
    path = candidate / STORAGE_NAME
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def network_settings_path():
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    if not base.is_absolute():
        base = Path.home() / ".config"
    return base / STORAGE_NAME / "network.json"


def read_proxy_mode(path=None):
    path = network_settings_path() if path is None else Path(path)
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(settings, dict) and settings.get("proxy_mode") in ("system", "direct"):
            return settings["proxy_mode"]
    except (OSError, ValueError):
        pass
    return "system"


def save_proxy_mode(mode, path=None):
    if mode not in ("system", "direct"):
        raise ValueError("未知的网络连接方式")
    path = network_settings_path() if path is None else Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".network-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({"proxy_mode": mode}, stream)
            stream.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def apply_proxy_mode(manager, context, mode):
    if mode not in ("system", "direct"):
        raise ValueError("未知的网络连接方式")
    proxy_mode = WebKit2.NetworkProxyMode.DEFAULT
    settings = None
    if mode == "direct":
        # An explicit empty proxy configuration also replaces an active route.
        # NO_PROXY can leave a running session on its previous system proxy.
        proxy_mode = WebKit2.NetworkProxyMode.CUSTOM
        settings = WebKit2.NetworkProxySettings.new(None, ["*"])
    if hasattr(manager, "set_network_proxy_settings"):
        manager.set_network_proxy_settings(proxy_mode, settings)
    else:
        # WebKitGTK 2.28/2.30 expose this setting on the context instead.
        context.set_network_proxy_settings(proxy_mode, settings)


def supported_uri(uri):
    """Remote content never launches a browser, shell or local protocol handler."""
    try:
        parsed = urlsplit(uri)
        return parsed.scheme in ("https", "http") and bool(parsed.hostname)
    except ValueError:
        return False


def is_player_uri(uri):
    try:
        parsed = urlsplit(uri or "")
        return (parsed.scheme == "https" and parsed.hostname == "music.163.com"
                and parsed.path.rstrip("/") == "/st/webplayer")
    except ValueError:
        return False


def page_response_error(response):
    status = response.get_status_code()
    mime = response.get_mime_type() or "未知"
    headers = response.get_http_headers()
    declared_type = headers.get_one("Content-Type") if headers else None
    disposition = headers.get_one("Content-Disposition") if headers else None
    return ("播放器首页没有返回可显示的网页。\n"
            f"HTTP 状态：{status}；WebKit 内容类型：{mime}\n"
            f"Content-Type：{declared_type or '未提供'}\n"
            f"Content-Disposition：{disposition or '未提供'}\n"
            "请稍后重试；若持续出现，请提供以上响应信息。")


class MusicApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.main_window = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        GLib.set_application_name(APP_NAME)
        GLib.set_prgname(APP_ID)
        self.data_dir = private_directory("XDG_DATA_HOME", ".local/share")
        self.cache_dir = private_directory("XDG_CACHE_HOME", ".cache")
        self.config_dir = private_directory("XDG_CONFIG_HOME", ".config")
        self.state_path = self.config_dir / "window.json"
        self.state = {}
        try:
            saved = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                self.state = saved
        except (OSError, ValueError):
            pass
        self.manager = WebKit2.WebsiteDataManager(
            base_data_directory=str(self.data_dir / "webkit"),
            base_cache_directory=str(self.cache_dir / "webkit"))
        self.manager.get_cookie_manager().set_persistent_storage(
            str(self.data_dir / "cookies.sqlite"), WebKit2.CookiePersistentStorage.SQLITE)
        self.context = WebKit2.WebContext.new_with_website_data_manager(self.manager)
        self.context.set_sandbox_enabled(True)
        self.proxy_mode = read_proxy_mode()
        apply_proxy_mode(self.manager, self.context, self.proxy_mode)
        self.context.connect("download-started", self.on_download)
        icon = Path(__file__).resolve().parent / "assets" / "netease-cloud-music.svg"
        Gtk.IconTheme.get_default().append_search_path(str(icon.parent))
        if icon.exists():
            try:
                Gtk.Window.set_default_icon_from_file(str(icon))
            except GLib.Error as exc:
                print(f"无法读取应用图标，请确认已安装 librsvg2-common：{exc.message}", file=sys.stderr)
        self.add_action_callback("quit", lambda *_: self.quit())
        self.set_accels_for_action("app.quit", ["<Primary>q"])

    def add_action_callback(self, name, callback):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)

    def do_activate(self):
        if self.main_window is None:
            self.main_window = MusicWindow(self)
            self.main_window.connect("destroy", self.on_main_destroy)
            self.main_window.webview.load_uri(HOME_URL)
        self.main_window.present()

    def do_shutdown(self):
        if self.main_window:
            self.save_state(self.main_window)
        Gtk.Application.do_shutdown(self)

    def on_main_destroy(self, *_):
        self.main_window = None
        for window in list(self.get_windows()):
            window.destroy()

    def on_download(self, _context, download):
        download.connect("decide-destination", self.choose_download)
        download.connect("failed", self.download_failed)

    def choose_download(self, download, suggested_name):
        parent = self.get_active_window()
        # The player entry page is a document, never an installation download.
        # Keep an unexpected response visible instead of saving a 'webplayer' file.
        response = download.get_response()
        if response and is_player_uri(response.get_uri()):
            download.cancel()
            view = download.get_web_view()
            window = view.get_toplevel() if view else self.main_window
            if isinstance(window, MusicWindow):
                window.show_error(page_response_error(response))
            return True
        chooser = Gtk.FileChooserDialog(title="保存文件", transient_for=parent,
                                       action=Gtk.FileChooserAction.SAVE)
        chooser.add_buttons("取消", Gtk.ResponseType.CANCEL, "保存", Gtk.ResponseType.ACCEPT)
        chooser.set_do_overwrite_confirmation(True)
        chooser.set_current_name(Path(suggested_name).name or "download")
        folder = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        if folder and Path(folder).is_dir():
            chooser.set_current_folder(folder)
        if chooser.run() == Gtk.ResponseType.ACCEPT:
            download.set_allow_overwrite(True)
            download.set_destination(Path(chooser.get_filename()).as_uri())
        else:
            download.cancel()
        chooser.destroy()
        return True

    def download_failed(self, _download, error):
        if error.matches(WebKit2.download_error_quark(), WebKit2.DownloadError.CANCELLED_BY_USER):
            return
        window = self.get_active_window()
        if window:
            window.message("下载失败", error.message)

    def save_state(self, window):
        width, height = window.normal_size
        self.state = {"width": width, "height": height,
                      "maximized": window.is_maximized(), "zoom": window.webview.get_zoom_level()}
        try:
            temp = self.state_path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.state), encoding="utf-8")
            temp.chmod(0o600)
            temp.replace(self.state_path)
        except OSError:
            pass


class MusicWindow(Gtk.ApplicationWindow):
    def __init__(self, app, related_view=None):
        super().__init__(application=app, title=APP_NAME)
        self.app = app
        self.is_popup = related_view is not None
        self.set_role(APP_ID)
        self.set_wmclass(APP_ID, APP_ID)
        self.set_size_request(640, 480)
        state = {} if self.is_popup else app.state
        def number(key, default, low, high):
            value = state.get(key, default)
            return max(low, min(high, value)) if isinstance(value, (int, float)) else default
        self.normal_size = (int(number("width", 1280, 640, 3840)),
                            int(number("height", 840, 480, 2160)))
        self.set_default_size(*self.normal_size)
        if state.get("maximized"):
            self.maximize()

        self.set_decorated(False)

        if related_view:
            self.webview = WebKit2.WebView.new_with_related_view(related_view)
        else:
            self.webview = WebKit2.WebView.new_with_context(app.context)
        settings = WebKit2.Settings()
        # The site only admits Firefox >=91 / Chrome >=84 via a UA regex.
        # Use its Firefox compatibility path; the actual engine stays WebKitGTK.
        settings.set_user_agent("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
                                "Gecko/20100101 Firefox/128.0")
        settings.set_enable_javascript(True)
        settings.set_enable_mediasource(True)
        settings.set_enable_webaudio(True)
        settings.set_media_playback_requires_user_gesture(True)
        settings.set_javascript_can_open_windows_automatically(False)
        # NetEase calls this API unconditionally during React startup. WebKitGTK
        # 2.52 includes it as a feature that is disabled by default.
        if hasattr(WebKit2.Settings, "get_all_features"):
            features = WebKit2.Settings.get_all_features()
            for index in range(features.get_length()):
                feature = features.get(index)
                if feature.get_identifier() == "RequestIdleCallback":
                    settings.set_feature_enabled(feature, True)
                    break
        self.webview.set_settings(settings)
        # Older WebKitGTK releases need the standard timer fallback instead.
        # It is scoped to the music site and never replaces a native API.
        if not related_view:
            self.webview.get_user_content_manager().add_script(WebKit2.UserScript.new(
                """if (!window.requestIdleCallback) {
                    window.requestIdleCallback = function(callback) {
                        return setTimeout(function() {
                            var start = performance.now();
                            callback({didTimeout: false, timeRemaining: function() {
                                return Math.max(0, 50 - (performance.now() - start));
                            }});
                        }, 1);
                    };
                    window.cancelIdleCallback = function(id) { clearTimeout(id); };
                }""",
                WebKit2.UserContentInjectedFrames.TOP_FRAME,
                WebKit2.UserScriptInjectionTime.START, ["https://music.163.com/*"], None))
        self.webview.set_zoom_level(number("zoom", 1.0, 0.5, 2.0))
        self.webview.connect("load-changed", self.load_changed)
        self.webview.connect("load-failed", self.load_failed)
        self.webview.connect("load-failed-with-tls-errors", self.tls_failed)
        self.webview.connect("notify::title", self.title_changed)
        self.webview.connect("decide-policy", self.decide_policy)
        self.webview.connect("create", self.create_popup)
        self.webview.connect("close", lambda *_: self.destroy())
        self.webview.connect("web-process-terminated", self.process_terminated)
        self.webview.connect("permission-request", self.permission_request)
        self.webview.connect("enter-fullscreen", self.enter_fullscreen)
        self.webview.connect("leave-fullscreen", self.leave_fullscreen)

        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.progress = Gtk.ProgressBar()
        self.progress.set_no_show_all(True)
        self.progress.set_valign(Gtk.Align.START)
        self.webview.connect("notify::estimated-load-progress", self.progress_changed)
        self.stack = Gtk.Stack()
        self.overlay.add(self.stack)
        self.stack.add_named(self.webview, "web")
        self.overlay.add_overlay(self.progress)
        self.overlay.set_overlay_pass_through(self.progress, True)
        error_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                            halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, margin=32)
        error_box.pack_start(Gtk.Image.new_from_icon_name("network-error-symbolic", Gtk.IconSize.DIALOG), False, False, 0)
        self.error_label = Gtk.Label(label="页面暂时无法打开", wrap=True, justify=Gtk.Justification.CENTER)
        self.error_label.set_max_width_chars(60)
        error_box.pack_start(self.error_label, False, False, 0)
        retry = Gtk.Button(label="重新加载")
        retry.connect("clicked", lambda *_: self.webview.load_uri(HOME_URL))
        error_box.pack_start(retry, False, False, 0)
        self.network_button = Gtk.Button()
        self.update_network_button()
        self.network_button.connect("clicked", self.switch_proxy_mode)
        error_box.pack_start(self.network_button, False, False, 0)
        self.stack.add_named(error_box, "error")
        self.create_window_controls()
        self.header_style = None
        self.webview.connect("notify::zoom-level", self.sync_page_controls)
        self.sync_page_controls()
        self.connect("key-press-event", self.key_press)
        self.connect("configure-event", self.configure)
        self.connect("delete-event", self.before_close)
        self.connect("window-state-event", self.window_state_changed)
        self.show_all()

    def update_network_button(self):
        self.network_button.set_label("使用直连并记住" if self.app.proxy_mode == "system"
                                      else "使用系统代理并记住")
        self.network_button.set_tooltip_text("只更改本应用的连接方式，下次启动继续使用。")

    def switch_proxy_mode(self, *_):
        mode = "direct" if self.app.proxy_mode == "system" else "system"
        try:
            save_proxy_mode(mode)
        except OSError as exc:
            self.message("无法保存网络设置", str(exc))
            return
        self.webview.stop_loading()
        apply_proxy_mode(self.app.manager, self.app.context, mode)
        self.app.proxy_mode = mode
        for window in self.app.get_windows():
            if isinstance(window, MusicWindow):
                window.update_network_button()
        self.webview.load_uri(HOME_URL)

    def create_window_controls(self):
        # Native controls float over the page; there is no title bar or toolbar,
        # and webpage scripts do not receive a bridge into window operations.
        self.window_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.window_controls.set_halign(Gtk.Align.END)
        self.window_controls.set_valign(Gtk.Align.START)
        self.window_controls.set_margin_end(16)
        self.window_controls.set_margin_top(22)
        css = Gtk.CssProvider()
        css.load_from_data(b"""
            button.music-window-control {
                min-width: 26px; min-height: 26px; padding: 0; margin: 0;
                border: 0; border-radius: 5px; box-shadow: none;
                background-image: none; background-color: transparent;
                color: #7b8090; outline-offset: 2px;
            }
            button.music-window-control:hover { background-color: rgba(123,128,144,0.08); }
            button.music-window-control:active { background-color: rgba(123,128,144,0.14); }
            button.music-window-close:hover { background-color: rgba(255,56,87,0.07); color: #ff3857; }
        """)
        self.control_buttons = {}
        for name, icon, tip, callback in [
            ("minimize", "netease-window-minimize-symbolic", "最小化", lambda *_: self.iconify()),
            ("maximize", "netease-window-maximize-symbolic", "最大化", self.toggle_maximize),
            ("close", "netease-window-close-symbolic", "关闭", lambda *_: self.close()),
        ]:
            button = Gtk.Button()
            image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)
            image.set_pixel_size(16)
            button.set_image(image)
            button.set_tooltip_text(tip)
            button.get_accessible().set_name(tip)
            context = button.get_style_context()
            context.add_class("music-window-control")
            if name == "close":
                context.add_class("music-window-close")
            context.add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            button.connect("clicked", callback)
            self.window_controls.pack_start(button, False, False, 0)
            self.control_buttons[name] = button
        self.overlay.add_overlay(self.window_controls)

    def sync_page_controls(self, *_):
        # Reserve space only in NetEase's real navigation row, not in the page
        # body. Compensate for page zoom because native buttons keep their size.
        manager = self.webview.get_user_content_manager()
        if self.header_style:
            if hasattr(manager, "remove_style_sheet"):
                manager.remove_style_sheet(self.header_style)
            else:
                # WebKitGTK 2.28 only exposes the bulk operation. This manager's
                # styles are owned by the application; user scripts are retained.
                manager.remove_all_style_sheets()
        zoom = self.webview.get_zoom_level()
        self.header_style = WebKit2.UserStyleSheet.new(
            "#page_pc_main_nav { padding-right: %.2fpx !important; }" % (144 / zoom),
            WebKit2.UserContentInjectedFrames.TOP_FRAME, WebKit2.UserStyleLevel.USER,
            ["https://music.163.com/st/webplayer*"], None)
        manager.add_style_sheet(self.header_style)
        self.position_window_controls()

    def position_window_controls(self):
        script = (
            "(() => { const nav = document.getElementById('page_pc_main_nav'); "
            "if (!nav) return 35; const r = nav.getBoundingClientRect(); "
            "return r.top + r.height / 2; })()")
        # Ubuntu 22.04 can provide WebKitGTK 2.36, before the 2.40 API.
        # Both paths run the same layout query and keep the native controls.
        if hasattr(self.webview, "evaluate_javascript"):
            self.webview.evaluate_javascript(
                script, -1, None, None, None, self.control_position_ready, False)
        else:
            self.webview.run_javascript(script, None, self.control_position_ready, True)

    def control_position_ready(self, view, task, legacy_api):
        try:
            if legacy_api:
                value = view.run_javascript_finish(task).get_js_value()
            else:
                value = view.evaluate_javascript_finish(task)
            center = value.to_double()
            if self.get_window() and 0 < center < 160:
                margin = round(center * view.get_zoom_level() - 13)
                self.window_controls.set_margin_top(max(6, min(120, margin)))
        except GLib.Error:
            pass

    def toggle_maximize(self, *_):
        if self.is_maximized():
            self.unmaximize()
        else:
            self.maximize()

    def window_state_changed(self, _window, event):
        # Focus/minimize events must not rebuild the image: Gtk.Image clears its
        # old content and queues a resize even when the icon name is unchanged.
        if event.changed_mask & Gdk.WindowState.MAXIMIZED:
            maximized = bool(event.new_window_state & Gdk.WindowState.MAXIMIZED)
            button = self.control_buttons["maximize"]
            button.get_image().set_from_icon_name(
                "netease-window-restore-symbolic" if maximized else "netease-window-maximize-symbolic", Gtk.IconSize.MENU)
            label = "还原" if maximized else "最大化"
            button.set_tooltip_text(label)
            button.get_accessible().set_name(label)
        if event.changed_mask & Gdk.WindowState.FULLSCREEN:
            self.window_controls.set_visible(not event.new_window_state & Gdk.WindowState.FULLSCREEN)
        return False

    def configure(self, _window, event):
        if not self.is_maximized() and not self.get_window().get_state() & Gdk.WindowState.FULLSCREEN:
            self.normal_size = (event.width, event.height)
        return False

    def before_close(self, *_):
        if not self.is_popup:
            self.app.save_state(self)
        return False

    def zoom(self, delta):
        self.webview.set_zoom_level(max(0.5, min(2.0, self.webview.get_zoom_level() + delta)))

    def key_press(self, _window, event):
        key = Gdk.keyval_name(event.keyval)
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        alt = event.state & Gdk.ModifierType.MOD1_MASK
        if key == "F5" or (ctrl and key.lower() == "r"):
            self.webview.reload()
        elif alt and key == "Home":
            self.webview.load_uri(HOME_URL)
        elif ctrl and key in ("plus", "equal", "KP_Add"):
            self.zoom(0.1)
        elif ctrl and key in ("minus", "KP_Subtract"):
            self.zoom(-0.1)
        elif ctrl and key in ("0", "KP_0"):
            self.webview.set_zoom_level(1.0)
        elif alt and key == "Left":
            self.webview.go_back()
        elif alt and key == "Right":
            self.webview.go_forward()
        elif key == "Escape":
            self.leave_fullscreen(self.webview)
            return False
        else:
            return False
        return True

    def load_changed(self, view, event):
        if event == WebKit2.LoadEvent.STARTED:
            self.stack.set_visible_child_name("web")
            self.progress.show()
        elif event == WebKit2.LoadEvent.FINISHED:
            self.progress.hide()
            self.position_window_controls()

    def progress_changed(self, view, _spec):
        self.progress.set_fraction(view.get_estimated_load_progress())

    def title_changed(self, view, _spec):
        title = view.get_title() or APP_NAME
        self.set_title(title)

    def show_error(self, message):
        self.progress.hide()
        self.error_label.set_text(message)
        self.stack.set_visible_child_name("error")

    def load_failed(self, _view, _event, _uri, error):
        if error.matches(WebKit2.network_error_quark(), WebKit2.NetworkError.CANCELLED):
            return False
        if error.matches(WebKit2.policy_error_quark(), WebKit2.PolicyError.FRAME_LOAD_INTERRUPTED_BY_POLICY_CHANGE):
            return False
        self.show_error("页面暂时无法打开，请检查网络后重试。\n" + error.message)
        return True

    def tls_failed(self, *_):
        self.show_error("无法验证网站的安全证书。请检查系统时间和网络后重试。")
        return True

    def process_terminated(self, *_):
        self.show_error("网页进程已停止。点击“重新加载”继续。")

    def decide_policy(self, _view, decision, kind):
        if kind in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION, WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
            action = decision.get_navigation_action()
            uri = action.get_request().get_uri()
            if uri == "about:blank" or supported_uri(uri):
                return False
            decision.ignore()
            if action.is_user_gesture():
                self.message("此链接需要其他客户端", "请继续使用网页中的播放或登录入口。")
            return True
        if kind == WebKit2.PolicyDecisionType.RESPONSE:
            response = decision.get_response()
            if is_player_uri(response.get_uri()):
                if 300 <= response.get_status_code() < 400:
                    return False
                if (response.get_mime_type() in ("text/html", "application/xhtml+xml")
                        and 200 <= response.get_status_code() < 300):
                    # Render the entry document even if a server or proxy adds
                    # Content-Disposition: attachment to an HTML response.
                    decision.use()
                else:
                    decision.ignore()
                    self.show_error(page_response_error(response))
                return True
            if decision.is_mime_type_supported():
                return False
            # WebKitGTK before 2.40 does not expose the main-resource check.
            # Leave its default handling in place instead of guessing from URI.
            if not hasattr(decision, "is_main_frame_main_resource"):
                return False
            if decision.is_main_frame_main_resource():
                decision.download()
                return True
        return False

    def create_popup(self, view, _action):
        popup = MusicWindow(self.app, related_view=view)
        popup.set_transient_for(self)
        return popup.webview

    def permission_request(self, _view, request):
        request.deny()
        return True

    def enter_fullscreen(self, *_):
        self.fullscreen()
        self.window_controls.hide()
        return True

    def leave_fullscreen(self, *_):
        self.unfullscreen()
        self.window_controls.show()
        return True

    def message(self, title, details):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True,
                                   message_type=Gtk.MessageType.INFO,
                                   buttons=Gtk.ButtonsType.CLOSE, text=title)
        dialog.format_secondary_text(details)
        dialog.run()
        dialog.destroy()

    def about(self, *_):
        self.message("网易云音乐 · 独立桌面版 " + VERSION,
                     "使用 GTK 3 与 WebKitGTK 运行网易云音乐网页。\n"
                     "无需安装或启动 Chrome、Chromium 或 Electron。\n"
                     "这是非官方桌面封装，音乐、账号和服务由网易云音乐提供。\n\n"
                     "登录数据保存在本应用的独立目录中。关闭窗口将停止播放。")


def main():
    parser = argparse.ArgumentParser(description="网易云音乐独立 WebKitGTK 桌面应用")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--check", action="store_true", help="检查运行依赖，不打开窗口")
    parser.add_argument("--set-proxy-mode", choices=("system", "direct"),
                        help="保存本应用的网络方式后退出：system 使用系统代理，direct 使用直连")
    args = parser.parse_args()
    if args.set_proxy_mode:
        try:
            save_proxy_mode(args.set_proxy_mode)
        except OSError as exc:
            print(f"无法保存网络设置：{exc}", file=sys.stderr)
            return 1
        label = "直连" if args.set_proxy_mode == "direct" else "系统代理"
        print(f"已保存本应用的网络方式：{label}。请完全退出应用后重新打开。")
        return 0
    if args.check:
        print(f"应用 {VERSION}; Python {sys.version.split()[0]}; "
              f"GTK {Gtk.MAJOR_VERSION}.{Gtk.MINOR_VERSION}.{Gtk.MICRO_VERSION}; "
              f"WebKitGTK {WebKit2.get_major_version()}.{WebKit2.get_minor_version()}.{WebKit2.get_micro_version()} (API {WEBKIT_API})")
        api = "evaluate_javascript" if hasattr(WebKit2.WebView, "evaluate_javascript") else "run_javascript"
        print(f"JavaScript 接口：{api}; 桌面会话：{os.environ.get('XDG_SESSION_TYPE', '未设置')}; "
              f"显示后端：{os.environ.get('GDK_BACKEND', '自动')}")
        print(f"已保存的网络方式：{read_proxy_mode()}")
        return 0
    os.umask(0o077)
    app = MusicApplication()
    try:
        return app.run([sys.argv[0]])
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
