/* Obtain an opaque, range-capable address for a complete native audio copy. */
(function () {
    'use strict';
    if (location.origin !== 'https://music.163.com' ||
        location.pathname.replace(/\/$/, '') !== '/st/webplayer') return;
    const requests = new Map();
    const prefix = Date.now().toString(36) + '-';
    let counter = 0;
    const send = value => window.webkit.messageHandlers.nativeAudio.postMessage(JSON.stringify(value));
    Object.defineProperty(window, '__musicNativeAudio', {value: (id, event, value) => {
        const request = requests.get(id);
        if (!request) return;
        if (event === 'head' || event === 'progress') {
            if (event === 'head') request.total = value.bytes;
            else request.size = value.bytes;
            if (request.progress) request.progress(request.size, request.total);
            return;
        }
        requests.delete(id);
        request.signal.removeEventListener('abort', request.abort);
        if (event !== 'complete' || !/^https:\/\/127\.0\.0\.1:\d+\/[\w-]+\/[\w-]+$/.test(value.url || '')) {
            request.reject(new Error('Complete audio unavailable'));
            return;
        }
        request.resolve({status: 200, bytes: value.bytes, url: value.url, persisted: value.persisted === true,
            release: () => send({event: 'cancel', id})});
    }});
    Object.defineProperty(window, '__musicFetchNativeAudio', {value: (url, signal, progress, background = false) => new Promise((resolve, reject) => {
        const id = prefix + (++counter);
        const abort = () => {
            requests.delete(id);
            send({event: 'cancel', id});
            reject(new DOMException('Audio download cancelled', 'AbortError'));
        };
        if (signal.aborted) { reject(new DOMException('Audio download cancelled', 'AbortError')); return; }
        requests.set(id, {resolve, reject, signal, abort, progress, size: 0, total: 0});
        signal.addEventListener('abort', abort, {once: true});
        send({event: 'request', id, url, background});
    })});
})();
