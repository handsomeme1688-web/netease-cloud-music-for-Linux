(() => {
    if (location.origin !== 'https://music.163.com' || location.pathname.replace(/\/$/, '') !== '/st/webplayer') return;

    function blankPlayerBar(target) {
        if (!(target instanceof Element)) return null;
        const bar = target.closest('#page_pc_mini_bar [class*="DefaultBarWrapper_"]');
        const control = target.closest('button, a, input, label, img, svg, [role="button"], [role="slider"], ' +
            '[tabindex], .title, .left > :first-child, .slider-default, .cmd-slider');
        return bar && !(control && bar.contains(control)) ? bar : null;
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
    let nav, pending = false, previous;
    const resize = typeof ResizeObserver === 'function' ? new ResizeObserver(schedule) : null;

    function dragGap() {
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
        if (right - left < 24 || bottom - top < 16) return null;
        // A popover or dialog over the header takes precedence over window dragging.
        for (const x of [left, (left + right) / 2, right - 1]) {
            for (const y of [top, (top + bottom) / 2, bottom - 1]) {
                const hit = document.elementFromPoint(x, y);
                if (hit !== nav && hit !== row &&
                    !(hit && row.contains(hit) && hit.matches('.draggable:empty'))) return null;
            }
        }
        return [innerWidth, innerHeight, devicePixelRatio, left, top, right, bottom];
    }

    function schedule() {
        if (pending) return;
        pending = true;
        requestAnimationFrame(() => {
            pending = false;
            const current = document.getElementById('page_pc_main_nav');
            if (current !== nav) {
                nav = current;
                if (resize) {
                    resize.disconnect();
                    if (nav) resize.observe(nav);
                }
            }
            const result = JSON.stringify(dragGap());
            if (result !== previous) handler.postMessage(previous = result);
        });
    }

    new MutationObserver(records => {
        if (nav !== document.getElementById('page_pc_main_nav') ||
            records.some(record => record.target === document.body || record.target === document.documentElement ||
                (nav && nav.contains(record.target)))) schedule();
    }).observe(document.body, {childList: true, subtree: true, attributes: true, characterData: true});
    window.addEventListener('resize', () => { previous = undefined; schedule(); });
    window.addEventListener('scroll', schedule, true);
    document.addEventListener('focusin', schedule);
    document.addEventListener('focusout', schedule);
    schedule();
})();
