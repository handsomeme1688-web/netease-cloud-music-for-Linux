"""Application-owned MPRIS identity and controls for the web player."""

import math
from urllib.parse import urlsplit

from gi.repository import Gio, GLib

ROOT = "org.mpris.MediaPlayer2"
PLAYER = ROOT + ".Player"
PATH = "/org/mpris/MediaPlayer2"
TRACK = PATH + "/track/current"
XML = """<node>
<interface name="org.mpris.MediaPlayer2">
 <method name="Raise"/><method name="Quit"/>
 <property name="CanQuit" type="b" access="read"/>
 <property name="CanRaise" type="b" access="read"/>
 <property name="HasTrackList" type="b" access="read"/>
 <property name="Identity" type="s" access="read"/>
 <property name="DesktopEntry" type="s" access="read"/>
 <property name="SupportedUriSchemes" type="as" access="read"/>
 <property name="SupportedMimeTypes" type="as" access="read"/>
</interface>
<interface name="org.mpris.MediaPlayer2.Player">
 <method name="Next"/><method name="Previous"/><method name="Pause"/>
 <method name="PlayPause"/><method name="Stop"/><method name="Play"/>
 <method name="Seek"><arg name="Offset" type="x" direction="in"/></method>
 <method name="SetPosition"><arg name="TrackId" type="o" direction="in"/>
  <arg name="Position" type="x" direction="in"/></method>
 <method name="OpenUri"><arg name="Uri" type="s" direction="in"/></method>
 <property name="PlaybackStatus" type="s" access="read"/>
 <property name="Rate" type="d" access="readwrite"/>
 <property name="Metadata" type="a{sv}" access="read"/>
 <property name="Volume" type="d" access="readwrite"/>
 <property name="Position" type="x" access="read">
  <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="false"/>
 </property>
 <property name="MinimumRate" type="d" access="read"/>
 <property name="MaximumRate" type="d" access="read"/>
 <property name="CanGoNext" type="b" access="read"/>
 <property name="CanGoPrevious" type="b" access="read"/>
 <property name="CanPlay" type="b" access="read"/>
 <property name="CanPause" type="b" access="read"/>
 <property name="CanSeek" type="b" access="read"/>
 <property name="CanControl" type="b" access="read"/>
 <signal name="Seeked"><arg name="Position" type="x"/></signal>
</interface></node>"""


def finite_number(value, default=0.0, low=0.0, high=86400.0):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return min(high, max(low, value))
    return default


def text_value(value):
    return value[:2048].replace("\x00", "") if isinstance(value, str) else ""


