"""Native quality authentication, protocol encoding and bounded responses."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess
import threading
import time
import unittest
from urllib.parse import parse_qs
from unittest.mock import patch

from gi.repository import GLib
from app import WEBKIT_API
from audio_buffer import AudioBuffer
from quality_service import QualityService, PATH, encode_request


def decoded(body):
    encrypted = bytes.fromhex(parse_qs(body.decode())['params'][0])
    plain = subprocess.run(['openssl', 'enc', '-d', '-aes-128-ecb', '-K', b'e82ckenh8dichen8'.hex()],
        input=encrypted, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True).stdout.decode()
    uri, text, digest = plain.split('-36cd479b6b5-')
    assert digest == hashlib.md5(('nobody' + uri + 'use' + text + 'md5forencrypt').encode()).hexdigest()
    return uri, json.loads(text)


class Cookie:
    def get_name(self):
        return 'MUSIC_U'

    def get_value(self):
        return 'fixture-session'


class Cookies:
    def __init__(self):
        self.calls = []
        self.auto = True

    def get_cookies(self, uri, cancel, callback, job):
        self.calls.append((callback, job))
        if self.auto:
            GLib.idle_add(lambda: (callback(self, None, job), False)[1])

    def get_cookies_finish(self, _):
        return [Cookie()]


class QualityServiceTests(unittest.TestCase):
    def setUp(self):
        self.requests, self.results = [], []
        owner = self
        self.response = None
        self.status = 200

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                uri, data = decoded(body)
                owner.requests.append((uri, data, self.headers.get('Cookie', '')))
                value = {'code': 200, 'data': [{'id': 123, 'code': 200, 'level': data['level'],
                    'type': 'av3a' if data['level'] == 'vivid' else 'flac', 'br': 1234000, 'size': 40000000,
                    'url': 'http://m10.music.126.net/fixture.flac', 'MUSIC_U': 'fixture-session'}]}
                payload = owner.response if owner.response is not None else json.dumps(value).encode()
                self.send_response(owner.status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Connection', 'close')
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.endpoint = patch('quality_service.ENDPOINT', 'http://127.0.0.1:%d/eapi/song/enhance/player/url/v1' % self.server.server_port)
        self.endpoint.start()
        self.cookies = Cookies()
        self.client = AudioBuffer(WEBKIT_API, lambda *_: None)
        self.service = QualityService(self.client, self.cookies, lambda *args: self.results.append(args))

    def tearDown(self):
        self.service.cancel_all()
        self.endpoint.stop()
        self.server.shutdown()
        self.server.server_close()

    def wait(self, predicate=None):
        predicate = predicate or (lambda: self.results)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            if predicate():
                return
            time.sleep(.005)
        self.fail('quality request did not finish')

    def test_protocol_digest_and_unicode_round_trip(self):
        uri, data = decoded(encode_request({'ids': '[123]', 'level': 'jymaster', 'note': '音质'}))
        self.assertEqual(uri, PATH)
        self.assertEqual(data['note'], '音质')

    def test_authentication_stays_native_and_response_is_filtered(self):
        self.service.request('one', {'ids': [123], 'level': 'jymaster'})
        self.wait()
        uri, data, cookie = self.requests[0]
        self.assertEqual(uri, PATH)
        self.assertEqual(data['header']['MUSIC_U'], 'fixture-session')
        self.assertIn('MUSIC_U=fixture-session', cookie)
        self.assertEqual(data['encodeType'], 'flac')
        response = self.results[0][1]
        self.assertEqual(response['data'][0]['url'], 'https://m10.music.126.net/fixture.flac')
        self.assertNotIn('fixture-session', json.dumps(response))
        self.assertFalse(self.service.jobs)

    def test_vivid_uses_compatible_client_headers_and_keeps_real_format(self):
        self.service.request('vivid', {'ids': [123], 'level': 'vivid'})
        self.wait()
        data = self.requests[0][1]
        self.assertEqual(data['header']['os'], 'android')
        self.assertEqual(data['encodeType'], 'mp3')
        self.assertEqual(self.results[0][1]['data'][0]['type'], 'av3a')

    def test_invalid_parameters_never_access_cookies_or_network(self):
        for index, params in enumerate([{'ids': [True], 'level': 'sky'}, {'ids': [], 'level': 'sky'},
                {'ids': [-1], 'level': 'sky'}, {'ids': [123], 'level': 'unsupported'}]):
            self.service.request(str(index), params)
        self.assertEqual(len(self.results), 4)
        self.assertEqual(self.cookies.calls, [])
        self.assertEqual(self.requests, [])

    def test_cancelled_cookie_callback_cannot_start_a_late_request(self):
        self.cookies.auto = False
        self.service.request('one', {'ids': [123], 'level': 'sky'})
        callback, job = self.cookies.calls[0]
        self.service.cancel('one')
        callback(self.cookies, None, job)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.results, [])

    def test_concurrent_request_budget(self):
        self.cookies.auto = False
        for index in range(5):
            self.service.request(str(index), {'ids': [123], 'level': 'sky'})
        self.assertEqual(len(self.service.jobs), 4)
        self.assertEqual(self.results, [('4', None)])

    def test_oversized_response_is_rejected(self):
        self.response = b'x' * (513 * 1024)
        self.service.request('one', {'ids': [123], 'level': 'sky'})
        self.wait()
        self.assertEqual(self.results, [('one', None)])

    def test_malformed_response_is_rejected(self):
        self.response = b'not JSON'
        self.service.request('one', {'ids': [123], 'level': 'sky'})
        self.wait()
        self.assertEqual(self.results, [('one', None)])

    def test_redirect_is_not_followed(self):
        self.status = 302
        self.service.request('one', {'ids': [123], 'level': 'sky'})
        self.wait()
        self.assertEqual(self.results, [('one', None)])
