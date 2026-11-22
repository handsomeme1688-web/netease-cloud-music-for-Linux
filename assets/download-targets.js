/* Read the resource attached to the official player's song and playlist controls. */
(() => {
    if (location.origin !== 'https://music.163.com' || location.pathname.replace(/\/$/, '') !== '/st/webplayer') return;
    const validId = id => /^[1-9]\d{0,15}$/.test(String(id || '')) && Number.isSafeInteger(Number(id));

    function resourceAt(node, wanted) {
        for (let element = node; element instanceof Element; element = element.parentElement) {
            const key = Object.keys(element).find(name => /^__react(?:Fiber|InternalInstance)\$/.test(name));
            let fiber = key && element[key];
            for (let depth = 0; depth < 10 && fiber; depth++, fiber = fiber.return) {
                const props = fiber.memoizedProps || {};
                const data = props.data;
                const kind = data?.resourceType;
                if (['track', 'playlist'].includes(kind) && (!wanted || kind === wanted) && validId(data.resource?.id))
                    return {kind, id: String(data.resource.id)};
                const song = props.track || props.song || props.rowData;
                if (wanted !== 'playlist' && validId(song?.id) && (song.ar || song.artists || song.privilege))
                    return {kind: 'track', id: String(song.id)};
            }
        }
        return null;
    }

    const songRow = '.tr, [role="row"]';
    const rowPlay = target => target.closest(songRow)?.querySelector('button.play-btn');

    document.addEventListener('contextmenu', event => {
        if (!event.isTrusted || !(event.target instanceof Element) ||
            event.target.closest('input, textarea, [contenteditable=true]')) return;
        const play = rowPlay(event.target);
        const resource = play ? resourceAt(play, 'track') : resourceAt(event.target);
        if (!resource) return;
        event.preventDefault();
        const {clientX: x, clientY: y} = event;
        window.dispatchEvent(new CustomEvent('music-download-target',
            {detail: JSON.stringify({...resource, x, y})}));
    }, true);

    window.addEventListener('click', event => {
        const button = event.target instanceof Element && event.target.closest('.ncm-track-download, .ncm-download-current');
        if (!event.isTrusted || !button) return;
        const play = rowPlay(button);
        const current = button.classList.contains('ncm-download-current');
        const track = current ? window.__musicLyricPlayback?.() : play && resourceAt(play, 'track');
        if (validId(track?.id) && (!track.kind || track.kind === 'track')) button.dataset.ncmDownload = 'track:' + track.id;
        else delete button.dataset.ncmDownload;
    }, true);

    function trackButtons() {
        for (const group of document.querySelectorAll('.cmd-metacard-extra, .td-oper')) {
            const favorite = group.querySelector('button[title="收藏"], button[title="收藏到歌单"], ' +
                'button[title="添加到歌单"], button[aria-label="收藏"]');
            const old = group.querySelector('.ncm-track-download');
            if (!favorite || !rowPlay(favorite)) {
                old?.remove();
                continue;
            }
            const button = old || document.createElement('button');
            if (!old) {
                button.type = 'button';
                button.className = 'icon ncm-track-download';
                button.title = '下载这首歌';
                button.setAttribute('aria-label', button.title);
                button.appendChild(document.createElement('span'));
            }
            const track = resourceAt(rowPlay(favorite), 'track');
            const action = track && 'track:' + track.id;
            if (action && button.dataset.ncmDownload !== action) button.dataset.ncmDownload = action;
            if (!action) delete button.dataset.ncmDownload;
            if (favorite.previousElementSibling !== button) favorite.before(button);
        }
    }

    function playlistButton() {
        const area = document.querySelector('section[class*="RightContainer_"]');
        if (!area) return;
        const selected = document.querySelector('#myFavoriteMusic.selected, [class*="PlayListItemContent_"].selected');
        const selectedList = selected && resourceAt(selected, 'playlist');
        const playAll = Array.from(area.querySelectorAll('button.play-all, button, [role="button"]')).find(button =>
            button.getClientRects().length && (button.matches('button.play-all') || button.innerText?.trim() === '播放全部'));
        const playlist = (playAll && resourceAt(playAll, 'playlist')) || selectedList;
        const old = document.querySelector('.ncm-playlist-download');
        if (!playAll || playlist?.kind !== 'playlist') {
            old?.remove();
            return;
        }
        const button = old || document.createElement('button');
        if (!old) {
            button.type = 'button';
            button.className = 'ncm-playlist-download';
            button.textContent = '下载整张歌单';
        }
        button.dataset.ncmDownload = 'playlist:' + playlist.id;
        if (playAll.nextElementSibling !== button) playAll.after(button);
    }

    let pending = false;
    function schedule() {
        if (pending) return;
        pending = true;
        setTimeout(() => {
            pending = false;
            playlistButton();
            trackButtons();
        }, 30);
    }
    new MutationObserver(records => {
        if (records.some(record => !record.target.parentElement?.closest('.ncm-download-popover'))) schedule();
    }).observe(document.documentElement, {subtree: true, childList: true, attributes: true,
        attributeFilter: ['class']});
    schedule();
})();
