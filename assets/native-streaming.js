/* Adapt the website's track controls to the native playback clock. */
(() => {
    'use strict';
    if (location.origin !== 'https://music.163.com' ||
        location.pathname.replace(/\/$/, '') !== '/st/webplayer') return;
    const handler = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.streamPlayer;
    if (!handler) return;
    let active = null, nextId = 0;
    const report = (name, detail) => window.dispatchEvent(new CustomEvent('music-audio-' + name, {detail}));
    const post = (id, event, value, url, position) =>
        handler.postMessage(JSON.stringify({id, event, value, url, position}));
    const formats = new Set(['mp3', 'flac', 'm4a', 'aac', 'ogg', 'wav']);
    const canStream = (source, format) => formats.has(format ||
        /\.([^./?#]+)$/.exec(source.split(/[?#]/, 1)[0])?.[1].toLowerCase());
    Object.defineProperty(window, '__musicCanStreamSource', {value: canStream});

    function adapt(howl, options, source) {
        if (!canStream(source, window.__musicStreamType?.(source))) return false;
        let id;
        const handlers = new Map();
        let position = 0, duration = 0, bytes = 0, total = 0, wanted = false;
        let started = false, prefetch = false, volume = options.volume ?? 1, muted = !!options.mute;
        let rate = options.rate || 1, loaded = false, earlyEnd = false, lastProgress, canMix;
        const on = (name, fn, once) => {
            if (typeof fn === 'function') {
                if (!handlers.has(name)) handlers.set(name, []);
                handlers.get(name).push({fn, once});
            }
            return howl;
        };
        const emit = (name, data) => {
            const listeners = handlers.get(name) || [];
            handlers.set(name, listeners.filter(listener => !listener.once));
            for (const {fn} of listeners) fn.call(howl, 1, data);
        };
        const gain = () => muted ? 0 : volume;
        for (const name of ['load', 'loaderror', 'playerror', 'play', 'pause', 'seek', 'stop', 'end', 'volume']) {
            on(name, options['on' + name], false);
        }
        howl._src = [source];
        howl._state = 'unloaded';
        howl._webAudio = false;
        howl._buffering = false;
        howl._sounds = [{_id: 1, _node: {
            get duration() { return duration; },
            get currentTime() { return position; },
            get paused() { return !howl.playing(); },
            get buffered() { return {length: total && duration ? 1 : 0, end: () => duration * bytes / total}; }
        }}];
        const progress = visible => {
            const label = visible ? (total ? Math.floor(100 * bytes / total) : -1) : null;
            if (lastProgress === label) return;
            lastProgress = label;
            report('progress', {howl, loading: visible, bytes, total});
        };
        const accept = (event, state) => {
            if (event === 'error') {
                wanted = started = false;
                if (active && active.id === id) active = null;
                howl._state = 'unloaded';
                progress(false);
                emit(loaded ? 'playerror' : 'loaderror', 'Audio could not be loaded');
                loaded = false;
                report('load-error', howl);
                return;
            }
            const previousPosition = position;
            ({position, duration, bytes, total} = state);
            howl._buffering = state.buffering;
            if (event === 'load') {
                loaded = true;
                howl._state = 'loaded';
                if (rate !== 1) post(id, 'rate', rate);
                emit('load');
            }
            if (state.playing && wanted && !started) {
                started = true;
                emit('play');
            }
            if (event === 'seek') emit('seek');
            if (event === 'transition' || event === 'advance') {
                if (!wanted || !started || !canMix || !canMix()) {
                    post(id, 'discard-prepare');
                    return;
                }
                if (event === 'transition') {
                    post(id, 'mix');
                    return;
                }
                earlyEnd = true;
            }
            if (event === 'advance' || event === 'end' && !earlyEnd) {
                wanted = started = false;
                emit('end');
            }
            // Once loaded, seek buffering belongs to the playback state.
            progress(!loaded);
            if (event === 'tick' && loaded && wanted && state.playing && !state.buffering &&
                position > 0 && position !== previousPosition) {
                report('clock', {howl, position, cacheProgress: total ? Math.min(1, bytes / total) : 0});
            }
            if (!prefetch && !state.transitioning && started && wanted && total && bytes >= total) {
                prefetch = true;
                report('ready', howl);
            }
        };
        Object.assign(howl, {
            on: (name, fn) => on(name, fn, false),
            once: (name, fn) => on(name, fn, true),
            off(name, fn) {
                if (!name) handlers.clear();
                else handlers.set(name, fn ? (handlers.get(name) || []).filter(listener => listener.fn !== fn) : []);
                return howl;
            },
            state: () => howl._state,
            load() {
                if (howl._state !== 'unloaded') return howl;
                id = Date.now().toString(36) + '-' + (++nextId);
                position = duration = bytes = total = 0;
                loaded = wanted = started = earlyEnd = prefetch = false;
                lastProgress = canMix = undefined;
                howl._buffering = false;
                active = {id, howl, accept, prepare(url, duration, valid) {
                    canMix = valid;
                    post(id, 'prepare', duration, url);
                }};
                howl._state = 'loading';
                report('stream-open', howl);
                progress(true);
                window.__musicDiscardPreload?.(source);
                post(id, 'load', gain(), source, window.__musicStreamStartPosition?.(source));
                window.__musicDiscardPreload?.();
                return howl;
            },
            play() {
                if (howl._state === 'unloaded') howl.load();
                earlyEnd = false;
                wanted = true;
                post(id, 'play');
                return 1;
            },
            pause() {
                const notify = wanted;
                wanted = started = false;
                post(id, 'pause');
                if (notify) emit('pause');
                return howl;
            },
            stop() {
                wanted = started = false;
                position = 0;
                post(id, 'stop');
                emit('stop');
                return howl;
            },
            unload() {
                wanted = started = false;
                howl._state = 'unloaded';
                if (active && active.id === id) active = null;
                post(id, 'unload');
                progress(false);
                return null;
            },
            seek(value) {
                if (typeof value !== 'number') return position;
                post(id, 'seek', value);
                return howl;
            },
            duration: () => duration,
            playing: () => wanted && started,
            volume(value) {
                if (typeof value !== 'number') return volume;
                volume = value;
                post(id, 'volume', gain());
                emit('volume');
                return howl;
            },
            mute(value) {
                muted = Boolean(value);
                post(id, 'volume', gain());
                return howl;
            },
            rate(value) {
                if (typeof value !== 'number') return rate;
                rate = value;
                if (loaded) post(id, 'rate', value);
                return howl;
            }
        });
        if (options.preload !== false) howl.load();
        if (options.autoplay) howl.play();
        return true;
    }
    Object.defineProperties(window, {
        __musicStreamingHowl: {value: adapt},
        __musicStreamingActive: {value: () => active && active.howl},
        __musicStreamingId: {value: () => active && active.id},
        __musicPrepareTransition: {value: (howl, url, duration, valid) => {
            if (active && active.howl === howl) active.prepare(url, duration, valid);
        }},
        __musicStreamEvent: {value: (id, event, state) => {
            if (active && active.id === id) active.accept(event, state);
        }}
    });
})();
