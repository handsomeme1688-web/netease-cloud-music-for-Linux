"""Native CDN request boundaries and complete, bounded audio delivery."""
import base64
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import app
from audio_buffer import AudioBuffer, MAX_BYTES, audio_uri, delivery_script
from gi.repository import GLib


class AudioBufferTests(unittest.TestCase):
    def setUp(self):
        self.send = Mock()
        self.buffer = AudioBuffer(app.WEBKIT_API, 'direct', self.send)

    def job(self, size=0, declared=0):
        job = {'id': 'fixture-1', 'cancel': app.Gio.Cancellable(), 'stream': Mock(),
               'size': size, 'declared': declared, 'mime': 'audio/mpeg'}
        self.buffer.jobs[job['id']] = job
        return job

    def test_only_music_cdn_https_destinations_are_allowed(self):
        self.assertEqual(audio_uri('http://m10.music.126.net/song.mp3?key=test'),
                         'https://m10.music.126.net/song.mp3?key=test')
        for uri in ('file:///tmp/a', 'https://127.0.0.1/a', 'https://m10.music.126.net.example.com/a',
                    'https://user@m10.music.126.net/a', 'https://m10.music.126.net:8080/a',
                    'https://[broken', 'https://music.163.com/api/a'):
            with self.subTest(uri=uri):
                self.assertIsNone(audio_uri(uri))

    def test_invalid_destination_does_not_start_request(self):
        with patch.object(self.buffer, 'start') as start:
            self.buffer.request('fixture-1', 'http://127.0.0.1/private')
            start.assert_not_called()
        self.send.assert_called_once_with('fixture-1', 'failed', {})

    def test_direct_mode_uses_explicit_direct_proxy_resolver(self):
        self.assertIsInstance(self.buffer.session.props.proxy_resolver, app.Gio.SimpleProxyResolver)

    def test_cancel_invalidates_late_callbacks(self):
        job = self.job()
        self.buffer.cancel(job['id'])
        self.assertFalse(self.buffer.active(job))
        stream = Mock()
        stream.read_bytes_finish.return_value = GLib.Bytes.new(b'data')
        self.buffer.received(stream, object(), job)
        self.send.assert_not_called()

    def test_chunks_are_delivered_with_backpressure(self):
        job = self.job(declared=3)
        stream = Mock()
        stream.read_bytes_finish.return_value = GLib.Bytes.new(b'abc')
        self.buffer.received(stream, object(), job)
        identifier, event, data, continuation = self.send.call_args.args
        self.assertEqual((identifier, event), ('fixture-1', 'chunk'))
        self.assertEqual(base64.b64decode(data['data']), b'abc')
        job['stream'].read_bytes_async.assert_not_called()
        continuation()
        job['stream'].read_bytes_async.assert_called_once()

    def test_truncated_audio_is_never_completed(self):
        job = self.job(size=3, declared=4)
        stream = Mock()
        stream.read_bytes_finish.return_value = GLib.Bytes.new(b'')
        self.buffer.received(stream, object(), job)
        self.send.assert_called_once_with('fixture-1', 'failed', {})
        self.assertEqual(self.buffer.jobs, {})

    def test_complete_audio_has_verified_length(self):
        job = self.job(size=3, declared=3)
        stream = Mock()
        stream.read_bytes_finish.return_value = GLib.Bytes.new(b'')
        self.buffer.received(stream, object(), job)
        self.send.assert_called_once_with('fixture-1', 'complete', {'bytes': 3, 'mime': 'audio/mpeg'})

    def test_stream_without_content_length_still_has_size_limit(self):
        job = self.job(size=MAX_BYTES)
        stream = Mock()
        stream.read_bytes_finish.return_value = GLib.Bytes.new(b'x')
        self.buffer.received(stream, object(), job)
        self.send.assert_called_once_with('fixture-1', 'failed', {})

    def test_delivery_quotes_untrusted_values_as_data(self):
        script = delivery_script('fixture-1', 'failed', {'mime': "';throw new Error();//"})
        self.assertIn('"mime":', script)
        self.assertTrue(script.startswith('window.__musicNativeAudio &&'))


if __name__ == '__main__':
    unittest.main()
