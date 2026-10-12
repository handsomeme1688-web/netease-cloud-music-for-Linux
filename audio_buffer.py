"""Bounded native downloads of the music CDN's already authorized audio URLs."""
import base64
import json
from urllib.parse import urljoin, urlsplit, urlunsplit

import gi
from gi.repository import Gio, GLib

MAX_BYTES = 64 * 1024 * 1024


def audio_uri(value):
    if not isinstance(value, str) or len(value) > 8192:
        return None
    try:
        uri = urlsplit(value)
        if (uri.scheme not in ('http', 'https') or not uri.hostname
                or not uri.hostname.endswith('.music.126.net') or uri.username
                or uri.password or uri.port not in (None, 80, 443)):
            return None
        # Music CDN requests use HTTPS, including URLs returned with an HTTP prefix.
        host = uri.hostname + (':443' if uri.port == 443 else '')
        return urlunsplit(('https', host, uri.path or '/', uri.query, ''))
    except ValueError:
        return None


class AudioBuffer:
    def __init__(self, api, proxy_mode, send):
        gi.require_version('Soup', '3.0' if api == '4.1' else '2.4')
        from gi.repository import Soup
        self.Soup = Soup
        self.api = api
        self.send = send
        self.jobs = {}
        self.session = Soup.Session(timeout=20)
        if api == '4.0':
            self.session.props.ssl_strict = True
        if proxy_mode == 'direct':
            self.session.props.proxy_resolver = Gio.SimpleProxyResolver.new(None, ['*'])
        else:
            self.session.props.proxy_resolver = Gio.ProxyResolver.get_default()

    def cancel_all(self):
        for identifier in list(self.jobs):
            self.cancel(identifier)

    def cancel(self, identifier):
        job = self.jobs.pop(identifier, None)
        if job:
            job['cancel'].cancel()
            if job.get('stream'):
                job['stream'].close_async(GLib.PRIORITY_DEFAULT, None, None, None)

    def request(self, identifier, uri):
        safe_uri = audio_uri(uri)
        if (not isinstance(identifier, str) or not identifier or len(identifier) > 64
                or not all(character.isalnum() or character in '-_' for character in identifier)):
            return
        if not safe_uri or len(self.jobs) >= 2 or identifier in self.jobs:
            self.send(identifier, 'failed', {})
            return
        job = {'id': identifier, 'uri': safe_uri, 'cancel': Gio.Cancellable(),
               'size': 0, 'declared': 0, 'redirects': 0, 'stream': None}
        self.jobs[identifier] = job
        self.start(job)

    def active(self, job):
        return self.jobs.get(job['id']) is job and not job['cancel'].is_cancelled()

    def fail(self, job):
        if not self.active(job):
            return
        identifier = job['id']
        self.cancel(identifier)
        self.send(identifier, 'failed', {})

    def start(self, job):
        message = self.Soup.Message.new('GET', job['uri'])
        if message is None:
            self.fail(job)
            return
        message.set_flags(self.Soup.MessageFlags.NO_REDIRECT)
        if self.api == '4.1':
            headers = message.get_request_headers()
        else:
            headers = message.request_headers
        headers.replace('Referer', 'https://music.163.com/')
        headers.replace('User-Agent', 'Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0')
        job['message'] = message
        if self.api == '4.1':
            self.session.send_async(message, GLib.PRIORITY_DEFAULT, job['cancel'], self.opened, job)
        else:
            self.session.send_async(message, job['cancel'], self.opened, job)

    def opened(self, session, result, job):
        try:
            stream = session.send_finish(result)
        except GLib.Error:
            self.fail(job)
            return
        if not self.active(job):
            stream.close_async(GLib.PRIORITY_DEFAULT, None, None, None)
            return
        job['stream'] = stream
        message = job['message']
        if self.api == '4.1':
            status, headers = message.get_status(), message.get_response_headers()
        else:
            status, headers = message.status_code, message.response_headers
        if status in (301, 302, 303, 307, 308):
            target = audio_uri(urljoin(job['uri'], headers.get_one('Location') or ''))
            stream.close_async(GLib.PRIORITY_DEFAULT, None, None, None)
            job['stream'] = None
            if not target or job['redirects'] >= 5:
                self.fail(job)
                return
            job['uri'] = target
            job['redirects'] += 1
            self.start(job)
            return
        if status != 200 or headers.get_one('Content-Range'):
            self.fail(job)
            return
        try:
            job['declared'] = int(headers.get_one('Content-Length') or '0')
        except ValueError:
            self.fail(job)
            return
        if job['declared'] < 0 or job['declared'] > MAX_BYTES:
            self.fail(job)
            return
        job['mime'] = (headers.get_one('Content-Type') or 'audio/mpeg').split(';', 1)[0]
        if not (job['mime'].startswith('audio/') or job['mime'] in ('application/octet-stream', 'application/ogg')):
            self.fail(job)
            return
        self.read(job)

    def read(self, job):
        if self.active(job):
            job['stream'].read_bytes_async(65536, GLib.PRIORITY_DEFAULT, job['cancel'], self.received, job)

    def received(self, stream, result, job):
        try:
            data = stream.read_bytes_finish(result).get_data()
        except GLib.Error:
            self.fail(job)
            return
        if not self.active(job):
            return
        if not data:
            if not job['size'] or (job['declared'] and job['size'] != job['declared']):
                self.fail(job)
                return
            self.jobs.pop(job['id'], None)
            stream.close_async(GLib.PRIORITY_DEFAULT, None, None, None)
            self.send(job['id'], 'complete', {'bytes': job['size'], 'mime': job['mime']})
            return
        job['size'] += len(data)
        if job['size'] > MAX_BYTES:
            self.fail(job)
            return
        self.send(job['id'], 'chunk', {'data': base64.b64encode(data).decode('ascii')},
                  lambda: self.read(job))


def delivery_script(identifier, event, value):
    return 'window.__musicNativeAudio && window.__musicNativeAudio(%s,%s,%s)' % (
        json.dumps(identifier), json.dumps(event), json.dumps(value))
