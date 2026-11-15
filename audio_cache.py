"""Private, bounded, range-capable in-memory audio transport."""
import base64
import secrets
import ssl
import subprocess
import tempfile
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from audio_buffer import AudioBuffer, MAX_BYTES


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
    def __init__(self, api, proxy_mode, send):
        self.send = send
        self.entries = {}
        self.lock = threading.RLock()
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
                    data = entry.get('data') if entry else None
                    mime = entry.get('mime') if entry else None
                if data is None:
                    self.send_error(404)
                    return
                try:
                    start, end, status = byte_range(self.headers.get('Range'), len(data))
                except (ValueError, TypeError):
                    self.send_response(416)
                    self.send_header('Content-Range', 'bytes */%d' % len(data))
                    self.send_header('Content-Length', '0')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    return
                self.send_response(status)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(end - start + 1))
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'close')
                if status == 206:
                    self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, len(data)))
                self.end_headers()
                if body:
                    try:
                        self.wfile.write(memoryview(data)[start:end + 1])
                    except (BrokenPipeError, ConnectionResetError):
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
        self.client = AudioBuffer(api, proxy_mode, self.receive)

    def request(self, identifier, uri):
        with self.lock:
            if identifier in self.entries or len(self.entries) >= 2:
                self.send(identifier, 'failed', {})
                return
            self.entries[identifier] = {'chunks': [], 'size': 0, 'reserved': 0}
        self.client.request(identifier, uri)

    def cancel(self, identifier):
        self.client.cancel(identifier)
        with self.lock:
            self.entries.pop(identifier, None)

    def cancel_all(self):
        self.client.cancel_all()
        with self.lock:
            self.entries.clear()

    def close(self):
        self.cancel_all()
        def stop():
            self.server.shutdown()
            self.server.server_close()
        threading.Thread(target=stop, daemon=True).start()

    def receive(self, identifier, event, value, continuation=None):
        with self.lock:
            entry = self.entries.get(identifier)
            if entry is None:
                return
            if event == 'head':
                requested = value['bytes']
                used = sum(item['reserved'] for key, item in self.entries.items() if key != identifier)
                if requested < 0 or requested + used > MAX_BYTES:
                    self.cancel(identifier)
                    self.send(identifier, 'failed', {})
                    return
                entry['reserved'] = requested
                self.send(identifier, 'head', value)
            elif event == 'chunk':
                data = base64.b64decode(value['data'])
                entry['size'] += len(data)
                entry['reserved'] = max(entry['reserved'], entry['size'])
                if sum(item['reserved'] for item in self.entries.values()) > MAX_BYTES:
                    self.cancel(identifier)
                    self.send(identifier, 'failed', {})
                    return
                entry['chunks'].append(data)
                self.send(identifier, 'progress', {'bytes': entry['size']})
            elif event == 'complete':
                entry['data'] = b''.join(entry.pop('chunks'))
                entry['mime'] = value['mime']
                self.send(identifier, 'complete', dict(value, url='https://127.0.0.1:%d%s%s' % (
                    self.server.server_port, self.prefix, identifier)))
            else:
                self.cancel(identifier)
                self.send(identifier, 'failed', {})
                return
        if continuation:
            continuation()
