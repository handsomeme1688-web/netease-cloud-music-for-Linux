"""Private audio transport with a bounded cache of complete tracks."""
import hashlib
from bisect import bisect_right
import os
import re
import secrets
import ssl
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from audio_buffer import AudioBuffer, MAX_BYTES, audio_uri


DISK_LIMIT = 1024 * 1024 * 1024
DISK_TRACKS = 64
MIME_TYPES = {'mp3': 'audio/mpeg', 'flac': 'audio/flac', 'aac': 'audio/aac',
              'm4a': 'audio/mp4', 'ogg': 'audio/ogg', 'wav': 'audio/wav'}
TRACK_FILE = re.compile(r'[0-9a-f]{32}-[0-9]+\.(?:' + '|'.join(MIME_TYPES) + r')')


def byte_range(value, size):
    if not value:
        return 0, size - 1, 200
    if not value.startswith('bytes=') or ',' in value:
        raise ValueError('Unsupported range')
    start, end = value[6:].split('-', 1)
    if not start:
        length = int(end)
        if length <= 0:
            raise ValueError('Empty suffix')
        return max(0, size - length), size - 1, 206
    start, end = int(start), int(end) if end else size - 1
    if start < 0 or start >= size or end < start:
        raise ValueError('Unsatisfiable range')
    return start, min(end, size - 1), 206


