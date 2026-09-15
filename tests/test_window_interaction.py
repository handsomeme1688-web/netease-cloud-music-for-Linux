"""Native window gestures preserve event details and leave page work alone."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


spec = importlib.util.spec_from_file_location(
    "window_app", Path(__file__).resolve().parents[1] / "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


def make_window(state=0, resizable=True):
    native = SimpleNamespace(get_state=lambda: state)
    return SimpleNamespace(
        get_window=lambda: native, get_resizable=lambda: resizable,
        begin_move_drag=Mock(), begin_resize_drag=Mock(), toggle_maximize=Mock(),
        resize_handles=[Mock() for _ in range(8)], drag_handle=Mock(),
        window_controls=Mock(), control_buttons={"maximize": Mock()},
        update_window_interaction=Mock(), is_maximized=lambda: bool(
            state & app.Gdk.WindowState.MAXIMIZED),
        webview=Mock(), sync_page_controls=Mock(), position_window_controls=Mock())


def press(button=1, event_type=None):
    return SimpleNamespace(button=button, type=event_type or app.Gdk.EventType.BUTTON_PRESS,
                           x_root=137.75, y_root=249.25, time=97812)


class WindowInteractionTests(unittest.TestCase):
    def test_drag_passes_original_press_to_window_manager(self):
        window = make_window()
        self.assertTrue(app.MusicWindow.move_pressed(window, None, press()))
        window.begin_move_drag.assert_called_once_with(1, 137, 249, 97812)
        window.webview.assert_not_called()

    def test_double_click_toggles_and_other_buttons_do_not_move(self):
        window = make_window()
        self.assertTrue(app.MusicWindow.move_pressed(
            window, None, press(event_type=app.Gdk.EventType.DOUBLE_BUTTON_PRESS)))
        window.toggle_maximize.assert_called_once_with()
        self.assertFalse(app.MusicWindow.move_pressed(window, None, press(button=3)))
        window.begin_move_drag.assert_not_called()

    def test_all_eight_edges_use_native_resize(self):
        for edge in (app.Gdk.WindowEdge.NORTH, app.Gdk.WindowEdge.NORTH_EAST,
                     app.Gdk.WindowEdge.EAST, app.Gdk.WindowEdge.SOUTH_EAST,
                     app.Gdk.WindowEdge.SOUTH, app.Gdk.WindowEdge.SOUTH_WEST,
                     app.Gdk.WindowEdge.WEST, app.Gdk.WindowEdge.NORTH_WEST):
            with self.subTest(edge=edge):
                window = make_window()
                self.assertTrue(app.MusicWindow.resize_pressed(window, None, press(), edge))
                window.begin_resize_drag.assert_called_once_with(edge, 1, 137, 249, 97812)

    def test_resize_rejects_nonresizable_states_and_nonprimary_presses(self):
        for state, resizable, event in (
                (app.Gdk.WindowState.MAXIMIZED, True, press()),
                (app.Gdk.WindowState.FULLSCREEN, True, press()),
                (0, False, press()), (0, True, press(button=2)),
                (0, True, press(event_type=app.Gdk.EventType.DOUBLE_BUTTON_PRESS))):
            with self.subTest(state=state, resizable=resizable, event=event):
                window = make_window(state, resizable)
                self.assertFalse(app.MusicWindow.resize_pressed(
                    window, None, event, app.Gdk.WindowEdge.EAST))
                window.begin_resize_drag.assert_not_called()

    def test_grips_follow_window_state_without_covering_fullscreen(self):
        for state, resize_visible, drag_visible in (
                (0, True, True), (app.Gdk.WindowState.MAXIMIZED, False, True),
                (app.Gdk.WindowState.FULLSCREEN, False, False)):
            with self.subTest(state=state):
                window = make_window(state)
                app.MusicWindow.update_window_interaction(window)
                for handle in window.resize_handles:
                    handle.set_visible.assert_called_once_with(resize_visible)
                window.drag_handle.set_visible.assert_called_once_with(drag_visible)

    def test_focus_change_does_not_rebuild_controls_or_page_styles(self):
        window = make_window()
        event = SimpleNamespace(changed_mask=app.Gdk.WindowState.FOCUSED,
                                new_window_state=app.Gdk.WindowState.FOCUSED)
        self.assertFalse(app.MusicWindow.window_state_changed(window, window, event))
        self.assertEqual(window.control_buttons["maximize"].mock_calls, [])
        window.update_window_interaction.assert_not_called()
        window.sync_page_controls.assert_not_called()
        window.position_window_controls.assert_not_called()

    def test_maximize_event_and_configure_do_not_run_page_layout_queries(self):
        window = make_window(app.Gdk.WindowState.MAXIMIZED)
        window.normal_size = (1000, 700)
        event = SimpleNamespace(changed_mask=app.Gdk.WindowState.MAXIMIZED,
                                new_window_state=app.Gdk.WindowState.MAXIMIZED)
        app.MusicWindow.window_state_changed(window, window, event)
        window.update_window_interaction.assert_called_once_with(app.Gdk.WindowState.MAXIMIZED)
        app.MusicWindow.configure(window, window, SimpleNamespace(width=1920, height=1080))
        self.assertEqual(window.normal_size, (1000, 700))
        window.sync_page_controls.assert_not_called()
        window.position_window_controls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
