/* Read the official player's lyrics only while the desktop window is open. */
(() => {
    'use strict';
    if (location.origin !== 'https://music.163.com' ||
        location.pathname.replace(/\/$/, '') !== '/st/webplayer') return;
    const handler = window.webkit?.messageHandlers?.desktopLyrics;
    if (!handler) return;

    const send = (event, data) => handler.postMessage(JSON.stringify({event, ...data}));
    const cached = new Map();
    let visible = false, queued = false, song = null, title = '', stream = '', position, advancing, pending, poll;

    async function load(id) {
        if (cached.has(id)) {
            send('lyrics', {id, ...cached.get(id)});
            return;
        }
        const request = pending = new AbortController();
        const timer = setTimeout(() => request.abort(), 12000);
        try {
            const response = await fetch('/api/song/lyric/v1?id=' + id + '&lv=1&tv=1&yv=1&ytv=1',
                {signal: request.signal});
            if (!response.ok) throw new Error('Lyrics request failed');
            const data = await response.json();
            if (pending !== request) return;
            if (data.code !== 200) throw new Error('Lyrics unavailable');
            const read = name => typeof data[name]?.lyric === 'string' ? data[name].lyric.slice(0, 180000) : '';
            const result = {lrc: read('lrc'), yrc: read('yrc'), translation: read('tlyric'),
                wordTranslation: read('ytlrc')};
            cached.set(id, result);
            if (cached.size > 8) cached.delete(cached.keys().next().value);
            send('lyrics', {id, ...result});
        } catch (_) {
            if (pending === request) send('lyrics', {id, failed: true});
        } finally {
            clearTimeout(timer);
            if (pending === request) pending = null;
        }
    }

    function refresh() {
        if (!visible) return;
        const current = window.__musicLyricPlayback?.();
        const id = /^[1-9]\d{0,12}$/.test(current?.id || '') ? current.id : '';
        const nextTitle = String(current?.title || '').slice(0, 220);
        const nextStream = current?.stream || '';
        const changed = id !== song;
        if (changed || nextTitle !== title || nextStream !== stream) {
            ({title, stream} = {title: nextTitle, stream: nextStream});
            song = id;
            position = undefined;
            send('track', {id, title, stream, position: current?.position});
        }
        if (changed) {
            const old = pending;
            pending = null;
            old?.abort();
            if (id) load(id);
        }
        if (id && !stream && Number.isFinite(current?.position) &&
            (current.position !== position || Boolean(current.advancing) !== advancing)) {
            position = current.position;
            advancing = Boolean(current.advancing);
            send('position', {id, position, advancing});
        }
    }

    function scheduleRefresh() {
        if (!visible || queued) return;
        queued = true;
        Promise.resolve().then(() => {
            queued = false;
            refresh();
        }).catch(error => console.warn('桌面歌词状态更新失败', error));
    }

    function setVisible(enabled) {
        if (enabled === visible) return;
        visible = enabled;
        if (enabled) {
            scheduleRefresh();
            poll = setInterval(() => { if (!stream) scheduleRefresh(); }, 250);
        } else {
            clearInterval(poll);
            song = null;
            title = stream = '';
            const old = pending;
            pending = null;
            old?.abort();
        }
    }

    Object.defineProperty(window, '__musicDesktopLyrics', {value: {refresh: scheduleRefresh, setVisible}});
    window.addEventListener('pagehide', () => setVisible(false));
})();
