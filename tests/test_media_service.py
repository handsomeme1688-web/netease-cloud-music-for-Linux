"""Desktop identity, metadata validation and system playback commands."""
import unittest
from unittest.mock import Mock

from gi.repository import GLib
from media_service import MediaService, ROOT, PLAYER, TRACK


class MediaServiceTests(unittest.TestCase):
    def setUp(self):
        self.control = Mock()
        self.raise_window = Mock()
        self.quit_app = Mock()
        self.media = MediaService(None, "io.github.neteasecloudmusic.Test", "网易云音乐",
                                  "netease-cloud-music", self.control, self.raise_window, self.quit_app)

    def property(self, interface, name):
        return self.media.get_property(None, None, None, interface, name).unpack()

    def test_utf8_identity_and_desktop_icon_association(self):
        self.assertEqual(self.property(ROOT, "Identity"), "网易云音乐")
        self.assertEqual(self.property(ROOT, "DesktopEntry"), "netease-cloud-music")

    def test_metadata_and_capabilities_follow_website(self):
        self.media.update({"active": True, "playing": True, "duration": 120, "position": 15,
                           "metadata": {"title": "歌名", "artist": "歌手", "album": "专辑",
                                        "artwork": "https://p.example.com/cover.jpg"},
                           "actions": ["nexttrack", "previoustrack"]})
        self.assertEqual(self.property(PLAYER, "PlaybackStatus"), "Playing")
        metadata = self.property(PLAYER, "Metadata")
        self.assertEqual(metadata["xesam:title"], "歌名")
        self.assertEqual(metadata["xesam:artist"], ["歌手"])
        self.assertEqual(metadata["mpris:length"], 120000000)
        self.assertTrue(self.property(PLAYER, "CanGoNext"))
        self.assertTrue(self.property(PLAYER, "CanGoPrevious"))
        self.assertTrue(self.property(PLAYER, "CanSeek"))

    def test_invalid_values_and_local_artwork_are_not_exported(self):
        self.media.update({"active": True, "duration": float('inf'), "position": float('nan'),
                           "metadata": {"title": 123, "artist": None, "artwork": "file:///private/cover"}})
        metadata = self.property(PLAYER, "Metadata")
        self.assertEqual(metadata["xesam:title"], "网易云音乐")
        self.assertNotIn("mpris:artUrl", metadata)
        self.assertFalse(self.property(PLAYER, "CanSeek"))
        self.assertEqual(self.property(PLAYER, "Position"), 0)

    def test_reset_removes_stale_song_and_capabilities(self):
        self.media.update({"active": True, "playing": True, "metadata": {"title": "歌名"}})
        self.media.reset()
        self.assertEqual(self.property(PLAYER, "PlaybackStatus"), "Stopped")
        self.assertEqual(self.property(PLAYER, "Metadata"), {})
        self.assertFalse(self.property(PLAYER, "CanPlay"))

    def call(self, interface, method, parameters=None):
        invocation = Mock()
        self.media.method_call(None, None, None, interface, method, parameters, invocation)
        return invocation

    def test_controls_forward_to_player(self):
        for method, action in (("PlayPause", "toggle"), ("Next", "nexttrack"),
                               ("Previous", "previoustrack"), ("Pause", "pause"), ("Play", "play")):
            self.call(PLAYER, method).return_value.assert_called_once_with(None)
            self.control.assert_called_with(action, {})

    def test_seek_converts_microseconds_and_rejects_wrong_track(self):
        self.call(PLAYER, "Seek", GLib.Variant("(x)", (-2000000,)))
        self.control.assert_called_once_with("seek", {"offset": -2.0})
        self.control.reset_mock()
        self.call(PLAYER, "SetPosition", GLib.Variant("(ox)", ("/old/track", 1000000)))
        self.control.assert_not_called()
        self.call(PLAYER, "SetPosition", GLib.Variant("(ox)", (TRACK, 3000000)))
        self.control.assert_called_once_with("seekto", {"seekTime": 3.0})

    def test_raise_and_quit_target_application(self):
        self.call(ROOT, "Raise")
        self.raise_window.assert_called_once()
        self.call(ROOT, "Quit")
        self.quit_app.assert_called_once()

    def test_unsupported_uri_does_not_open_browser(self):
        invocation = self.call(PLAYER, "OpenUri", GLib.Variant("(s)", ("file:///tmp/example",)))
        invocation.return_dbus_error.assert_called_once()
        self.control.assert_not_called()

    def test_volume_is_bounded_without_changing_playback_rate(self):
        self.assertTrue(self.media.set_property(None, None, None, PLAYER, "Volume", GLib.Variant("d", 2.0)))
        self.control.assert_called_once_with("volume", {"value": 1.0})
        self.assertFalse(self.media.set_property(None, None, None, PLAYER, "Rate", GLib.Variant("d", 2.0)))


if __name__ == "__main__":
    unittest.main()
