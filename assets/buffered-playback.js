/* Select one complete copy or one stream before loading a track. Keep the
 * browser's media clock, state and events intact throughout playback. */
(function () {
    'use strict';
    if (location.origin !== 'https://music.163.com' ||
        location.pathname.replace(/\/$/, '') !== '/st/webplayer' ||
        typeof AbortController !== 'function') return;
    const LIMIT = 64 * 1024 * 1024;
    const WAIT = 6000;
    const states = new WeakMap();
    // Includes downloads, not just completed copies. Selected copies stay pinned
    // until the site replaces their source, even if the element is paused.
    const entries = new Set();
    const waiting = new Set();
    const proto = HTMLMediaElement.prototype;
    const nativePlay = proto.play, nativePause = proto.pause, nativeLoad = proto.load;
    const source = Object.getOwnPropertyDescriptor(proto, 'src');
    const currentSource = Object.getOwnPropertyDescriptor(proto, 'currentSrc');
    const rawSource = audio => source.get.call(audio);
    const setSource = (audio, value) => source.set.call(audio, value);
    const notify = (event, data = {}) => {
        const handlers = window.webkit && window.webkit.messageHandlers;
        if (handlers && handlers.playbackRecovery)
            handlers.playbackRecovery.postMessage(JSON.stringify(Object.assign({event}, data)));
    };
    const eligible = value => {
        try {
            const uri = new URL(value);
            return (uri.protocol === 'https:' || uri.protocol === 'http:') &&
                uri.hostname.endsWith('.music.126.net');
        } catch (_) { return false; }
    };
    const current = state => states.get(state.audio) === state;
    const aborted = () => new DOMException('Audio request cancelled', 'AbortError');
    const rejectWaiting = state => {
        for (const waiter of state.waiters.splice(0)) waiter.reject(aborted());
        for (const cancel of Array.from(state.replays)) cancel();
    };
    const release = state => {
        entries.delete(state);
        state.reserved = 0;
        if (state.release) state.release();
        state.release = null;
        state.copyURL = null;
    };
    const clearReady = state => {
        clearInterval(state.readyTimer);
        state.readyTimer = 0;
        state.deferred.length = 0;
    };
    const cancelDownload = state => {
        clearTimeout(state.timer);
        waiting.delete(state);
        if (state.controller) state.controller.abort();
    };
    const discard = state => {
        state.epoch++;
        clearTimeout(state.transitionTimer);
        cancelDownload(state);
        clearReady(state);
        rejectWaiting(state);
        release(state);
        states.delete(state.audio);
    };
    const reserve = (state, amount) => {
        if (!current(state) || state.mode !== 'waiting') throw aborted();
        const total = Array.from(entries).reduce((sum, item) => sum + item.reserved, 0);
        const extra = Math.max(0, amount - state.reserved);
        if ((!entries.has(state) && entries.size >= 2) || total + extra > LIMIT)
            throw new Error('Audio cache is full');
        entries.add(state);
        state.reserved += extra;
    };
    const invokePlay = state => {
        const epoch = state.epoch, resource = state.resource;
        const result = nativePlay.call(state.audio);
        if (!result || !result.catch) return result;
        return result.catch(error => {
            if (current(state) && state.epoch === epoch &&
                state.resource !== resource && rawSource(state.audio) === state.resource) {
                if (state.started && !state.audio.paused) return;
                // A failed copy can leave a stale decoder error until the new
                // resource reaches canplay. Do not immediately replay that error.
                return new Promise((resolve, reject) => {
                    let timer;
                    const cleanup = () => {
                        clearTimeout(timer);
                        state.audio.removeEventListener('canplay', ready);
                        state.replays.delete(cancel);
                    };
                    const cancel = () => { cleanup(); reject(aborted()); };
                    const ready = () => {
                        cleanup();
                        if (!current(state) || state.epoch !== epoch) { reject(aborted()); return; }
                        state.transitioning = false;
                        try { resolve(nativePlay.call(state.audio)); } catch (error) { reject(error); }
                    };
                    state.replays.add(cancel);
                    state.audio.addEventListener('canplay', ready);
                    timer = setTimeout(() => { cleanup(); state.transitioning = false; reject(error); }, 12000);
                    if (state.audio.readyState >= 3 && !state.audio.error) ready();
                });
            }
            throw error;
        });
    };
    const startWaitingPlay = state => {
        const waiters = state.waiters.splice(0);
        if (!waiters.length) return;
        try {
            Promise.resolve(invokePlay(state)).then(
                () => waiters.forEach(waiter => waiter.resolve()),
                error => waiters.forEach(waiter => waiter.reject(error)));
        } catch (error) { waiters.forEach(waiter => waiter.reject(error)); }
    };
    const select = (state, mode, reason) => {
        if (!current(state) || state.mode !== 'waiting') return;
        state.mode = mode;
        cancelDownload(state);
        if (mode === 'stream') release(state);
        state.resource = mode === 'copy' ? state.copyURL : state.source;
        notify(mode === 'copy' ? 'copy-start' : 'stream-start', {reason});
        state.audio.preload = 'auto';
        setSource(state.audio, state.resource);
        nativeLoad.call(state.audio);
        startWaitingPlay(state);
    };
    const fallback = (state, reason) => {
        if (!current(state)) return;
        if (state.mode === 'waiting') { select(state, 'stream', reason); return; }
        // A copy that cannot start may fall back once. Never replace a source
        // after it has played: a reload would invalidate the site's seek state.
        if (state.mode !== 'copy' || state.started || state.audio.currentTime > 0) return;
        clearReady(state);
        state.mode = 'stream';
        state.transitioning = true;
        state.transitionTimer = setTimeout(() => { state.transitioning = false; }, 12000);
        state.resource = state.source;
        setSource(state.audio, state.resource);
        nativeLoad.call(state.audio);
        release(state);
        notify('stream-start', {reason});
        startWaitingPlay(state);
    };
    const guarded = new WeakSet();

    const protect = audio => {
        if (guarded.has(audio)) return;
        guarded.add(audio);
        audio.addEventListener('playing', () => {
            const state = states.get(audio);
            if (state) {
                state.started = true;
                state.transitioning = false;
                clearTimeout(state.transitionTimer);
            }
        }, true);
        audio.addEventListener('error', event => {
            const state = states.get(audio);
            if (event.isTrusted && state && state.mode === 'copy' && !state.started && audio.currentTime === 0) {
                event.stopImmediatePropagation();
                fallback(state, 'copy-unavailable');
            }
        }, true);

    };
    const prepare = async state => {
        const controller = state.controller;
        try {
            reserve(state, 0);
            const progress = (received, total) => {
                try { reserve(state, Math.max(received, total)); }
                catch (_) { fallback(state, 'cache-limit'); }
            };
            if (!window.__musicFetchNativeAudio) throw new Error('Native cache unavailable');
            const response = await window.__musicFetchNativeAudio(state.source, controller.signal, progress);
            if (!current(state) || state.mode !== 'waiting') { response.release(); return; }
            state.release = typeof response.release === 'function' ? response.release : null;
            if (response.status !== 200 || !Number.isSafeInteger(response.bytes) || response.bytes <= 0 || !state.release)
                throw new Error('Complete audio unavailable');
            reserve(state, response.bytes);
            const bytes = response.bytes;
            state.copyURL = response.url;
            notify('buffer-ready', {bytes});
            select(state, 'copy', 'complete');
        } catch (error) {
            if (current(state) && state.mode === 'waiting') fallback(state, 'unavailable');
        }
    };
    const hold = (audio, value) => {
        const state = {audio, source: value, mode: 'waiting', resource: '', copyURL: null,
            release: null, reserved: 0, started: false, transitioning: false, epoch: 0, controller: new AbortController(),
            waiters: [], replays: new Set(), deferred: [], readyTimer: 0, transitionTimer: 0, timer: 0};
        states.set(audio, state);
        waiting.add(state);
        protect(audio);
        // Detach the previous song once; it must not continue during download.
        if (rawSource(audio)) { audio.removeAttribute('src'); nativeLoad.call(audio); }
        state.timer = setTimeout(() => fallback(state, 'timeout'), WAIT);
        prepare(state);
    };
    const synchronize = audio => {
        let state = states.get(audio);
        const raw = rawSource(audio);
        if (state && raw !== state.resource) { discard(state); state = null; }
        if (!state && eligible(raw)) { hold(audio, raw); state = states.get(audio); }
        return state;
    };
    proto.play = function () {
        const state = synchronize(this);
        if (state && state.mode === 'waiting')
            return new Promise((resolve, reject) => state.waiters.push({resolve, reject}));
        return state ? invokePlay(state) : nativePlay.apply(this, arguments);
    };
    proto.pause = function () {
        const state = states.get(this);
        if (state) { state.epoch++; rejectWaiting(state); }
        return nativePause.apply(this, arguments);
    };
    proto.load = function () {
        const state = synchronize(this);
        if (state) state.epoch++;
        if (state && state.mode === 'waiting') { rejectWaiting(state); return; }
        return nativeLoad.apply(this, arguments);
    };
    Object.defineProperty(proto, 'src', {
        configurable: source.configurable, enumerable: source.enumerable,
        get: function () {
            const state = states.get(this), raw = rawSource(this);
            return state && raw === state.resource ? state.source : raw;
        },
        set: function (value) {
            const state = states.get(this);
            if (state && value === state.source) {
                if (state.mode !== 'waiting') setSource(this, state.resource);
                return;
            }
            if (state) discard(state);
            if (typeof value === 'string' && eligible(value)) hold(this, value);
            else setSource(this, value);
        }
    });
    Object.defineProperty(proto, 'currentSrc', {
        configurable: currentSource.configurable, enumerable: currentSource.enumerable,
        get: function () {
            const state = states.get(this), raw = currentSource.get.call(this);
            return state && raw === state.copyURL ? state.source : raw;
        }
    });
    Object.defineProperty(window, '__musicHasCompleteAudio', {value: audio => {
        const state = states.get(audio);
        return !!(state && state.mode === 'copy' && rawSource(audio) === state.copyURL);
    }});
    Object.defineProperty(window, '__musicPlaybackManaged', {value: audio => {
        const state = states.get(audio);
        return !!(state && (state.mode === 'waiting' || state.transitioning));
    }});
    window.addEventListener('pagehide', event => {
        if (event.persisted) return;
        for (const state of Array.from(waiting)) discard(state);
        for (const state of Array.from(entries)) discard(state);
    });
})();
