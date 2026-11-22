"""Native window gestures preserve event details and leave page work alone."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


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
        drag_gap=Mock(), drag_gap_bounds=(200, 18, 160, 42),
        window_controls=Mock(), control_buttons={"maximize": Mock()},
        update_window_interaction=Mock(), is_maximized=lambda: bool(
            state & app.Gdk.WindowState.MAXIMIZED),
        webview=Mock(), sync_page_controls=Mock(), position_window_controls=Mock())


def press(button=1, event_type=None):
    return SimpleNamespace(button=button, type=event_type or app.Gdk.EventType.BUTTON_PRESS,
                           x_root=137.75, y_root=249.25, time=97812)


class WindowInteractionTests(unittest.TestCase):
    def test_opening_ignores_legacy_maximized_geometry(self):
        saved = {"width": 1858, "height": 1045, "maximized": True, "zoom": 1.5}
        self.assertEqual(app.opening_window_geometry(saved, (1858, 1045)),
                         ((800, 540), (1080, 720)))

    def test_opening_remembers_normal_size_and_fits_small_desktop(self):
        self.assertEqual(app.opening_window_geometry({"width": 860, "height": 620}, (1920, 1048)),
                         ((800, 540), (860, 620)))
        self.assertEqual(app.opening_window_geometry({}, (800, 480)),
                         ((680, 408), (680, 408)))

    def test_small_window_fits_zoom_and_larger_window_restores_preference(self):
        view = Mock()
        view.get_zoom_level.return_value = 2.0
        window = SimpleNamespace(webview=view, viewport_timer=1, requested_zoom=2.0,
                                 viewport_size=(480, 320), page_scale=1.1,
                                 compact_header=True, position_window_controls=Mock())

        app.MusicWindow.update_viewport_fit(window)
        view.set_zoom_level.assert_called_once_with(0.9)
        self.assertEqual(window.requested_zoom, 2.0)
        view.get_zoom_level.return_value = 0.9
        window.viewport_size = (2560, 1440)

        app.MusicWindow.update_viewport_fit(window)
        view.set_zoom_level.assert_called_with(2.0)

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

    def test_drag_gap_uses_current_viewport_and_display_scale(self):
        window = make_window()
        window.viewport_size = (1200, 720)
        window.webview.get_uri.return_value = app.HOME_URL
        window.webview.get_scale_factor.return_value = 2
        window.stack = SimpleNamespace(get_visible_child_name=lambda: "web")
        result = Mock()
        result.get_js_value.return_value.to_string.return_value = json.dumps(
            [600, 360, 4, 280, 12, 460, 50])

        app.MusicWindow.drag_gap_message(window, None, result)

        self.assertEqual(window.drag_gap_bounds, (560, 24, 360, 76))
        window.drag_gap.set_size_request.assert_called_once_with(360, 76)
        window.drag_gap.set_visible.assert_called_once_with(True)
        window.viewport_size = (1400, 720)
        app.MusicWindow.drag_gap_message(window, None, result)
        window.drag_gap.set_size_request.assert_called_once_with(360, 76)

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
                window.drag_gap.set_visible.assert_called_once_with(drag_visible)

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

    def test_native_content_draw_receives_rectangular_corner_clip(self):
        cairo = app.cairo
        size = (80, 60)
        native = Mock()
        native.get_display.return_value.supports_shapes.return_value = False
        native.get_display.return_value.supports_input_shapes.return_value = True
        native.get_scale_factor.return_value = 1
        window = SimpleNamespace(alpha_corners=True, corner_geometry=None, get_style_context=Mock(),
                                 get_window=lambda: native, queue_draw=Mock(),
                                 get_allocated_width=lambda: size[0], get_allocated_height=lambda: size[1])
        maximized, fullscreen = app.Gdk.WindowState.MAXIMIZED, app.Gdk.WindowState.FULLSCREEN
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, *size)
        context = cairo.Context(surface)

        def draw_content(_window, cr):
            self.assertTrue(cr.copy_clip_rectangle_list())
            self.assertEqual(cr.in_clip(0.5, 0.5), square_corners)
            self.assertEqual(cr.in_clip(79.5, 59.5), square_corners)
            self.assertTrue(cr.in_clip(40, 30))
            return False

        with patch.object(app.Gtk, "render_background"), patch.object(
                app.Gtk.ApplicationWindow, "do_draw", side_effect=draw_content):
            for state, square_corners in ((0, False), (maximized, True), (maximized | fullscreen, True),
                                          (maximized, True), (0, False), (fullscreen, True), (0, False)):
                with self.subTest(state=state):
                    native.get_state.return_value = state
                    app.MusicWindow.sync_corner_region(window)
                    region = native.input_shape_combine_region.call_args.args[0]
                    self.assertEqual(region.contains_point(0, 0), square_corners)
                    self.assertFalse(app.MusicWindow.do_draw(window, context))


if __name__ == "__main__":
    unittest.main()
