"""Login recovery using synthetic cookies, windows and asynchronous callbacks."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location(
    "music_login_app", Path(__file__).resolve().parents[1] / "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

LOGIN_URL = ("https://music.163.com/#/login?targetUrl="
             "https%3A%2F%2Fmusic.163.com%2Fst%2Fwebplayer")
OTHER_URL = "https://example.org/"


def cookie(name, value):
    return SimpleNamespace(get_name=lambda: name, get_value=lambda: value)


def authenticated(value="synthetic-session"):
    return [cookie("MUSIC_U", value)]


class CookieManager:
    def __init__(self):
        self.listeners = {}
        self.pending = []
        self.requested_uris = []

    def connect(self, name, callback):
        assert name == "changed"
        self.listeners[1] = callback
        return 1

    def disconnect(self, identifier):
        del self.listeners[identifier]

    def changed(self):
        for callback in list(self.listeners.values()):
            callback(self)

    def get_cookies(self, uri, cancellable, callback, data):
        assert not self.pending, "cookie requests must not overlap"
        self.requested_uris.append(uri)
        self.pending.append((callback, data))

    def reply(self, cookies=None, error=None):
        callback, data = self.pending.pop(0)
        callback(self, SimpleNamespace(cookies=cookies, error=error), data)

    def get_cookies_finish(self, result):
        if result.error is not None:
            raise result.error
        return result.cookies


class Scheduler:
    def __init__(self):
        self.next_id = 1
        self.callbacks = {}

    def add(self, interval, callback, *args):
        identifier = self.next_id
        self.next_id += 1
        self.callbacks[identifier] = (callback, args)
        return identifier

    def remove(self, identifier):
        return self.callbacks.pop(identifier, None) is not None

    def run(self):
        for identifier in list(self.callbacks):
            callback, args = self.callbacks.pop(identifier)
            assert not callback(*args), "login recovery must not repeat itself"


class View:
    def __init__(self, uri):
        self.uri = uri
        self.listeners = []
        self.loads = []

    def connect(self, name, callback, *args):
        assert name in ("notify::uri", "load-changed")
        self.listeners.append((name, callback, args))

    def get_uri(self):
        return self.uri

    def navigate(self, uri):
        self.uri = uri
        for name, callback, args in self.listeners:
            if name == "notify::uri":
                callback(self, None, *args)
        self.commit()

    def commit(self):
        for name, callback, args in self.listeners:
            if name == "load-changed":
                callback(self, app.WebKit2.LoadEvent.COMMITTED, *args)

    def load_uri(self, uri):
        self.loads.append(uri)
        self.navigate(uri)


class Window:
    def __init__(self, application, uri):
        self.application = application
        self.webview = View(uri)
        self.destroyed = False
        self.present = Mock()
        application.windows.append(self)

    def destroy(self):
        self.destroyed = True
        self.application.windows.remove(self)


class Application:
    start_login_watch = app.MusicApplication.start_login_watch
    stop_login_watch = app.MusicApplication.stop_login_watch
    watch_login_window = app.MusicApplication.watch_login_window
    login_uri_changed = app.MusicApplication.login_uri_changed
    login_document_changed = app.MusicApplication.login_document_changed
    check_login_cookies = app.MusicApplication.check_login_cookies
    login_cookies_ready = app.MusicApplication.login_cookies_ready
    return_after_login = app.MusicApplication.return_after_login

    def __init__(self, manager):
        self.manager = SimpleNamespace(get_cookie_manager=lambda: manager)
        self.windows = []
        self.main_window = None

    def get_windows(self):
        return list(self.windows)


class LoginRecognitionTests(unittest.TestCase):
    def test_login_routes_are_limited_to_the_music_site(self):
        for uri in (LOGIN_URL, "https://music.163.com/login",
                    "https://music.163.com/login/?targetUrl=ignored"):
            with self.subTest(uri=uri):
                self.assertTrue(app.is_login_uri(uri))
        for uri in (None, "", app.HOME_URL, OTHER_URL + "#/login",
                    "http://music.163.com/login", "https://music.163.com.evil.test/login",
                    "https://music.163.com/login-help", "https://music.163.com/?next=/login",
                    "https://music.163.com/#//[invalid"):
            with self.subTest(uri=uri):
                self.assertFalse(app.is_login_uri(uri))

    def test_fingerprint_ignores_non_authentication_cookies_and_empty_values(self):
        unrelated = SimpleNamespace(get_name=lambda: "MUSIC_A", get_value=Mock())
        self.assertEqual(app.login_cookie_fingerprint([unrelated, cookie("MUSIC_U", "")]), b"")
        unrelated.get_value.assert_not_called()
        first = app.login_cookie_fingerprint(authenticated("first-synthetic-session"))
        changed = app.login_cookie_fingerprint(authenticated("second-synthetic-session"))
        self.assertIsInstance(first, bytes)
        self.assertNotEqual(first, changed)
        self.assertNotIn(b"first-synthetic-session", first)
        self.assertEqual(first, app.login_cookie_fingerprint(
            [unrelated] + authenticated("first-synthetic-session")))
        values = authenticated("first-synthetic-session") + authenticated("second-synthetic-session")
        self.assertEqual(app.login_cookie_fingerprint(values),
                         app.login_cookie_fingerprint(list(reversed(values))))


class LoginReturnTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = Scheduler()
        for name, replacement in (("timeout_add", self.scheduler.add),
                                  ("source_remove", self.scheduler.remove)):
            patcher = patch.object(app.GLib, name, side_effect=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.cookies = CookieManager()
        self.application = Application(self.cookies)
        self.application.start_login_watch()
        self.main = Window(self.application, app.HOME_URL)
        self.application.main_window = self.main
        self.application.watch_login_window(self.main)
        self.addCleanup(self.application.stop_login_watch)

    def enter_login(self, current_cookies=None, window=None):
        window = self.main if window is None else window
        window.webview.navigate(LOGIN_URL)
        self.cookies.reply(current_cookies or [])

    def complete_login(self, new_cookies=None):
        self.cookies.changed()
        self.cookies.reply(authenticated() if new_cookies is None else new_cookies)

    def popup(self, uri):
        window = Window(self.application, uri)
        self.application.watch_login_window(window)
        return window

    def test_initial_saved_session_does_not_reload_the_player(self):
        self.cookies.reply(authenticated())
        self.complete_login()
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [])
        self.main.present.assert_not_called()

    def test_scan_login_returns_to_player_once(self):
        self.cookies.reply([])
        self.enter_login()
        self.complete_login()
        self.assertEqual(self.main.webview.loads, [])
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [app.HOME_URL])
        self.main.present.assert_called_once_with()
        self.complete_login()
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [app.HOME_URL])
        self.assertTrue(all(uri == app.HOME_URL for uri in self.cookies.requested_uris))

    def test_replacing_stale_session_during_login_recovers(self):
        old = authenticated("old-synthetic-session")
        self.cookies.reply(old)
        self.enter_login(old)
        self.complete_login(authenticated("new-synthetic-session"))
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [app.HOME_URL])

    def test_session_renewal_during_playback_does_not_reload(self):
        self.cookies.reply(authenticated("old-synthetic-session"))
        self.complete_login(authenticated("renewed-synthetic-session"))
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [])
        self.main.present.assert_not_called()

    def test_cookie_notifications_are_coalesced_while_a_read_is_pending(self):
        self.cookies.reply([])
        self.main.webview.navigate(LOGIN_URL)
        before = len(self.cookies.requested_uris)
        for _ in range(20):
            self.cookies.changed()
        self.assertEqual(len(self.cookies.requested_uris), before)
        self.cookies.reply(authenticated())
        self.assertEqual(len(self.cookies.requested_uris), before + 1)
        self.cookies.reply(authenticated())
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [app.HOME_URL])
        self.assertEqual(self.cookies.pending, [])

    def test_cookie_read_failure_does_not_erase_the_baseline_or_navigate(self):
        old = authenticated("old-synthetic-session")
        self.cookies.reply(old)
        self.main.webview.navigate(LOGIN_URL)
        self.cookies.reply(error=app.GLib.Error("synthetic read failure"))
        self.complete_login(old)
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [])
        self.complete_login(authenticated("new-synthetic-session"))
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [app.HOME_URL])

    def test_logout_before_deferred_return_cancels_navigation(self):
        self.cookies.reply([])
        self.enter_login()
        self.complete_login()
        self.complete_login([])
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [])
        self.main.present.assert_not_called()

    def test_site_returning_to_player_first_is_not_reloaded(self):
        self.cookies.reply([])
        self.enter_login()
        self.complete_login()
        self.main.webview.navigate(app.HOME_URL)
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [])

    def test_rejected_session_cannot_loop_back_to_player(self):
        self.cookies.reply([])
        self.enter_login()
        self.complete_login()
        self.scheduler.run()
        self.enter_login(authenticated())
        self.complete_login()
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [app.HOME_URL])

    def test_login_page_moving_to_legacy_home_still_returns_to_player(self):
        self.cookies.reply([])
        self.enter_login()
        self.complete_login()
        self.main.webview.navigate("https://music.163.com/#/discover")
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [app.HOME_URL])

    def test_leaving_music_site_cancels_pending_main_window_return(self):
        self.cookies.reply([])
        self.enter_login()
        self.complete_login()
        self.main.webview.navigate(OTHER_URL)
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [])
        self.main.present.assert_not_called()

    def test_external_popup_cannot_start_a_login_return(self):
        self.cookies.reply([])
        popup = self.popup(OTHER_URL + "#/login")
        self.complete_login()
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [])
        self.assertFalse(popup.destroyed)
        self.main.present.assert_not_called()

    def test_only_completed_login_popup_closes(self):
        self.cookies.reply([])
        login = self.popup(LOGIN_URL)
        self.cookies.reply([])
        other = self.popup("https://music.163.com/song?id=1")
        self.complete_login()
        self.scheduler.run()
        self.assertTrue(login.destroyed)
        self.assertFalse(other.destroyed)
        self.assertFalse(self.main.destroyed)
        self.assertEqual(self.main.webview.loads, [app.HOME_URL])
        self.main.present.assert_called_once_with()
        self.complete_login(authenticated("renewed-synthetic-session"))
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [app.HOME_URL])

    def test_login_popup_that_reaches_player_before_timer_still_closes(self):
        self.cookies.reply([])
        login = self.popup(LOGIN_URL)
        self.cookies.reply([])
        self.complete_login()
        login.webview.navigate(app.HOME_URL)
        self.scheduler.run()
        self.assertTrue(login.destroyed)
        self.assertEqual(self.main.webview.loads, [app.HOME_URL])
        self.main.present.assert_called_once_with()

    def test_login_popup_does_not_reload_main_after_its_own_document_commit(self):
        self.cookies.reply([])
        login = self.popup(LOGIN_URL)
        self.cookies.reply([])
        self.complete_login()
        # A reload of the same URL commits a new document without changing URI.
        self.main.webview.commit()
        self.scheduler.run()
        self.assertTrue(login.destroyed)
        self.assertEqual(self.main.webview.loads, [])
        self.main.present.assert_called_once_with()

    def test_login_popup_does_not_redirect_an_external_main_window(self):
        self.cookies.reply([])
        self.popup(LOGIN_URL)
        self.cookies.reply([])
        self.complete_login()
        self.main.webview.navigate(OTHER_URL)
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [])

    def test_destroyed_login_popup_does_not_present_or_reload_main(self):
        self.cookies.reply([])
        login = self.popup(LOGIN_URL)
        self.cookies.reply([])
        self.complete_login()
        login.destroy()
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [])
        self.main.present.assert_not_called()

    def test_destroyed_main_window_is_not_navigated(self):
        self.cookies.reply([])
        self.enter_login()
        self.complete_login()
        self.main.destroy()
        self.application.main_window = None
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [])
        self.main.present.assert_not_called()

    def test_stop_cancels_timer_and_ignores_late_cookie_reply(self):
        self.cookies.reply([])
        self.enter_login()
        self.complete_login()
        self.cookies.changed()
        self.application.stop_login_watch()
        self.assertEqual(self.scheduler.callbacks, {})
        self.assertEqual(self.cookies.listeners, {})
        self.cookies.reply(authenticated("late-synthetic-session"))
        self.cookies.changed()
        self.scheduler.run()
        self.assertEqual(self.main.webview.loads, [])
        self.main.present.assert_not_called()
        self.assertEqual(self.cookies.pending, [])


if __name__ == "__main__":
    unittest.main()
