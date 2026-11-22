"""Authenticated quality requests; session credentials stay in the native client."""
import hashlib
import json
import secrets
import subprocess
import threading
import time
from urllib.parse import quote, urlencode

from gi.repository import Gio, GLib
from audio_buffer import MAX_DOWNLOAD_BYTES, audio_uri

LEVELS = {'standard', 'higher', 'exhigh', 'lossless', 'hires', 'jyeffect', 'jymaster', 'sky', 'vivid'}
PATH = '/api/song/enhance/player/url/v1'
ENDPOINT = 'https://interface.music.163.com/eapi/song/enhance/player/url/v1'
FIELDS = {'id', 'code', 'level', 'type', 'br', 'size', 'md5', 'expi', 'flag', 'fee', 'freeTrialInfo',
          'freeTrialPrivilege', 'freeTimeTrialPrivilege', 'trialMode', 'time', 'gain', 'peak',
          'volumeDelta', 'rightSource', 'podcastCtrp', 'encodeType'}


def encode_request(data, path=PATH):
    text = json.dumps(data, separators=(',', ':'))
    digest = hashlib.md5(('nobody' + path + 'use' + text + 'md5forencrypt').encode()).hexdigest()
    plain = (path + '-36cd479b6b5-' + text + '-36cd479b6b5-' + digest).encode()
    encrypted = subprocess.run(['openssl', 'enc', '-aes-128-ecb', '-K', b'e82ckenh8dichen8'.hex()],
        input=plain, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True, timeout=3).stdout
    return urlencode({'params': encrypted.hex().upper()}).encode()


class QualityService:
    def __init__(self, client, cookie_manager, send):
        self.client, self.cookies, self.send = client, cookie_manager, send
        self.jobs = {}
        self.device = secrets.token_hex(16)

    def cancel(self, identifier):
        job = self.jobs.pop(identifier, None)
        if job:
            job['cancel'].cancel()
            GLib.source_remove(job['timer'])
            if job.get('stream'):
                job['stream'].close_async(GLib.PRIORITY_DEFAULT, None, None, None)

    def cancel_all(self):
        for identifier in list(self.jobs):
            self.cancel(identifier)

    def fail(self, job):
        if self.jobs.get(job['id']) is job:
            self.cancel(job['id'])
            self.send(job['id'], None)
        return False

    def request(self, identifier, params):
        if (not isinstance(identifier, str) or not 0 < len(identifier) <= 64 or
                not all(c.isalnum() or c in '-_' for c in identifier)):
            return
        if not isinstance(params, dict):
            self.send(identifier, None)
            return
        ids, level = params.get('ids'), params.get('level')
        if (not isinstance(ids, list) or not 0 < len(ids) <= 20 or
                any(type(value) is not int or not 0 < value < 10**13 for value in ids) or
                not isinstance(level, str) or level not in LEVELS or identifier in self.jobs or len(self.jobs) >= 4):
            self.send(identifier, None)
            return
        data = {'ids': json.dumps(ids), 'level': level, 'encodeType': 'mp3' if level in {'standard', 'higher', 'exhigh', 'vivid'} else 'flac',
                'e_r': False, 'trialMode': -1}
        if level == 'sky':
            mode = params.get('immerseType', 'ste')
            data['immerseType'] = mode if mode in {'ste', 'ste2', 'c51', 'c512', 'aac', 'aac2'} else 'ste'
        job = {'id': identifier, 'data': data, 'cancel': Gio.Cancellable(), 'chunks': [], 'size': 0}
        self.jobs[identifier] = job
        job['timer'] = GLib.timeout_add_seconds(20, self.fail, job)
        self.cookies.get_cookies('https://music.163.com/st/webplayer', job['cancel'], self.authorized, job)

    def authorized(self, manager, result, job):
        try:
            cookies = manager.get_cookies_finish(result) or []
        except GLib.Error:
            self.fail(job)
            return
        if self.jobs.get(job['id']) is not job:
            return
        vivid = job['data']['level'] == 'vivid'
        header = {'os': 'android' if vivid else 'pc', 'appver': '9.5.61' if vivid else '3.1.17.204416',
                  'osver': '14' if vivid else 'Linux', 'deviceId': self.device, 'channel': 'netease',
                  'versioncode': '9005061' if vivid else '140', 'buildver': str(int(time.time())),
                  'resolution': '1920x1080', 'requestId': str(int(time.time() * 1000)) + '_0000'}
        for cookie in cookies:
            if cookie.get_name() in {'MUSIC_U', 'MUSIC_A', '__csrf', 'NMTID'}:
                header[cookie.get_name()] = cookie.get_value()
        job['data']['header'] = header
        job['cookie'] = '; '.join(quote(key, safe='') + '=' + quote(str(value), safe='') for key, value in header.items())
        job['ua'] = 'NeteaseMusic/9.5.61.260802021928(9005061);Dalvik/2.1.0 (Linux; Android 14)' if vivid else \
            'NeteaseMusicDesktop/3.1.17.204416'
        def prepare():
            try:
                body = encode_request(job.pop('data'))
                GLib.idle_add(self.post, job, body)
            except (OSError, subprocess.SubprocessError):
                GLib.idle_add(self.fail, job)
        threading.Thread(target=prepare, daemon=True).start()

    def post(self, job, body):
        if self.jobs.get(job['id']) is not job:
            return False
        soup = self.client.Soup
        message = soup.Message.new('POST', ENDPOINT)
        message.set_flags(soup.MessageFlags.NO_REDIRECT)
        headers = message.get_request_headers() if self.client.api == '4.1' else message.request_headers
        headers.replace('Cookie', job.pop('cookie'))
        headers.replace('User-Agent', job.pop('ua'))
        if self.client.api == '4.1':
            message.set_request_body_from_bytes('application/x-www-form-urlencoded', GLib.Bytes.new(body))
            self.client.session.send_async(message, GLib.PRIORITY_DEFAULT, job['cancel'], self.opened, job)
        else:
            message.set_request('application/x-www-form-urlencoded', soup.MemoryUse.COPY, body)
            self.client.session.send_async(message, job['cancel'], self.opened, job)
        job['message'] = message
        return False

    def opened(self, session, result, job):
        try:
            stream = session.send_finish(result)
        except GLib.Error:
            self.fail(job)
            return
        if self.jobs.get(job['id']) is not job:
            stream.close_async(GLib.PRIORITY_DEFAULT, None, None, None)
            return
        job['stream'] = stream
        message = job['message']
        status = message.get_status() if self.client.api == '4.1' else message.status_code
        if status != 200:
            self.fail(job)
            return
        self.read(job)

    def read(self, job):
        job['stream'].read_bytes_async(16384, GLib.PRIORITY_DEFAULT, job['cancel'], self.received, job)

    def received(self, stream, result, job):
        try:
            data = stream.read_bytes_finish(result).get_data()
        except GLib.Error:
            self.fail(job)
            return
        if self.jobs.get(job['id']) is not job:
            return
        if data:
            job['size'] += len(data)
            if job['size'] > 512 * 1024:
                self.fail(job)
                return
            job['chunks'].append(data)
            self.read(job)
            return
        try:
            response = json.loads(b''.join(job['chunks']))
            items = []
            for item in response.get('data', []):
                safe = {key: value for key, value in item.items() if key in FIELDS}
                safe['url'] = audio_uri(item.get('url'))
                items.append(safe)
            output = {'code': response.get('code', 0), 'data': items, 'cacheLimit': MAX_DOWNLOAD_BYTES}
        except (ValueError, TypeError, AttributeError):
            self.fail(job)
            return
        self.cancel(job['id'])
        self.send(job['id'], output)
