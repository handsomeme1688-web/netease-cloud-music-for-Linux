(() => {
    "use strict";
    if (window.__musicPlaybackRecovery) return;
    window.__musicPlaybackRecovery = true;

    const states = new WeakMap();
    const active = new Set();
    const nativePlay = HTMLMediaElement.prototype.play;
    const nativePause = HTMLMediaElement.prototype.pause;
    const nativeLoad = HTMLMediaElement.prototype.load;
    const notify = event => {
        const handlers = window.webkit && window.webkit.messageHandlers;
        if (handlers && handlers.playbackRecovery) {
            handlers.playbackRecovery.postMessage(JSON.stringify({event}));
        }
    };

    const cancelRecovery = (audio, state) => {
        clearTimeout(state.timeout);
        if (state.resume) audio.removeEventListener("canplay", state.resume);
        state.resume = null;
        state.timeout = null;
        state.recovering = false;
    };

    const stop = (audio, state) => {
        state.generation += 1;
        for (const waiter of state.waiters.splice(0)) waiter.reject(waiter.error);
        state.wanted = false;
        state.loading = false;
        active.delete(audio);
        cancelRecovery(audio, state);
    };

    const observe = audio => {
        let state = states.get(audio);
        if (state) return state;
        state = {wanted: false, loading: false, started: false, retries: 0,
            source: "", position: 0, progress: Date.now(), recovering: false,
            generation: 0, waiters: []};
        states.set(audio, state);
        audio.addEventListener("playing", () => {
            state.started = true;
            state.loading = false;
            state.progress = Date.now();
            state.position = audio.currentTime;
            if (state.wanted) active.add(audio);
            notify("playing");
        });
        audio.addEventListener("canplay", () => {
            state.loading = false;
            if (!state.wanted && !state.recovering) active.delete(audio);
        });
        audio.addEventListener("pause", () => {
            if (!state.recovering && !state.loading) stop(audio, state);
        });
        audio.addEventListener("ended", () => stop(audio, state));
        audio.addEventListener("error", () => {
            const requested = state.wanted || state.loading;
            stop(audio, state);
            if (requested) notify("failed");
        });
        return state;
    };

    const recover = (audio, state) => {
        const wanted = state.wanted;
        const position = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
        const generation = state.generation;
        state.retries += 1;
        state.recovering = true;
        notify("retry");
        const fail = () => {
            if (state.generation !== generation) return;
            stop(audio, state);
            notify("failed");
        };
        state.resume = () => {
            if (state.generation !== generation) return;
            audio.removeEventListener("canplay", state.resume);
            state.resume = null;
            if (wanted && !state.wanted) return;
            try {
                if (wanted && position > 0) audio.currentTime = position;
                const result = wanted ? nativePlay.call(audio) : null;
                const complete = () => {
                    if (state.generation !== generation) return;
                    for (const waiter of state.waiters.splice(0)) waiter.resolve();
                    cancelRecovery(audio, state);
                    state.loading = false;
                    state.progress = Date.now();
                    state.position = audio.currentTime;
                    if (!state.wanted) active.delete(audio);
                };
                if (result && typeof result.then === "function") result.then(complete, fail);
                else complete();
            } catch (_) {
                fail();
            }
        };
        audio.addEventListener("canplay", state.resume);
        state.timeout = setTimeout(fail, 12000);
        try {
            nativeLoad.call(audio);
        } catch (_) {
            fail();
        }
    };

    HTMLMediaElement.prototype.play = function (...args) {
        // Audio libraries probe empty elements while preparing their pool.
        if (!this.src && !this.currentSrc && !this.querySelector("source")) {
            return nativePlay.apply(this, args);
        }
        const state = observe(this);
        const generation = state.generation;
        state.wanted = true;
        state.progress = Date.now();
        state.position = this.currentTime;
        active.add(this);
        const result = nativePlay.apply(this, args);
        if (!result || typeof result.catch !== "function") return result;
        return result.catch(error => {
            // Our reload can abort a still-pending play request. Keep the site's
            // request pending until recovery succeeds or is explicitly stopped.
            if (error && error.name === "AbortError" && state.recovering
                    && state.generation === generation) {
                return new Promise((resolve, reject) => state.waiters.push({resolve, reject, error}));
            }
            throw error;
        });
    };
    HTMLMediaElement.prototype.pause = function (...args) {
        const state = states.get(this);
        if (state) stop(this, state);
        return nativePause.apply(this, args);
    };
    HTMLMediaElement.prototype.load = function (...args) {
        const state = observe(this);
        stop(this, state);
        const source = this.src || this.currentSrc || "";
        if (source !== state.source) {
            state.source = source;
            state.retries = 0;
            state.started = false;
        }
        state.loading = Boolean(source);
        state.progress = Date.now();
        state.position = this.currentTime;
        if (state.loading) active.add(this);
        return nativeLoad.apply(this, args);
    };

    const poll = () => {
        const now = Date.now();
        for (const audio of active) {
            const state = states.get(audio);
            if (state.recovering) continue;
            if (audio.error || audio.ended || (!state.loading && (!state.wanted || audio.paused))) {
                stop(audio, state);
                continue;
            }
            if (Math.abs(audio.currentTime - state.position) > 0.05) {
                state.position = audio.currentTime;
                state.progress = now;
                continue;
            }
            if (now - state.progress < (audio.seeking ? 30000 : 15000)) continue;
            if (state.retries >= 2) {
                stop(audio, state);
                notify("failed");
            } else if (state.loading || state.started) {
                recover(audio, state);
            }
        }
    };
    let timer = setInterval(poll, 1000);
    window.addEventListener("pagehide", () => {
        clearInterval(timer);
        timer = null;
        for (const audio of active) stop(audio, states.get(audio));
    });
    window.addEventListener("pageshow", () => {
        if (timer === null) timer = setInterval(poll, 1000);
    });
})();
