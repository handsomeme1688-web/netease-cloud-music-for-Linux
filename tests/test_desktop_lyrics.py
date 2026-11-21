"""Test timed lyrics and desktop lyric style preferences."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")

from desktop_lyrics import DEFAULT_STYLE, MAX_SIZE, load_style, lrc_lines, parse_lyrics, rounded_rectangles, word_progress


class DesktopLyricsTests(unittest.TestCase):
    def test_lrc_supports_repeated_lines_and_optional_milliseconds(self):
        self.assertEqual(lrc_lines("[ar:Artist]\n[00:02.4][01:03.045]Again\n[03:17]End"),
                         {2400: "Again", 63045: "Again", 197000: "End"})

    def test_yrc_uses_one_timeline_when_lrc_has_different_timestamps(self):
        rows = parse_lyrics(
            "[00:10.10]One two\n[00:15.00]Three",
            "[10000,1700](10000,725,0)One (10725,740,0)two",
            "[00:10.10]一 二\n[00:15.01]三",
            "[10001,1700]逐字翻译",
        )
        self.assertEqual([row.time for row in rows], [10000])
        self.assertEqual(rows[0].text, "One two")
        self.assertEqual(rows[0].words, ((10000, 725, "One "), (10725, 740, "two")))
        self.assertEqual(rows[0].translation, "逐字翻译")

    def test_unavailable_yrc_uses_translated_lrc(self):
        rows = parse_lyrics("[00:15.00]Three", "", "[00:15.01]三", "")
        self.assertEqual((rows[0].time, rows[0].text, rows[0].translation), (15000, "Three", "三"))
        self.assertFalse(rows[0].words)

    def test_word_progress_uses_duration_and_clamps_after_seeking(self):
        self.assertEqual([word_progress(1000, 800, at) for at in (800, 1000, 1400, 1800, 8000)],
                         [0, 0, .5, 1, 1])
        self.assertEqual(word_progress(1000, 0, 1001), 1)

    def test_saved_style_validates_each_field(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "desktop-lyrics.json"
            path.write_text('{"size": 99, "color": "#39D860", "highlight": "invalid"}', encoding="utf-8")
            self.assertEqual(load_style(path), {**DEFAULT_STYLE, "size": MAX_SIZE, "color": "#39d860"})

    def test_unreadable_style_uses_defaults(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "desktop-lyrics.json"
            self.assertEqual(load_style(path), DEFAULT_STYLE)
            path.write_text("{", encoding="utf-8")
            self.assertEqual(load_style(path), DEFAULT_STYLE)

    def test_window_shape_cuts_each_corner_at_both_display_scales(self):
        for scale in (1, 2):
            width, height = 340 * scale, 164 * scale
            shape = rounded_rectangles(width, height, 16 * scale)
            for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
                self.assertFalse(any(left <= x < left + w and top <= y < top + h for left, top, w, h in shape))
            self.assertIn((0, 16 * scale, width, height - 32 * scale), shape)

    def test_background_transparency_and_locked_location_are_restored(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "desktop-lyrics.json"
            path.write_text('{"transparency": 73, "locked": true, "location": [-400, 660]}', encoding="utf-8")
            self.assertEqual(load_style(path), {
                **DEFAULT_STYLE, "transparency": 73, "locked": True, "location": [-400, 660],
            })
            path.write_text('{"transparency": 130, "locked": "true", "location": [0, 660]}', encoding="utf-8")
            self.assertEqual(load_style(path), {**DEFAULT_STYLE, "transparency": 100})
