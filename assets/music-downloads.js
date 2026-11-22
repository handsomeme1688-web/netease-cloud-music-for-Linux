/* The download bridge runs in the application's isolated script world. */
(() => {
    if (location.origin !== 'https://music.163.com' || location.pathname.replace(/\/$/, '') !== '/st/webplayer') return;
    const handler = window.webkit.messageHandlers.musicDownload;
    const style = document.createElement('style');
    style.textContent = `
        .ncm-playlist-download{margin-inline-start:8px;border:1px solid #8885;border-radius:8px;
            padding:6px 12px;color:inherit;background:transparent;font:inherit;white-space:nowrap;cursor:pointer}
        .ncm-track-download{display:inline-grid;place-items:center;box-sizing:border-box;flex:0 0 20px;
            inline-size:20px;block-size:28px;padding:0;border:0;border-radius:5px;background:transparent;
            color:var(--colorBlack5,currentColor);cursor:pointer}
        .ncm-track-download:hover{background:#8882}
        .ncm-track-download>span,.ncm-download-toggle>span{position:relative;width:13px;height:13px;border-bottom:1.5px solid}
        :is(.ncm-track-download,.ncm-download-toggle)>span::before,:is(.ncm-track-download,.ncm-download-toggle)>span::after{
            content:'';position:absolute;left:50%}
        :is(.ncm-track-download,.ncm-download-toggle)>span::before{width:1.5px;height:8px;top:0;
            background:currentColor;transform:translateX(-50%)}
        :is(.ncm-track-download,.ncm-download-toggle)>span::after{width:5px;height:5px;top:3px;
            border:solid currentColor;border-width:0 1.5px 1.5px 0;
            transform:translateX(-50%) rotate(45deg)}
        .ncm-track-download.ncm-is-downloaded>span{color:#248b6b;box-sizing:border-box;border:1.5px solid;border-radius:50%}
        .ncm-track-download.ncm-is-downloaded>span::before{display:none}
        .ncm-track-download.ncm-is-downloaded>span::after{width:5.5px;height:3px;top:2px;
            transform:translateX(-50%) rotate(-45deg);border-width:0 0 1.5px 1.5px}
        .ncm-download-toggle{display:inline-grid;place-items:center;position:relative;flex:0 0 24px;
            inline-size:24px;block-size:24px;padding:0;color:inherit;border:0;border-radius:5px;
            background:transparent;cursor:pointer}
        .vinyl-page-bar-wrapper .ncm-download-toggle{color:var(--colorWhite4,#d4d5d8)}
        .ncm-download-toggle:hover,.ncm-download-toggle[aria-expanded="true"]{background:#8882}
        .ncm-download-toggle.is-running::after{content:'';position:absolute;inset:auto 3px 1px;height:2px;
            background:#ff465b;border-radius:2px;transform:scaleX(var(--download-fraction,0));transform-origin:left}
        .ncm-download-popover{position:fixed;z-index:2147483646;box-sizing:border-box;width:min(284px,calc(100vw - 24px));
            padding:12px 14px;border:1px solid #8883;border-radius:11px;box-shadow:0 4px 22px #0003;
            background:#f9fafb;color:#303642;max-height:calc(100vh - 24px);overflow:auto;
            font:inherit;font-size:13px;line-height:1.45;text-align:start}
        .ncm-download-popover[hidden],.ncm-download-popover [hidden]{display:none!important}
        .ncm-download-popover strong{font-weight:650}
        .ncm-download-summary{overflow-wrap:anywhere;white-space:pre-line;margin-block:7px}
        .ncm-download-meter{display:flex;gap:8px;align-items:center;margin-block:7px}
        .ncm-download-meter progress{appearance:none;flex:1;min-width:0;height:4px;border:0;border-radius:4px;overflow:hidden}
        .ncm-download-meter progress::-webkit-progress-bar{background:#8883}
        .ncm-download-meter progress::-webkit-progress-value{background:#ff465b}
        .ncm-download-meter output{font-variant-numeric:tabular-nums;color:inherit}
        .ncm-download-popover button{font:inherit;color:inherit;background:transparent;border:1px solid #8885;
            border-radius:6px;padding:3px 8px;cursor:pointer}
        .ncm-download-popover button:disabled{opacity:.5;cursor:default}
        .ncm-download-popover button:hover:not(:disabled){background:#8882}
        .ncm-download-menu{position:fixed;z-index:2147483647;max-width:calc(100vw - 16px);padding:5px;
            border:1px solid #8884;border-radius:8px;box-shadow:0 3px 12px #0002;background:#f7f8fa;color:#303642}
        .ncm-download-action{width:100%;border:0;background:transparent;color:inherit;text-align:start;
            font:inherit;white-space:nowrap;cursor:pointer}
        .ncm-download-menu .ncm-download-action{display:block;padding:7px 12px}
        .cmd-dropdown-menu .ncm-download-action{padding:0}
        .ncm-playlist-download:hover,.ncm-download-menu .ncm-download-action:hover{background:#8882}
        @media(prefers-color-scheme:dark){.ncm-download-menu,.ncm-download-popover{background:#262831;color:#edf0f4}}
    `;
    document.head.appendChild(style);

    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'ncm-download-toggle';
    toggle.title = '下载';
    toggle.setAttribute('aria-label', toggle.title);
    toggle.setAttribute('aria-controls', 'ncm-download-popover');
    toggle.appendChild(document.createElement('span'));
    const toggles = [toggle, toggle.cloneNode(true)];
    const panel = document.createElement('section');
    panel.id = 'ncm-download-popover';
    panel.className = 'ncm-download-popover';
    panel.setAttribute('aria-labelledby', 'ncm-download-title');
    panel.innerHTML = `<strong id="ncm-download-title">下载</strong>
        <div class="ncm-download-summary"></div>
        <div class="ncm-download-meter"><progress max="1" aria-label="下载进度"></progress><output></output></div>
        <button type="button" class="ncm-download-current">下载当前歌曲</button>
        <button type="button" class="ncm-download-cancel">取消下载</button>`;
    document.body.appendChild(panel);
    const summary = panel.querySelector('.ncm-download-summary');
    const meter = panel.querySelector('.ncm-download-meter');
    const progress = meter.querySelector('progress');
    const output = meter.querySelector('output');
    const start = panel.querySelector('.ncm-download-current');
    const cancel = panel.querySelector('.ncm-download-cancel');
    let anchor = null;
    let job = null;
    let downloaded = new Set();

    function visibleToggleRect(button) {
        const rect = button?.getBoundingClientRect();
        return rect?.width && rect.height && rect.top < innerHeight && rect.bottom > 0 &&
            getComputedStyle(button).visibility !== 'hidden' ? rect : null;
    }
    function positionPanel() {
        if (panel.hidden) return;
        let rect = visibleToggleRect(anchor);
        if (!rect) {
            anchor = visibleToggleRect(toggles[1]) ? toggles[1] : toggles[0];
            rect = visibleToggleRect(anchor);
        }
        for (const button of toggles) button.setAttribute('aria-expanded', String(button === anchor && !!rect));
        const {width, height} = panel.getBoundingClientRect();
        const left = Math.min(innerWidth - width - 12, (rect?.right || innerWidth - 12) - width);
        panel.style.left = Math.max(12, left) + 'px';
        panel.style.bottom = Math.max(8, Math.min(innerHeight - height - 12,
            rect ? innerHeight - rect.top + 9 : 60)) + 'px';
    }
    function showPanel(open) {
        if (panel.hidden === open) panel.hidden = !open;
        if (open) positionPanel();
        else {
            anchor = null;
            for (const button of toggles) button.setAttribute('aria-expanded', 'false');
        }
    }
    function drawJob() {
        const fraction = Math.max(0, Math.min(1, job?.fraction || 0));
        const running = !!job?.running;
        const message = job?.message || '暂无下载任务';
        if (summary.textContent !== message) summary.textContent = message;
        const percent = Math.floor(fraction * 100) + '%';
        if (output.textContent !== percent) output.textContent = percent;
        progress.value = fraction;
        meter.hidden = !running && fraction !== 1;
        cancel.hidden = !running;
        cancel.disabled = !!job?.cancelling;
        start.hidden = running;
        for (const button of toggles) {
            button.classList.toggle('is-running', running);
            button.style.setProperty('--download-fraction', String(fraction));
        }
    }
    window.updateMusicDownloadJob = (state, reveal) => {
        job = state;
        drawJob();
        if (reveal) showPanel(true);
        else positionPanel();
    };
    function drawRows() {
        for (const button of document.querySelectorAll('button.ncm-track-download')) {
            const saved = downloaded.has(button.dataset.ncmDownload?.slice(6));
            button.classList.toggle('ncm-is-downloaded', saved);
            const label = saved ? '已下载' : '下载这首歌';
            if (button.title !== label) {
                button.title = label;
                button.setAttribute('aria-label', label);
            }
        }
    }
    window.updateMusicDownloadedSongs = ids => { downloaded = new Set(ids); drawRows(); };
    window.markMusicSongDownloaded = id => { downloaded.add(id); drawRows(); };
    function mountToggles() {
        const bars = [...document.querySelectorAll('#page_pc_mini_bar .right-side .right')];
        for (const [index, button] of toggles.entries()) {
            const candidates = bars.filter(bar => Number(!!bar.closest('.vinyl-page-bar-wrapper')) === index);
            const quality = candidates.map(bar => bar.querySelector('.ncm-quality-button:not([hidden])')).find(Boolean);
            if (quality) {
                if (quality.previousElementSibling !== button) quality.before(button);
            } else if (candidates[0] && button.parentElement !== candidates[0]) {
                candidates[0].prepend(button);
            }
        }
        positionPanel();
    }
    let mounting = false;
    new MutationObserver(records => {
        if (records.every(record => panel.contains(record.target))) return;
        mountToggles();
        if (mounting) return;
        mounting = true;
        setTimeout(() => { mounting = false; drawRows(); }, 40);
    }).observe(document.body, {subtree:true, childList:true, attributes:true, attributeFilter:['hidden','data-ncm-download']});
    window.addEventListener('resize', positionPanel);
    window.addEventListener('focus', event => { if (event.isTrusted) handler.postMessage('read'); });
    showPanel(false);
    drawJob();
    mountToggles();
    drawRows();
    handler.postMessage('read');
    let menu, observer, timer;
    function stopWatching() {
        clearTimeout(timer);
        observer?.disconnect();
        observer = null;
    }
    function close() {
        stopWatching();
        menu?.remove();
        menu = null;
    }

    window.addEventListener('music-download-target', event => {
        close();
        let payload;
        try { payload = JSON.parse(event.detail); } catch (_) { return; }
        if (!payload || !['track', 'playlist'].includes(payload.kind) ||
            !/^[1-9]\d{0,15}$/.test(payload.id) || !Number.isFinite(payload.x) || !Number.isFinite(payload.y)) return;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'ncm-download-action';
        button.textContent = payload.kind === 'track' ? '下载这首歌' : '下载整张歌单';
        button.dataset.ncmDownload = payload.kind + ':' + payload.id;

        function attachToSiteMenu() {
            const siteMenu = [...document.querySelectorAll('ul.cmd-dropdown-menu')]
                .find(list => list.getClientRects().length && list.textContent.includes('下一首播放'));
            if (!siteMenu) return false;
            close();
            menu = document.createElement('li');
            menu.className = 'ellipsis-content cmd-dropdown-item cmd-dropdown-item-withoutIcon';
            menu.setAttribute('role', 'none');
            button.classList.add('cmd-dropdown-item-content');
            button.setAttribute('role', 'menuitem');
            menu.appendChild(button);
            siteMenu.prepend(menu);
            return true;
        }

        function showFloating() {
            menu = document.createElement('div');
            menu.className = 'ncm-download-menu';
            menu.appendChild(button);
            document.body.appendChild(menu);
            const rect = menu.getBoundingClientRect();
            menu.style.left = Math.max(4, Math.min(innerWidth - rect.width - 4, payload.x)) + 'px';
            menu.style.top = Math.max(4, Math.min(innerHeight - rect.height - 4, payload.y)) + 'px';
        }
        if (payload.kind === 'track') {
            observer = new MutationObserver(attachToSiteMenu);
            observer.observe(document.body, {subtree: true, childList: true, attributes: true,
                attributeFilter: ['class', 'style', 'hidden']});
            timer = setTimeout(() => {
                if (attachToSiteMenu()) return;
                showFloating();
                timer = setTimeout(stopWatching, 1000);
            }, 350);
        } else {
            showFloating();
        }
    });
    document.addEventListener('click', event => {
        const button = event.target instanceof Element && event.target.closest(
            '.ncm-download-action, .ncm-playlist-download, .ncm-track-download, .ncm-download-toggle, ' +
            '.ncm-download-current, .ncm-download-cancel');
        if (!event.isTrusted || !button) return;
        event.preventDefault();
        event.stopPropagation();
        close();
        if (toggles.includes(button)) {
            const open = panel.hidden || anchor !== button;
            anchor = button;
            showPanel(open);
            if (!panel.hidden) handler.postMessage('read');
        } else if (button === cancel) {
            handler.postMessage('cancel');
        } else {
            const action = button.dataset.ncmDownload;
            if (!/^(track|playlist):[1-9]\d{0,15}$/.test(action)) {
                window.updateMusicDownloadJob({message:button === start ? '请先播放一首歌曲' : '暂未识别此歌曲'}, true);
            } else if (!job?.running && action.startsWith('track:') && downloaded.has(action.slice(6))) {
                window.updateMusicDownloadJob({message:'所选音质已下载', fraction:1}, true);
            } else {
                handler.postMessage(action);
            }
        }
    }, true);
    document.addEventListener('pointerdown', event => {
        if (!menu?.contains(event.target)) close();
        if (!panel.contains(event.target) && !toggles.some(button => button.contains(event.target))) showPanel(false);
    }, true);
    document.addEventListener('keydown', event => { if (event.key === 'Escape') { close(); showPanel(false); } });
    document.addEventListener('scroll', close, true);
    document.addEventListener('transitionend', positionPanel, true);
    document.addEventListener('animationend', positionPanel, true);
})();
