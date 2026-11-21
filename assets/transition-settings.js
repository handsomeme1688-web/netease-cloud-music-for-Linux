(() => {
    'use strict';
    if (location.origin !== 'https://music.163.com' || location.pathname.replace(/\/$/, '') !== '/st/webplayer') return;
    const handler = window.webkit.messageHandlers.transitionSettings;
    const lyricSettings = window.webkit.messageHandlers.desktopLyricsSettings;
    const row = document.createElement('div');
    const root = row.attachShadow({mode: 'closed'});
    root.innerHTML = `
        <style>
            :host{display:block;color:inherit;font-size:var(--music-setting-font-size,14px);line-height:20px}
            .row{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 8px}
            .row>span{flex:0 0 var(--music-setting-label-width,7em)}
            .controls,.options,.duration{display:flex;align-items:center;flex-wrap:wrap}
            .controls{flex:1 1 16em;min-width:0;gap:6px 20px}
            .options{gap:4px 20px}
            .options label{display:inline-flex;align-items:center;gap:8px;min-height:24px;white-space:nowrap;cursor:pointer}
            input[type="radio"],input[type="checkbox"]{flex:none;width:16px;height:16px;margin:0;accent-color:#ff3348}
            .desktop-lyrics{margin-top:14px}
            .desktop-lyrics label{display:inline-flex;align-items:center;gap:8px;min-height:24px;cursor:pointer}
            .duration{gap:4px 8px}
            input[type="number"]{box-sizing:border-box;width:4.5em;min-height:var(--music-setting-control-height,28px);font:inherit;color:inherit;background:transparent;border:1px solid #8886;border-radius:6px;padding:2px 8px}
            [hidden]{display:none}
            .error:not(:empty){display:block;margin-top:6px}
        </style>
        <div class="row">
            <span id="transition-label">歌曲过渡</span>
            <div class="controls">
                <div class="options" role="radiogroup" aria-labelledby="transition-label">
                    <label><input type="radio" name="mode" value="off" disabled>关闭</label>
                    <label><input type="radio" name="mode" value="fade" disabled>淡入淡出</label>
                    <label><input type="radio" name="mode" value="mix" disabled>混音过渡</label>
                </div>
                <div class="duration" hidden>
                    <label for="seconds">过渡时长</label>
                    <input id="seconds" type="number" min="1" max="12" step="1" value="3">
                    <span>秒</span>
                </div>
            </div>
        </div>
        <div class="row desktop-lyrics" hidden>
            <span>桌面歌词</span>
            <label><input id="desktop-lyrics" type="checkbox" disabled>显示悬浮歌词</label>
        </div>
        <span class="error" role="status"></span>`;
    const modes = [...root.querySelectorAll('input[name="mode"]')];
    const seconds = root.querySelector('#seconds');
    const duration = root.querySelector('.duration');
    const status = root.querySelector('.error');
    const lyrics = root.querySelector('#desktop-lyrics');
    const lyricButton = lyricSettings && document.createElement('button');
    let savedSeconds = 3;
    window.updateMusicTransition = (settings, error) => {
        for (const radio of modes) {
            radio.checked = radio.value === settings.mode;
            radio.disabled = false;
        }
        seconds.value = savedSeconds = settings.seconds;
        duration.hidden = settings.mode === 'off';
        status.textContent = error;
    };
    if (lyricSettings) {
        const style = document.createElement('style');
        style.textContent = `
            .ncm-lyrics-button{flex:none;align-self:center;min-width:22px;padding:0 4px;
                box-sizing:border-box;font:inherit;font-size:12px;line-height:20px;
                color:inherit;opacity:.75;background:transparent;border:1px solid currentColor;
                border-radius:4px;cursor:pointer}
            .ncm-lyrics-button[hidden]{display:none}
            .ncm-lyrics-button:hover{opacity:1}
            .ncm-lyrics-button[aria-pressed="true"]{color:#ff3348;opacity:1;background:#ff334815}`;
        document.head.appendChild(style);
        lyricButton.type = 'button';
        lyricButton.className = 'ncm-lyrics-button';
        lyricButton.textContent = '词';
        lyricButton.title = '桌面歌词（Ctrl+D）';
        lyricButton.setAttribute('aria-label', '桌面歌词');
        lyricButton.setAttribute('aria-pressed', 'false');
        lyricButton.addEventListener('click', event => {
            if (event.isTrusted) lyricSettings.postMessage('toggle');
        });
        root.querySelector('.desktop-lyrics').hidden = false;
        window.updateDesktopLyricsSetting = enabled => {
            lyrics.checked = enabled;
            lyrics.disabled = false;
            lyricButton.setAttribute('aria-pressed', String(enabled));
        };
        lyrics.addEventListener('change', event => {
            if (event.isTrusted) lyricSettings.postMessage(lyrics.checked ? 'show' : 'hide');
        });
    }
    function save(event) {
        if (!event.isTrusted) return;
        const mode = modes.find(radio => radio.checked);
        if (!mode) return;
        if (!seconds.value || !seconds.validity.valid) {
            seconds.value = savedSeconds;
            status.textContent = '时长可设为 1 至 12 秒。';
            return;
        }
        handler.postMessage(JSON.stringify({mode: mode.value, seconds: Number(seconds.value)}));
    }
    for (const radio of modes) radio.addEventListener('change', save);
    seconds.addEventListener('change', save);
    function mount() {
        const playback = document.querySelector('#page_pc_setting #play > .play');
        if (playback && row.parentNode !== playback) {
            const quality = playback.querySelector('.ncm-quality-setting-row');
            playback.insertBefore(row, quality ? quality.nextSibling : playback.firstChild);
            handler.postMessage('"read"');
            lyricSettings?.postMessage('read');
        }
        if (lyricButton) {
            const quality = document.querySelector('#page_pc_mini_bar .right-side .right > .ncm-quality-button:not([hidden])');
            if (quality && quality.nextElementSibling !== lyricButton) {
                quality.after(lyricButton);
                lyricSettings.postMessage('read');
            }
            const hide = !quality;
            if (lyricButton.hidden !== hide) lyricButton.hidden = hide;
        }
    }
    new MutationObserver(mount).observe(document.body, {
        childList: true, subtree: true, attributes: true, attributeFilter: ['hidden']
    });
    mount();
})();
