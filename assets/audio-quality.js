/* Desktop quality controls, using the website's authenticated player actions. */
(() => {
    'use strict';
    if (location.origin !== 'https://music.163.com' ||
        location.pathname.replace(/\/$/, '') !== '/st/webplayer') return;
    const choices = [
        ['jymaster', 4999, '超清母带', '更丰富的录音细节', 'MASTER', 'SVIP'],
        ['jyeffect', 3999, '高清臻音', '增强声音细节与空间听感', '臻音', 'VIP'],
        ['hires', 1999, 'Hi-Res', '高解析度无损音质', 'Hi-Res', 'VIP'],
        ['lossless', 999, '无损', '高保真无损音质', 'SQ', 'VIP'],
        ['exhigh', 320, '极高', '最高 320 kbps', 'HQ', ''],
        ['higher', 192, '较高', '192 kbps', '♪', ''],
        ['standard', 128, '标准', '128 kbps', '♪', ''],
        ['vivid', 6999, '臻音全景声', '立体空间音频体验', 'VIVID', 'SVIP'],
        ['sky', 5999, '沉浸环绕声', '沉浸式空间听感', '环绕', 'SVIP']
    ].map(([level, value, name, description, icon, tier]) => ({level, value, name, description, icon, tier}));
    const find = value => choices.find(q => q.value === Number(value) || q.level === value);
    const audioTest = document.createElement('audio');
    const vividSupported = ['audio/av3a', 'audio/avs3', 'audio/mp4; codecs="av3a"']
        .some(type => audioTest.canPlayType(type));
    const nativeRequests = new Map();
    let requestId = 0;
    const nativeHandler = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.musicQuality;
    function takeNative(id) {
        const request = nativeRequests.get(id);
        if (!request) return null;
        nativeRequests.delete(id); clearTimeout(request.timer);
        if (request.signal) request.signal.removeEventListener('abort', request.cancel);
        return request;
    }
    Object.defineProperty(window, '__musicQualityResponse', {value: (id, data) => {
        const request = takeNative(id);
        if (!request) return;
        if (data) request.resolve(data); else request.reject(new Error('quality'));
    }});
    function requestNative(params, signal) {
        return new Promise((resolve, reject) => {
            if (signal && signal.aborted) { reject(new Error('cancelled')); return; }
            const input = Array.isArray(params.ids) ? params.ids : [params.ids];
            const ids = input.flatMap(value => typeof value === 'string' ? [].concat(JSON.parse(value)) : [value]).map(Number);
            const id = Date.now().toString(36) + '-' + (++requestId);
            const cancel = () => {
                if (!takeNative(id)) return;
                nativeHandler.postMessage(JSON.stringify({event: 'cancel', id})); reject(new Error('cancelled'));
            };
            const timer = setTimeout(cancel, 20000);
            nativeRequests.set(id, {resolve, reject, timer, signal, cancel});
            if (signal) signal.addEventListener('abort', cancel, {once: true});
            nativeHandler.postMessage(JSON.stringify({event: 'request', id, params: {ids,
                level: params.level, immerseType: params.immerseType}}));
        });
    }
    const metadata = new Map(), details = new Map(), patched = new WeakSet(), rows = new Map();
    const fingerprints = new Map();
    const sourceKey = url => String(url).replace(/^http:/, 'https:');
    const fingerprint = (url, hash, size) =>
        typeof hash === 'string' && /^[a-f0-9]{32}$/i.test(hash) && size > 0 ? hash.toLowerCase() + ':' + size : sourceKey(url);
    let preload;
    const fields = {standard: 'l', higher: 'm', exhigh: 'h', lossless: 'sq', hires: 'hr',
        jyeffect: 'je', jymaster: 'jm', sky: 'sk', vivid: 'vi'};
    let tool, store, playerUrl, musicDetail, songQualities, pending, panel, list, footer, anchor, control, loading;
    let signature = '', scheduled = false, notice = '', lastTrack = '';
    const trackId = state => String(state.playing.resourceTrackId || '');
    const currentHowl = () => window.__musicNativeHowl && window.__musicNativeHowl();
    const pauseAction = () => store.dispatch({type: 'playing/pause', payload: {}});
    const remember = (state, choice) => store.dispatch({type: 'setting/updateQuantity', payload: {
        listen: choice.value, [state.host.isAnonymous ? 'listenAnon' : 'listenReg']: choice.value}});
    const emit = text => { notice = text; sync(); };
    function discardPreload() {
        if (!preload) return;
        const task = preload;
        preload = null;
        task.controller.abort();
        task.download.then(result => { if (result) result.release(); });
    }
    function preloadNext(info) {
        const howl = currentHowl(), url = sourceKey(info.musicurl);
        if (!howl || howl._state !== 'loaded' || !howl.playing() || pending ||
            !/^https:\/\/[^/]+\.music\.126\.net\//.test(url) || info.format === 'av3a' ||
            info.audioFormat === 'av3a' || (store && String(info.songId) === trackId(store.getState())) ||
            url === sourceKey([].concat(howl._src)[0])) return;
        const key = fingerprint(url, info.md5, info.fileSize);
        if (preload && preload.key === key) return;
        discardPreload();
        const task = preload = {key, controller: new AbortController(), bytes: 0, total: 0};
        task.download = window.__musicFetchNativeAudio(url, task.controller.signal, (bytes, total) => {
            task.bytes = bytes; task.total = total;
            if (task.progress) task.progress(bytes, total);
        }).catch(() => {
            if (preload === task) preload = null;
            return null;
        });
    }
    Object.defineProperty(window, '__musicTakePreload', {value: (url, signal, progress) => {
        const task = preload, key = sourceKey(url);
        if (!task) return null;
        if ((fingerprints.get(key) || key) !== task.key) { discardPreload(); return null; }
        preload = null;
        task.progress = progress;
        progress(task.bytes, task.total);
        const abort = () => task.controller.abort();
        signal.addEventListener('abort', abort, {once: true});
        return task.download.finally(() => signal.removeEventListener('abort', abort));
    }});
    function clearPending() {
        if (pending) {
            clearTimeout(pending.timer);
            if (pending.controller) pending.controller.abort();
            if (pending.prepared) pending.prepared.release();
        }
        pending = null;
    }
    function patchExports(module, source, overrides) {
        const exports = module.exports;
        if (source.includes('getCacheProgressPercent()') && exports.AudioPlayer &&
            typeof exports.AudioPlayer.preLoad === 'function') {
            const audio = exports.AudioPlayer, original = audio.preLoad;
            audio.preLoad = function (info) {
                if (info && window.__musicFetchNativeAudio) preloadNext(info);
                return original.apply(this, arguments);
            };
        }
        for (const value of Object.values(exports)) {
            if (!value) continue;
            if (typeof value.getDispatch === 'function' && typeof value.getStore === 'function') tool = value;
            if (value instanceof Map) {
                if (value.get('jymaster') === 4999000) value.set('vivid', 6999000);
                if (value.get(4999000) === 'jymaster') value.set(6999000, 'vivid');
                if (value.get(4999000) === '超清母带') value.set(6999000, '臻音全景声');
            } else if (value[4999] && value[4999].serverUsedId === 'jymaster') {
                value[6999] = {type: 'envSound', vipType: 'svip', bitRate: 6999,
                    label: '臻音全景声', tagName: '臻音全景声', serverUsedId: 'vivid'};
            } else if (value[4999] === 'jymaster') value[6999] = 'vivid';
        }
        if (source.includes('serverUsedId:"jymaster"') && typeof exports.d === 'function') songQualities = exports.d;
        for (const key of Object.keys(exports)) {
            const fn = exports[key];
            if (typeof fn === 'function' && fn.toString().includes('.quality') && fn.toString().includes('"jymaster"'))
                overrides[key] = (choice, track) => (find(choice.quality) || {}).level || fn(choice, track);
        }
        if (source.includes('/api/song/enhance/player/url/v1') && typeof exports.Of === 'function') {
            const request = exports.Of;
            musicDetail = exports.Sf;
            playerUrl = overrides.Of = async (params, options) => {
                const input = Array.isArray(params.ids) ? params.ids : [params.ids];
                const ids = input.flatMap(value => typeof value === 'string' ? [].concat(JSON.parse(value)) : [value]).map(String);
                if (pending && pending.phase === 'switching' && pending.reply &&
                    ids.length === 1 && ids[0] === pending.track && params.level === pending.actual.level) return pending.reply;
                const high = ['lossless', 'hires', 'jyeffect', 'jymaster', 'sky'].includes(params.level);
                const response = await (nativeHandler ? requestNative(params, options && options.signal) :
                    request({...params, encodeType: params.level === 'vivid' ? 'mp3' : high ? 'flac' : params.encodeType}, options));
                for (const item of response && response.data || []) {
                    if (item.url) fingerprints.set(sourceKey(item.url), fingerprint(item.url, item.md5, item.size));
                    const choice = find(item.level);
                    if (!choice || !item.id) continue;
                    metadata.set(String(item.id) + ':' + choice.value, {bitrate: Number(item.br) || 0});
                }
                while (metadata.size > 24) metadata.delete(metadata.keys().next().value);
                while (fingerprints.size > 24) fingerprints.delete(fingerprints.keys().next().value);
                return response;
            };
        }
        for (const key of Object.keys(overrides)) {
            if ((Object.getOwnPropertyDescriptor(exports, key) || {}).writable) exports[key] = overrides[key];
        }
    }
    function inspect(chunk) {
        const factories = chunk && chunk[1];
        if (!factories) return;
        for (const key of Object.keys(factories)) {
            const factory = factories[key];
            if (typeof factory !== 'function' || patched.has(factory)) continue;
            const source = factory.toString();
            if (!source.includes('this.app._store.dispatch') && !source.includes('serverUsedId:"jymaster"') &&
                !source.includes('[[5999e3,"sky"]') && !source.includes('5999:"sky"') &&
                !source.includes('/api/song/enhance/player/url/v1') && !source.includes('getCacheProgressPercent()')) continue;
            const wrapped = function (module, exports, require) {
                const overrides = {};
                const adapted = new Proxy(require, {get: (target, key) => key === 'd' ?
                    (output, name, getter) => target.d(output, name, () => overrides[name] || getter()) : Reflect.get(target, key)});
                factory.call(this, module, exports, adapted);
                patchExports(module, source, overrides);
            };
            patched.add(wrapped);
            factories[key] = wrapped;
        }
    }
    const chunks = window.webpackJsonp = window.webpackJsonp || [];
    const wrapPush = push => function (chunk) { inspect(chunk); return push.apply(this, arguments); };
    let push = wrapPush(chunks.push);
    Object.defineProperty(chunks, 'push', {configurable: true, get: () => push,
        set: next => { push = wrapPush(next); }});
    for (const chunk of chunks) inspect(chunk);

    function fetchDetails() {
        const id = trackId(store.getState());
        if (!id || !musicDetail || details.has(id) && details.get(id) !== false) return;
        details.set(id, null);
        musicDetail({songId: Number(id)}).then(response => {
            details.set(id, response && response.data || false);
            while (details.size > 24) details.delete(details.keys().next().value);
            sync();
        }).catch(() => { details.set(id, false); sync(); });
    }

    function availability(choice, state) {
        const host = state.host || {}, playing = state.playing;
        const track = playing.curPlaying && playing.curPlaying.track;
        if (playing.curPlaying && (playing.trackFileType === 'local' ||
            track && track.privilege && track.privilege.cloudSong || /voice/i.test(playing.resourceType || '')))
            return '当前内容使用原始音质';
        const maxFree = Math.max(192, Number((playing.resourcePrivilege || {}).maxFreeBr) || 0);
        const purchased = !!(track && track.privilege && track.privilege.payed);
        const musicPackage = host.isMusicPackage && (state.configCenter || {})['preload#musicPackageCanUseHiresAndLoseless'];
        const trial = (host.soundQualityUseRightInfoMap || {})[choice.level];
        const allowed = host.isPlusVip || host.isVinylVip && choice.tier !== 'SVIP' || choice.value <= maxFree ||
            purchased || musicPackage && [320, 999, 1999].includes(choice.value) || trial && trial.canUse;
        if (!allowed) return host.isAnonymous ? '登录后查看可用音质' : choice.tier === 'SVIP' ? '需超级会员' : '需黑胶会员';
        if (choice.level === 'vivid' && !vividSupported) return '需 AV3A 解码支持';
        const detail = details.get(trackId(state));
        if (detail) {
            const audio = detail[fields[choice.level]];
            const exists = audio && Number(audio.size) > 0 || choice.level === 'sky' &&
                Array.isArray(detail.sks) && detail.sks.some(item => Number(item.size) > 0);
            return exists ? '' : '当前歌曲暂无该音质';
        }
        if (detail === null) return '正在查询歌曲音质';
        if (track && songQualities && choice.level !== 'vivid' && !songQualities(track).includes(choice.value))
            return '当前歌曲暂无该音质';
        return '';
    }
    async function choose(choice) {
        if (!store || pending || availability(choice, store.getState())) return;
        const state = store.getState(), id = trackId(state);
        if (!id) { remember(state, choice); emit('已记住音质偏好'); return; }
        const howl = currentHowl();
        if (howl && howl._state !== 'loaded') { emit('请等待当前歌曲加载完成'); return; }
        const ticket = pending = {track: id, choice, phase: 'checking', controller: new AbortController(),
            paused: howl ? !howl.playing() : state.playing.playingState !== 2};
        ticket.timer = setTimeout(() => {
            if (pending === ticket) { clearPending(); emit('切换超时，请重试'); }
        }, 930000);
        emit('正在获取' + choice.name + '…');
        let checkTimer;
        try {
            const response = await Promise.race([
                playerUrl({ids: [JSON.stringify(Number(id))], level: choice.level,
                    encodeType: 'mp3', immerseType: 'ste', trialMode: -1}, {skipLocalRpcCache: true, signal: ticket.controller.signal}),
                new Promise((_, reject) => { checkTimer = setTimeout(() => reject(new Error('timeout')), 15000); })
            ]);
            if (pending !== ticket || trackId(store.getState()) !== id) return;
            const audio = response && response.data && response.data.find(item => String(item.id) === id);
            const actual = audio && find(audio.level);
            if (!audio || !audio.url || !actual || audio.freeTrialInfo) throw new Error('unavailable');
            if (audio.type === 'av3a' && !vividSupported) throw new Error('codec');
            if (response.cacheLimit && audio.size > response.cacheLimit) throw new Error('size');
            if (actual.value === Number(store.getState().playing.resourcePlayingQuality)) {
                remember(store.getState(), choice);
                clearPending(); emit(actual.value === choice.value ? '已使用' + actual.name : '已保存偏好；当前歌曲提供' + actual.name);
                return;
            }
            ticket.actual = actual; ticket.reply = response;
            if (window.__musicFetchNativeAudio) {
                discardPreload();
                ticket.phase = 'buffering';
                let last = -1;
                const prepared = await window.__musicFetchNativeAudio(audio.url, ticket.controller.signal, (bytes, total) => {
                    const percent = total ? Math.min(99, Math.floor(bytes * 100 / total)) : 0;
                    if (pending === ticket && percent !== last) { last = percent; emit('正在加载' + actual.name + ' · ' + percent + '%'); }
                });
                if (pending !== ticket || trackId(store.getState()) !== id) { prepared.release(); return; }
                ticket.prepared = prepared;
            }
            remember(store.getState(), choice);
            const active = currentHowl();
            const position = active && active._state === 'loaded' ? Number(active.seek()) : 0;
            ticket.paused = active ? !active.playing() : store.getState().playing.playingState !== 2;
            ticket.phase = 'switching';
            ticket.actual = actual;
            ticket.awaiting = true;
            emit('正在切换至' + actual.name + '…');
            const result = store.dispatch({type: 'playing/switchQuality', payload: {quality: {
                quality: actual.value, type: ['sky', 'vivid'].includes(actual.level) ? 'envSound' : 'soundQuality'},
                current: Number.isFinite(position) ? position : 0, triggerScene: 'miniBar'}});
            if (result && typeof result.then === 'function') { await result; ticket.finished = true; }
            ticket.awaiting = false; sync();
        } catch (error) {
            if (pending === ticket) {
                clearPending(); emit(error.message === 'size' ? '该音质文件较大，请选择其他档位' :
                    error.message === 'codec' ? '当前播放引擎需要 AV3A 解码支持' :
                    error.message === 'unavailable' ? '当前账号或歌曲暂未提供' + choice.name : '音质加载失败，请重试或选择其他档位');
            }
        } finally { clearTimeout(checkTimer); }
    }
    function element(tag, className, text) {
        const node = document.createElement(tag);
        node.className = className;
        if (text) node.textContent = text;
        return node;
    }
    function close() {
        if (!panel) return;
        panel.hidden = true;
        if (anchor) anchor.setAttribute('aria-expanded', 'false');
    }
    function position() {
        if (!anchor || panel.hidden) return;
        const rect = anchor.getBoundingClientRect(), width = Math.min(356, innerWidth - 24);
        panel.style.width = width + 'px';
        panel.style.left = Math.max(12, Math.min(rect.right - width, innerWidth - width - 12)) + 'px';
        panel.style.bottom = Math.max(12, innerHeight - rect.top + 12) + 'px';
    }
    function open(button) {
        if (anchor === button && !panel.hidden) { close(); return; }
        close(); anchor = button; panel.hidden = false; fetchDetails();
        button.setAttribute('aria-expanded', 'true');
        const computed = getComputedStyle(button);
        const colors = (computed.getPropertyValue('--q-control-fg') || computed.color).match(/\d+/g) || [];
        panel.dataset.theme = colors.slice(0, 3).reduce((sum, n) => sum + Number(n), 0) > 480 ? 'dark' : 'light';
        sync(); position();
        const selected = list.querySelector('[aria-checked="true"]:not(:disabled)') || list.querySelector('button:not(:disabled)');
        if (selected) selected.focus();
    }
    function sync() {
        if (!store || !panel) return;
        const state = store.getState(), playing = state.playing, id = trackId(state);
        if (lastTrack !== id) { lastTrack = id; notice = ''; if (!panel.hidden) fetchDetails(); }
        if (pending && pending.track !== id) {
            const switching = pending.phase === 'switching'; clearPending(); notice = '';
            if (switching) store.dispatch({type: 'playing/onLoadingSeekUpdate', payload: {loadingSeekDuration: 0}});
        }
        if (pending && pending.phase === 'switching' && !pending.awaiting &&
            (pending.finished || Number(playing.resourcePlayingQuality) === pending.actual.value)) {
            const howl = currentHowl();
            if (howl && howl._state === 'loaded') {
                const ticket = pending; clearPending();
                notice = Number(playing.resourcePlayingQuality) === ticket.choice.value ? '已切换至' + ticket.choice.name :
                    '当前歌曲提供' + (find(playing.resourcePlayingQuality) || ticket.actual).name;
                if (ticket.paused) pauseAction();
            }
        }
        const actual = find(playing.resourcePlayingQuality);
        const quantity = state.setting.quantity || {};
        const preferred = find(state.host.isAnonymous ? quantity.listenAnon : quantity.listenReg);
        const reasons = choices.map(q => availability(q, state));
        const next = [id, actual && actual.value, preferred && preferred.value, notice,
            !!pending, loading && loading.label, reasons.join(',')].join('|');
        if (next === signature) return;
        signature = next;
        for (const button of document.querySelectorAll('.ncm-quality-button')) {
            button.textContent = loading ? loading.label : pending ? '切换中…' : actual && id ? actual.name : '音质';
            button.title = loading ? '正在准备整首歌曲' : actual && id ? '当前音质：' + actual.name : '选择播放音质';
        }
        choices.forEach((choice, index) => {
            const row = rows.get(choice.value), reason = reasons[index];
            row.disabled = !!pending || !!reason;
            row.title = reason || choice.description;
            row.setAttribute('aria-checked', String(!!actual && actual.value === choice.value && !!id));
            row.querySelector('.ncm-quality-description').textContent = reason || choice.description;
        });
        const info = actual && metadata.get(id + ':' + actual.value);
        footer.textContent = notice || (id && actual ? '当前：' + actual.name +
            (info && info.bitrate ? ' · ' + Math.round(info.bitrate / 1000) + ' kbps' : '') +
            (preferred && preferred.value !== actual.value ? ' · 优先：' + preferred.name : '') : '选择后记住偏好');
    }
    function place() {
        scheduled = false;
        const bar = [...document.querySelectorAll('#page_pc_mini_bar .right-side .right')].find(node => {
            const rect = node.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 && rect.top < innerHeight && rect.bottom > 0;
        });
        control.hidden = !bar;
        if (bar) {
            const rect = bar.getBoundingClientRect(), size = control.getBoundingClientRect();
            control.style.left = Math.max(12, rect.left - size.width - 16) + 'px';
            control.style.top = rect.top + (rect.height - size.height) / 2 + 'px';
            control.style.setProperty('--q-control-fg', getComputedStyle(bar).color);
        } else close();
        sync();
    }
    function mount() {
        if (!tool || !tool.app || !tool.app._store || !playerUrl || !document.body) return false;
        store = tool.app._store;
        if (!store.getState().playing || !store.getState().setting) return false;
        const style = element('style', ''); style.textContent = STYLE; document.head.appendChild(style);
        control = element('button', 'ncm-quality-button', '音质'); control.type = 'button';
        control.setAttribute('aria-label', '选择播放音质'); control.setAttribute('aria-haspopup', 'menu');
        control.setAttribute('aria-expanded', 'false');
        control.addEventListener('click', event => { event.stopPropagation(); open(control); });
        document.body.appendChild(control);
        panel = element('div', 'ncm-quality-panel'); panel.hidden = true;
        panel.setAttribute('role', 'menu'); panel.setAttribute('aria-label', '播放音质');
        const header = element('div', 'ncm-quality-header', '播放音质');
        const dismiss = element('button', 'ncm-quality-close', '×'); dismiss.type = 'button';
        dismiss.setAttribute('aria-label', '关闭音质菜单'); dismiss.addEventListener('click', close); header.appendChild(dismiss);
        list = element('div', 'ncm-quality-list'); footer = element('div', 'ncm-quality-footer');
        footer.setAttribute('aria-live', 'polite');
        choices.forEach((choice, index) => {
            if (!index || index === 7) list.appendChild(element('div', 'ncm-quality-group', index ? '空间音频' : '音质'));
            const row = element('button', 'ncm-quality-row'); row.type = 'button';
            row.setAttribute('role', 'menuitemradio'); row.dataset.level = choice.level;
            const icon = element('span', 'ncm-quality-icon', choice.icon);
            const text = element('span', 'ncm-quality-text');
            const name = element('span', 'ncm-quality-name', choice.name);
            if (choice.tier) name.appendChild(element('span', 'ncm-quality-tier', choice.tier));
            text.appendChild(name); text.appendChild(element('span', 'ncm-quality-description', choice.description));
            row.appendChild(icon); row.appendChild(text); row.appendChild(element('span', 'ncm-quality-check', '✓'));
            row.addEventListener('click', () => choose(choice)); rows.set(choice.value, row); list.appendChild(row);
        });
        panel.appendChild(header); panel.appendChild(list); panel.appendChild(footer); document.body.appendChild(panel);
        panel.addEventListener('keydown', event => {
            if (event.key === 'Escape') { close(); if (anchor) anchor.focus(); event.preventDefault(); return; }
            if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
            const buttons = [...list.querySelectorAll('button:not(:disabled)')];
            if (!buttons.length) return;
            const index = buttons.indexOf(document.activeElement);
            const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 :
                (index + (event.key === 'ArrowUp' ? -1 : 1) + buttons.length) % buttons.length;
            buttons[next].focus(); event.preventDefault();
        });
        document.addEventListener('pointerdown', event => {
            if (!panel.hidden && !panel.contains(event.target) && event.target !== anchor) close();
        }, true);
        window.addEventListener('resize', () => { place(); position(); });
        window.addEventListener('music-audio-progress', ({detail}) => {
            if (detail.loading) {
                const percent = detail.total ? Math.min(99, Math.floor(detail.bytes * 100 / detail.total)) : null;
                loading = {howl: detail.howl, label: detail.decoding ? '解码中…' :
                    percent === null ? '加载中…' : '加载 ' + percent + '%'};
            } else if (loading && loading.howl === detail.howl) {
                loading = null;
            }
            sync();
        });
        window.addEventListener('music-audio-ready', ({detail: howl}) => setTimeout(() => {
            if (howl === currentHowl() && howl.playing() && !pending)
                store.dispatch({type: 'playing/preFetchNext', payload: {}});
        }, 1000));
        window.addEventListener('music-audio-load-error', event => {
            if (pending && pending.phase === 'switching' && event.detail === currentHowl()) {
                clearPending(); emit('音质加载失败，请重试或选择其他档位');
            }
        });
        const observer = new MutationObserver(() => {
            if (!scheduled) { scheduled = true; requestAnimationFrame(place); }
        });
        observer.observe(document.body, {childList: true, subtree: true});
        store.subscribe(sync); place();
        window.addEventListener('pageshow', place);
        window.addEventListener('pagehide', () => { clearPending(); discardPreload(); });
        return true;
    }
    const STYLE = `
.ncm-quality-button{position:fixed;z-index:1000;font:inherit;font-size:11px;line-height:20px;white-space:nowrap;color:var(--q-control-fg,inherit);background:transparent;border:1px solid currentColor;border-radius:4px;padding:0 7px;opacity:.75;cursor:pointer}
.ncm-quality-button:hover,.ncm-quality-button[aria-expanded=true]{color:#ba8c45;opacity:1}
.ncm-quality-panel{--q-bg:#fff;--q-fg:#292a30;--q-muted:#909098;--q-hover:#f7f5f1;position:fixed;z-index:2147483000;display:flex;flex-direction:column;max-height:calc(100vh - 120px);color:var(--q-fg);background:var(--q-bg);border:1px solid rgba(128,128,128,.14);border-radius:14px;box-shadow:0 8px 36px #0003;font-family:inherit;font-size:13px;overflow:hidden;text-align:left}
.ncm-quality-panel[hidden]{display:none}
.ncm-quality-panel[data-theme=dark]{--q-bg:#26262c;--q-fg:#efeff2;--q-muted:#96969f;--q-hover:#333238}
.ncm-quality-header{display:flex;align-items:center;justify-content:space-between;padding:16px 20px 10px;font-size:16px;font-weight:600;flex-shrink:0}
.ncm-quality-close{border:0;background:none;color:var(--q-muted);font:22px/24px sans-serif;cursor:pointer;padding:0 2px}
.ncm-quality-list{overflow-y:auto;padding:0 8px 8px;overscroll-behavior:contain}
.ncm-quality-group{padding:10px 12px 5px;color:var(--q-muted);font-size:11px}
.ncm-quality-row{display:flex;align-items:center;gap:13px;width:100%;padding:10px 12px;border:0;border-radius:8px;background:none;color:var(--q-fg);font:inherit;text-align:left;cursor:pointer}
.ncm-quality-row:hover,.ncm-quality-row:focus-visible{background:var(--q-hover);outline:none}
.ncm-quality-row:disabled{cursor:default;opacity:.48}
.ncm-quality-row:disabled:hover{background:none}
.ncm-quality-icon{display:flex;align-items:center;justify-content:center;width:43px;height:31px;flex-shrink:0;color:#ae8242;background:linear-gradient(140deg,#ead0a629,#d5b27a12);border:1px solid #c7a57255;border-radius:6px;font-size:9px;letter-spacing:-.3px;font-weight:700}
.ncm-quality-text{display:flex;flex-direction:column;gap:4px;flex:1;min-width:0}
.ncm-quality-name{display:flex;align-items:center;gap:7px;font-size:13px;white-space:nowrap}
.ncm-quality-tier{font-size:8px;line-height:13px;letter-spacing:.3px;padding:0 4px;color:#8c632e;background:linear-gradient(110deg,#f8e5c3,#d9b980);border-radius:3px;font-weight:600}
.ncm-quality-description{color:var(--q-muted);font-size:11px;line-height:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ncm-quality-check{visibility:hidden;color:#bc8d46;font-size:19px;width:18px;text-align:center;flex-shrink:0}
.ncm-quality-row[aria-checked=true] .ncm-quality-check{visibility:visible}
.ncm-quality-row[aria-checked=true] .ncm-quality-name{color:#b88a43}
.ncm-quality-footer{padding:11px 20px;color:var(--q-muted);border-top:1px solid #8882;font-size:11px;line-height:17px;flex-shrink:0}
`;
    let attempts = 0;
    const timer = setInterval(() => { if (mount() || ++attempts >= 600) clearInterval(timer); }, 100);
    window.addEventListener('pagehide', () => {
        clearInterval(timer);
        for (const [id, request] of nativeRequests) {
            takeNative(id);
            nativeHandler.postMessage(JSON.stringify({event: 'cancel', id}));
        }
        nativeRequests.clear();
    });
})();
