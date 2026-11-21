"""Timed, transparent desktop lyrics driven by the native playback clock."""

from bisect import bisect_left, bisect_right
from ctypes import CDLL, POINTER, Structure, c_char_p, c_int, c_short, c_ulong, c_ushort, c_void_p
from dataclasses import dataclass
from functools import lru_cache
import json
import logging
from math import ceil, sqrt
import os
import re

from gi.repository import Gdk, GLib, Gtk, Pango


LRC_TIME = re.compile(r"\[(\d{1,4}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
YRC_LINE = re.compile(r"^\[(\d{1,9}),\d{1,9}\](.*)$")
YRC_WORD = re.compile(r"\((\d{1,9}),(\d{1,9}),-?\d{1,3}\)")


@dataclass(frozen=True)
class LyricLine:
    time: int
    text: str
    translation: str = ""
    words: tuple = ()


def lrc_lines(text):
    rows = {}
    for line in text.splitlines():
        marks = list(LRC_TIME.finditer(line))
        if marks:
            lyric = line[marks[-1].end():].strip()
            if lyric:
                for mark in marks:
                    minute, second, fraction = mark.groups()
                    at = (int(minute) * 60 + int(second)) * 1000 + int((fraction or "").ljust(3, "0"))
                    rows[at] = lyric
        else:
            mark = YRC_LINE.match(line)
            if mark and mark[2].strip():
                rows[int(mark[1])] = YRC_WORD.sub("", mark[2]).strip()
    return rows


def nearest(timestamps, target, tolerance=280):
    index = bisect_left(timestamps, target)
    candidates = timestamps[max(0, index - 1):index + 1]
    if candidates:
        timestamp = min(candidates, key=lambda value: abs(value - target))
        if abs(timestamp - target) <= tolerance:
            return timestamp
    return None


def parse_lyrics(lrc, yrc, translated, word_translation):
    translations = lrc_lines(translated)
    timed_translations = lrc_lines(word_translation)
    translation_times = sorted(translations)
    timed_translation_times = sorted(timed_translations)
    lines = {}
    for line in yrc.splitlines():
        match = YRC_LINE.match(line)
        if not match:
            continue
        at, body = int(match[1]), match[2]
        marks = list(YRC_WORD.finditer(body))
        words = tuple((int(mark[1]), int(mark[2]), body[mark.end():marks[index + 1].start()]
                       if index + 1 < len(marks) else body[mark.end():])
                      for index, mark in enumerate(marks))
        text = "".join(word for _, _, word in words)
        if text.strip():
            translation = timed_translations.get(nearest(timed_translation_times, at), "")
            if not translation:
                translation = translations.get(nearest(translation_times, at), "")
            lines[at] = LyricLine(at, text, translation, words)
    if not lines:
        for at, text in lrc_lines(lrc).items():
            lines[at] = LyricLine(at, text, translations.get(nearest(translation_times, at), ""))
    return [lines[at] for at in sorted(lines)]


def word_progress(start, duration, position):
    return max(0.0, min(1.0, (position - start) / max(duration, 1)))


def rgb(color):
    return tuple(int(color[i:i + 2], 16) * 257 for i in (1, 3, 5))


def word_attributes(words, levels, base, highlight):
    attrs = Pango.AttrList()

    def put(attribute, start, end):
        attribute.start_index, attribute.end_index = start, end
        attrs.insert(attribute)

    offset = 0
    for (_, _, word), level in zip(words, levels):
        end = offset + len(word.encode("utf-8"))
        if level:
            color = [a + (b - a) * level // 64 for a, b in zip(base, highlight)]
            put(Pango.attr_foreground_new(*color), offset, end)
        if level < 64:
            put(Pango.attr_foreground_alpha_new(39000 + 26535 * level // 64), offset, end)
        offset = end
    return attrs


MIN_SIZE, MAX_SIZE = 16, 56
DEFAULT_STYLE = {"size": 27, "color": "#fffaf4", "highlight": "#ffd18a",
                 "transparency": 14, "locked": False, "location": None}


def load_style(path):
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULT_STYLE.copy()
    style = DEFAULT_STYLE.copy()
    if isinstance(saved, dict):
        size = saved.get("size")
        if type(size) is int:
            style["size"] = min(MAX_SIZE, max(MIN_SIZE, size))
        for key in ("color", "highlight"):
            color = saved.get(key)
            if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                style[key] = color.lower()
        transparency = saved.get("transparency")
        if type(transparency) is int:
            style["transparency"] = max(0, min(100, transparency))
        style["locked"] = saved.get("locked") is True
        location = saved.get("location")
        if (style["locked"] and isinstance(location, list) and len(location) == 2 and
                all(type(value) is int and abs(value) < 2**31 for value in location)):
            style["location"] = location
    return style


STYLE = b"""
window.music-desktop-lyrics { background-color: transparent; }
window.music-desktop-lyrics.opaque { background-color: #171c24; }
eventbox { background-color: transparent; background-image: none; }
box.music-lyric-panel {
    background-color: rgba(23,28,36,%(alpha).2f); border: 1px solid rgba(220,230,240,0.56);
    border-radius: 12px; padding: 5px;
}
box.music-lyric-panel.locked { background-color: transparent; border-color: transparent; }
label.music-lyric-line {
    color: %(color)s; font-size: %(size)dpx; font-weight: 700; text-shadow: none;
}
.music-lyric-stack { min-height: %(line_height)dpx; background: transparent; }
.music-lyric-controls { background-color: rgba(30,28,35,0.86); border-radius: 7px; padding: 1px 5px; }
.music-lyric-controls label, .music-lyric-controls button {
    color: #f6eee9; font-size: 12px; text-shadow: none;
}
.music-lyric-controls button {
    min-height: 24px; min-width: 24px; padding: 0 4px; border-color: transparent;
    background-color: transparent; background-image: none; box-shadow: none;
}
.music-lyric-playback button { padding: 0 2px; }
.music-lyric-controls button:hover { background-color: rgba(255,255,255,0.16); }
"""

PREFERENCES_RADIUS = 16
PREFERENCES_STYLE = b"""
window.music-lyric-preferences {
    background: transparent; box-shadow: none;
}
window.music-lyric-preferences.opaque { background: @theme_bg_color; }
box.music-lyric-preferences-body {
    background: @theme_bg_color; border-radius: %dpx; padding: 16px;
}
.music-lyric-preferences-title { font-size: 15px; font-weight: 700; }
button.music-lyric-preferences-done { border-radius: 14px; padding: 5px 18px; }
""" % PREFERENCES_RADIUS


def rounded_rectangles(width, height, radius):
    radius = min(radius, width // 2, height // 2)
    rectangles = []
    for y in range(radius):
        inset = ceil(radius - sqrt(radius**2 - (radius - y - .5)**2) - .5)
        rectangles.append((inset, y, width - 2 * inset, 1))
        rectangles.append((inset, height - 1 - y, width - 2 * inset, 1))
    if height > 2 * radius:
        rectangles.append((0, radius, width, height - 2 * radius))
    return rectangles


class XRectangle(Structure):
    _fields_ = [("x", c_short), ("y", c_short), ("width", c_ushort), ("height", c_ushort)]


@lru_cache(maxsize=1)
def x11_shape_functions():
    # Use the X Shape extension available through GTK's X11 runtime libraries.
    x11, shape = CDLL("libX11.so.6"), CDLL("libXext.so.6")
    open_display, close_display, combine = x11.XOpenDisplay, x11.XCloseDisplay, shape.XShapeCombineRectangles
    open_display.argtypes, open_display.restype = [c_char_p], c_void_p
    close_display.argtypes, close_display.restype = [c_void_p], c_int
    combine.argtypes = [c_void_p, c_ulong, c_int, c_int, c_int, POINTER(XRectangle), c_int, c_int, c_int]
    combine.restype = None
    return open_display, close_display, combine


def set_x11_shape(window, rectangles, kind):
    display = window.get_display()
    try:
        import gi
        gi.require_version("GdkX11", "3.0")
        from gi.repository import GdkX11
        xid = GdkX11.X11Window.get_xid(window)
        open_display, close_display, combine = x11_shape_functions()
    except (ImportError, OSError, ValueError) as error:
        logging.getLogger(__name__).warning("无法裁剪桌面歌词窗口区域：%s", error)
        return False
    # Flush GTK's window creation before setting the shape from the second connection.
    display.sync()
    connection = open_display(display.get_name().encode())
    if not connection:
        return False
    try:
        shape = (XRectangle * len(rectangles))(*rectangles)
        # ShapeSet, Unsorted.
        combine(connection, xid, kind, 0, 0, shape, len(shape), 0, 0)
    finally:
        close_display(connection)
    return True


def clip_x11_preferences(dialog, *_):
    window = dialog.get_window()
    if not window or not window.get_display().supports_shapes():
        return
    scale = window.get_scale_factor()
    width, height = window.get_width() * scale, window.get_height() * scale
    shape_size = width, height, scale
    if getattr(dialog, "_rounded_shape_size", None) != shape_size:
        rects = rounded_rectangles(width, height, PREFERENCES_RADIUS * scale)
        if set_x11_shape(window, rects, 0):  # ShapeBounding
            dialog._rounded_shape_size = shape_size


class DesktopLyrics(Gtk.Window):
    def __init__(self, display, dismiss, style_path, media_control):
        super().__init__(title="桌面歌词", decorated=False, accept_focus=False,
                         focus_on_map=False, skip_taskbar_hint=True, skip_pager_hint=True)
        if display.__gtype__.name == "GdkWaylandDisplay" and os.environ.get("DISPLAY"):
            display = Gdk.Display.open(os.environ["DISPLAY"]) or display
        self.set_screen(display.get_default_screen())
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)
        else:
            self.get_style_context().add_class("opaque")
        self.get_style_context().add_class("music-desktop-lyrics")
        self.set_keep_above(True)
        self.set_resizable(False)
        self.style_path = style_path
        self.style = load_style(style_path)
        self.media_control = media_control
        self.x11 = display.__gtype__.name == "GdkX11Display"
        location = self.style["location"] if self.x11 else None
        monitor = (display.get_monitor_at_point(*location) if location else
                   display.get_primary_monitor() or display.get_monitor(0))
        area = monitor.get_workarea() if monitor else None
        width = min(700, max(240, area.width - 36)) if area else 600
        height = round(self.style["size"] * 1.75) + 42
        self.set_default_size(width, -1)
        if area and self.x11:
            if location:
                x = max(area.x, min(location[0], area.x + area.width - width))
                y = max(area.y, min(location[1], area.y + area.height - height))
            else:
                x = area.x + (area.width - width) // 2
                y = area.y + max(0, area.height - height - 32)
            self.move(x, y)

        self.style_dialog = None
        self.css = Gtk.CssProvider()
        self.preferences_css = Gtk.CssProvider()
        self.preferences_css.load_from_data(PREFERENCES_STYLE)
        self.update_css()
        self.apply_style(self)
        # Keep the buttons' event windows under the same hover surface as the labels.
        self.panel = Gtk.EventBox(visible_window=True, halign=Gtk.Align.CENTER)
        self.apply_style(self.panel)
        self.panel.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK |
                              Gdk.EventMask.BUTTON_PRESS_MASK)
        self.panel.connect("enter-notify-event", self.hover, True)
        self.panel.connect("leave-notify-event", self.hover, False)
        self.panel.connect("button-press-event", self.drag)
        self.panel.connect_after("size-allocate", self.clip_panel_input)
        self.add(self.panel)
        self.surface = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.surface.get_style_context().add_class("music-lyric-panel")
        self.apply_style(self.surface)
        self.panel.add(self.surface)
        self.line_width_limit = width - 24
        self.line_region = Gtk.EventBox(visible_window=True, halign=Gtk.Align.CENTER, margin_start=6, margin_end=6)
        self.apply_style(self.line_region)
        self.line_region.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK)
        self.line_region.connect("enter-notify-event", self.enter_line)
        self.line_region.connect_after("size-allocate", self.clip_panel_input)
        self.lyric_stack = Gtk.Stack(transition_duration=280, homogeneous=True)
        self.lyric_stack.get_style_context().add_class("music-lyric-stack")
        self.apply_style(self.lyric_stack)
        self.line = self.make_line()
        self.other_line = self.make_line()
        self.lyric_stack.add(self.line)
        self.lyric_stack.add(self.other_line)
        self.line_region.add(self.lyric_stack)

        self.controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7,
                                halign=Gtk.Align.CENTER)
        self.controls.get_style_context().add_class("music-lyric-controls")
        self.apply_style(self.controls)
        grip = Gtk.Label(label="拖动歌词", margin_start=4)
        self.apply_style(grip)
        self.controls.pack_start(grip, False, False, 0)
        playback = Gtk.Box(spacing=1)
        playback.get_style_context().add_class("music-lyric-playback")
        self.playback_buttons = {}
        for action, icon, label in (
            ("previoustrack", "media-skip-backward-symbolic", "上一首"),
            ("toggle", "media-playback-start-symbolic", "播放"),
            ("nexttrack", "media-skip-forward-symbolic", "下一首"),
        ):
            button = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.MENU)
            button.set_focus_on_click(False)
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.set_tooltip_text(label)
            button.get_accessible().set_name(label)
            button.connect("clicked", self.playback_clicked, action)
            self.apply_style(button)
            playback.pack_start(button, False, False, 0)
            self.playback_buttons[action] = button
        self.playback_state = None
        self.set_playback(False, False, False, False)
        self.controls.pack_start(playback, False, False, 0)
        settings = Gtk.Button(label="样式", relief=Gtk.ReliefStyle.NONE, focus_on_click=False)
        settings.set_tooltip_text("调整桌面歌词的字号和颜色")
        settings.connect("clicked", self.open_style_dialog)
        self.apply_style(settings)
        self.controls.pack_start(settings, False, False, 0)
        transparency = Gtk.Button(label="透明度", relief=Gtk.ReliefStyle.NONE, focus_on_click=False)
        transparency.set_tooltip_text("调整桌面歌词背景透明度")
        transparency.connect("clicked", self.open_transparency_dialog)
        self.apply_style(transparency)
        self.controls.pack_start(transparency, False, False, 0)
        self.lock = Gtk.Button(relief=Gtk.ReliefStyle.NONE, focus_on_click=False)
        self.lock.connect("clicked", self.toggle_lock)
        self.apply_style(self.lock)
        self.controls.pack_start(self.lock, False, False, 0)
        close = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
        close.set_focus_on_click(False)
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_tooltip_text("关闭桌面歌词")
        close.get_accessible().set_name("关闭桌面歌词")
        close.connect("clicked", lambda *_: dismiss())
        self.apply_style(close)
        self.controls.pack_start(close, False, False, 0)
        self.unlocked_controls = grip, settings, transparency, close, playback
        self.surface.pack_start(self.controls, False, False, 0)
        self.surface.pack_start(self.line_region, True, True, 0)
        self.connect("delete-event", self.close_requested, dismiss)
        self.connect("map", self.apply_move_hint)
        self.connect("map", self.clip_panel_input)
        self.connect("hide", self.on_hide)
        self.connect("destroy", self.on_hide)

        self.song = self.stream = self.title_text = ""
        self.lines, self.times = [], []
        self.position = self.sample_at = self.timer = 0
        self.advancing = False
        self.rate = 1.0
        self.status = ""
        self.index = self.last = self.highlight_frame = self.input_shape = None
        self.apply_lock()
        self.panel.show_all()
        self.render()

    def apply_style(self, widget):
        widget.get_style_context().add_provider(self.css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def update_css(self):
        size = self.style["size"]
        color = self.style["color"].encode("ascii")
        self.css.load_from_data(STYLE % {b"color": color, b"size": size,
                                         b"line_height": round(size * 1.75),
                                         b"alpha": (100 - self.style["transparency"]) / 100})
        self.base_color = rgb(self.style["color"])
        self.highlight_color = rgb(self.style["highlight"])
        self.highlight_frame = None

    def change_style(self, key, value):
        if self.style["locked"] or self.style[key] == value:
            return
        self.style[key] = value
        self.update_css()
        if key == "size":
            self.fit_line()
        self.render()
        self.save_style()

    def save_style(self):
        try:
            temp = self.style_path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.style), encoding="utf-8")
            temp.replace(self.style_path)
        except OSError as error:
            logging.getLogger(__name__).warning("无法保存桌面歌词样式：%s", error)

    def apply_lock(self, hovered=False):
        locked = self.style["locked"]
        for widget in self.unlocked_controls:
            widget.set_no_show_all(locked)
            widget.set_visible(not locked)
        self.lock.set_label("解锁" if locked else "锁定")
        self.lock.set_tooltip_text("解锁后可以拖动和更改样式" if locked else "锁定位置和样式")
        panel_style = self.surface.get_style_context()
        if locked:
            panel_style.add_class("locked")
        else:
            panel_style.remove_class("locked")
        self.show_controls(hovered and not locked)
        self.apply_move_hint()

    def apply_move_hint(self, *_):
        window = self.get_window()
        if self.x11 and window:
            operations = Gdk.WMFunction.CLOSE
            if not self.style["locked"]:
                operations |= Gdk.WMFunction.MOVE
            window.set_functions(operations)

    def toggle_lock(self, _button):
        locked = self.style["locked"] = not self.style["locked"]
        if locked and self.style_dialog:
            self.style_dialog.destroy()
        self.style["location"] = list(self.get_position()) if locked and self.x11 else None
        self.apply_lock(hovered=True)
        self.save_style()

    def open_style_dialog(self, _button):
        size = Gtk.SpinButton.new_with_range(MIN_SIZE, MAX_SIZE, 1)
        size.set_value(self.style["size"])
        size.set_numeric(True)
        size.connect("value-changed", lambda button: self.change_style("size", button.get_value_as_int()))
        fields = [("字号（像素）", size)]
        for key, label in (("color", "歌词颜色"), ("highlight", "逐字高亮颜色")):
            rgba = Gdk.RGBA()
            rgba.parse(self.style[key])
            button = Gtk.ColorButton(rgba=rgba, title=label, use_alpha=False)
            button.connect("color-set", self.select_color, key)
            fields.append((label, button))
        self.present_preferences("桌面歌词样式", fields)

    def open_transparency_dialog(self, _button):
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        scale.set_size_request(220, -1)
        scale.set_value(self.style["transparency"])
        scale.connect("format-value", lambda _, value: f"{value:.0f}%")
        scale.connect("value-changed", lambda slider: self.change_style("transparency", int(slider.get_value())))
        label = "背景透明度"
        if self.get_style_context().has_class("opaque"):
            scale.set_sensitive(False)
            label += "（需要桌面合成）"
        self.present_preferences("桌面歌词背景", [(label, scale)])

    def present_preferences(self, title, fields):
        if self.style["locked"]:
            return
        if self.style_dialog:
            if self.style_dialog.get_title() == title:
                self.style_dialog.present()
                return
            self.style_dialog.destroy()
        dialog = Gtk.Window(title=title, decorated=False, destroy_with_parent=True, resizable=False,
                            skip_taskbar_hint=True, window_position=Gtk.WindowPosition.CENTER)
        screen = self.get_screen()
        dialog.set_screen(screen)
        if self.get_style_context().has_class("opaque"):
            dialog.get_style_context().add_class("opaque")
        else:
            dialog.set_visual(screen.get_rgba_visual())
        dialog.set_transient_for(self)
        dialog.set_keep_above(True)
        self.style_dialog = dialog
        dialog.get_style_context().add_class("music-lyric-preferences")
        dialog.get_style_context().add_provider(self.preferences_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        if self.x11:
            dialog.connect_after("realize", clip_x11_preferences)
            dialog.connect("configure-event", clip_x11_preferences)
            dialog.connect("notify::scale-factor", clip_x11_preferences)
        dialog.connect("destroy", self.style_dialog_closed)
        dialog.connect("key-press-event", self.preferences_key_press)
        # Keep the toplevel's opaque-region hint clear so the compositor blends the rounded edge.
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        body.get_style_context().add_class("music-lyric-preferences-body")
        body.get_style_context().add_provider(self.preferences_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        dialog.add(body)
        heading = Gtk.Label(label=title)
        heading.get_style_context().add_class("music-lyric-preferences-title")
        heading.get_style_context().add_provider(self.preferences_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        body.pack_start(heading, False, False, 0)
        grid = Gtk.Grid(row_spacing=12, column_spacing=24)
        body.pack_start(grid, False, False, 0)
        for row, (label, field) in enumerate(fields):
            caption = Gtk.Label(label=label, xalign=0)
            caption.set_mnemonic_widget(field)
            grid.attach(caption, 0, row, 1, 1)
            grid.attach(field, 1, row, 1, 1)
        done = Gtk.Button(label="完成", halign=Gtk.Align.END)
        done.get_style_context().add_class("music-lyric-preferences-done")
        done.get_style_context().add_provider(self.preferences_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        done.connect("clicked", lambda _button: dialog.destroy())
        body.pack_start(done, False, False, 0)
        dialog.show_all()
        dialog.present()

    def preferences_key_press(self, window, event):
        if event.keyval == Gdk.KEY_Escape:
            window.destroy()
            return True
        return False

    def style_dialog_closed(self, _dialog):
        self.style_dialog = None

    def select_color(self, button, key):
        rgba = button.get_rgba()
        color = "#" + "".join(f"{round(channel * 255):02x}" for channel in (rgba.red, rgba.green, rgba.blue))
        self.change_style(key, color)

    def make_line(self):
        label = Gtk.Label(single_line_mode=True, max_width_chars=1)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.get_style_context().add_class("music-lyric-line")
        self.apply_style(label)
        return label

    def fit_line(self):
        width, _ = self.line.create_pango_layout(self.line.get_text()).get_pixel_size()
        self.lyric_stack.set_size_request(min(width + 2, self.line_width_limit), -1)

    def clip_panel_input(self, *_):
        window = self.get_window()
        if not self.x11 or not window or not self.panel.get_mapped():
            return
        opaque = self.get_style_context().has_class("opaque")
        display = window.get_display()
        if not (display.supports_shapes() if opaque else display.supports_input_shapes()):
            return
        target = self.panel
        if self.style["locked"] and self.controls.get_opacity() == 0:
            target = self.line_region
        origin = target.translate_coordinates(self, 0, 0)
        if origin is None:
            return
        scale = window.get_scale_factor()
        region = tuple(value * scale for value in (*origin, target.get_allocated_width(),
                                                    target.get_allocated_height()))
        if (window, region) != self.input_shape:
            if set_x11_shape(window, [region], 0 if opaque else 2):  # ShapeBounding or ShapeInput
                self.input_shape = window, region

    def show_controls(self, visible):
        self.controls.set_opacity(1 if visible else 0)
        self.controls.set_sensitive(visible)
        self.clip_panel_input()

    def set_playback(self, playing, can_toggle, can_previous, can_next):
        state = playing, can_toggle, can_previous, can_next
        if self.playback_state == state:
            return
        self.playback_state = state
        toggle = self.playback_buttons["toggle"]
        label = "暂停" if playing else "播放"
        icon = "media-playback-pause-symbolic" if playing else "media-playback-start-symbolic"
        toggle.get_image().set_from_icon_name(icon, Gtk.IconSize.MENU)
        toggle.set_tooltip_text(label)
        toggle.get_accessible().set_name(label)
        toggle.set_sensitive(can_toggle)
        self.playback_buttons["previoustrack"].set_sensitive(can_previous)
        self.playback_buttons["nexttrack"].set_sensitive(can_next)

    def playback_clicked(self, button, action):
        if not self.style["locked"] and button.is_sensitive():
            self.media_control(action)

    def hover(self, _widget, event, visible):
        if event.mode == Gdk.CrossingMode.NORMAL and event.detail != Gdk.NotifyType.INFERIOR:
            if not visible or not self.style["locked"]:
                self.show_controls(visible)
        return False

    def enter_line(self, _widget, event):
        if self.style["locked"] and event.mode == Gdk.CrossingMode.NORMAL:
            self.show_controls(True)
        return False

    def drag(self, _widget, event):
        if (event.type != Gdk.EventType.BUTTON_PRESS or event.button != 1 or
                isinstance(Gtk.get_event_widget(event), Gtk.Button)):
            return False
        if not self.style["locked"]:
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
        return True

    def close_requested(self, _window, _event, dismiss):
        if not self.style["locked"]:
            dismiss()
        return True

    def on_hide(self, *_):
        if self.style_dialog:
            self.style_dialog.destroy()
        self.advancing = False
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        self.show_controls(False)

    def set_track(self, song, title, stream):
        self.stream = stream
        self.title_text = title
        if song == self.song:
            self.render()
            return
        self.song = song
        self.lines, self.times = [], []
        self.position = 0
        self.advancing = False
        self.status = "正在加载歌词…" if song else ""
        self.render()

    def set_lyrics(self, song, lrc, yrc, translation, word_translation, failed):
        if song != self.song:
            return
        self.lines = parse_lyrics(lrc, yrc, translation, word_translation)
        self.times = [line.time for line in self.lines]
        self.status = "歌词加载失败" if failed else "暂无同步歌词"
        self.render()
        self.animate()

    def playback_position(self):
        position = self.position
        if self.advancing:
            elapsed = (GLib.get_monotonic_time() - self.sample_at) / 1000
            position += min(elapsed, 185 if self.stream else 280) * self.rate
        return position

    def render(self, scroll=True):
        position = self.playback_position()
        index = bisect_right(self.times, position) - 1
        row = self.lines[index] if index >= 0 else None
        if row:
            text = row.text
        elif not self.lines and self.status:
            text = self.status
        else:
            text = self.title_text or ("桌面歌词" if self.song else "播放歌曲后显示歌词")
        frame = index, text
        if self.last != frame:
            self.last = frame
            slide = scroll and self.index is not None and index == self.index + 1 and self.advancing
            self.index = index
            self.line, self.other_line = self.other_line, self.line
            self.highlight_frame = None
            self.lyric_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP if slide else
                                                 Gtk.StackTransitionType.NONE)
            self.line.set_text(text)
            self.lyric_stack.set_visible_child(self.line)
            self.fit_line()
        words = row.words if row else ()
        levels = tuple(round(64 * word_progress(start, duration, position)) for start, duration, _ in words)
        highlight = words, levels
        if highlight != self.highlight_frame:
            self.highlight_frame = highlight
            attrs = word_attributes(words, levels, self.base_color, self.highlight_color) if words else None
            self.line.set_attributes(attrs)

    def tick(self):
        if not self.advancing or not self.get_visible() or not self.lines:
            self.timer = 0
            return False
        self.render()
        return True

    def animate(self):
        if self.advancing and self.get_visible() and self.lines and not self.timer:
            self.timer = GLib.timeout_add(33, self.tick)

    def clock(self, position, advancing=False, rate=1.0):
        if type(position) not in (float, int) or not 0 <= position <= 86400:
            return
        scroll = abs(position * 1000 - self.playback_position()) < 500
        self.position = position * 1000
        self.sample_at = GLib.get_monotonic_time()
        self.advancing, self.rate = advancing, rate
        self.render(scroll)
        self.animate()