class MediaService:
    def __init__(self, connection, app_id, name, desktop_entry, control, raise_window, quit_app):
        self.connection = connection
        self.name = ROOT + "." + app_id
        self.control = control
        self.raise_window = raise_window
        self.quit_app = quit_app
        self.owner = 0
        self.registrations = []
        self.root = {
            "CanQuit": GLib.Variant("b", True), "CanRaise": GLib.Variant("b", True),
            "HasTrackList": GLib.Variant("b", False), "Identity": GLib.Variant("s", name),
            "DesktopEntry": GLib.Variant("s", desktop_entry),
            "SupportedUriSchemes": GLib.Variant("as", []),
            "SupportedMimeTypes": GLib.Variant("as", []),
        }
        self.reset()
        if connection:
            node = Gio.DBusNodeInfo.new_for_xml(XML)
            for interface in node.interfaces:
                self.registrations.append(connection.register_object(
                    PATH, interface, self.method_call, self.get_property, self.set_property))

    def reset(self):
        if self.owner:
            Gio.bus_unown_name(self.owner)
            self.owner = 0
        self.position = 0.0
        self.updated_at = GLib.get_monotonic_time()
        self.properties = {
            "PlaybackStatus": GLib.Variant("s", "Stopped"),
            "Rate": GLib.Variant("d", 1.0), "Volume": GLib.Variant("d", 1.0),
            "MinimumRate": GLib.Variant("d", 1.0), "MaximumRate": GLib.Variant("d", 1.0),
            "Metadata": GLib.Variant("a{sv}", {}),
            **{key: GLib.Variant("b", False) for key in
               ("CanGoNext", "CanGoPrevious", "CanPlay", "CanPause", "CanSeek")},
            "CanControl": GLib.Variant("b", True),
        }

    def close(self):
        self.reset()
        for registration in self.registrations:
            self.connection.unregister_object(registration)
        self.registrations.clear()

    def update(self, message):
        if not isinstance(message, dict):
            return
        if message.get("active") is not True:
            self.reset()
            return
        metadata = message.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        duration = finite_number(message.get("duration"))
        values = {
            "mpris:trackid": GLib.Variant("o", TRACK),
            "xesam:title": GLib.Variant("s", text_value(metadata.get("title")) or self.root["Identity"].unpack()),
            "xesam:artist": GLib.Variant("as", [text_value(metadata.get("artist"))]),
            "xesam:album": GLib.Variant("s", text_value(metadata.get("album"))),
        }
        if duration:
            values["mpris:length"] = GLib.Variant("x", int(duration * 1000000))
        artwork = text_value(metadata.get("artwork"))
        try:
            parsed = urlsplit(artwork)
            if parsed.scheme in ("http", "https") and parsed.hostname:
                values["mpris:artUrl"] = GLib.Variant("s", artwork)
        except ValueError:
            pass
        actions = message.get("actions")
        actions = actions if isinstance(actions, list) else []
        updated = {
            "Metadata": GLib.Variant("a{sv}", values),
            "PlaybackStatus": GLib.Variant("s", "Playing" if message.get("playing") is True else "Paused"),
            "Volume": GLib.Variant("d", finite_number(message.get("volume"), 1.0, high=1.0)),
            "CanGoNext": GLib.Variant("b", "nexttrack" in actions),
            "CanGoPrevious": GLib.Variant("b", "previoustrack" in actions),
            "CanPlay": GLib.Variant("b", True), "CanPause": GLib.Variant("b", True),
            "CanSeek": GLib.Variant("b", duration > 0),
        }
        changed = {key: value for key, value in updated.items() if value != self.properties.get(key)}
        self.properties.update(updated)
        self.position = finite_number(message.get("position"), high=duration or 86400.0)
        self.updated_at = GLib.get_monotonic_time()
        if not self.connection:
            return
        if not self.owner:
            self.owner = Gio.bus_own_name_on_connection(
                self.connection, self.name, Gio.BusNameOwnerFlags.NONE, None, None)
        if changed:
            self.connection.emit_signal(None, PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                        GLib.Variant("(sa{sv}as)", (PLAYER, changed, [])))

    def get_property(self, _connection, _sender, _path, interface, prop):
        if interface == ROOT:
            return self.root.get(prop)
        if prop == "Position":
            position = self.position
            if self.properties["PlaybackStatus"].unpack() == "Playing":
                position += (GLib.get_monotonic_time() - self.updated_at) / 1000000
            duration = self.properties["Metadata"].unpack().get("mpris:length", 0) / 1000000
            return GLib.Variant("x", int(min(position, duration or position) * 1000000))
        return self.properties.get(prop)

    def set_property(self, _connection, _sender, _path, interface, prop, value):
        if interface == PLAYER and prop == "Volume":
            volume = finite_number(value.unpack(), 1.0, high=1.0)
            self.control("volume", {"value": volume})
            return True
        return interface == PLAYER and prop == "Rate" and value.unpack() == 1.0

    def method_call(self, _connection, _sender, _path, interface, method, parameters, invocation):
        if interface == ROOT:
            (self.raise_window if method == "Raise" else self.quit_app)()
        else:
            actions = {"Next": "nexttrack", "Previous": "previoustrack", "Pause": "pause",
                       "Play": "play", "PlayPause": "toggle", "Stop": "stop"}
            if method in actions:
                self.control(actions[method], {})
            elif method == "Seek":
                self.control("seek", {"offset": parameters.unpack()[0] / 1000000})
            elif method == "SetPosition":
                track, position = parameters.unpack()
                if track == TRACK and position >= 0:
                    self.control("seekto", {"seekTime": position / 1000000})
            else:
                invocation.return_dbus_error("org.mpris.MediaPlayer2.Error.NotSupported", "Unsupported operation")
                return
        invocation.return_value(None)
