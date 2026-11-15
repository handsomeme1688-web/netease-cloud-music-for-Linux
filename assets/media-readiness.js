/* WebKit can play cached audio without issuing canplaythrough. Use the
 * supported canplay event and keep queued seeks attached to their source. */
(() => {
    'use strict';
    if (location.origin !== 'https://music.163.com' ||
        location.pathname.replace(/\/$/, '') !== '/st/webplayer') return;
    const patched = new WeakSet(), sources = new WeakMap();
    const key = howl => Array.isArray(howl._src) ? howl._src.join('\n') : String(howl._src || '');
    function configure() {
        const global = window.Howler, Howl = window.Howl;
        if (!global) return false;
        global._canPlayEvent = 'canplay';
        for (const howl of global._howls || []) {
            if (!sources.has(howl)) sources.set(howl, key(howl));
            if (howl._state !== 'loading') continue;
            for (const sound of howl._sounds || []) {
                const audio = sound._node;
                if (!audio || !sound._loadFn) continue;
                audio.removeEventListener('canplaythrough', sound._loadFn, false);
                audio.removeEventListener('canplay', sound._loadFn, false);
                audio.addEventListener('canplay', sound._loadFn, false);
                if (audio.readyState >= 3 && Number.isFinite(audio.duration) && audio.duration > 0)
                    sound._loadFn();
            }
        }
        if (!Howl || !Howl.prototype) return false;
        const proto = Howl.prototype;
        if (patched.has(proto)) return true;
        patched.add(proto);
        const load = proto.load, seek = proto.seek, play = proto.play;
        proto.play = function () {
            // After an HTML5 seek, WebKit may wait for play() to preroll while
            // Howler waits for canplay before calling play(): break that cycle.
            if (!this._webAudio && this._state === 'loaded') {
                const id = typeof arguments[0] === 'number' ? arguments[0] : null;
                for (const sound of this._sounds || []) {
                    if (id !== null && sound._id !== id) continue;
                    const audio = sound._node;
                    if (audio && audio.paused && audio.readyState === 2 && !audio.error &&
                        (audio.src || audio.currentSrc)) {
                        const pending = audio.play();
                        if (pending && pending.catch) pending.catch(() => {});
                        break;
                    }
                }
            }
            return play.apply(this, arguments);
        };
        proto.load = function () {
            const source = key(this), previous = sources.get(this);
            if (previous !== undefined && previous !== source) {
                this._playLock = false;
                this._queue = (this._queue || []).filter(item => item.event !== 'seek');
                for (const sound of this._sounds || []) {
                    if (this._clearTimer) this._clearTimer(sound._id);
                    sound._seek = 0;
                    sound._rateSeek = 0;
                    sound._paused = true;
                    sound._ended = true;
                }
                if (this._sprite) delete this._sprite.__default;
            }
            sources.set(this, source);
            const result = load.apply(this, arguments);
            sources.set(this, key(this));
            return result;
        };
        proto.seek = function () {
            const before = new Set(this._queue || []), source = key(this);
            const result = seek.apply(this, arguments);
            for (const item of this._queue || []) {
                if (before.has(item) || item.event !== 'seek') continue;
                const action = item.action, howl = this;
                item.action = function () {
                    if (key(howl) === source) return action.apply(this, arguments);
                    // Let a rejected old request leave the queue normally.
                    if (howl._loadQueue) howl._loadQueue('seek');
                };
            }
            return result;
        };
        return true;
    }
    // Configure synchronously when the library publishes its globals, before
    // the first track can register a canplaythrough listener.
    for (const name of ['Howler', 'Howl']) {
        const descriptor = Object.getOwnPropertyDescriptor(window, name);
        if (descriptor && (!descriptor.configurable || descriptor.get || descriptor.set)) continue;
        let value = descriptor && descriptor.value;
        Object.defineProperty(window, name, {configurable: true, enumerable: true,
            get: () => value, set: next => { value = next; configure(); }});
    }
    if (!configure()) {
        let attempts = 0;
        const timer = setInterval(() => {
            if (configure() || ++attempts >= 300) clearInterval(timer);
        }, 100);
        window.addEventListener('pagehide', () => clearInterval(timer));
    }
})();
