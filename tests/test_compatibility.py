"""API and response-policy regression checks without a display or window."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location(
    "music_app", Path(__file__).resolve().parents[1] / "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class Controls:
    def __init__(self):
        self.margin_top = 22

    def set_margin_top(self, margin):
        self.margin_top = margin


def make_window(view):
    window = SimpleNamespace(
        webview=view, window_controls=Controls(), get_window=lambda: True)
    window.control_position_ready = lambda *args: app.MusicWindow.control_position_ready(
        window, *args)
    return window


def make_response(uri=app.HOME_URL, status=200, mime="text/html", headers=None):
    http_headers = SimpleNamespace(get_one=headers.get) if headers else None
    return SimpleNamespace(
        get_uri=lambda: uri, get_status_code=lambda: status,
        get_mime_type=lambda: mime, get_http_headers=lambda: http_headers)


def make_decision(response, mime_supported=True):
    return SimpleNamespace(
        get_response=lambda: response,
        is_mime_type_supported=lambda: mime_supported,
        use=Mock(), ignore=Mock(), download=Mock())


class LegacyView:
    """Only the API available before WebKitGTK 2.40 is exposed."""

    def __init__(self, center=40, zoom=1.5, error=None):
        self.zoom = zoom
        value = SimpleNamespace(to_double=lambda: center)
        result = SimpleNamespace(get_js_value=lambda: value)
        self.run_javascript_finish = Mock(return_value=result, side_effect=error)

    def run_javascript(self, script, cancellable, callback, user_data):
        callback(self, "legacy-task", user_data)

    def get_zoom_level(self):
        return self.zoom


class ModernView:
    """The modern completion method returns a JavaScript value directly."""

    def __init__(self, center=35, zoom=2, error=None):
        self.zoom = zoom
        value = SimpleNamespace(to_double=lambda: center)
        self.evaluate_javascript_finish = Mock(return_value=value, side_effect=error)

    def evaluate_javascript(self, script, length, world, source, cancellable,
                            callback, user_data):
        callback(self, "modern-task", user_data)

    def get_zoom_level(self):
        return self.zoom


class LegacyStyleManager:
    """Only the bulk CSS removal API exists on older WebKitGTK releases."""

    def __init__(self, styles):
        self.styles = list(styles)
        self.scripts = [object()]

    def remove_all_style_sheets(self):
        self.styles.clear()

    def add_style_sheet(self, style):
        self.styles.append(style)


class ModernStyleManager(LegacyStyleManager):
    def remove_style_sheet(self, style):
        self.styles.remove(style)


class WebKitCompatibilityTests(unittest.TestCase):
    def test_legacy_view_without_evaluate_positions_controls(self):
        view = LegacyView()
        window = make_window(view)
        self.assertFalse(hasattr(view, "evaluate_javascript"))

        app.MusicWindow.position_window_controls(window)

        self.assertEqual(window.window_controls.margin_top, 47)
        view.run_javascript_finish.assert_called_once_with("legacy-task")

    def test_modern_value_positions_controls(self):
        view = ModernView()
        window = make_window(view)

        app.MusicWindow.position_window_controls(window)

        self.assertEqual(window.window_controls.margin_top, 57)
        view.evaluate_javascript_finish.assert_called_once_with("modern-task")

    def test_javascript_failure_preserves_default_position(self):
        for view_type in (LegacyView, ModernView):
            with self.subTest(api=view_type.__name__):
                view = view_type(error=app.GLib.Error("JavaScript execution failed"))
                window = make_window(view)

                app.MusicWindow.position_window_controls(window)

                self.assertEqual(window.window_controls.margin_top, 22)

    def test_old_response_api_leaves_unsupported_mime_to_webkit(self):
        response = make_response(
            uri="https://music.163.com/download/example.pdf", mime="application/pdf")
        decision = make_decision(response, mime_supported=False)

        handled = app.MusicWindow.decide_policy(
            SimpleNamespace(), None, decision, app.WebKit2.PolicyDecisionType.RESPONSE)

        self.assertFalse(handled)
        decision.download.assert_not_called()

    def test_old_style_manager_replaces_css_without_removing_scripts(self):
        previous = object()
        manager = LegacyStyleManager([previous])
        self.assertFalse(hasattr(manager, "remove_style_sheet"))
        scripts = list(manager.scripts)
        updated = object()
        window = SimpleNamespace(
            header_style=previous,
            webview=SimpleNamespace(get_user_content_manager=lambda: manager,
                                    get_zoom_level=lambda: 1.5),
            position_window_controls=Mock())

        with patch.object(app.WebKit2.UserStyleSheet, "new", return_value=updated):
            app.MusicWindow.sync_page_controls(window)

        self.assertEqual(manager.styles, [updated])
        self.assertEqual(manager.scripts, scripts)
        self.assertIs(window.header_style, updated)
        window.position_window_controls.assert_called_once_with()

    def test_modern_style_manager_preserves_other_styles(self):
        previous, other, updated = object(), object(), object()
        manager = ModernStyleManager([previous, other])
        window = SimpleNamespace(
            header_style=previous,
            webview=SimpleNamespace(get_user_content_manager=lambda: manager,
                                    get_zoom_level=lambda: 1),
            position_window_controls=Mock())

        with patch.object(app.WebKit2.UserStyleSheet, "new", return_value=updated):
            app.MusicWindow.sync_page_controls(window)

        self.assertEqual(manager.styles, [other, updated])
        self.assertIs(window.header_style, updated)


class PlayerResponseTests(unittest.TestCase):
    def test_html_player_response_is_explicitly_used(self):
        for mime in ("text/html", "application/xhtml+xml"):
            with self.subTest(mime=mime):
                response = make_response(mime=mime, headers={
                    "Content-Type": mime,
                    "Content-Disposition": 'attachment; filename="webplayer"',
                })
                decision = make_decision(response)
                window = SimpleNamespace(show_error=Mock())

                handled = app.MusicWindow.decide_policy(
                    window, None, decision, app.WebKit2.PolicyDecisionType.RESPONSE)

                self.assertTrue(handled)
                decision.use.assert_called_once_with()
                decision.ignore.assert_not_called()
                decision.download.assert_not_called()
                window.show_error.assert_not_called()

    def test_invalid_player_response_reports_status_and_mime_without_download(self):
        for status, mime in ((200, "application/octet-stream"), (403, "text/html")):
            with self.subTest(status=status, mime=mime):
                decision = make_decision(make_response(status=status, mime=mime, headers={
                    "Content-Type": "text/html; charset=utf-8",
                    "Content-Disposition": 'attachment; filename="webplayer"',
                }))
                window = SimpleNamespace(show_error=Mock())

                handled = app.MusicWindow.decide_policy(
                    window, None, decision, app.WebKit2.PolicyDecisionType.RESPONSE)

                self.assertTrue(handled)
                decision.ignore.assert_called_once_with()
                decision.use.assert_not_called()
                decision.download.assert_not_called()
                window.show_error.assert_called_once()
                message = window.show_error.call_args.args[0]
                self.assertIn(str(status), message)
                self.assertIn(mime, message)
                self.assertIn("text/html; charset=utf-8", message)
                self.assertIn('attachment; filename="webplayer"', message)

    def test_player_redirect_and_cache_responses_keep_default_handling(self):
        for status in (301, 302, 303, 304, 307, 308):
            with self.subTest(status=status):
                decision = make_decision(make_response(status=status, mime=None))
                window = SimpleNamespace(show_error=Mock())

                handled = app.MusicWindow.decide_policy(
                    window, None, decision, app.WebKit2.PolicyDecisionType.RESPONSE)

                self.assertFalse(handled)
                decision.use.assert_not_called()
                decision.ignore.assert_not_called()
                decision.download.assert_not_called()
                window.show_error.assert_not_called()

    def test_non_player_attachment_can_still_download(self):
        response = make_response(
            uri="https://music.163.com/download/example.zip", mime="application/zip")
        decision = make_decision(response, mime_supported=False)
        decision.is_main_frame_main_resource = lambda: True
        window = SimpleNamespace(show_error=Mock())

        handled = app.MusicWindow.decide_policy(
            window, None, decision, app.WebKit2.PolicyDecisionType.RESPONSE)

        self.assertTrue(handled)
        decision.download.assert_called_once_with()
        decision.use.assert_not_called()
        decision.ignore.assert_not_called()
        window.show_error.assert_not_called()

    def test_player_download_is_cancelled_before_creating_file_chooser(self):
        response = make_response(status=200, mime="application/octet-stream")
        for has_view in (True, False):
            with self.subTest(has_view=has_view):
                window = Mock(spec=app.MusicWindow)
                active_window = Mock(spec=app.MusicWindow)
                view = SimpleNamespace(get_toplevel=lambda: window) if has_view else None
                application = SimpleNamespace(
                    get_active_window=lambda: active_window,
                    main_window=window, download_failed=Mock())
                application.choose_download = lambda *args: app.MusicApplication.choose_download(
                    application, *args)
                handlers = {}
                download = SimpleNamespace(
                    get_response=lambda: response, get_web_view=lambda: view,
                    cancel=Mock(), connect=lambda signal, callback: handlers.__setitem__(
                        signal, callback))

                app.MusicApplication.on_download(application, None, download)
                with patch.object(app.Gtk, "FileChooserDialog") as chooser:
                    handled = handlers["decide-destination"](download, "webplayer")

                self.assertTrue(handled)
                download.cancel.assert_called_once_with()
                chooser.assert_not_called()
                window.show_error.assert_called_once()
                active_window.show_error.assert_not_called()
                self.assertIn("application/octet-stream", window.show_error.call_args.args[0])

    def test_mime_policy_failure_is_visible(self):
        window = SimpleNamespace(show_error=Mock())
        error = app.GLib.Error.new_literal(
            app.WebKit2.policy_error_quark(), "Cannot show MIME type",
            app.WebKit2.PolicyError.CANNOT_SHOW_MIME_TYPE)

        handled = app.MusicWindow.load_failed(window, None, None, app.HOME_URL, error)

        self.assertTrue(handled)
        window.show_error.assert_called_once()
        self.assertIn("Cannot show MIME type", window.show_error.call_args.args[0])

    def test_policy_interruption_preserves_existing_page_diagnostic(self):
        window = SimpleNamespace(show_error=Mock())
        error = app.GLib.Error.new_literal(
            app.WebKit2.policy_error_quark(), "Frame interrupted by policy change",
            app.WebKit2.PolicyError.FRAME_LOAD_INTERRUPTED_BY_POLICY_CHANGE)

        handled = app.MusicWindow.load_failed(window, None, None, app.HOME_URL, error)

        self.assertFalse(handled)
        window.show_error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
