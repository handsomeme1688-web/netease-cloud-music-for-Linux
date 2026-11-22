(() => {
    if (location.origin !== 'https://music.163.com' || location.pathname.replace(/\/$/, '') !== '/st/webplayer') return;

    const detailPageSelector = '[class*="VinylPageContainer_"]';
    const detailHeaderSelector = detailPageSelector + ' > .page-header';
    const detailBarSelector = '#page_pc_mini_bar .vinyl-page-bar-wrapper';
    const homeBarSelector = '#page_pc_mini_bar [class*="DefaultBarWrapper_"], #page_pc_mini_bar .default-bar-wrapper';
    const controls = 'button, a, input, label, img, svg, [role="button"], [role="slider"], [tabindex], .slider-default, .cmd-slider';
    const detailControls = controls + ', .cmd-button, .play-btn, .icon, .close';
    const style = document.createElement('style');
    style.textContent = detailBarSelector + ' .unfold-button { display: none !important; }';
    document.head.appendChild(style);

    function blankPlayerBar(target) {
        if (!(target instanceof Element)) return null;
        const detail = target.closest(detailBarSelector);
        const bar = detail || target.closest(homeBarSelector);
        if (!bar) return null;
        const control = target.closest(detail ? detailControls : controls + ', .title, .left > :first-child');
        return control && bar.contains(control) ? null : bar;
    }

    let blankPress, blankClick;
    document.addEventListener('mousedown', event => {
        blankPress = event.button === 0 && blankPlayerBar(event.target);
        blankClick = null;
    }, true);
    document.addEventListener('mouseup', event => {
        blankClick = event.button === 0 && blankPress && blankPress === blankPlayerBar(event.target) ? blankPress : null;
        blankPress = null;
        if (blankClick) event.stopPropagation();
    }, true);
    document.addEventListener('click', event => {
        if (blankClick && blankClick === blankPlayerBar(event.target)) event.stopPropagation();
        blankClick = null;
    }, true);

    const handler = window.webkit.messageHandlers.windowDragGap;
    let nav, detailHeader, pending = false, previous;
    const resize = typeof ResizeObserver === 'function' ? new ResizeObserver(schedule) : null;

    function measureGap(left, top, right, bottom, isBlank) {
        if (right - left < 24 || bottom - top < 16) return null;
        // A popover or dialog over the header takes precedence over window dragging.
        for (const x of [left, (left + right) / 2, right - 1]) {
            for (const y of [top, (top + bottom) / 2, bottom - 1]) {
                if (!isBlank(document.elementFromPoint(x, y))) return null;
            }
        }
        return [innerWidth, innerHeight, devicePixelRatio, left, top, right, bottom];
    }

    function homeDragGap() {
        const row = nav && nav.querySelector('[class*="HeaderRow_"]');
        const search = row && row.querySelector('.searchbox');
        if (!search) return null;
        const header = nav.getBoundingClientRect();
        const field = search.getBoundingClientRect();
        if (!field.width || !field.height || !header.height) return null;
        const rightGroup = [...row.children]
            .filter(node => node.hasChildNodes() || node.hasAttribute('tabindex'))
            .map(node => node.getBoundingClientRect())
            .filter(rect => rect.width && rect.height && rect.left >= field.right &&
                rect.top < field.bottom && rect.bottom > field.top)
            .sort((a, b) => a.left - b.left)[0];
        if (!rightGroup) return null;
        const left = Math.ceil(field.right + 6);
        const right = Math.floor(rightGroup.left - 6);
        const top = Math.ceil(Math.max(header.top + 6, field.top - 8));
        const bottom = Math.floor(Math.min(header.bottom - 4, field.bottom + 8));
        return measureGap(left, top, right, bottom, hit => hit === nav || hit === row ||
            (hit && row.contains(hit) && hit.matches('.draggable:empty')));
    }

    function detailDragGap() {
        if (!detailHeader) return null;
        const header = detailHeader.getBoundingClientRect();
        if (!header.height || header.top > 18) return null;
        const reserve = parseFloat(getComputedStyle(document.documentElement)
            .getPropertyValue('--music-window-controls-width')) || 106;
        let left = Math.ceil(Math.max(12, header.left + 6));
        let right = Math.floor(Math.min(header.right, innerWidth - reserve) - 6);
        const top = Math.ceil(Math.max(6, header.top + 6));
        const bottom = Math.floor(Math.min(innerHeight, header.bottom - 4));
        const center = (left + right) / 2;
        for (const control of detailHeader.querySelectorAll(detailControls)) {
            const rect = control.getBoundingClientRect();
            if (rect.width && rect.height && rect.bottom > top && rect.top < bottom) {
                if (rect.left < center) left = Math.max(left, Math.ceil(rect.right + 6));
                else right = Math.min(right, Math.floor(rect.left - 6));
            }
        }
        const page = detailHeader.parentElement;
        const passThrough = getComputedStyle(detailHeader).pointerEvents === 'none';
        return measureGap(left, top, right, bottom, hit => hit &&
            (detailHeader.contains(hit) || (passThrough && hit.closest(detailPageSelector) === page)) &&
            !hit.closest(detailControls + ', [role="dialog"], [role="menu"], .cmd-popover, .title, .cover'));
    }

    function schedule() {
        if (pending) return;
        pending = true;
        requestAnimationFrame(() => {
            pending = false;
            const currentNav = document.getElementById('page_pc_main_nav');
            const currentDetail = document.querySelector(detailHeaderSelector);
            if (currentNav !== nav || currentDetail !== detailHeader) {
                nav = currentNav;
                detailHeader = currentDetail;
                if (resize) {
                    resize.disconnect();
                    if (nav) resize.observe(nav);
                    if (detailHeader) resize.observe(detailHeader);
                }
            }
            const result = JSON.stringify(detailDragGap() || homeDragGap());
            if (result !== previous) handler.postMessage(previous = result);
        });
    }

    new MutationObserver(records => {
        if (nav !== document.getElementById('page_pc_main_nav') ||
            detailHeader !== document.querySelector(detailHeaderSelector) ||
            records.some(record => record.target === document.body || record.target === document.documentElement ||
                (nav && nav.contains(record.target)) || (detailHeader && (detailHeader.contains(record.target) ||
                    (record.type === 'attributes' && record.target.contains(detailHeader)))))) schedule();
    }).observe(document.body, {childList: true, subtree: true, attributes: true, characterData: true});
    window.addEventListener('resize', () => { previous = undefined; schedule(); });
    window.addEventListener('scroll', schedule, true);
    document.addEventListener('focusin', schedule);
    document.addEventListener('focusout', schedule);
    schedule();
})();
