"""Start before the download ends and seek using the actual GStreamer clock."""
import io
import unittest
import wave
from unittest.mock import patch

from audio_cache import AudioCache
from stream_player import GLib, Gst, StreamPlayer


class StreamPlayerTests(unittest.TestCase):
    def test_play_during_download_and_seek_while_paused(self):
        Gst.init(None)
        sink = Gst.ElementFactory.make('fakesink')
        sink.set_property('sync', True)
        file = io.BytesIO()
        with wave.open(file, 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', ''))
            wav.writeframes(b'\0\0' * 16000 * 14)
        audio = file.getvalue()
        prefix = len(audio) // 3
        loop = GLib.MainLoop()
        observed = {}

        def send(event, **args):
            player.command(dict(id='test', event=event, **args))

        def send_tail():
            cache.receive('stream-test', 'chunk', {'data': audio[prefix:]})
            cache.receive('stream-test', 'complete', {'bytes': len(audio), 'mime': 'audio/wav'})
            send('pause')
            send('seek', value=8)
            return False

        def received(_id, event, state):
            if event == 'error':
                observed['error'] = True
                loop.quit()
                return
            if 'early' not in observed and state['position'] > .12:
                observed['early'] = state['bytes']
                GLib.idle_add(send_tail)
            if event == 'seek':
                observed['seek'] = (state['position'], state['playing'])
                send('play')
            if 'seek' in observed and state['playing'] and state['position'] > 8.2:
                observed['resumed'] = True
                loop.quit()

        with patch('audio_cache.AudioBuffer'):
            cache = AudioCache('4.1', lambda *_: None)
        player = StreamPlayer(cache, received, sink)
        timer = GLib.timeout_source_new_seconds(12)
        timer.set_callback(lambda *_: (loop.quit(), False)[1])
        timer.attach()
        try:
            send('load', url='https://m10.music.126.net/test.wav')
            send('play')
            cache.receive('stream-test', 'head', {'bytes': len(audio), 'mime': 'audio/wav'})
            cache.receive('stream-test', 'chunk', {'data': audio[:prefix]})
            loop.run()
            self.assertNotIn('error', observed)
            self.assertEqual(observed.get('early'), prefix)
            self.assertIn('seek', observed)
            self.assertAlmostEqual(observed['seek'][0], 8, delta=.25)
            self.assertFalse(observed['seek'][1])
            self.assertTrue(observed.get('resumed'))
        finally:
            timer.destroy()
            player.close()
            cache.close()
