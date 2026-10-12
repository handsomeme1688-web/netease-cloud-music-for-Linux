/* Decode complete music responses instead of repeatedly seeking remote ranges. */
(function () {
    'use strict';
    if (location.origin !== 'https://music.163.com' ||
        location.pathname.replace(/\/$/, '') !== '/st/webplayer' ||
        typeof fetch !== 'function' || typeof AbortController !== 'function') return;
    const limit = 64 * 1024 * 1024;
    const states = new WeakMap();
    const cached = new Set();
    const pending = new Set();
    const nativePlay = HTMLMediaElement.prototype.play;
    const nativePause = HTMLMediaElement.prototype.pause;
    const nativeLoad = HTMLMediaElement.prototype.load;
    const sourceProperty = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'src');
    const currentProperty = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'currentSrc');
    const actualSource = audio => sourceProperty ? sourceProperty.get.call(audio) : audio.src;
    const setSource = (audio, value) => sourceProperty ? sourceProperty.set.call(audio, value) : (audio.src = value);
    const cancelled = () => new DOMException('Playback was cancelled', 'AbortError');
    const notify = (event, data = {}) => {
        const handlers = window.webkit && window.webkit.messageHandlers;
        if (handlers && handlers.playbackRecovery)
            handlers.playbackRecovery.postMessage(JSON.stringify(Object.assign({event}, data)));
    };
    const eligible = source => {
        try {
            const uri = new URL(source);
            return (uri.protocol === 'https:' || uri.protocol === 'http:') &&
                uri.hostname.endsWith('.music.126.net');
        } catch (_) { return false; }
    };
    const release = state => {
        cached.delete(state);
        if (state.objectURL) {
            state.retiredURL = state.objectURL;
            URL.revokeObjectURL(state.objectURL);
            state.objectURL = null;
        }
    };
    const stateFor = audio => {
        let state = states.get(audio);
        let source = audio.src || audio.currentSrc || '';
        if (state && (source === state.objectURL || source === state.retiredURL)) source = state.source;
        if (state && source === state.source) return state;
        if (state) {
            state.intent++;
            if (state.controller) state.controller.abort();
            release(state);
        }
        if (!eligible(source)) return null;
        state = {audio: audio, source: source, intent: 0, wanted: false,
            objectURL: null, retiredURL: null, controller: null, promise: null,
            size: 0, fallback: false};
        states.set(audio, state);
        return state;
    };
    const prepare = state => {
        if (state.promise) return state.promise;
        if (state.objectURL || state.fallback) return Promise.resolve();
        if (actualSource(state.audio) === state.retiredURL) setSource(state.audio, state.source);
        const controller = new AbortController();
        pending.add(controller);
        state.controller = controller;
        const timeout = setTimeout(() => controller.abort(), 20000);
        const current = () => states.get(state.audio) === state &&
            (state.audio.src === state.source || state.audio.src === state.objectURL);
        state.promise = (async () => {
            // No credentials or range manipulation: use the site's authorized URL
            // and its CORS policy, through the existing WebKit network settings.
            const response = window.__musicFetchNativeAudio ?
                await window.__musicFetchNativeAudio(state.source, controller.signal) :
                await fetch(state.source, {cache: 'reload', signal: controller.signal});
            notify('buffer-response', {status: response.status});
            if (response.status !== 200 || !response.body || !response.body.getReader)
                throw new Error('A complete response is unavailable');
            const declared = Number(response.headers.get('Content-Length'));
            if (declared > limit) throw new Error('Audio exceeds the memory limit');
            const reader = response.body.getReader();
            const chunks = [];
            let size = 0;
            try {
                for (;;) {
                    const chunk = await reader.read();
                    if (chunk.done) break;
                    size += chunk.value.byteLength;
                    if (size > limit) throw new Error('Audio exceeds the memory limit');
                    chunks.push(chunk.value);
                }
            } catch (error) {
                await reader.cancel().catch(() => {});
                throw error;
            }
            if (!size || (declared > 0 && size !== declared)) throw new Error('Incomplete audio');
            if (!current()) throw cancelled();
            let used = Array.from(cached).reduce((total, item) => total + item.size, 0);
            for (const old of Array.from(cached)) {
                if (cached.size < 2 && used + size <= limit) break;
                if (old.audio.paused || old.audio.ended) { used -= old.size; release(old); }
            }
            if (cached.size >= 2 || used + size > limit) throw new Error('Audio cache is full');
            state.objectURL = URL.createObjectURL(new Blob(chunks, {
                type: response.headers.get('Content-Type') || 'audio/mpeg'}));
            state.size = size;
            notify('buffer-ready', {bytes: size});
            cached.add(state);
        })().catch(error => {
            controller.abort();
            if (!current()) throw cancelled();
            notify('buffer-fallback', {name: error.name});
            // A failed, unsupported or oversized full fetch keeps the normal
            // streaming path. Never change website authentication or TLS policy.
            state.fallback = true;
        }).finally(() => {
            clearTimeout(timeout);
            pending.delete(controller);
            state.controller = null;
            state.promise = null;
        });
        return state.promise;
    };
    HTMLMediaElement.prototype.load = function () {
        const state = stateFor(this);
        if (!state) return nativeLoad.apply(this, arguments);
        state.intent++;
        state.wanted = false;
        if (state.objectURL) setSource(this, state.objectURL);
        else if (!state.fallback) prepare(state).catch(() => {});
        return nativeLoad.apply(this, arguments);
    };
    HTMLMediaElement.prototype.play = function () {
        const state = stateFor(this);
        if (!state) return nativePlay.apply(this, arguments);
        state.wanted = true;
        const args = arguments;
        if (!state.objectURL && !state.fallback) prepare(state).catch(() => {});
        return nativePlay.apply(this, args);
    };
    HTMLMediaElement.prototype.pause = function () {
        const state = states.get(this);
        if (state) { state.intent++; state.wanted = false; }
        return nativePause.apply(this, arguments);
    };
    if (sourceProperty && currentProperty) {
        // The site's player compares source URLs and otherwise reloads a track.
        // Keep its requested URL visible while the native decoder reads the blob.
        Object.defineProperty(HTMLMediaElement.prototype, 'src', {
            configurable: sourceProperty.configurable, enumerable: sourceProperty.enumerable,
            get: function () {
                const source = sourceProperty.get.call(this), state = states.get(this);
                return state && (source === state.objectURL || source === state.retiredURL) ? state.source : source;
            },
            set: function (value) {
                const state = states.get(this);
                if (state && value === state.source) {
                    sourceProperty.set.call(this, state.objectURL || value);
                    return;
                }
                if (state) {
                    state.intent++;
                    if (state.controller) state.controller.abort();
                    release(state);
                    states.delete(this);
                }
                sourceProperty.set.call(this, value);
            }
        });
        Object.defineProperty(HTMLMediaElement.prototype, 'currentSrc', {
            configurable: currentProperty.configurable, enumerable: currentProperty.enumerable,
            get: function () {
                const source = currentProperty.get.call(this), state = states.get(this);
                return state && (source === state.objectURL || source === state.retiredURL) ? state.source : source;
            }
        });
    }
    Object.defineProperty(window, '__musicHasCompleteAudio', {value: audio => {
        const state = states.get(audio);
        return !!(state && state.objectURL && audio.src === state.source);
    }});
    window.addEventListener('pagehide', event => {
        if (event.persisted) return;
        for (const controller of pending) controller.abort();
        for (const state of cached) release(state);
    });
})();
