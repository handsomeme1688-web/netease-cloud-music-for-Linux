"""The web player uses direct connections on both WebKitGTK APIs."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import app


class WebKitDirectConnectionTests(unittest.TestCase):
    def test_modern_manager_configures_direct_connection(self):
        manager = Mock()
        context = Mock()
        app.configure_direct_connection(manager, context)
        mode, settings = manager.set_network_proxy_settings.call_args.args
        self.assertEqual(mode, app.WebKit2.NetworkProxyMode.CUSTOM)
        self.assertIsInstance(settings, app.WebKit2.NetworkProxySettings)
        context.set_network_proxy_settings.assert_not_called()

    def test_legacy_webkit_configures_direct_connection_on_context(self):
        context = Mock()
        app.configure_direct_connection(SimpleNamespace(), context)
        mode, settings = context.set_network_proxy_settings.call_args.args
        self.assertEqual(mode, app.WebKit2.NetworkProxyMode.CUSTOM)
        self.assertIsInstance(settings, app.WebKit2.NetworkProxySettings)

    def test_configures_all_hosts_to_bypass_the_proxy(self):
        manager = Mock()
        with patch.object(app.WebKit2, 'NetworkProxySettings') as settings:
            app.configure_direct_connection(manager, Mock())
            settings.new.assert_called_once_with(None, ["*"])
            manager.set_network_proxy_settings.assert_called_once_with(
                app.WebKit2.NetworkProxyMode.CUSTOM, settings.new.return_value)
