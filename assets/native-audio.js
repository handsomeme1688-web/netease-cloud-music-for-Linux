/* Receive bounded audio chunks from the application's native music CDN client. */
(function () {
    'use strict';
    if (location.origin !== 'https://music.163.com' ||
        location.pathname.replace(/\/$/, '') !== '/st/webplayer') return;
    const requests = new Map();
    const prefix = Date.now().toString(36) + '-';
    let counter = 0;
    const send = value => window.webkit.messageHandlers.nativeAudio.postMessage(JSON.stringify(value));
    const report = request => {
        if (typeof request.progress !== 'function') return;
        try { request.progress(request.size, request.total); } catch (_) {}
    };
    Object.defineProperty(window, '__musicNativeAudio', {value: (id, event, value) => {
        const request = requests.get(id);
        if (!request) return;
        if (event === 'head') {
            request.total = Number(value.bytes) || 0;
            report(request);
        } else if (event === 'chunk') {
            const data = atob(value.data);
            const bytes = new Uint8Array(data.length);
            for (let index = 0; index < data.length; index++) bytes[index] = data.charCodeAt(index);
            request.size += bytes.length;
            if (request.size > 64 * 1024 * 1024) {
                request.reject(new Error('Audio exceeds the memory limit'));
                request.signal.removeEventListener('abort', request.abort);
                request.chunks.length = 0;
                requests.delete(id);
                send({event: 'cancel', id});
            } else {
                request.chunks.push(bytes);
                report(request);
            }
        } else {
            requests.delete(id);
            request.signal.removeEventListener('abort', request.abort);
            if (event !== 'complete' || value.bytes !== request.size) {
                request.reject(new Error('A complete audio response is unavailable'));
                return;
            }
            request.resolve({status: 200, headers: {get: name => {
                name = name.toLowerCase();
                return name === 'content-length' ? String(value.bytes) :
                    name === 'content-type' ? value.mime : null;
            }},
                body: {getReader: () => ({read: async () => request.chunks.length ?
                    {done: false, value: request.chunks.shift()} : {done: true},
                    cancel: async () => {request.chunks.length = 0;}})}});
        }
    }});
    Object.defineProperty(window, '__musicFetchNativeAudio', {value: (url, signal, progress) => new Promise((resolve, reject) => {
        const id = prefix + (++counter);
        const abort = () => {
            const request = requests.get(id);
            if (request) request.chunks.length = 0;
            requests.delete(id);
            send({event: 'cancel', id});
            reject(new DOMException('Audio download was cancelled', 'AbortError'));
        };
        if (signal.aborted) { abort(); return; }
        requests.set(id, {resolve, reject, chunks: [], size: 0, total: 0, signal, abort, progress});
        signal.addEventListener('abort', abort, {once: true});
        send({event: 'request', id, url});
    })});
})();
