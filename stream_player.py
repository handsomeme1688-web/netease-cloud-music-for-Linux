"""GStreamer playback of the application's growing local audio copy."""
import gi

gi.require_version('Gst', '1.0')
from gi.repository import GLib, Gst
from audio_buffer import audio_uri


def transition_settings(settings):
    mode = settings.get('mode')
    seconds = settings.get('seconds')
    return dict(mode=mode if mode in ('fade', 'mix') else 'off',
                seconds=seconds if type(seconds) is int and 1 <= seconds <= 12 else 3)


def number(value, default, lower, upper):
    if type(value) not in (int, float) or not lower <= value <= upper:
        return default
    return value


class StreamPlayer:
    def __init__(self, cache, send, sink=None, transition=None):
        Gst.init(None)
        self.cache, self.send, self.sink = cache, send, sink
        self.track = self.prepared = self.tail = None
        self.transition = transition_settings(transition or {})

    def close(self):
        self.release('track')
        self.release('prepared')
        self.release('tail')

    def release(self, slot):
        track = getattr(self, slot)
        setattr(self, slot, None)
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

    def configure(self, settings):
        self.transition = transition_settings(settings)
        self.release('tail')
        if self.transition['mode'] != 'mix':
            self.release('prepared')
        if self.track:
            self.apply_gain(self.track)
            self.update_state(self.track)
            self.prepare(self.track, self.track['next_uri'], self.track['next_duration'])

    def finish_tail(self):
        self.release('tail')
        if self.track:
            self.apply_gain(self.track)
            self.update_state(self.track)

    def unload(self):
        track = self.track
        if not (track['ended'] or track['handoff']):
            self.release('prepared')
        self.release('tail')
        # Howler unloads the outgoing song before it loads the selected next song.
        if track['handoff'] and self.can_overlap(track):
            grace = 1_100_000 if track['mix_at'] else 650_000
            track.update(stopped=False, stop_until=GLib.get_monotonic_time() + grace, wants_play=True)
            self.tail, self.track = track, None
        else:
            self.release('track')

    def open(self, identifier, uri, volume, position=0):
        if self.track:
            self.unload()
        uri = audio_uri(uri)
        track = self.prepared
        key = self.cache.sources.get(uri)
        if self.tail and (position or uri == self.tail['uri'] or key and key == self.cache.sources.get(self.tail['uri'])):
            self.release('tail')
        fade = not position and (self.transition['mode'] == 'fade' or self.tail is not None)
        if track and (uri == track['uri'] or key and key == self.cache.sources.get(track['uri'])):
            self.prepared, self.track = None, track
            track.update(id=identifier, volume=volume, fade_in=fade, seek_next=position or None)
            self.apply_gain(track)
            if track['ready']:
                self.emit(track, 'load')
        else:
            self.release('prepared')
            self.request('track', identifier, uri, volume, fade_in=fade, position=position)

    def request(self, slot, identifier, uri, volume=0, fade_in=False, duration_hint=0, position=0):
        prefix = 'stream-' if slot == 'track' else 'next-'
        track = dict(id=identifier, ref=prefix + identifier, pipeline=None, uri=uri,
            volume=volume, duration=0, position=position, total=0, bytes=0, rate=1.0,
            ready=False, wants_play=False, playing=False, buffering=False,
            seeking=None, seek_deadline=0, seek_next=position or None, ended=False, stopped=False,
            stop_until=0, last_progress=0, duration_hint=duration_hint, mix_at=0,
            fade_in=fade_in, mix_span=0, tail_gain=0, gain=1, applied_volume=None,
            offered=False, handoff=False, next_uri=None, next_duration=0)
        setattr(self, slot, track)
        self.cache.request(track['ref'], uri, lambda event, data: self.cache_event(track, event, data))

    def slot(self, track):
        if self.track is track:
            return 'track'
        if self.prepared is track:
            return 'prepared'
        if self.tail is track:
            return 'tail'

    def cache_event(self, track, event, data):
        if self.slot(track) is None:
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
        if self.slot(track) is None or track['pipeline'] is not None:
            return False
        pipeline = Gst.ElementFactory.make('playbin')
        if not pipeline:
            return self.failed(track)
        track['pipeline'] = pipeline
        pipeline.set_property('flags', 0x112)  # Audio, software volume, buffering.
        pipeline.set_property('buffer-duration', 2 * Gst.SECOND)
        pipeline.set_property('uri', uri)
        self.apply_gain(track)
        if self.sink is not None:
            sink = self.sink() if callable(self.sink) else self.sink
            pipeline.set_property('audio-sink', sink)
        pipeline.connect('source-setup', self.local_source)
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        track['watch'] = bus.connect('message', self.message, track)
        if self.prepared is not track:
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
        elif self.tail is track:
            self.finish_tail()
        else:
            slot = self.slot(track)
            if slot:
                self.release(slot)
        return False

    @staticmethod
    def refresh(track):
        pipeline = track['pipeline']
        if pipeline is not None and track['ready'] and track['seeking'] is None and not track['stopped']:
            ok, position = pipeline.query_position(Gst.Format.TIME)
            if ok and position >= 0 and track['seek_next'] is None:
                seconds = position / Gst.SECOND
                if seconds - track['position'] > .01:
                    track['last_progress'] = GLib.get_monotonic_time()
                track['position'] = seconds
            ok, duration = pipeline.query_duration(Gst.Format.TIME)
            if ok and duration > 0:
                track['duration'] = duration / Gst.SECOND

    def emit(self, track, event, refresh=True):
        if self.track is not track:
            return
        if refresh:
            self.refresh(track)
        state = {key: track[key] for key in ('position', 'duration', 'playing', 'buffering', 'bytes', 'total')}
        if track['stopped']:
            state.update(position=0, playing=False)
        state['buffering'] |= track['seeking'] is not None or track['seek_next'] is not None
        state['transitioning'] = self.tail is not None
        self.send(track['id'], event, state)

    def fade_span(self, track):
        return min(self.transition['seconds'], track['duration'] / 2) if track['duration'] else self.transition['seconds']

    @staticmethod
    def set_gain(track, gain):
        track['gain'] = gain
        volume = track['volume'] * gain
        if track['pipeline'] is not None and track['applied_volume'] != volume:
            track['pipeline'].set_property('volume', volume)
            track['applied_volume'] = volume

    def apply_gain(self, track):
        mode = self.transition['mode']
        if mode == 'off':
            return self.set_gain(track, 1)
        span = self.fade_span(track)
        position, duration = track['position'], track['duration']
        remaining = max(0, duration - position)
        out = min(1, remaining / span) if mode == 'fade' and duration else 1
        if track is self.track and self.tail and track['playing']:
            if not track['mix_span']:
                self.refresh(self.tail)
                track['mix_span'] = min(span, max(.05, self.tail['duration'] - self.tail['position']))
                track['tail_gain'] = self.tail['gain']
            progress = min(1, position / track['mix_span'])
            self.set_gain(self.tail, track['tail_gain'] * (1 - progress))
            if progress >= 1:
                self.release('tail')
        fading = track['fade_in'] and (mode == 'fade' or self.tail or track['mix_span'])
        fade_in = min(1, position / (track['mix_span'] or span)) if fading else 1
        self.set_gain(track, min(fade_in, out))

    def tick(self, track):
        if self.tail is track:
            self.refresh(track)
            mixing = self.track and self.track['mix_span']
            if (not self.can_overlap(track) or
                    not mixing and GLib.get_monotonic_time() >= track['stop_until']):
                self.finish_tail()
                return False
            if track['mix_at'] and track['position'] >= track['mix_at']:
                track['mix_at'] = 0
                if self.track:
                    self.update_state(self.track)
            return True
        if self.track is not track:
            return False
        if track['stopped']:
            if track['stop_until'] and GLib.get_monotonic_time() >= track['stop_until']:
                track.update(stop_until=0, handoff=False)
                self.update_state(track)
            return True
        self.seek_checked(track)
        self.seek_next(track)
        self.refresh(track)
        if (self.transition['mode'] != 'off' and track['playing'] and not track['buffering']
                and track['seeking'] is None and track['seek_next'] is None):
            self.apply_gain(track)
            remaining = track['duration'] - track['position']
            if (self.transition['mode'] == 'mix' and not track['offered'] and self.prepared_ready()
                    and track['wants_play'] and self.can_overlap(track)
                    and .3 < remaining <= self.fade_span(track) + .55):
                track['offered'] = True
                self.emit(track, 'transition', refresh=False)
        self.emit(track, 'tick', refresh=False)
        return True

    @staticmethod
    def can_overlap(track):
        return (track['playing'] and not track['buffering'] and track['seeking'] is None
                and track['seek_next'] is None and track['bytes'] >= track['total'] > 0
                and 0 < GLib.get_monotonic_time() - track['last_progress'] < 650_000)

    def prepared_ready(self):
        track = self.prepared
        if not track or not track['ready'] or track['buffering'] or track['ended'] or not track['total']:
            return False
        if track['bytes'] >= track['total']:
            return True
        duration = track['duration_hint']
        required = min(duration, self.transition['seconds'] + 4)
        return duration > 0 and duration * track['bytes'] / track['total'] >= required

    def prepare(self, track, uri, duration_hint):
        track.update(next_uri=uri, next_duration=duration_hint)
        if (self.transition['mode'] == 'mix' and uri and uri != track['uri']
                and (not self.prepared or self.prepared['uri'] != uri)):
            self.release('prepared')
            track['offered'] = False
            self.request('prepared', track['id'], uri, duration_hint=duration_hint)

    def update_state(self, track):
        pipeline = track['pipeline']
        if pipeline is not None and track['ready']:
            waiting = track is self.track and self.tail and self.tail['mix_at'] > self.tail['position']
            play = ((track['wants_play'] or track['stop_until']) and not waiting and
                    not track['buffering'] and track['seek_next'] is None)
            state = Gst.State.PLAYING if play else Gst.State.PAUSED
            pipeline.set_state(state)

    def message(self, _bus, message, track):
        if self.slot(track) is None:
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
                if buffering and self.track is track and track['mix_span']:
                    self.release('tail')
                self.update_state(track)
                self.emit(track, 'tick')
        elif kind == Gst.MessageType.STATE_CHANGED and message.src == track['pipeline']:
            _, state, _ = message.parse_state_changed()
            playing = state == Gst.State.PLAYING
            if track['playing'] != playing:
                track['playing'] = playing
                self.emit(track, 'state')
        elif kind == Gst.MessageType.EOS:
            if self.tail is track:
                self.finish_tail()
                return
            if track['stopped']:
                track.update(ended=True, playing=False, handoff=False, stop_until=0)
                return
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
        if position > 0 and track['bytes'] < track['total']:
            available = track['duration'] * track['bytes'] / track['total']
            if position >= available:
                return
        track['seek_next'] = None
        track['ended'] = False
        ok = track['pipeline'].seek(track['rate'], Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE, Gst.SeekType.SET,
            int(position * Gst.SECOND), Gst.SeekType.NONE, -1)
        track['seeking'] = position if ok else None
        track['seek_deadline'] = GLib.get_monotonic_time() + 35_000_000
        if not ok:
            self.emit(track, 'seek')
        self.update_state(track)

    def command(self, message):
        identifier, event = message.get('id'), message.get('event')
        if (not isinstance(identifier, str) or not 0 < len(identifier) <= 40 or not identifier.isascii()
                or not all(c.isalnum() or c == '-' for c in identifier)):
            return
        track, value = self.track, message.get('value')
        if event == 'load':
            self.open(identifier, message.get('url'), number(value, 1, 0, 1),
                      number(message.get('position'), 0, 0, 86400))
        elif not track or identifier != track['id']:
            return
        elif event == 'prepare':
            self.prepare(track, audio_uri(message.get('url')), number(value, 0, 0, 86400))
        elif event == 'discard-prepare':
            track.update(next_uri=None, handoff=False, mix_at=0)
            self.release('prepared')
        elif event == 'mix':
            track['handoff'] = bool(track['offered'] and track['wants_play']
                                    and self.can_overlap(track) and self.prepared_ready())
            if track['handoff']:
                track['mix_at'] = max(0, track['duration'] - self.fade_span(track))
                self.emit(track, 'advance', refresh=False)
        elif event == 'unload':
            self.unload()
        elif event == 'stop':
            self.release('tail')
            # A stop before manual next must never seek the outgoing pipeline.
            overlap = self.transition['mode'] == 'mix' and self.can_overlap(track)
            track.update(wants_play=False, stopped=True, handoff=bool(overlap), mix_at=0,
                         stop_until=GLib.get_monotonic_time() + 750_000 if overlap else 0,
                         seeking=None, seek_next=None)
            self.update_state(track)
        elif event in ('play', 'pause'):
            replay = track['stopped'] or track['ended']
            if event == 'pause':
                self.release('tail')
            track.update(handoff=False, stop_until=0)
            track['wants_play'] = event == 'play'
            if event == 'play' and not track.get('timer') and track['pipeline'] is not None:
                track['timer'] = GLib.timeout_add(150, self.tick, track)
            if event == 'play' and replay:
                track.update(stopped=False, offered=False, seek_next=0, position=0)
                self.seek_next(track)
            self.update_state(track)
        elif event == 'volume':
            track['volume'] = number(value, track['volume'], 0, 1)
            self.set_gain(track, track['gain'])
            if self.tail:
                self.tail['volume'] = track['volume']
                self.set_gain(self.tail, self.tail['gain'])
        elif event in ('seek', 'rate'):
            if event == 'rate':
                track['rate'] = number(value, track['rate'], .25, 4)
                value = track['position']
            target = number(value, None, 0, 86400)
            if target is not None:
                if event == 'seek' and track['fade_in'] and target == 0 and track['position'] < .15:
                    self.emit(track, 'seek')
                    return
                self.release('tail')
                track.update(handoff=False, fade_in=False)
                track['seek_next'] = min(target, track['duration']) if track['duration'] else target
                self.seek_next(track)
                self.update_state(track)
