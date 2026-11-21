(() => {
    if (location.origin !== 'https://music.163.com' || location.pathname.replace(/\/$/, '') !== '/st/webplayer') return;
    const handler = window.webkit.messageHandlers.cacheSettings;
    const row = document.createElement('div');
    // The cache path lives in the desktop script world and a closed shadow tree.
    const root = row.attachShadow({mode: 'closed'});
    root.innerHTML = `
        <style>
            :host{display:block;max-width:520px;color:inherit;font-size:var(--music-setting-font-size,14px);line-height:20px}
            .controls{display:flex;align-items:center;row-gap:6px;flex-wrap:wrap}
            label{min-width:var(--music-setting-label-width,7em);margin-right:8px}
            input,button{box-sizing:border-box;min-height:var(--music-setting-control-height,28px);font:inherit;color:inherit;background:transparent;border:1px solid #8886;border-radius:6px;padding:2px 8px}
            input{flex:1 1 9em;min-width:0;margin-right:8px;text-overflow:ellipsis}
            button{cursor:pointer;white-space:nowrap}
            button+button{margin-left:8px}
            button:hover{background:#8882}
            .error:not(:empty){display:block;margin-top:6px;color:inherit}
        </style>
        <div class="controls">
            <label for="directory">音乐缓存目录</label>
            <input id="directory" type="text" readonly>
            <button type="button" class="choose">更改…</button>
            <button type="button" class="reset" hidden>恢复默认</button>
        </div>
        <span class="error" role="status"></span>`;
    const path = root.querySelector('input');
    const reset = root.querySelector('.reset');
    const status = root.querySelector('.error');
    window.updateMusicCacheDirectory = (directory, custom, error) => {
        path.value = path.title = directory;
        reset.hidden = !custom;
        status.textContent = error;
    };
    for (const [button, action] of [[root.querySelector('.choose'), 'choose'], [reset, 'reset']]) {
        button.addEventListener('click', event => {
            if (event.isTrusted) handler.postMessage(action);
        });
    }
    function mount() {
        const playback = document.querySelector('#page_pc_setting #play > .play');
        if (playback && row.parentNode !== playback) {
            playback.appendChild(row);
            handler.postMessage('read');
        }
    }
    new MutationObserver(mount).observe(document.body, {childList: true, subtree: true});
    mount();
})();
