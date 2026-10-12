/* Keep the website's media controls while supplying a native desktop identity. */
(function () {
    'use strict';
    if (location.origin !== 'https://music.163.com' ||
        location.pathname.replace(/\/$/, '') !== '/st/webplayer') return;
    const handlers = new Map();
    const observed = new WeakSet();
    let audio = null;
    let metadata = null;
    let lastSent = 0;
    const session = navigator.mediaSession;
    if (session && window.MediaMetadata) {
        const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(session), 'metadata');
        if (descriptor && descriptor.set) {
            // WebKit's built-in MPRIS uses ASCII for Identity and leaves DesktopEntry
            // empty. An empty native title prevents that duplicate service from
            // registering; the original metadata remains available to the website.
            const empty = new MediaMetadata({title: ''});
            descriptor.set.call(session, empty);
            Object.defineProperty(session, 'metadata', {
                configurable: true,
                get: function () { return metadata; },
                set: function (value) {
                    metadata = value;
                    descriptor.set.call(session, empty);
                    send(true);
                }
            });
        }
        const original = session.setActionHandler.bind(session);
        session.setActionHandler = function (action, handler) {
            original(action, handler);
            if (handler) handlers.set(action, handler);
            else handlers.delete(action);
            send(true);
        };
    }
    function send(force) {
        const now = performance.now();
        if (!force && now - lastSent < 1000) return;
        lastSent = now;
        let artwork = '';
        if (metadata && metadata.artwork && metadata.artwork.length)
            artwork = metadata.artwork[metadata.artwork.length - 1].src;
        const number = value => Number.isFinite(value) ? value : 0;
        window.webkit.messageHandlers.systemMedia.postMessage(JSON.stringify({
            active: !!(audio && (audio.currentSrc || audio.src)),
            playing: !!(audio && !audio.paused && !audio.ended),
            position: audio ? number(audio.currentTime) : 0,
            duration: audio ? number(audio.duration) : 0,
            volume: audio ? audio.volume : 1,
            metadata: {title: metadata ? metadata.title : document.title,
                artist: metadata ? metadata.artist : '', album: metadata ? metadata.album : '', artwork: artwork},
            actions: Array.from(handlers.keys())
        }));
    }
    function observe(element) {
        if (observed.has(element)) return;
        observed.add(element);
        ['playing', 'pause', 'ended', 'durationchange', 'timeupdate', 'seeked', 'volumechange', 'emptied'].forEach(event => {
            element.addEventListener(event, function () {
                if (event === 'playing') audio = element;
                if (audio === element) send(event !== 'timeupdate');
            });
        });
    }
    const originalPlay = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
        observe(this);
        // Ignore the empty Audio elements used by the site's capability probes.
        if (this.currentSrc || this.src) audio = this;
        return originalPlay.apply(this, arguments);
    };
    document.addEventListener('play', event => {
        if (event.target instanceof HTMLMediaElement) observe(event.target);
    }, true);
    window.addEventListener('pagehide', () => {
        window.webkit.messageHandlers.systemMedia.postMessage(JSON.stringify({active: false}));
    });
    window.addEventListener('pageshow', () => send(true));
    Object.defineProperty(window, '__neteaseSystemMedia', {value: function (action, args) {
        if (!audio) return;
        if (action === 'toggle') action = audio.paused ? 'play' : 'pause';
        if (action === 'seek') {
            args.seekTime = Math.max(0, audio.currentTime + args.offset);
            action = 'seekto';
        }
        if (action === 'seekto') {
            if (!Number.isFinite(audio.duration)) return;
            args.seekTime = Math.max(0, Math.min(audio.duration, args.seekTime));
        }
        if (handlers.has(action)) {
            handlers.get(action)(Object.assign({action: action}, args));
        } else if (action === 'play') {
            const promise = audio.play();
            if (promise && promise.catch) promise.catch(() => {});
        } else if (action === 'pause' || action === 'stop') {
            audio.pause();
            if (action === 'stop') audio.currentTime = 0;
        } else if (action === 'seekto') {
            audio.currentTime = args.seekTime;
        } else if (action === 'volume') {
            audio.volume = args.value;
        }
        send(true);
    }});
})();
