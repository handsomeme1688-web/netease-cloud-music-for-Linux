"""Full and partial HTTP reads of private bounded audio copies."""
import base64
import ssl
import socket
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
        self.cache=AudioCache('4.1','direct',self.send)
        self.opener=build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context(cadata=self.cache.certificate)))

    def tearDown(self):
        self.cache.close()
        self.patch.stop()

    def store(self, identifier='one', data=b'0123456789'):
        self.cache.request(identifier,'https://m10.music.126.net/fixture.mp3')
        self.cache.receive(identifier,'head',{'bytes':len(data)})
        self.cache.receive(identifier,'chunk',{'data':base64.b64encode(data).decode()})
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
            self.cache.request('two','https://m10.music.126.net/fixture.mp3')
            self.cache.receive('two','head',{'bytes':10})
            self.assertNotIn('two',self.cache.entries)
            self.assertIn('one',self.cache.entries)
            self.send.assert_called_with('two','failed',{})

    def test_unknown_length_downloads_are_also_bounded(self):
        with patch('audio_cache.MAX_BYTES',4):
            self.cache.request('one','https://m10.music.126.net/fixture.mp3')
            self.cache.receive('one','head',{'bytes':0})
            self.cache.receive('one','chunk',{'data':base64.b64encode(b'12345').decode()})
            self.assertNotIn('one',self.cache.entries)
            self.send.assert_called_with('one','failed',{})
