/* Receive bounded audio chunks from the application's native music CDN client. */
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
        if (event === 'chunk') {
            const data = atob(value.data);
            const bytes = new Uint8Array(data.length);
            for (let index = 0; index < data.length; index++) bytes[index] = data.charCodeAt(index);
            request.size += bytes.length;
            if (request.size > 64 * 1024 * 1024) {
                request.reject(new Error('Audio exceeds the memory limit'));
                requests.delete(id);
                send({event: 'cancel', id});
            } else request.chunks.push(bytes);
        } else {
            requests.delete(id);
            request.signal.removeEventListener('abort', request.abort);
            if (event !== 'complete' || value.bytes !== request.size) {
                request.reject(new Error('A complete audio response is unavailable'));
                return;
            }
            let index = 0;
            request.resolve({status: 200, headers: {get: name =>
                name === 'Content-Length' ? String(value.bytes) : value.mime},
                body: {getReader: () => ({read: async () => index < request.chunks.length ?
                    {done: false, value: request.chunks[index++]} : {done: true},
                    cancel: async () => {request.chunks.length = 0;}})}});
        }
    }});
    Object.defineProperty(window, '__musicFetchNativeAudio', {value: (url, signal) => new Promise((resolve, reject) => {
        const id = prefix + (++counter);
        const abort = () => {
            requests.delete(id);
            send({event: 'cancel', id});
            reject(new DOMException('Audio download was cancelled', 'AbortError'));
        };
        if (signal.aborted) { abort(); return; }
        requests.set(id, {resolve, reject, chunks: [], size: 0, signal, abort});
        signal.addEventListener('abort', abort, {once: true});
        send({event: 'request', id, url});
    })});
})();
