/* TripMind Partner Hub — shared runtime.
 *
 * The Flask app already refuses to serve a protected Partner Hub page without an
 * approved partner session (see partner_hub_page in backend/app.py). This file
 * is the client half of the same rule: it confirms the signed-in account really
 * is a partner before rendering any provider data, so a passenger never sees
 * provider UI and a partner never lands on a passenger dashboard by accident.
 *
 * Shared by every page under /tripmind-partner.
 */
var PARTNER_PREFIX = '/tripmind-partner';

var TM_PARTNER = (function () {
    'use strict';

    var PARTNER_ROLE = 'TRANSPORT_ADMIN';

    var PARTNER_TYPES = {
        BUS_OPERATOR: { label: 'Bus operator', service: 'BUS' },
        DRIVER: { label: 'Driver / vehicle owner', service: 'CAB' },
        TRAVEL_OPERATOR: { label: 'Travel operator', service: 'BUS' },
        OTHER: { label: 'Other travel partner', service: 'BUS' }
    };

    var NAV = [
        { href: 'dashboard', label: 'Dashboard', n: '01' },
        { href: 'buses', label: 'My services', n: '02' },
        { href: 'boarding-points', label: 'Boarding points', n: '03' },
        { href: 'bookings', label: 'Bookings', n: '04' },
        { href: 'profile', label: 'Profile', n: '05' }
    ];

    var state = { user: null, partnerType: 'BUS_OPERATOR' };

    /* ------------------------------------------------------------- helpers */
    function q(sel, root) { return (root || document).querySelector(sel); }
    function qa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
    function esc(s) { return (typeof TM !== 'undefined' && TM.esc) ? TM.esc(s) : String(s == null ? '' : s); }
    function money(n) {
        if (typeof TM !== 'undefined' && TM.fmtMoney) return TM.fmtMoney(n);
        return '₹' + Math.round(Number(n) || 0).toLocaleString('en-IN');
    }

    function initials(name) {
        var parts = String(name || '').trim().split(/\s+/).filter(Boolean);
        if (!parts.length) return 'P';
        return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
    }

    function typeLabel(key) {
        return (PARTNER_TYPES[key] || {}).label || 'Travel partner';
    }

    function partnerTypeOf(user) {
        var reg = (user && user.registration) || {};
        var key = String(reg.partnerType || '').toUpperCase().replace(/[\s-]+/g, '_');
        return PARTNER_TYPES[key] ? key : 'BUS_OPERATOR';
    }

    function serviceName() {
        var prof = (state.user && state.user.profile) || {};
        return prof.serviceName || (reg(state.user).companyName) || (state.user && state.user.name) || 'Your service';
    }

    function reg(user) { return ((user || {}).registration) || {}; }

    function serviceForType() {
        return (PARTNER_TYPES[state.partnerType] || PARTNER_TYPES.BUS_OPERATOR).service;
    }

    function fmtDate(value) {
        if (!value) return '—';
        var d = new Date(value);
        if (isNaN(d.getTime())) return String(value);
        return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
    }

    function fmtDayTime(doc) {
        if (!doc) return '';
        var t = doc.boardingTime || '';
        return 'Day ' + (doc.boardingDay == null ? 0 : doc.boardingDay) + (t ? ' · ' + t : '');
    }

    var STATUS_PILL = {
        APPROVED: 'ph-pill--ok',
        PENDING: 'ph-pill--wait',
        REJECTED: 'ph-pill--bad',
        SUSPENDED: 'ph-pill--bad',
        CONFIRMED: 'ph-pill--ok',
        CANCELLED: 'ph-pill--bad',
        PENDING_PAYMENT: 'ph-pill--wait'
    };

    function pill(status, label) {
        var key = String(status || '').toUpperCase();
        var cls = STATUS_PILL[key] || 'ph-pill--mute';
        return '<span class="ph-pill ' + cls + '">' + esc(label || key.replace(/_/g, ' ') || 'n/a') + '</span>';
    }

    function empty(title, text, cta) {
        return '<div class="ph-empty"><h3>' + esc(title) + '</h3><p>' + esc(text) + '</p>' +
            (cta ? '<div class="ph-empty__cta">' + cta + '</div>' : '') + '</div>';
    }

    function loading(text) {
        return '<div class="ph-loading"><span>' + esc(text || 'Loading…') + '</span></div>';
    }

    function fail(node, err) {
        if (!node) return;
        node.innerHTML = empty('Could not load this right now',
            (err && err.message) ? err.message : 'Please try again in a moment.',
            '<a class="tm-btn tm-btn--ghost" href="' + PARTNER_PREFIX + '/dashboard">Back to dashboard</a>');
    }

    function toast(message, kind) {
        if (typeof TM !== 'undefined' && TM.toast) TM.toast(message, kind);
    }

    function reducedMotion() {
        return (typeof TM !== 'undefined' && TM.reducedMotion) ? TM.reducedMotion() : false;
    }

    function busy(btn, on) { if (typeof TM !== 'undefined' && TM.button) TM.button(btn, on); }

    /* --------------------------------------------------------------- shell */
    function renderUser() {
        var name = (state.user && state.user.name) || 'Partner';
        var chip = q('[data-ph-user-name]');
        if (chip) chip.textContent = name;
        var av = q('[data-ph-user-avatar]');
        if (av) av.textContent = initials(name);
        var who = q('[data-ph-partner-type]');
        if (who) who.textContent = typeLabel(state.partnerType);
        qa('[data-ph-role-note]').forEach(function (n) { n.textContent = serviceName(); });
    }

    function renderNav() {
        var host = q('[data-ph-nav]');
        if (!host) return;
        var here = (location.pathname.replace(/\/+$/, '') || PARTNER_PREFIX).split('/').pop() || 'dashboard';
        host.innerHTML = NAV.map(function (item) {
            var current = item.href === here;
            return '<li><a class="ph-drawer__link" href="' + PARTNER_PREFIX + '/' + item.href + '"' +
                (current ? ' aria-current="page"' : '') + '>' + esc(item.label) +
                '<span>' + esc(item.n) + '</span></a></li>';
        }).join('');
    }

    function initDrawer() {
        var drawer = q('[data-ph-drawer]');
        if (!drawer) return;
        renderNav();
        var burger = q('[data-ph-burger]');
        var close = q('[data-ph-drawer-close]');
        var scrim = q('[data-ph-drawer-scrim]');
        function setOpen(on) {
          drawer.setAttribute('data-open', on ? 'true' : 'false');
          drawer.hidden = !on;
          if (on) { document.body.style.overflow = 'hidden'; }
          else { document.body.style.overflow = ''; }
          if (burger) burger.setAttribute('aria-expanded', on ? 'true' : 'false');
          if (on) { var f = drawer.querySelector('a, button'); if (f) f.focus(); }
          else if (burger) burger.focus();
        }
        if (burger) burger.addEventListener('click', function () { setOpen(drawer.hidden); });
        if (close) close.addEventListener('click', function () { setOpen(false); });
        if (scrim) scrim.addEventListener('click', function () { setOpen(false); });
        document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !drawer.hidden) setOpen(false); });
        setOpen(false);
    }

    async function logout() {
        try { await api.logout(); } catch (e) { /* the session ends server-side regardless */ }
        location.href = PARTNER_PREFIX + '/';
    }

    function initShell() {
        renderUser();
        initDrawer();
        qa('[data-ph-signout]').forEach(function (b) { b.addEventListener('click', logout); });
    }

    /* -------------------------------------------------------------- routing */
    function safeNext() {
        var next = new URLSearchParams(location.search).get('next') || '';
        if (next.indexOf(PARTNER_PREFIX) !== 0) return '';
        return next;
    }

    function go(path) { location.href = PARTNER_PREFIX + '/' + path; }

    /* Boot a protected Partner Hub page.
     * view(state) is called only once the session is confirmed to be a partner. */
    async function boot(opts) {
        opts = opts || {};
        var me;
        try {
            me = await api.me();
        } catch (e) {
            location.replace(PARTNER_PREFIX + '/login?next=' + encodeURIComponent(location.pathname));
            return;
        }
        var user = me && me.user;
        if (!user) {
            location.replace(PARTNER_PREFIX + '/login?next=' + encodeURIComponent(location.pathname));
            return;
        }
        if (user.role !== PARTNER_ROLE) {
            location.replace(PARTNER_PREFIX + '/forbidden');
            return;
        }
        state.user = user;
        state.partnerType = partnerTypeOf(user);
        initShell();
        document.documentElement.setAttribute('data-partner', state.partnerType.toLowerCase());
        if (opts.view) {
            try { await opts.view(state); }
            catch (e) { console.error('[partner]', e); toast('Something went wrong loading this page.', 'error'); }
        }
    }

    /* ------------------------------------------------------------- location */
    /* Wires the shared Google Maps picker when a key is configured, and always
     * leaves working manual coordinate fields behind so the form is usable
     * without Maps. Coordinates are what the passenger planner consumes. */
    async function locationPicker(opts) {
        opts = opts || {};
        var mapEl = opts.mapId ? document.getElementById(opts.mapId) : null;
        var ready = false;
        try {
            ready = (await TM_MAPS.init()) === true;
        } catch (e) { ready = false; }
        if (!ready || !TM_MAPS || !TM_MAPS.initLocationPicker) {
            if (mapEl) mapEl.setAttribute('data-ready', 'false');
            return null;
        }
        var controller = TM_MAPS.initLocationPicker({
            addressId: opts.addressId,
            latId: opts.latId,
            lngId: opts.lngId,
            mapId: opts.mapId,
            required: !!opts.required,
            onPick: opts.onPick
        });
        if (mapEl) mapEl.setAttribute('data-ready', controller ? 'true' : 'false');
        return controller;
    }

    function fillLocation(ids, lat, lng, name) {
        var latEl = document.getElementById(ids.latId);
        var lngEl = document.getElementById(ids.lngId);
        var addrEl = document.getElementById(ids.addressId);
        if (lat == null || isNaN(parseFloat(lat))) return false;
        if (latEl) latEl.value = Number(lat).toFixed(6);
        if (lngEl) lngEl.value = Number(lng).toFixed(6);
        if (addrEl && name) addrEl.value = name;
        return true;
    }

    function readLocation(ids) {
        var latEl = document.getElementById(ids.latId);
        var lngEl = document.getElementById(ids.lngId);
        var addrEl = document.getElementById(ids.addressId);
        if (!latEl || !lngEl) return { lat: null, lng: null, address: '' };
        var lat = parseFloat(latEl.value);
        var lng = parseFloat(lngEl.value);
        return {
            lat: isNaN(lat) ? null : lat,
            lng: isNaN(lng) ? null : lng,
            address: (addrEl && addrEl.value) || ''
        };
    }

    function routeLabel(doc) {
        if (!doc) return '—';
        if (doc.type === 'BUS') return (doc.boardingPoint || '—') + ' → ' + (doc.droppingPoint || '—');
        if (doc.type === 'TRAIN') return (doc.boardingStation || '—') + ' → ' + (doc.destinationStation || '—');
        if (doc.type === 'FLIGHT') return (doc.departureAirport || '—') + ' → ' + (doc.arrivalAirport || '—');
        return (doc.baseLocation || doc.serviceArea || '—');
    }

    function numberOf(doc) {
        if (!doc) return '';
        return doc.busNumber || doc.trainNumber || doc.flightNumber || doc.vehicleNumber || '—';
    }

    function capacityOf(doc) {
        if (!doc) return 0;
        if (doc.totalSeats) return Number(doc.totalSeats);
        if (doc.seatingCapacity) return Number(doc.seatingCapacity);
        if (Array.isArray(doc.coaches)) {
            return doc.coaches.reduce(function (n, c) {
                return n + (Number(c.coachCount) || 0) * (Number(c.capacityPerCoach) || 0);
            }, 0);
        }
        if (Array.isArray(doc.classes)) {
            return doc.classes.reduce(function (n, c) { return n + (Number(c.seats) || 0); }, 0);
        }
        return 0;
    }

    function typeLabelOf(doc) {
        if (!doc) return '—';
        if (doc.type === 'BUS') return 'Bus';
        if (doc.type === 'TRAIN') return 'Train';
        if (doc.type === 'FLIGHT') return 'Flight';
        if (doc.type === 'CAB') return 'Cab';
        if (doc.type === 'AUTO') return 'Auto';
        return doc.type || '—';
    }

    return {
        PARTNER_ROLE: PARTNER_ROLE,
        PARTNER_TYPES: PARTNER_TYPES,
        NAV: NAV,
        state: state,
        q: q, qa: qa, esc: esc, money: money,
        pill: pill, empty: empty, loading: loading, fail: fail,
        toast: toast, busy: busy, initials: initials, reducedMotion: reducedMotion,
        typeLabel: typeLabel, partnerTypeOf: partnerTypeOf, serviceName: serviceName,
        serviceForType: serviceForType, reg: reg,
        fmtDate: fmtDate, fmtDayTime: fmtDayTime,
        boot: boot, go: go, logout: logout, safeNext: safeNext, initShell: initShell,
        locationPicker: locationPicker, fillLocation: fillLocation, readLocation: readLocation,
        routeLabel: routeLabel, numberOf: numberOf, capacityOf: capacityOf, typeLabelOf: typeLabelOf,
        renderUser: renderUser
    };
})();
