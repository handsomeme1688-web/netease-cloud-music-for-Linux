"""Start before the download ends and seek using the actual GStreamer clock."""
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import wave
from unittest.mock import Mock, patch

from audio_cache import AudioCache
from stream_player import GLib, Gst, StreamPlayer


class StreamPlayerTests(unittest.TestCase):
    def check_transition(self, mode, prepare, expected_mix, manual=False):
        loop = GLib.MainLoop()
        observed = {}
        source = 'https://m10.music.126.net/first.wav'
        next_source = 'https://m10.music.126.net/second.wav'
        output = []

        def capture(_sink, buffer, pad, samples):
            if pad.get_current_caps().get_structure(0).get_string('format') == 'S16LE':
                position = buffer.pts / Gst.SECOND
                sample = int.from_bytes(buffer.extract_dup(0, 2), 'little', signed=True)
                start = GLib.get_monotonic_time() / 1_000_000
                samples.append((position, sample, start, start + buffer.duration / Gst.SECOND))

        def sink():
            element = Gst.ElementFactory.make('fakesink')
            element.set_property('sync', True)
            samples = []
            output.append(samples)
            element.set_property('signal-handoffs', True)
            element.connect('handoff', capture, samples)
            return element

        def send(identifier, event, **data):
            player.command(dict(id=identifier, event=event, **data))

        def switch(mix):
            if mix:
                send('first', 'mix')
            elif manual:
                send('first', 'stop')
            send('first', 'unload')
            send('second', 'load', url=next_source)
            send('second', 'play')
            return False

        def received(identifier, event, state):
            if event == 'error':
                observed['error'] = identifier
                loop.quit()
            elif identifier == 'first' and event in ('transition', 'end'):
                observed['advance'] = (event, state['position'])
                GLib.idle_add(switch, event == 'transition')
            elif manual and identifier == 'first' and state['position'] > .5:
                if 'advance' not in observed:
                    observed['advance'] = ('manual', state['position'])
                    GLib.idle_add(switch, False)
            elif identifier == 'first' and event == 'tick' and 2.3 < state['position'] < 2.6:
                observed['out'] = player.track['pipeline'].get_property('volume')
            elif identifier == 'second' and event == 'load':
                observed['start'] = state['position']
            elif identifier == 'second' and event == 'tick':
                if player.tail and .15 < state['position'] < .65:
                    observed['overlap'] = (player.tail['playing'], player.tail['gain'], player.track['gain'])
                if state['position'] > 1.1:
                    observed['after'] = (player.tail, player.track['gain'])
                    loop.quit()

        with TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setparams((1, 2, 16000, 0, 'NONE', ''))
                wav.writeframes(b'\x40\x01' * 16000 * 3)
            cache = Mock(sources={})

            def download(_identifier, _source, callback):
                size = path.stat().st_size
                callback('source', {'url': path.as_uri()})
                callback('complete', {'bytes': size})

            cache.request.side_effect = download
            player = StreamPlayer(cache, received, sink, {'mode': mode, 'seconds': 1})
            timeout = GLib.timeout_add_seconds(9, lambda: (loop.quit(), False)[1])
            try:
                send('first', 'load', url=source)
                if prepare:
                    send('first', 'prepare', url=next_source)
                send('first', 'play')
                loop.run()
            finally:
                GLib.source_remove(timeout)
                player.close()

        self.assertNotIn('error', observed)
        self.assertAlmostEqual(observed['start'], 0, delta=.1)
        self.assertEqual(observed['after'], (None, 1))
        if expected_mix:
            self.assertEqual(observed['advance'][0], 'manual' if manual else 'transition')
            self.assertLess(observed['advance'][1], 2.25)
            playing, tail, incoming = observed['overlap']
            self.assertTrue(playing)
            self.assertTrue(0 < tail < 1 and 0 < incoming < 1)
            self.assertEqual(cache.request.call_count, 2)
            first, second = ([(start, end) for _, sample, start, end in channel if sample > 10]
                             for channel in output)
            self.assertGreater(min(first[-1][1], second[-1][1]) - max(first[0][0], second[0][0]), .40)
        else:
            self.assertEqual(observed['advance'][0], 'end')
            self.assertGreater(observed['advance'][1], 2.85)
            if mode == 'fade':
                self.assertTrue(0 < observed['out'] < 1)
            else:
                self.assertEqual(observed['out'], 1)
            self.assertNotIn('overlap', observed)
        if mode == 'fade':
            early = [sample for position, sample, *_ in output[0] if .15 < position < .6]
            steady = [sample for position, sample, *_ in output[0] if 1.2 < position < 1.8]
            late = [sample for position, sample, *_ in output[0] if 2.4 < position < 2.85]
            self.assertTrue(early and steady and late, output[0])
            self.assertTrue(0 < max(early) < min(steady))
            self.assertTrue(0 < max(late) < min(steady))

    def test_sequential_fades_use_the_song_clock(self):
        self.check_transition('fade', False, False)

    def test_mix_overlaps_the_prepared_song_and_reuses_its_pipeline(self):
        self.check_transition('mix', True, True)

    def test_mix_waits_for_natural_end_when_next_song_is_unavailable(self):
        self.check_transition('mix', False, False)

    def test_manual_next_can_mix_two_ready_songs(self):
        self.check_transition('mix', False, True, manual=True)

    def test_skip_during_an_unbuffered_seek_starts_next_song_at_zero(self):
        file = io.BytesIO()
        with wave.open(file, 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', ''))
            wav.writeframes(b'\x40\x01' * 16000 * 14)
        audio = file.getvalue()
        prefix = len(audio) // 3
        loop = GLib.MainLoop()
        observed = {}

        def command(identifier, event, value=None, url=None):
            player.command(dict(id=identifier, event=event, value=value, url=url))

        def load(identifier, count):
            command(identifier, 'load', url='https://m10.music.126.net/' + identifier + '.wav')
            command(identifier, 'play')
            ref = 'stream-' + identifier
            cache.receive(ref, 'head', {'bytes': len(audio), 'mime': 'audio/wav'})
            cache.receive(ref, 'chunk', {'data': audio[:count]})
            if count == len(audio):
                cache.receive(ref, 'complete', {'bytes': count, 'mime': 'audio/wav'})

        def skip():
            command('old', 'stop')
            command('old', 'unload')
            load('new', len(audio))
            command('old', 'seek', 9)
            return False

        def received(identifier, event, state):
            if event == 'error':
                observed['error'] = identifier
                loop.quit()
            elif identifier == 'old' and state['position'] > .25 and 'waiting' not in observed:
                observed['gain_while_downloading'] = player.track['gain']
                command('old', 'seek', 9)
                observed['waiting'] = player.track['seek_next']
                GLib.idle_add(skip)
            elif identifier == 'new' and event == 'load':
                observed['start'] = state['position']
            elif identifier == 'new' and state['position'] > .1:
                observed['position'] = state['position']
                observed['tail'] = player.tail
                loop.quit()

        def sink():
            element = Gst.ElementFactory.make('fakesink')
            element.set_property('sync', True)
            return element

        with patch('audio_cache.AudioBuffer'):
            cache = AudioCache('4.1', lambda *_: None)
        player = StreamPlayer(cache, received, sink, {'mode': 'mix', 'seconds': 6})
        timeout = GLib.timeout_source_new_seconds(9)
        timeout.set_callback(lambda *_: (loop.quit(), False)[1])
        timeout.attach()
        try:
            load('old', prefix)
            loop.run()
        finally:
            timeout.destroy()
            player.close()
            cache.close()
        self.assertNotIn('error', observed)
        self.assertEqual(observed['waiting'], 9)
        self.assertEqual(observed['gain_while_downloading'], 1)
        self.assertAlmostEqual(observed['start'], 0, delta=.1)
        self.assertTrue(.1 < observed['position'] < 1)
        self.assertIsNone(observed['tail'])

    def test_play_during_download_and_seek_while_paused(self):
        self.check_stream_seek(14, 4, 8, finish_download=True)

    def test_can_seek_to_160_seconds_when_buffered_to_180(self):
        self.check_stream_seek(220, 180, 160, finish_download=False)

    def test_quality_switch_starts_at_resume_position_during_download(self):
        self.check_stream_seek(24, 15, 11, finish_download=False, start=8)

    def check_stream_seek(self, duration, buffered, target, finish_download, start=0):
        Gst.init(None)
        sink = Gst.ElementFactory.make('fakesink')
        sink.set_property('sync', True)
        file = io.BytesIO()
        with wave.open(file, 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', ''))
            wav.writeframes(b'\0\0' * 16000 * duration)
        audio = file.getvalue()
        prefix = 44 + 2 * 16000 * buffered
        loop = GLib.MainLoop()
        observed = {}

        def send(event, **args):
            player.command(dict(id='test', event=event, **args))

        def send_tail():
            if finish_download:
                cache.receive('stream-test', 'chunk', {'data': audio[prefix:]})
                cache.receive('stream-test', 'complete', {'bytes': len(audio), 'mime': 'audio/wav'})
            send('pause')
            send('seek', value=target)
            return False

        def received(_id, event, state):
            if event == 'error':
                observed['error'] = True
                loop.quit()
                return
            if 'first_play' not in observed and state['playing']:
                observed['first_play'] = state['position']
            if 'early' not in observed and state['playing'] and state['position'] > start + .12:
                observed['early'] = state['bytes']
                GLib.idle_add(send_tail)
            if event == 'seek' and 'early' in observed:
                observed['seek'] = (state['position'], state['playing'])
                send('play')
            if 'seek' in observed and state['playing'] and state['position'] > target + .2:
                observed['resumed'] = state['bytes']
                loop.quit()

        with patch('audio_cache.AudioBuffer'):
            cache = AudioCache('4.1', lambda *_: None)
        player = StreamPlayer(cache, received, sink)
        timer = GLib.timeout_source_new_seconds(12)
        timer.set_callback(lambda *_: (loop.quit(), False)[1])
        timer.attach()
        try:
            send('load', url='https://m10.music.126.net/test.wav', position=start)
            send('play')
            cache.receive('stream-test', 'head', {'bytes': len(audio), 'mime': 'audio/wav'})
            cache.receive('stream-test', 'chunk', {'data': audio[:prefix]})
            loop.run()
            self.assertNotIn('error', observed)
            self.assertAlmostEqual(observed['first_play'], start, delta=.25)
            self.assertEqual(observed.get('early'), prefix)
            self.assertIn('seek', observed)
            self.assertAlmostEqual(observed['seek'][0], target, delta=.25)
            self.assertFalse(observed['seek'][1])
            self.assertEqual(observed.get('resumed'), len(audio) if finish_download else prefix)
        finally:
            timer.destroy()
            player.close()
            cache.close()
