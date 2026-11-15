/* Decode complete authorized tracks before playback. Web Audio seeks address
 * decoded samples and avoid WebKit's compressed-media seek/preroll pipeline. */
(() => {
    'use strict';
    if (location.origin !== 'https://music.163.com' ||
        location.pathname.replace(/\/$/, '') !== '/st/webplayer') return;
    const routes = new Map(), tickets = new WeakMap(), patched = new WeakSet();
    let active = null;
    const sourceOf = howl => Array.isArray(howl._src) ? howl._src[0] : howl._src;
    const eligible = source => {
        try {
            const uri = new URL(source);
            return ['http:', 'https:'].includes(uri.protocol) && uri.hostname.endsWith('.music.126.net');
        } catch (_) { return false; }
    };
    const stop = (howl, ticket) => {
        clearTimeout(ticket.timer);
        ticket.controller.abort();
        for (const xhr of ticket.xhrs) xhr.abort();
        ticket.xhrs.clear();
        if (ticket.release) { ticket.release(); ticket.release = null; }
        if (routes.get(ticket.source) === ticket) routes.delete(ticket.source);
        if (tickets.get(howl) === ticket) tickets.delete(howl);
    };
    // Howler still sees its requested URL. Only its authorized audio XHR is
    // routed to the complete private copy, keeping source and queue identity.
    const open = XMLHttpRequest.prototype.open, send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url, ...args) {
        this.__musicTicket = null;
        const ticket = routes.get(String(url));
        if (ticket && ticket.url && method.toUpperCase() === 'GET') {
            ticket.xhrs.add(this);
            this.__musicTicket = ticket;
            return open.call(this, method, ticket.url, ...args);
        }
        return open.call(this, method, url, ...args);
    };
    XMLHttpRequest.prototype.send = function () {
        const ticket = this.__musicTicket;
        if (ticket) {
            const callback = this.onload;
            this.onload = function () {
                ticket.xhrs.delete(this);
                if (!ticket.controller.signal.aborted && callback) return callback.apply(this, arguments);
            };
        }
        return send.apply(this, arguments);
    };
    function install() {
        const Howl = window.Howl;
        if (!Howl || !Howl.prototype) return false;
        const proto = Howl.prototype;
        if (patched.has(proto)) return true;
        patched.add(proto);
        const init = proto.init, load = proto.load, unload = proto.unload, play = proto.play;
        proto.init = function (options) {
            const source = options && (Array.isArray(options.src) ? options.src[0] : options.src);
            if (eligible(source)) options = Object.assign({}, options, {html5: false});
            return init.call(this, options);
        };
        proto.load = function () {
            const source = sourceOf(this);
            if (!this._webAudio || !eligible(source) || !window.__musicFetchNativeAudio)
                return load.apply(this, arguments);
            let ticket = tickets.get(this);
            if (ticket && ticket.source === source) {
                if (ticket.url) return load.apply(this, arguments);
                return this;
            }
            if (ticket) stop(this, ticket);
            ticket = {source, controller: new AbortController(), xhrs: new Set(),
                timer: 0, release: null, url: null};
            tickets.set(this, ticket);
            this._state = 'loading';
            ticket.timer = setTimeout(() => ticket.controller.abort(), 20000);
            window.__musicFetchNativeAudio(source, ticket.controller.signal).then(response => {
                if (tickets.get(this) !== ticket || ticket.controller.signal.aborted) { response.release(); return; }
                ticket.url = response.url;
                ticket.release = response.release;
                clearTimeout(ticket.timer);
                routes.set(source, ticket);
                this.once('loaderror', () => { if (tickets.get(this) === ticket) stop(this, ticket); });
                this.once('load', () => {
                    // The decoded AudioBuffer owns its samples. Release the
                    // encoded copy as soon as decoding succeeds.
                    if (ticket.release) { ticket.release(); ticket.release = null; }
                    if (routes.get(source) === ticket) routes.delete(source);
                });
                load.call(this);
            }).catch(() => {
                if (tickets.get(this) !== ticket) return;
                stop(this, ticket);
                this._state = 'unloaded';
                this._queue = [];
                this._emit('loaderror', null, 'Audio could not be loaded');
            });
            return this;
        };
        proto.unload = function () {
            const ticket = tickets.get(this);
            if (ticket) stop(this, ticket);
            if (active === this) active = null;
            return unload.apply(this, arguments);
        };
        proto.play = function () {
            if (this._webAudio && eligible(sourceOf(this))) active = this;
            return play.apply(this, arguments);
        };
        return true;
    }
    Object.defineProperty(window, '__musicNativeHowl', {value: () => active});
    const descriptor = Object.getOwnPropertyDescriptor(window, 'Howl');
    if (!descriptor || descriptor.configurable) {
        let value = descriptor && descriptor.value;
        Object.defineProperty(window, 'Howl', {configurable: true, enumerable: true,
            get: () => descriptor && descriptor.get ? descriptor.get.call(window) : value,
            set: next => {
                if (descriptor && descriptor.set) descriptor.set.call(window, next);
                else value = next;
                install();
            }});
    }
    if (!install()) {
        let attempts = 0;
        const timer = setInterval(() => { if (install() || ++attempts >= 300) clearInterval(timer); }, 100);
        window.addEventListener('pagehide', () => clearInterval(timer));
    }
})();
