/* Supply the website's media-element view from the decoded playback clock. */
(() => {
    'use strict';
    if (location.origin !== 'https://music.163.com' ||
        location.pathname.replace(/\/$/, '') !== '/st/webplayer') return;
    const nodes = new WeakSet();
    function adapt(howl, sound) {
        const node = sound._node;
        if (!node || node instanceof HTMLMediaElement || nodes.has(node)) return;
        nodes.add(node);
        const position = () => {
            if (howl._state !== 'loaded') return 0;
            const value = howl.seek(sound._id);
            return Number.isFinite(value) ? value : 0;
        };
        const duration = () => {
            if (howl._state !== 'loaded') return NaN;
            const value = howl.duration();
            return Number.isFinite(value) ? value : NaN;
        };
        Object.defineProperties(node, {
            currentTime: {configurable: true, get: position,
                set: value => { if (Number.isFinite(Number(value))) howl.seek(Number(value), sound._id); }},
            duration: {configurable: true, get: duration},
            paused: {configurable: true, get: () => !howl.playing(sound._id)},
            ended: {configurable: true, get: () => !!sound._ended},
            readyState: {configurable: true, get: () => howl._state === 'loaded' ? 4 : 0},
            buffered: {configurable: true, get: () => ({length: howl._state === 'loaded' ? 1 : 0,
                start: () => 0, end: duration})}
        });
    }
    function update() {
        if (!window.Howler) return;
        for (const howl of window.Howler._howls || []) {
            if (!howl._webAudio) continue;
            for (const sound of howl._sounds || []) {
                adapt(howl, sound);
                if (sound._node && sound._node.dispatchEvent && howl._state === 'loaded')
                    sound._node.dispatchEvent(new Event('timeupdate'));
            }
        }
    }
    update();
    const timer = setInterval(update, 250);
    window.addEventListener('pagehide', () => clearInterval(timer));
})();
