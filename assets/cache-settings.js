(() => {
    if (location.origin !== 'https://music.163.com' || location.pathname.replace(/\/$/, '') !== '/st/webplayer') return;
    const handler = window.webkit.messageHandlers.cacheSettings;
    const row = document.createElement('div');
    // The cache path lives in the desktop script world and a closed shadow tree.
    const root = row.attachShadow({mode: 'closed'});
    root.innerHTML = `
        <style>
            :host{display:block}
            .controls,.error{font-size:var(--music-setting-font-size,13px);
                line-height:var(--music-setting-line-height,20px);font-weight:400}
            .controls{display:grid;grid-template-columns:var(--music-setting-label-width,7em) minmax(0,1fr);
                align-items:start;column-gap:8px}
            .caption{display:flex;align-items:center;min-height:var(--music-setting-option-height,24px)}
            .controls:not(:first-of-type){margin-top:12px}
            .paths{display:flex;align-items:center;flex-wrap:wrap;gap:6px 8px;min-width:0;max-width:36rem}
            .paths input,.paths button{box-sizing:border-box;min-height:var(--music-setting-option-height,24px);
                font:inherit;color:inherit;background:transparent;border:1px solid var(--colorBlack8,#8886);border-radius:6px;padding:2px 8px}
            .paths input{flex:1 1 8em;min-width:0;text-overflow:ellipsis}
            button{cursor:pointer;white-space:nowrap}
            button:hover{background:#8882}
            .quality-options{display:flex;min-width:0;flex-wrap:wrap;gap:var(--music-setting-option-gap,8px 16px)}
            .quality-options label{position:relative;display:inline-flex;align-items:center;
                min-height:var(--music-setting-option-height,24px);
                gap:8px;white-space:nowrap;cursor:pointer}
            .quality-options input{position:absolute;inset:0;width:100%;height:100%;margin:0;opacity:0;cursor:pointer}
            .radio-mark{box-sizing:border-box;display:grid;place-items:center;flex:none;width:16px;height:16px;
                border:1px solid var(--colorBlack7,#a3aab8);border-radius:50%}
            input:checked+.radio-mark{border-color:var(--colorPrimary1,#ff3348)}
            input:checked+.radio-mark::after{content:'';width:8px;height:8px;border-radius:50%;background:var(--colorPrimary1,#ff3348)}
            input:focus-visible+.radio-mark{outline:2px solid var(--colorPrimary1,#ff3348);outline-offset:2px}
            input:disabled~span{opacity:.55}
            .error:empty{display:none}
            .error:not(:empty){display:block;margin-top:6px;color:inherit}
        </style>
        <div class="controls">
            <label class="caption" for="directory">音乐缓存目录</label>
            <div class="paths">
                <input id="directory" type="text" readonly>
                <button type="button" class="choose">更改…</button>
                <button type="button" class="reset" hidden>恢复默认</button>
            </div>
        </div>
        <span class="error" role="status"></span>
        <div class="controls">
            <label class="caption" for="download-directory">音乐下载目录</label>
            <div class="paths">
                <input id="download-directory" type="text" readonly>
                <button type="button" class="download-choose">更改…</button>
                <button type="button" class="download-reset" hidden>恢复默认</button>
            </div>
        </div>
        <div class="controls">
            <span class="caption" id="download-quality-label">下载音质</span>
            <div class="quality-options" role="radiogroup" aria-labelledby="download-quality-label">
                ${[['mp3', '极高（MP3）'], ['flac', '无损（FLAC）'], ['jymaster', '超清母带'], ['sky', '沉浸环绕声']]
                    .map(([value, label]) => `<label><input type="radio" name="download-quality" value="${value}" disabled>
                        <span class="radio-mark" aria-hidden="true"></span><span>${label}</span></label>`).join('')}
            </div>
        </div>
        <span class="download-error error" role="status"></span>`;
    const path = root.querySelector('#directory');
    const reset = root.querySelector('.reset');
    const status = root.querySelector('.error');
    const downloadPath = root.querySelector('#download-directory');
    const downloadReset = root.querySelector('.download-reset');
    const downloadFormats = root.querySelectorAll('input[name="download-quality"]');
    const downloadError = root.querySelector('.download-error');
    window.updateMusicCacheDirectory = (directory, custom, error) => {
        path.value = path.title = directory;
        reset.hidden = !custom;
        status.textContent = error;
    };
    window.updateMusicDownloadPreferences = (directory, format, custom, error) => {
        downloadPath.value = downloadPath.title = directory;
        for (const radio of downloadFormats) {
            radio.checked = radio.value === format;
            radio.disabled = false;
        }
        downloadReset.hidden = !custom;
        downloadError.textContent = error;
    };
    for (const [button, action] of [[root.querySelector('.choose'), 'choose'], [reset, 'reset'],
        [root.querySelector('.download-choose'), 'download-choose'], [downloadReset, 'download-reset']]) {
        button.addEventListener('click', event => {
            if (event.isTrusted) handler.postMessage(action);
        });
    }
    for (const radio of downloadFormats) {
        radio.addEventListener('change', event => {
            if (event.isTrusted && radio.checked) handler.postMessage('download-format:' + radio.value);
        });
    }
    let reference;
    function mount() {
        const playback = document.querySelector('#page_pc_setting #play > .play');
        if (!playback) return;
        if (row.parentNode !== playback) {
            playback.appendChild(row);
            handler.postMessage('read');
            handler.postMessage('download-read');
        }
        const native = playback.querySelector('.cmd-radio-content') || playback.querySelector('.cmd-radio-addon');
        if (native && native !== reference) {
            reference = native;
            const font = getComputedStyle(native);
            playback.style.setProperty('--music-setting-font-size', font.fontSize);
            playback.style.setProperty('--music-setting-line-height', font.lineHeight);
        }
    }
    new MutationObserver(mount).observe(document.body, {childList: true, subtree: true});
    mount();
})();
