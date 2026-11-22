(() => {
    'use strict';
    if (location.origin !== 'https://music.163.com' || location.pathname.replace(/\/$/, '') !== '/st/webplayer') return;
    const handler = window.webkit.messageHandlers.transitionSettings;
    const lyricSettings = window.webkit.messageHandlers.desktopLyricsSettings;
    const row = document.createElement('div');
    const root = row.attachShadow({mode: 'closed'});
    root.innerHTML = `
        <style>
            :host{display:block}
            .row,.error{font-size:var(--music-setting-font-size,13px);line-height:var(--music-setting-line-height,20px);
                font-weight:400}
            .row{display:grid;grid-template-columns:var(--music-setting-label-width,7em) minmax(0,1fr);
                align-items:start;column-gap:8px}
            .caption{display:flex;align-items:center;min-height:var(--music-setting-option-height,24px)}
            .controls,.options,.duration{display:flex;align-items:center;flex-wrap:wrap}
            .controls,.options{gap:var(--music-setting-option-gap,8px 16px);min-width:0}
            .options label,.desktop-lyrics label{display:inline-flex;align-items:center;gap:8px;justify-self:start;
                min-height:var(--music-setting-option-height,24px);font:inherit;cursor:pointer}
            .options label{white-space:nowrap}
            input[type="radio"],.checkbox-mark{box-sizing:border-box;flex:none;width:16px;height:16px;
                border:1px solid var(--colorBlack7,#a3aab8)}
            input[type="radio"]{appearance:none;margin:0;border-radius:50%;cursor:pointer}
            input[type="radio"]:checked{border-color:var(--colorPrimary1,#ff3348);
                background:radial-gradient(circle,var(--colorPrimary1,#ff3348) 4px,transparent 4.5px)}
            input[type="radio"]:focus-visible,input[type="checkbox"]:focus-visible+.checkbox-mark{
                outline:2px solid var(--colorPrimary1,#ff3348);outline-offset:2px}
            .desktop-lyrics{margin-top:var(--music-setting-section-gap,18px)}
            .desktop-lyrics label{position:relative}
            input[type="checkbox"]{position:absolute;inset:0;width:100%;height:100%;margin:0;opacity:0;cursor:pointer}
            .checkbox-mark{display:grid;place-items:center;border-radius:4px}
            input[type="checkbox"]:checked+.checkbox-mark{border-color:transparent;background:var(--colorPrimary1,#ff3348)}
            input[type="checkbox"]:checked+.checkbox-mark::after{content:'';width:4px;height:7px;
                border:solid var(--colorWhite1,#fff);border-width:0 2px 2px 0;transform:translateY(-1px) rotate(45deg)}
            .duration{gap:4px 8px;min-height:var(--music-setting-option-height,24px)}
            input[type="number"]{box-sizing:border-box;width:4.5em;height:var(--music-setting-option-height,24px);
                font:inherit;color:inherit;background:transparent;border:1px solid var(--colorBlack8,#8886);border-radius:6px;padding:2px 6px}
            [hidden]{display:none}
            .error:not(:empty){display:block;margin-top:6px}
        </style>
        <div class="row">
            <span class="caption" id="transition-label">歌曲过渡</span>
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
            <span class="caption">桌面歌词</span>
            <label><input id="desktop-lyrics" type="checkbox" disabled><span class="checkbox-mark" aria-hidden="true"></span>显示悬浮歌词</label>
        </div>
        <span class="error" role="status"></span>`;
    const modes = [...root.querySelectorAll('input[name="mode"]')];
    const seconds = root.querySelector('#seconds');
    const duration = root.querySelector('.duration');
    const status = root.querySelector('.error');
    const lyrics = root.querySelector('#desktop-lyrics');
    const lyricButtons = [];
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
            .ncm-lyrics-button[aria-pressed="true"]{color:#ff3348;opacity:1;background:#ff334815}
            .vinyl-page-bar-wrapper .ncm-lyrics-button{color:var(--colorWhite3,#dedfe2);opacity:1}
            .vinyl-page-bar-wrapper .ncm-lyrics-button[aria-pressed="true"]{
                color:var(--colorWhite2,#f0f1f3);border-color:#ff7b88;background:#ff334829}`;
        document.head.appendChild(style);
        const lyricButton = document.createElement('button');
        lyricButton.type = 'button';
        lyricButton.className = 'ncm-lyrics-button';
        lyricButton.textContent = '词';
        lyricButton.title = '桌面歌词（Ctrl+D）';
        lyricButton.setAttribute('aria-label', '桌面歌词');
        lyricButton.setAttribute('aria-pressed', 'false');
        lyricButtons.push(lyricButton, lyricButton.cloneNode(true));
        for (const button of lyricButtons) {
            button.addEventListener('click', event => {
                if (event.isTrusted) lyricSettings.postMessage('toggle');
            });
        }
        root.querySelector('.desktop-lyrics').hidden = false;
        window.updateDesktopLyricsSetting = enabled => {
            lyrics.checked = enabled;
            lyrics.disabled = false;
            for (const button of lyricButtons) button.setAttribute('aria-pressed', String(enabled));
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
        if (!lyricButtons.length) return;
        const qualities = [...document.querySelectorAll(
            '#page_pc_mini_bar .right-side .right > .ncm-quality-button:not([hidden])')];
        let moved = false;
        for (const [index, lyricButton] of lyricButtons.entries()) {
            const quality = qualities.find(button => Number(!!button.closest('.vinyl-page-bar-wrapper')) === index);
            if (quality && quality.nextElementSibling !== lyricButton) {
                quality.after(lyricButton);
                moved = true;
            }
            const hide = !quality;
            if (lyricButton.hidden !== hide) lyricButton.hidden = hide;
        }
        if (moved) lyricSettings.postMessage('read');
    }
    new MutationObserver(mount).observe(document.body, {
        childList: true, subtree: true, attributes: true, attributeFilter: ['hidden']
    });
    mount();
})();
