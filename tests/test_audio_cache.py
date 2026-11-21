"""Full and partial HTTP reads of private bounded audio copies."""
import hashlib
from pathlib import Path
import ssl
import socket
import tempfile
from urllib.request import build_opener, ProxyHandler, Request, HTTPSHandler
from urllib.error import HTTPError
from unittest.mock import Mock, patch
import unittest
from audio_cache import AudioCache, byte_range


class ByteRangeTests(unittest.TestCase):
    def test_full_open_ended_suffix_and_clipped_ranges(self):
        for value, expected in [(None,(0,9,200)),('bytes=2-5',(2,5,206)),
                ('bytes=3-',(3,9,206)),('bytes=-4',(6,9,206)),('bytes=2-100',(2,9,206))]:
            self.assertEqual(byte_range(value,10),expected)

    def test_unsatisfiable_and_multiple_ranges_are_rejected(self):
        for value in ['bytes=10-','bytes=4-2','bytes=-0','bytes=0-1,3-4','items=0-1','bytes=x-y']:
            with self.assertRaises((ValueError,TypeError)):
                byte_range(value,10)


class AudioCacheTests(unittest.TestCase):
    def setUp(self):
        self.patch=patch('audio_cache.AudioBuffer')
        self.patch.start()
        self.send=Mock()
        self.cache=AudioCache('4.1',self.send)
        self.opener=build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context(cadata=self.cache.certificate)))

    def tearDown(self):
        self.cache.close()
        self.patch.stop()

    def store(self, identifier='one', data=b'0123456789', uri='https://m10.music.126.net/fixture.mp3'):
        self.cache.request(identifier, uri)
        self.cache.receive(identifier,'head',{'bytes':len(data)})
        self.cache.receive(identifier,'chunk',{'data':data})
        self.cache.receive(identifier,'complete',{'bytes':len(data),'mime':'audio/mpeg'})
        return self.send.call_args.args[2]['url']

    def test_full_body_and_content_length(self):
        url=self.store()
        with self.opener.open(url) as response:
            self.assertEqual(response.status,200)
            self.assertEqual(response.read(),b'0123456789')
            self.assertEqual(response.headers['Accept-Ranges'],'bytes')
            self.assertEqual(response.headers['Access-Control-Allow-Origin'],'https://music.163.com')
            self.assertEqual(response.headers['Access-Control-Allow-Credentials'],'true')
            self.assertEqual(response.headers['Content-Length'],'10')

    def test_seek_range_is_exact_and_head_has_no_body(self):
        url=self.store()
        with self.opener.open(Request(url,headers={'Range':'bytes=3-6'})) as response:
            self.assertEqual(response.status,206)
            self.assertEqual(response.headers['Content-Range'],'bytes 3-6/10')
            self.assertEqual(response.read(),b'3456')
        with self.opener.open(Request(url,method='HEAD')) as response:
            self.assertEqual(response.read(),b'')
            self.assertEqual(response.headers['Content-Length'],'10')

    def test_idle_preconnection_does_not_block_seek_range(self):
        url=self.store()
        idle=socket.create_connection(('127.0.0.1',self.cache.server.server_port),timeout=2)
        try:
            with self.opener.open(Request(url,headers={'Range':'bytes=6-9'}),timeout=2) as response:
                self.assertEqual(response.status,206)
                self.assertEqual(response.read(),b'6789')
        finally:
            idle.close()

    def test_invalid_range_is_416(self):
        with self.assertRaises(HTTPError) as error:
            self.opener.open(Request(self.store(),headers={'Range':'bytes=100-'}))
        self.assertEqual(error.exception.code,416)
        error.exception.close()

    def test_released_or_wrong_host_cannot_read_audio(self):
        url=self.store()
        with self.assertRaises(HTTPError) as error:
            self.opener.open(Request(url,headers={'Host':'example.org'}))
        self.assertEqual(error.exception.code,404)
        error.exception.close()
        self.cache.cancel('one')
        with self.assertRaises(HTTPError) as error:
            self.opener.open(url)
        self.assertEqual(error.exception.code,404)
        error.exception.close()

    def test_pending_and_completed_copies_share_one_budget(self):
        with patch('audio_cache.MAX_BYTES',16):
            self.store(data=b'1234567890')
            self.cache.request('two','https://m10.music.126.net/other.mp3')
            self.cache.receive('two','head',{'bytes':10})
            self.assertNotIn('two',self.cache.entries)
            self.assertIn('one',self.cache.entries)
            self.send.assert_called_with('two','failed',{})

    def test_prepared_copy_is_reused_without_a_second_download(self):
        self.store()
        self.cache.request('player','https://m10.music.126.net/fixture.mp3')
        self.assertEqual(self.cache.client.request.call_count,1)
        self.assertIs(self.cache.entries['one'],self.cache.entries['player'])
        url=self.send.call_args.args[2]['url']
        self.cache.cancel('one')
        with self.opener.open(url) as response:
            self.assertEqual(response.read(),b'0123456789')

    def test_shared_copy_is_counted_once_in_the_byte_budget(self):
        with patch('audio_cache.MAX_BYTES',16):
            self.store()
            self.cache.request('player','https://m10.music.126.net/fixture.mp3')
            self.cache.request('next','https://m10.music.126.net/next.mp3')
            self.cache.receive('next','head',{'bytes':6})
            self.assertIn('next',self.cache.entries)

    def test_shared_copy_reference_count_is_bounded(self):
        self.store()
        for index in range(8):
            self.cache.request('copy'+str(index),'https://m10.music.126.net/fixture.mp3')
        self.assertEqual(len(self.cache.entries),8)
        self.send.assert_called_with('copy7','failed',{})

    def test_unknown_length_downloads_are_also_bounded(self):
        with patch('audio_cache.MAX_BYTES',4):
            self.cache.request('one','https://m10.music.126.net/fixture.mp3')
            self.cache.receive('one','head',{'bytes':0})
            self.cache.receive('one','chunk',{'data':b'12345'})
            self.assertNotIn('one',self.cache.entries)
            self.send.assert_called_with('one','failed',{})

    def archive(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.cache.directory = Path(directory.name)
        return self.cache.directory

    @staticmethod
    def source(uri, data=b'0123456789', **changes):
        item = dict(url=uri, code=200, md5=hashlib.md5(data).hexdigest(), size=len(data), type='mp3')
        item.update(changes)
        return {'code': 200, 'data': [item]}

    def test_archive_reuses_complete_track_across_restart_and_fresh_url(self):
        directory = self.archive()
        first = 'https://m10.music.126.net/fixture.mp3?old'
        self.cache.authorize_sources(self.source(first))
        self.store(uri=first)
        self.cache.cancel('one')
        self.assertEqual(len(list(directory.iterdir())), 1)

        second = 'https://m20.music.126.net/fixture.mp3?new'
        self.cache.close()
        self.cache = AudioCache('4.1', self.send, directory)
        self.cache.client.request.reset_mock()
        self.opener = build_opener(ProxyHandler({}),
            HTTPSHandler(context=ssl.create_default_context(cadata=self.cache.certificate)))
        self.cache.authorize_sources(self.source(second))
        self.cache.request('again', second)
        self.cache.client.request.assert_not_called()
        url = self.send.call_args.args[2]['url']
        with self.opener.open(Request(url, headers={'Range': 'bytes=4-7'})) as response:
            self.assertEqual(response.read(), b'4567')
            self.assertEqual(response.headers['Content-Range'], 'bytes 4-7/10')

    def test_archive_requires_current_full_source_authorization(self):
        self.archive()
        uri = 'https://m10.music.126.net/fixture.mp3'
        self.cache.authorize_sources(self.source(uri))
        self.store()
        self.cache.cancel_all()
        self.cache.authorize_sources(self.source(uri, freeTrialInfo={'start': 0, 'end': 30}))
        self.cache.request('trial', uri)
        self.cache.client.request.assert_called_with('trial', uri)

    def test_stream_can_take_over_an_incomplete_prefetch(self):
        self.archive()
        first = 'https://m10.music.126.net/fixture.mp3?preload'
        second = 'https://m20.music.126.net/fixture.mp3?play'
        self.cache.authorize_sources(self.source(first))
        self.cache.authorize_sources(self.source(second))
        self.cache.request('prefetch', first)
        self.cache.receive('prefetch', 'head', {'bytes': 10, 'mime': 'audio/mpeg'})
        self.cache.receive('prefetch', 'chunk', {'data': b'012345'})
        stream = Mock()
        self.cache.request('playing', second, stream)
        self.cache.cancel('prefetch')
        self.cache.client.request.assert_called_once_with('prefetch', first)
        self.cache.client.cancel.assert_not_called()
        url = stream.call_args.args[1]['url']
        with self.opener.open(Request(url, headers={'Range': 'bytes=2-4'})) as response:
            self.assertEqual(response.read(), b'234')
        self.cache.receive('prefetch', 'chunk', {'data': b'6789'})
        self.cache.receive('prefetch', 'complete', {'bytes': 10, 'mime': 'audio/mpeg'})
        self.assertEqual(stream.call_args.args[0], 'complete')

    def test_bad_digest_remains_playable_but_is_not_archived(self):
        directory = self.archive()
        uri = 'https://m10.music.126.net/fixture.mp3'
        self.cache.authorize_sources(self.source(uri, data=b'x' * 10))
        url = self.store()
        with self.opener.open(url) as response:
            self.assertEqual(response.read(), b'0123456789')
        self.assertEqual(list(directory.iterdir()), [])

    def test_archive_prunes_least_recently_used_tracks(self):
        directory = self.archive()
        with patch('audio_cache.DISK_LIMIT', 20):
            for index in range(3):
                uri = f'https://m10.music.126.net/{index}.mp3'
                data = bytes([index]) * 10
                self.cache.authorize_sources(self.source(uri, data))
                self.store('archive', data, uri)
                self.cache.cancel('archive')
        self.assertEqual(len(list(directory.iterdir())), 2)
        with patch.object(self.cache.client, 'request') as request:
            self.cache.request('first', 'https://m10.music.126.net/0.mp3')
            request.assert_called_once()
