"""Persisted, application-scoped proxy choices without a display or network."""

import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location(
    "music_proxy_app", Path(__file__).resolve().parents[1] / "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class ProxyPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="music-proxy-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.settings = self.root / "preferences" / "network.json"

    def test_absolute_xdg_path_is_used_without_creating_directories(self):
        config = self.root / "custom config"
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
            self.assertEqual(
                app.network_settings_path(),
                config / "netease-cloud-music" / "network.json")
            self.assertEqual(app.read_proxy_mode(), "system")
        self.assertFalse(config.exists())

    def test_missing_empty_and_relative_xdg_use_home_config(self):
        home = self.root / "home"
        expected = home / ".config" / "netease-cloud-music" / "network.json"
        for value in (None, "", "relative/config"):
            with self.subTest(xdg=value), patch.dict(os.environ), \
                    patch.object(app.Path, "home", return_value=home):
                if value is None:
                    os.environ.pop("XDG_CONFIG_HOME", None)
                else:
                    os.environ["XDG_CONFIG_HOME"] = value
                self.assertEqual(app.network_settings_path(), expected)
                self.assertEqual(app.read_proxy_mode(), "system")
        self.assertFalse(home.exists())

    def test_unusable_preferences_keep_system_default(self):
        self.settings.parent.mkdir()
        samples = (
            b"{broken", b"\xff", b"null", b"[]", b'"direct"', b"true",
            b"{}", b'{"proxy_mode": null}', b'{"proxy_mode": []}',
            b'{"proxy_mode": "auto"}', b'{"proxy_mode": "DIRECT"}',
        )
        for content in samples:
            with self.subTest(content=content):
                self.settings.write_bytes(content)
                self.assertEqual(app.read_proxy_mode(self.settings), "system")

    def test_unreadable_preferences_keep_system_default(self):
        with patch.object(app.Path, "read_text", side_effect=PermissionError):
            self.assertEqual(app.read_proxy_mode(self.settings), "system")

    def test_save_round_trip_has_only_the_choice_and_private_permissions(self):
        self.settings.parent.mkdir()
        self.settings.write_text(
            '{"proxy_mode": "system", "unrelated": "old value"}',
            encoding="utf-8")
        self.settings.chmod(0o644)
        for mode in ("direct", "system"):
            with self.subTest(mode=mode):
                app.save_proxy_mode(mode, str(self.settings))
                self.assertEqual(app.read_proxy_mode(self.settings), mode)
                self.assertEqual(
                    json.loads(self.settings.read_text(encoding="utf-8")),
                    {"proxy_mode": mode})
                self.assertEqual(stat.S_IMODE(self.settings.stat().st_mode), 0o600)
        self.assertEqual(list(self.settings.parent.iterdir()), [self.settings])

    def test_default_save_creates_private_application_directory(self):
        config = self.root / "custom config"
        config.mkdir()
        unrelated = config / "unrelated.conf"
        unrelated.write_text("keep", encoding="utf-8")
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
            app.save_proxy_mode("direct")
            self.assertEqual(app.read_proxy_mode(), "direct")
            saved = app.network_settings_path()
        self.assertEqual(stat.S_IMODE(saved.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(saved.stat().st_mode), 0o600)
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")

    def test_invalid_save_does_not_create_or_change_preferences(self):
        for mode in (None, "", "auto", "DIRECT", 1, []):
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError):
                    app.save_proxy_mode(mode, self.settings)
                self.assertFalse(self.settings.parent.exists())
        app.save_proxy_mode("system", self.settings)
        original = self.settings.read_bytes()
        with self.assertRaises(ValueError):
            app.save_proxy_mode("invalid", self.settings)
        self.assertEqual(self.settings.read_bytes(), original)

    def test_failed_atomic_replacement_preserves_saved_choice_and_cleans_temp(self):
        app.save_proxy_mode("system", self.settings)
        original = self.settings.read_bytes()
        with patch.object(app.Path, "replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                app.save_proxy_mode("direct", self.settings)
        self.assertEqual(self.settings.read_bytes(), original)
        self.assertEqual(list(self.settings.parent.iterdir()), [self.settings])


class WebKitProxyModeTests(unittest.TestCase):
    def test_modern_manager_applies_direct_and_restores_system(self):
        manager = SimpleNamespace(set_network_proxy_settings=Mock())
        context = SimpleNamespace(set_network_proxy_settings=Mock())
        for mode, expected in (
                ("direct", app.WebKit2.NetworkProxyMode.CUSTOM),
                ("system", app.WebKit2.NetworkProxyMode.DEFAULT)):
            with self.subTest(mode=mode):
                manager.set_network_proxy_settings.reset_mock()
                app.apply_proxy_mode(manager, context, mode)
                manager.set_network_proxy_settings.assert_called_once()
                actual_mode, settings = manager.set_network_proxy_settings.call_args.args
                self.assertEqual(actual_mode, expected)
                if mode == "direct":
                    self.assertIsInstance(settings, app.WebKit2.NetworkProxySettings)
                else:
                    self.assertIsNone(settings)
        context.set_network_proxy_settings.assert_not_called()

    def test_legacy_context_applies_direct_and_restores_system(self):
        manager = SimpleNamespace()
        context = SimpleNamespace(set_network_proxy_settings=Mock())
        for mode, expected in (
                ("direct", app.WebKit2.NetworkProxyMode.CUSTOM),
                ("system", app.WebKit2.NetworkProxyMode.DEFAULT)):
            with self.subTest(mode=mode):
                context.set_network_proxy_settings.reset_mock()
                app.apply_proxy_mode(manager, context, mode)
                context.set_network_proxy_settings.assert_called_once()
                actual_mode, settings = context.set_network_proxy_settings.call_args.args
                self.assertEqual(actual_mode, expected)
                if mode == "direct":
                    self.assertIsInstance(settings, app.WebKit2.NetworkProxySettings)
                else:
                    self.assertIsNone(settings)

    def test_missing_preference_keeps_system_and_does_not_change_resolver_environment(self):
        manager = SimpleNamespace(set_network_proxy_settings=Mock())
        with tempfile.TemporaryDirectory(prefix="music-proxy-default-") as directory, \
                patch.dict(os.environ, {"GIO_USE_PROXY_RESOLVER": "fixture-resolver"}):
            mode = app.read_proxy_mode(Path(directory) / "missing.json")
            app.apply_proxy_mode(manager, SimpleNamespace(), mode)
            manager.set_network_proxy_settings.assert_called_once_with(
                app.WebKit2.NetworkProxyMode.DEFAULT, None)
            app.apply_proxy_mode(manager, SimpleNamespace(), "direct")
            self.assertEqual(os.environ["GIO_USE_PROXY_RESOLVER"], "fixture-resolver")

    def test_invalid_mode_never_changes_either_webkit_interface(self):
        manager = SimpleNamespace(set_network_proxy_settings=Mock())
        context = SimpleNamespace(set_network_proxy_settings=Mock())
        with self.assertRaises(ValueError):
            app.apply_proxy_mode(manager, context, "invalid")
        manager.set_network_proxy_settings.assert_not_called()
        context.set_network_proxy_settings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