class AudioCache:
    def __init__(self, api, send, directory=None):
        self.send = send
        self.entries = {}
        self.downloads = {}
        self.streams = {}
        self.sources = {}
        self.directory = Path(directory) if directory else None
        if self.directory:
            try:
                self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            except OSError:
                self.directory = None
        self.lock = threading.RLock()
        self.updated = threading.Condition(self.lock)
        self.prefix = '/' + secrets.token_urlsafe(24) + '/'
        cache = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def setup(self):
                super().setup()
                self.connection.settimeout(10)
                self.connection.do_handshake()

            def log_message(self, *_args):
                pass

            def do_HEAD(self):
                self.respond(False)

            def do_GET(self):
                self.respond(True)

            def respond(self, body):
                host = '127.0.0.1:%d' % self.server.server_port
                if self.headers.get('Host') != host or not self.path.startswith(cache.prefix):
                    self.send_error(404)
                    return
                identifier = self.path[len(cache.prefix):]
                with cache.lock:
                    entry = cache.entries.get(identifier)
                    if entry and ('data' in entry or 'path' in entry):
                        size = entry['size']
                    elif entry and identifier in cache.streams:
                        size = entry['expected']
                    else:
                        size = 0
                if not size:
                    self.send_error(404)
                    return
                try:
                    start, end, status = byte_range(self.headers.get('Range'), size)
                except (ValueError, TypeError):
                    self.send_response(416)
                    self.send_header('Content-Range', 'bytes */%d' % size)
                    self.send_header('Content-Length', '0')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    return
                self.send_response(status)
                self.send_header('Content-Type', entry['mime'])
                self.send_header('Content-Length', str(end - start + 1))
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Access-Control-Allow-Origin', 'https://music.163.com')
                self.send_header('Access-Control-Allow-Credentials', 'true')
                self.send_header('Connection', 'close')
                if status == 206:
                    self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, size))
                self.end_headers()
                if body:
                    try:
                        cache.write_range(self.wfile, identifier, entry, start, end)
                    except OSError:
                        pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        # The official page upgrades media requests to HTTPS. Trust only this
        # process's ephemeral loopback certificate in its own WebKit context.
        with tempfile.TemporaryDirectory(prefix='music-cache-tls-') as directory:
            key, cert = Path(directory) / 'key.pem', Path(directory) / 'cert.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt',
                'ec_paramgen_curve:prime256v1', '-nodes', '-keyout', str(key), '-out', str(cert),
                '-subj', '/CN=127.0.0.1', '-addext', 'subjectAltName=IP:127.0.0.1', '-days', '365'],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.certificate = cert.read_text()
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.load_cert_chain(str(cert), str(key))
        # Handshake in each request worker. A browser's idle preconnection must
        # not hold the accept loop and block later range requests.
        self.server.socket = tls.wrap_socket(self.server.socket, server_side=True,
                                             do_handshake_on_connect=False)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = AudioBuffer(api, self.receive)

    def authorize_sources(self, response):
        if not self.directory or not response or response.get('code') != 200:
            return
        for track in response.get('data', ()):
            uri = audio_uri(track.get('url'))
            self.sources.pop(uri, None)
            digest, size, kind = (track.get(name) for name in ('md5', 'size', 'type'))
            if (uri and track.get('code') == 200 and not track.get('freeTrialInfo') and
                    isinstance(digest, str) and re.fullmatch(r'[a-fA-F0-9]{32}', digest) and
                    type(size) is int and 0 < size <= MAX_BYTES and isinstance(kind, str) and kind in MIME_TYPES):
                self.sources[uri] = (digest.lower(), size, kind)
        while len(self.sources) > 64:
            del self.sources[next(iter(self.sources))]

    def archive_path(self, key):
        return self.directory / ('%s-%d.%s' % key)

    def cached_track(self, key):
        path = self.archive_path(key)
        try:
            if not path.is_file() or path.stat().st_size != key[1]:
                return None
            os.utime(path, None)
        except OSError:
            return None
        return path

    def store_track(self, key, chunks, size):
        if not key or key[1] != size:
            return None
        temporary = None
        try:
            digest = hashlib.md5()
            with tempfile.NamedTemporaryFile(dir=self.directory, prefix='.track-', delete=False) as file:
                temporary = Path(file.name)
                for chunk in chunks:
                    digest.update(chunk)
                    file.write(chunk)
            if digest.hexdigest() != key[0]:
                return None
            path = self.archive_path(key)
            temporary.replace(path)
            return path
        except OSError:
            return None
        finally:
            if temporary:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def prune_tracks(self):
        try:
            tracks = [(file, file.stat()) for file in self.directory.iterdir()
                      if TRACK_FILE.fullmatch(file.name) and file.is_file()]
        except OSError:
            return
        pinned = {entry.get('path') for entry in self.entries.values()}
        total, count = sum(info.st_size for _, info in tracks), len(tracks)
        for file, info in sorted(tracks, key=lambda item: item[1].st_mtime_ns):
            if total <= DISK_LIMIT and count <= DISK_TRACKS:
                break
            if file not in pinned:
                try:
                    file.unlink(missing_ok=True)
                except OSError:
                    continue
                total -= info.st_size
                count -= 1

    def local_url(self, identifier):
        return 'https://127.0.0.1:%d%s%s' % (self.server.server_port, self.prefix, identifier)

    def write_range(self, output, identifier, entry, offset, end):
        while offset <= end:
            with self.updated:
                self.updated.wait_for(lambda: self.entries.get(identifier) is not entry or entry['size'] > offset,
                                      timeout=32)
                if self.entries.get(identifier) is not entry or entry['size'] <= offset:
                    return
                path, data = entry.get('path'), entry.get('data')
                if path is None and data is None:
                    index = bisect_right(entry['offsets'], offset)
                    chunk_start = entry['offsets'][index - 1] if index else 0
                    chunk = entry['chunks'][index]
                    part = memoryview(chunk)[offset - chunk_start:end - chunk_start + 1]
                else:
                    part = None
            if path:
                with path.open('rb') as file:
                    file.seek(offset)
                    while offset <= end:
                        chunk = file.read(min(256 * 1024, end - offset + 1))
                        if not chunk:
                            break
                        output.write(chunk)
                        offset += len(chunk)
                return
            if data is not None:
                output.write(memoryview(data)[offset:end + 1])
                return
            output.write(part)
            offset += len(part)

    def notify(self, identifier, event, value):
        if identifier in self.streams:
            self.streams[identifier](event, value)
        else:
            self.send(identifier, event, value)

    def announce(self, identifier, entry):
        if identifier in self.streams and entry['expected']:
            self.notify(identifier, 'source', {'url': self.local_url(identifier), 'bytes': entry['expected']})

    def deliver_complete(self, identifier, entry):
        self.notify(identifier, 'complete', {'bytes': entry['size'], 'mime': entry['mime'],
            'url': self.local_url(identifier)})

    def request(self, identifier, uri, stream=None):
        if (not isinstance(identifier, str) or not 0 < len(identifier) <= 64 or
                not identifier.isascii() or not all(c.isalnum() or c in '-_' for c in identifier)):
            return
        with self.lock:
            if identifier in self.entries or len(self.entries) >= 8:
                if stream:
                    stream('failed', {})
                else:
                    self.send(identifier, 'failed', {})
                return
            if stream:
                self.streams[identifier] = stream
            uri = audio_uri(uri)
            if not uri:
                self.notify(identifier, 'failed', {})
                self.streams.pop(identifier, None)
                return
            unique = {id(entry): entry for entry in self.entries.values()}.values()
            key = self.sources.get(uri)
            shared = next((entry for entry in unique if entry['uri'] == uri or key and entry.get('key') == key), None)
            if shared is None and key:
                path = self.cached_track(key)
                if path:
                    shared = {'uri': uri, 'key': key, 'path': path, 'size': key[1], 'expected': key[1],
                              'reserved': 0, 'mime': MIME_TYPES[key[2]]}
            if shared is not None:
                self.entries[identifier] = shared
                self.notify(identifier, 'head', {'bytes': shared['expected']})
                self.announce(identifier, shared)
                if 'data' in shared or 'path' in shared:
                    self.deliver_complete(identifier, shared)
                return
            if sum('path' not in entry for entry in unique) >= 2:
                self.notify(identifier, 'failed', {})
                self.streams.pop(identifier, None)
                return
            entry = {'uri': uri, 'key': key, 'job': identifier, 'chunks': [], 'offsets': [],
                     'size': 0, 'expected': 0, 'reserved': 0, 'mime': 'application/octet-stream'}
            self.entries[identifier] = self.downloads[identifier] = entry
        self.client.request(identifier, uri)

    def cancel(self, identifier):
        with self.updated:
            entry = self.entries.pop(identifier, None)
            self.streams.pop(identifier, None)
            if entry and entry.get('job') in self.downloads and all(other is not entry for other in self.entries.values()):
                job = entry['job']
                del self.downloads[job]
                self.client.cancel(job)
            self.updated.notify_all()

    def cancel_all(self):
        self.client.cancel_all()
        with self.updated:
            self.entries.clear()
            self.downloads.clear()
            self.streams.clear()
            self.sources.clear()
            self.updated.notify_all()

    def close(self):
        self.cancel_all()
        def stop():
            self.server.shutdown()
            self.server.server_close()
        threading.Thread(target=stop, daemon=True).start()

    def receive(self, identifier, event, value, continuation=None):
        with self.updated:
            entry = self.downloads.get(identifier)
            if entry is None:
                return
            refs = [ref for ref, other in self.entries.items() if other is entry]
            if event == 'head':
                key = entry['key']
                requested = value['bytes'] or (key[1] if key else 0)
                unique = {id(item): item for item in self.entries.values()}.values()
                used = sum(item['reserved'] for item in unique if item is not entry)
                if requested < 0 or requested + used > MAX_BYTES:
                    self.fail(refs)
                    return
                entry['expected'] = requested
                entry['mime'] = value.get('mime') or (MIME_TYPES[key[2]] if key else 'application/octet-stream')
                entry['reserved'] = requested
                for ref in refs:
                    self.notify(ref, 'head', {'bytes': requested})
                    self.announce(ref, entry)
            elif event == 'chunk':
                data = value['data']
                entry['size'] += len(data)
                entry['reserved'] = max(entry['reserved'], entry['size'])
                unique = {id(item): item for item in self.entries.values()}.values()
                if sum(item['reserved'] for item in unique) > MAX_BYTES:
                    self.fail(refs)
                    return
                entry['chunks'].append(data)
                entry['offsets'].append(entry['size'])
                self.updated.notify_all()
                now = time.monotonic()
                if now - entry.get('reported_at', 0) >= .25:
                    entry['reported_at'] = now
                    for ref in refs:
                        self.notify(ref, 'progress', {'bytes': entry['size']})
            elif event == 'complete':
                if entry['expected'] and entry['expected'] != entry['size']:
                    self.fail(refs)
                    return
                self.downloads.pop(identifier, None)
                chunks = entry.pop('chunks')
                entry.pop('offsets')
                path = self.store_track(entry['key'], chunks, entry['size'])
                if path:
                    entry['path'], entry['reserved'] = path, 0
                    self.prune_tracks()
                else:
                    entry['data'] = b''.join(chunks)
                entry['mime'] = value['mime']
                for ref in refs:
                    if not entry['expected']:
                        self.announce(ref, dict(entry, expected=entry['size']))
                    self.deliver_complete(ref, entry)
                self.updated.notify_all()
            else:
                self.fail(refs)
                return
        if continuation:
            continuation()

    def fail(self, refs):
        for ref in refs:
            notify = self.streams.get(ref)
            self.cancel(ref)
            if notify:
                notify('failed', {})
            else:
                self.send(ref, 'failed', {})
