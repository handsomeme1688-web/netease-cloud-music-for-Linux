"""GStreamer playback of the application's growing local audio copy."""
import gi

gi.require_version('Gst', '1.0')
from gi.repository import GLib, Gst


def number(value, default, lower, upper):
    if type(value) not in (int, float) or not lower <= value <= upper:
        return default
    return value


class StreamPlayer:
    def __init__(self, cache, send, sink=None):
        Gst.init(None)
        self.cache, self.send, self.sink = cache, send, sink
        self.track = None

    def close(self):
        track, self.track = self.track, None
        if not track:
            return
        self.cache.cancel(track['ref'])
        if track.get('timer'):
            GLib.source_remove(track['timer'])
        pipeline = track.get('pipeline')
        if pipeline is not None:
            bus = pipeline.get_bus()
            bus.disconnect(track['watch'])
            bus.remove_signal_watch()
            pipeline.set_state(Gst.State.NULL)

    def open(self, identifier, uri, volume):
        self.close()
        track = self.track = dict(id=identifier, ref='stream-' + identifier, pipeline=None,
            volume=volume, duration=0, position=0, total=0, bytes=0, rate=1.0,
            ready=False, wants_play=False, playing=False, buffering=False,
            seeking=None, seek_deadline=0, seek_next=None, ended=False)
        self.cache.request(track['ref'], uri, lambda event, data: self.cache_event(track, event, data))

    def cache_event(self, track, event, data):
        if self.track is not track:
            return
        if event == 'source':
            GLib.idle_add(self.start, track, data['url'])
        elif event == 'head':
            track['total'] = data['bytes']
        elif event == 'progress':
            track['bytes'] = data['bytes']
        elif event == 'complete':
            track['bytes'] = track['total'] = data['bytes']
        elif event == 'failed':
            GLib.idle_add(self.failed, track)

    def start(self, track, uri):
        if self.track is not track or track['pipeline'] is not None:
            return False
        pipeline = Gst.ElementFactory.make('playbin')
        if not pipeline:
            return self.failed(track)
        track['pipeline'] = pipeline
        pipeline.set_property('flags', 0x112)  # Audio, software volume, buffering.
        pipeline.set_property('buffer-duration', 2 * Gst.SECOND)
        pipeline.set_property('uri', uri)
        pipeline.set_property('volume', track['volume'])
        if self.sink is not None:
            pipeline.set_property('audio-sink', self.sink)
        pipeline.connect('source-setup', self.local_source)
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        track['watch'] = bus.connect('message', self.message, track)
        track['timer'] = GLib.timeout_add(150, self.tick, track)
        if pipeline.set_state(Gst.State.PAUSED) == Gst.StateChangeReturn.FAILURE:
            return self.failed(track)
        return False

    @staticmethod
    def local_source(_pipeline, source):
        # The URI is an opaque address issued by this cache on 127.0.0.1.
        if source.find_property('ssl-strict'):
            source.set_property('ssl-strict', False)
            source.set_property('automatic-redirect', False)
            source.set_property('proxy', '')
            source.set_property('timeout', 35)

    def failed(self, track):
        if self.track is track:
            identifier = track['id']
            self.close()
            self.send(identifier, 'error', {})
        return False

    def emit(self, track, event):
        if self.track is not track:
            return
        pipeline = track['pipeline']
        if pipeline is not None and track['ready'] and track['seeking'] is None:
            ok, position = pipeline.query_position(Gst.Format.TIME)
            if ok and position >= 0:
                track['position'] = position / Gst.SECOND
            ok, duration = pipeline.query_duration(Gst.Format.TIME)
            if ok and duration > 0:
                track['duration'] = duration / Gst.SECOND
        state = {key: track[key] for key in ('position', 'duration', 'playing', 'buffering', 'bytes', 'total')}
        state['buffering'] |= track['seeking'] is not None
        self.send(track['id'], event, state)

    def tick(self, track):
        if self.track is not track:
            return False
        self.seek_checked(track)
        self.emit(track, 'tick')
        return True

    def update_state(self, track):
        pipeline = track['pipeline']
        if pipeline is not None and track['ready']:
            state = Gst.State.PLAYING if track['wants_play'] and not track['buffering'] else Gst.State.PAUSED
            pipeline.set_state(state)

    def message(self, _bus, message, track):
        if self.track is not track:
            return
        kind = message.type
        if kind == Gst.MessageType.ERROR:
            self.failed(track)
        elif kind == Gst.MessageType.ASYNC_DONE and message.src == track['pipeline']:
            if not track['ready']:
                track['ready'] = True
                self.emit(track, 'load')
                self.seek_next(track)
                self.update_state(track)
            else:
                self.seek_checked(track)
        elif kind == Gst.MessageType.BUFFERING:
            buffering = message.parse_buffering() < 100
            if track['buffering'] != buffering:
                track['buffering'] = buffering
                self.update_state(track)
                self.emit(track, 'tick')
        elif kind == Gst.MessageType.STATE_CHANGED and message.src == track['pipeline']:
            _, state, _ = message.parse_state_changed()
            playing = state == Gst.State.PLAYING
            if track['playing'] != playing:
                track['playing'] = playing
                self.emit(track, 'state')
        elif kind == Gst.MessageType.EOS:
            self.seek_checked(track)
            track.update(ended=True, playing=False, wants_play=False)
            self.emit(track, 'end')

    def seek_checked(self, track):
        target = track['seeking']
        if target is None:
            return
        ok, position = track['pipeline'].query_position(Gst.Format.TIME)
        reached = ok and abs(position / Gst.SECOND - target) <= .4
        if not reached and GLib.get_monotonic_time() < track['seek_deadline']:
            return
        track['seeking'] = None
        if track['seek_next'] is not None:
            self.seek_next(track)
        else:
            self.emit(track, 'seek')

    def seek_next(self, track):
        if track['seeking'] is not None or not track['ready'] or track['seek_next'] is None:
            return
        position = track['seek_next']
        track['seek_next'] = None
        track['ended'] = False
        ok = track['pipeline'].seek(track['rate'], Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE, Gst.SeekType.SET,
            int(position * Gst.SECOND), Gst.SeekType.NONE, -1)
        track['seeking'] = position if ok else None
        track['seek_deadline'] = GLib.get_monotonic_time() + 35_000_000
        if not ok:
            self.emit(track, 'seek')

    def command(self, message):
        identifier, event = message.get('id'), message.get('event')
        if (not isinstance(identifier, str) or not 0 < len(identifier) <= 40 or not identifier.isascii()
                or not all(c.isalnum() or c == '-' for c in identifier)):
            return
        track, value = self.track, message.get('value')
        if event == 'load':
            self.open(identifier, message.get('url'), number(value, 1, 0, 1))
        elif not track or identifier != track['id']:
            return
        elif event == 'unload':
            self.close()
        elif event in ('play', 'pause', 'stop'):
            track['wants_play'] = event == 'play'
            if event == 'stop' or (event == 'play' and track['ended']):
                track['seek_next'] = 0
                self.seek_next(track)
            self.update_state(track)
        elif event == 'volume':
            track['volume'] = number(value, track['volume'], 0, 1)
            if track['pipeline'] is not None:
                track['pipeline'].set_property('volume', track['volume'])
        elif event in ('seek', 'rate'):
            if event == 'rate':
                track['rate'] = number(value, track['rate'], .25, 4)
                value = track['position']
            target = number(value, None, 0, 86400)
            if target is not None:
                track['seek_next'] = min(target, track['duration']) if track['duration'] else target
                self.seek_next(track)
