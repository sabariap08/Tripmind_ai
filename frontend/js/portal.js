/* TripMind AI \u2014 role-aware portal controller */
(function () {
    'use strict';

    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const money = (v) => '\u20b9' + Number(v || 0).toLocaleString('en-IN');
    const STYLE_LABEL = { BUDGET: 'Budget', BALANCED: 'Balanced', COMFORT: 'Comfort', PREMIUM: 'Premium' };
    const styleLabel = (v) => STYLE_LABEL[String(v || '').toUpperCase()] || '';
    const payPill = (s) => {
        const v = String(s || 'PENDING').toUpperCase();
        const cls = v === 'PAID' ? 'good' : v === 'PENDING' ? 'warn' : 'bad';
        return `<span class="pill ${cls}">${esc(v === 'PAID' ? 'Paid' : v)}</span>`;
    };
    const timeago = (iso) => iso ? String(iso).slice(0, 19).replace('T', ' ') : '';

    let toastTimer = null;

    /* Read-only registration helpers: the business identity declared at
       registration is rendered from user.registration everywhere in the
       portal. */
    const regVal = (label) => (user.registration || {})[label] || '';
    function regList(label, fallback) {
        const v = regVal(label) || (fallback || '');
        if (Array.isArray(v)) return v;
        return String(v).split(',').map(s => s.trim()).filter(Boolean);
    }
    function wkHoursList() {
        try {
            const v = regVal('Weekly Working Hours');
            const arr = v ? JSON.parse(v) : [];
            return Array.isArray(arr) ? arr : [];
        } catch (e) { return []; }
    }
    function wkHoursText() {
        const arr = wkHoursList();
        return arr.length ? arr.map(x => `${String(x.day || '').slice(0, 3)} ${x.open}\u2013${x.close}`).join(', ')
            : (regVal('Weekly Working Hours') || '\u2014');
    }
    function bizLoc() {
        return { address: regVal('Location Address') || regVal('Address') || '',
                 lat: regVal('Latitude') || regVal('lat') || '',
                 lng: regVal('Longitude') || regVal('lng') || '' };
    }
    function infoRow(label, value) {
        if (value === undefined || value === null || String(value).trim() === '') return '';
        return `<div class="detail-item"><span class="k">${esc(label)}</span><span class="v">${esc(String(value))}</span></div>`;
    }

    function toast(msg, err) {
        const t = $('toast');
        t.style.display = 'block';
        t.style.background = err ? '#b91c1c' : '#0f172a';
        t.textContent = msg;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => t.style.display = 'none', 3500);
    }
    async function run(fn) {
        try { await fn(); } catch (e) { toast(e.message, true); console.error(e); }
    }

    let user = null;
    let currentPanel = null;
    const PANELS = [];

    function definePanel(id, roles, render) {
        PANELS.push({ id, roles, render });
    }

    const ADMIN = 'ADMIN', RAILWAY = 'RAILWAY_ADMIN', TRANSPORT = 'TRANSPORT_ADMIN', TOURIST = 'TOURIST_SPOT_ADMIN',
          HOTEL = 'HOTEL_ADMIN', RESTAURANT = 'RESTAURANT_ADMIN', GUIDE = 'GUIDE', USER = 'USER';

    const ROLE_LABEL = {
        ADMIN: 'Administrator', RAILWAY_ADMIN: 'Railways / IRCTC',
        TRANSPORT_ADMIN: 'Transport Admin',
        TOURIST_SPOT_ADMIN: 'Travel Spot Admin', HOTEL_ADMIN: 'Hotel Admin',
        RESTAURANT_ADMIN: 'Restaurant Admin',
        GUIDE: 'Guide', USER: 'Normal User',
    };

    function navFor(role) {
        const fixtures = {
            USER: [
                { group: '', items: [['Dashboard', 'overview'], ['Passenger Details', 'url:/passengers.html'], ['Profile', 'myprofile']] },
                { group: 'Plan', items: [['Plan My Trip', 'plantrip']] },
                { group: 'My Stuff', items: [['My Bookings', 'book'], ['My Wallet', 'wallet'], ['Feedback', 'pfeedback']] },
            ],
            TRANSPORT_ADMIN: [
                { group: '', items: [['Dashboard', 'pstats']] },
                { group: 'Manage', items: [['Manage Transport', 'register'], ['Upcoming Passengers', 'fleet'], ['Company Profile', 'profile']] },
            ],
            TOURIST_SPOT_ADMIN: [
                { group: '', items: [['Dashboard', 'pstats']] },
                { group: 'Add New', items: [['Tourist Spot', 'spotform'], ['Guide Locations', 'cat'], ['Tours & Experiences', 'tourform']] },
            ],
            HOTEL_ADMIN: [
                { group: '', items: [['Dashboard', 'pstats']] },
                { group: 'Manage', items: [['Hotel Profile', 'hotel'], ['Room Inventory', 'hinv'], ['Hotel Bookings', 'hbook']] },
            ],
            RESTAURANT_ADMIN: [
                { group: '', items: [['Dashboard', 'pstats']] },
                { group: 'Manage', items: [['Restaurant Profile', 'restform'], ['Food Items', 'rfood'], ['Orders', 'rbook']] },
            ],
            GUIDE: [
                { group: '', items: [['Dashboard', 'pstats']] },
                { group: 'Manage', items: [['Guide Profile', 'gprofile'], ['Availability', 'gavail']] },
                { group: 'Requests', items: [['Tour Requests', 'greq'], ['Assignments', 'gassign']] },
            ],
            ADMIN: [
                { group: '', items: [['Dashboard', 'dash'], ['Approvals', 'approvals'], ['All Users', 'users'], ['Plans of Users', 'plans']] },
                { group: 'AI Insights', items: [['What TripMind Learned', 'insights'], ['Feedback Analysis', 'feedback']] },
            ],
            RAILWAY_ADMIN: [
                { group: '', items: [['Dashboard', 'pstats']] },
                { group: 'Manage', items: [['Manage Trains', 'register'], ['Railway Lounges', 'rlounges'], ['Passenger Bookings', 'fleet'], ['Company Profile', 'profile']] },
            ],
        };
        return fixtures[role] || fixtures.USER;
    }

    async function init() {
        const res = await api.me();
        user = res.user;
        if (!user) { location.href = '/login.html'; return; }
        $('userName').textContent = user.name;
        $('userSub').textContent = `${ROLE_LABEL[user.role] || user.role} \u00b7 ${user.email}`;
        $('userChip').innerHTML = `<span class="user-chip-name">${esc(user.name)}</span><span class="role-badge">${esc(user.role)}</span>`;
        definePanels();
        setupDrawer();
        renderNav();
        const secs = navFor(user.role);
        const first = secs.length && secs[0].items.length ? secs[0].items[0][1] : null;
        if (location.hash && location.hash.indexOf('#user/') === 0) {
            handleHash();
        } else {
            showPanel(first || PANELS.find(p => p.roles.includes(user.role)).id);
        }
    }

    /* MERGE, do not replace.
     *
     * This used to be `window.TM = { logout, reviewTrip }`, which threw away
     * everything ui.js and api.js had put on the namespace. The damage was
     * silent rather than loud: ui.js's own listeners close over the *global*
     * `TM` binding, not over the object they were defined against, so after
     * this line they resolved `TM.drawer` / `TM.lockScroll` to undefined and
     * threw a TypeError the first time a drawer or burger was used. TM.esc,
     * TM.toast, TM.button and TM.api were equally gone. */
    window.TM = window.TM || {};
    Object.assign(window.TM, {
        logout: () => run(async () => { await api.logout(); location.href = '/login.html'; }),
        reviewTrip: async (id, origin, destination) => {
            const m = dialog(`<h3>Review your trip</h3>
                <p class="text-muted">${esc(origin)} \u2192 ${esc(destination)}</p>
                ${field('Your rating', 'tr_stars', `<select id="tr_stars" class="form-select">${[1,2,3,4,5].map(s => `<option value="${s}" ${s === 5 ? 'selected' : ''}>${'\u2605'.repeat(s)}${'\u2606'.repeat(5 - s)}</option>`).join('')}</select>`)}
                ${field('Your comment (optional)', 'tr_comment', `<textarea id="tr_comment" class="form-textarea" placeholder="What did you like or dislike?"></textarea>`)}
                <div class="flex end gap">
                    <button class="btn btn-outline" data-close>Cancel</button>
                    <button class="btn btn-primary" id="__ok">Submit Review</button>
                </div>`);
            m.get('#__ok').addEventListener('click', () => run(async () => {
                await api.addTripReview(id, +m.get('#tr_stars').value, m.get('#tr_comment').value);
                toast('Thanks for your feedback!');
                m.close();
            }));
        },
    });
    window.showPanel = showPanel;

    /* Simplified, role-based navigation (groups + sign-out). */
    function definePanels() {
        definePanel('overview', [USER], userOverview);
        definePanel('book', [USER], userMyBookings);
        definePanel('wallet', [USER], userWallet);
        definePanel('myprofile', [USER], userProfilePanel);
        definePanel('plantrip', [USER], userPlanTrip);
        definePanel('pfeedback', [USER], userFeedbackPanel);
        definePanel('pstats', [USER, TRANSPORT, RAILWAY, TOURIST, HOTEL, RESTAURANT, GUIDE], providerStatsPanel);
        definePanel('profile', [TRANSPORT, RAILWAY], transportProfile);
        definePanel('register', [TRANSPORT, RAILWAY], transportRegister);
        definePanel('fleet', [TRANSPORT, RAILWAY], transportFleet);
        definePanel('rlounges', [RAILWAY], railwayLounges);
        definePanel('spotform', [TOURIST], touristSpotForm);
        definePanel('cat', [TOURIST], touristCatalogue);
        definePanel('tourform', [TOURIST], touristTours);
        definePanel('hotel', [HOTEL], hotelProfile);
        definePanel('hinv', [HOTEL], hotelInventory);
        definePanel('hbook', [HOTEL], hotelBookings);
        definePanel('rest', [RESTAURANT], restaurantList);
        definePanel('restform', [RESTAURANT], restaurantForm);
        definePanel('rfood', [RESTAURANT], foodItemsPanel);
        definePanel('rbook', [RESTAURANT], restaurantOrdersPanel);
        definePanel('gprofile', [GUIDE], guideProfile);
        definePanel('gavail', [GUIDE], guideAvailability);
        definePanel('greq', [GUIDE], guideRequests);
        definePanel('gassign', [GUIDE], guideAssignments);
        definePanel('dash', [ADMIN], adminDashboard);
        definePanel('approvals', [ADMIN], adminApprovals);
        definePanel('users', [ADMIN], adminAllUsers);
        definePanel('plans', [ADMIN], adminPlans);
        definePanel('feedback', [ADMIN], adminFeedbackAnalysis);
        definePanel('insights', [ADMIN], adminMlInsights);
    }

    const NAV_ICONS = {
        overview: 'M3 12l9-9 9 9M5 10v10h5v-6h4v6h5V10',
        book: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
        hotels: 'M3 21h18M5 21V7a2 2 0 012-2h10a2 2 0 012 2v14M9 7h6M9 11h6M9 15h6M10 19h4',
        dine: 'M6 3a3 3 0 00-3 3c0 1.7 1 2.8 3 6 2-3.2 3-4.3 3-6a3 3 0 00-3-3zM18 3h-5v3h2v18h3V3zM4 21h16',
        tours: 'M12 22a10 10 0 100-20 10 10 0 000 20zM16.24 7.76l-2.12 6.36-6.36 2.12 2.12-6.36 6.36-2.12z',
        trip: 'M6 3a3 3 0 00-3 3c0 1.7 1.1 2.9 3 6 1.9-3.1 3-4.3 3-6a3 3 0 00-3-3zM18 21a3 3 0 003-3c0-1.7-1.1-2.9-3-6-1.9 3.1-3 4.3-3 6a3 3 0 003 3zM14 3l-1 4 4 1-4 1 1 4-4-1-1 4-1-4-4 1 1-4-4-1 4-1 1-4 1 4 4-1-1-4 4 1z',
        wallet: 'M21 7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2h14a2 2 0 002-2V7zM3 10h18M16 15h.01',
        ratings: 'M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z',
        pstats: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
        profile: 'M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2M12 11a4 4 0 100-8 4 4 0 000 8z',
        register: 'M12 8v8M8 12h8M22 12a10 10 0 11-20 0 10 10 0 0120 0z',
        fleet: 'M1 3h15v13H1zM16 8h4l3 3v5h-7V8zM5.5 21a2 2 0 100-4 2 2 0 000 4zM18.5 21a2 2 0 100-4 2 2 0 000 4z',
        spotform: 'M21 10c0 7-9 13-9 13S3 17 3 10a9 9 0 1118 0zM12 13a3 3 0 100-6 3 3 0 000 6z',
        cat: 'M20.59 13.41L11 3H4v7l10.59 10.59a2 2 0 002.82 0l3.18-3.18a2 2 0 000-2.82zM7 7h.01',
        tourform: 'M3 11l18-7-7 18-2.5-7.5L3 11z',
        hotel: 'M3 21h18M5 21V7a2 2 0 012-2h10a2 2 0 012 2v14M9 7h6M9 11h6M9 15h6M10 19h4',
        hinv: 'M21 8l-9-5-9 5v8l9 5 9-5V8zM3 8l9 5 9-5M12 13v8',
        hbook: 'M8 2v4M16 2v4M3 6h18v16H3V6zM3 10h18',
        rest: 'M6 3a3 3 0 00-3 3c0 1.7 1 2.8 3 6 2-3.2 3-4.3 3-6a3 3 0 00-3-3zM18 3h-5v3h2v18h3V3z',
        restform: 'M12 22a10 10 0 100-20 10 10 0 000 20zM12 8v8M8 12h8',
        rfood: 'M4 21h16M5 18h14M6 14h12a6 6 0 00-12 0zM7 6l1 2M9 6l-1 2M15 6l1 2M17 6l-1 2',
        gprofile: 'M4 4h16a2 2 0 012 2v12a2 2 0 01-2 2H4a2 2 0 01-2-2V6a2 2 0 012-2zM8 8a2 2 0 11-4 0 2 2 0 014 0zm-4 9v-1a2 2 0 012-2h0a2 2 0 012 2v1M16 8h2M16 12h2',
        gpricing: 'M20.59 13.41L11 3H4v7l10.59 10.59a2 2 0 002.82 0l3.18-3.18a2 2 0 000-2.82zM7 7h.01',
        gavail: 'M8 2v4M16 2v4M3 6h18v16H3V6zM3 10h18M9 16l2 2 4-4',
        greq: 'M22 12h-6l-2 3h-4l-2-3H2v9h20v-9zM4 3h16l2 12H2L4 3z',
        gassign: 'M9 11l3 3L22 4M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11',
        dash: 'M3 3h8v8H3V3zM13 3h8v5h-8V3zM13 10h8v11h-8V10zM3 13h8v8H3v-8z',
        approvals: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 012-2h2a2 2 0 012 2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 15l2 2 5-5',
        users: 'M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M8 11a4 4 0 100-8 4 4 0 000 8zM23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75',
        insights: 'M4 19h16M7 17V9M12 17V4M17 17v-6M3 21h18',
        'url:/passengers.html': 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z',
    };
    const ICON_SVG = (d) => `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
    const navIcon = (id) => NAV_ICONS[id] ? ICON_SVG(NAV_ICONS[id]) : '';

    function renderNav() {
        const nav = $('portalNav');
        nav.innerHTML = navFor(user.role).map(sec => {
            const items = sec.items.map(([label, id]) => {
                if (typeof id === 'string' && id.startsWith('url:')) {
                    const href = id.slice(4);
                    return `<a href="${esc(href)}">${navIcon(id)}<span>${esc(label)}</span></a>`;
                }
                return `<a href="#" data-panel="${id}">${navIcon(id)}<span>${esc(label)}</span></a>`;
            }).join('');
            const head = sec.group ? `<div class="portal-nav-group">${esc(sec.group)}</div>` : '';
            return head + items;
        }).join('') +
            '<a href="#" class="portal-nav-logout" data-logout="1">Sign out</a>';
        nav.querySelectorAll('a[data-panel]').forEach(a => a.addEventListener('click', e => {
            e.preventDefault();
            showPanel(a.dataset.panel);
        }));
        const lo = nav.querySelector('[data-logout]');
        if (lo) lo.addEventListener('click', e => { e.preventDefault(); window.TM.logout(); });
    }

    function openMobileNav() {
        const sb = $('portalSidebar'), sc = $('portalScrim'), mb = $('portalMenuBtn');
        if (sb) sb.classList.add('open');
        if (sc) sc.classList.add('open');
        if (mb) mb.setAttribute('aria-expanded', 'true');
    }
    function closeMobileNav() {
        const sb = $('portalSidebar'), sc = $('portalScrim'), mb = $('portalMenuBtn');
        if (sb) sb.classList.remove('open');
        if (sc) sc.classList.remove('open');
        if (mb) mb.setAttribute('aria-expanded', 'false');
    }
    function setupDrawer() {
        const mb = $('portalMenuBtn'), cb = $('portalCloseBtn'), sc = $('portalScrim');
        if (mb) mb.addEventListener('click', openMobileNav);
        if (cb) cb.addEventListener('click', closeMobileNav);
        if (sc) sc.addEventListener('click', closeMobileNav);
        window.addEventListener('keydown', e => { if (e.key === 'Escape') closeMobileNav(); });
        window.addEventListener('hashchange', handleHash);
        window.TM.openMobileNav = openMobileNav;
        window.TM.closeMobileNav = closeMobileNav;
    }

    /* Page title shown in the top bar. */
    const PANEL_TITLES = {
        overview: 'Dashboard', book: 'My Bookings',
        pstats: 'My Statistics', wallet: 'Wallet',
        myprofile: 'Profile', plantrip: 'Plan My Trip', pfeedback: 'Feedback',
        profile: 'Company Profile', register: 'Manage Transport', fleet: 'Upcoming Passengers',
        spotform: 'Add Tourist Spot', cat: 'Guide Locations', tourform: 'Tours & Experiences',
        hotel: 'Hotel Profile', hinv: 'Room Inventory', hbook: 'Hotel Bookings',
        rest: 'My Restaurants', restform: 'Restaurant Profile', rfood: 'Food Items', rbook: 'Orders',
        gprofile: 'Guide Profile', gpricing: 'Pricing', gavail: 'Availability',
        greq: 'Tour Requests', gassign: 'Assignments',
        dash: 'Admin Dashboard', approvals: 'Approvals', users: 'All Users',
        plans: 'Current Plans of Users',
        feedback: 'Feedback Analysis',
        insights: 'What TripMind Learned',
    };
    function panelTitle(id) {
        return PANEL_TITLES[id] || String(id || '').replace(/[_-]/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    }
    function setPageTitle(t) {
        const el = $('portalTitle');
        if (el) el.textContent = t || 'Portal';
    }
    function clearNavActive() {
        document.querySelectorAll('#portalNav a[data-panel]').forEach(a => a.classList.remove('active'));
    }
    function clearHash() {
        if (location.hash) history.replaceState(null, '', location.pathname + location.search);
    }
    function handleHash() {
        const m = (location.hash || '').match(/^#user\/(.+)$/);
        if (!m) return;
        currentPanel = 'userDetail';
        clearNavActive();
        closeMobileNav();
        setPageTitle('User Details');
        $('portalContent').innerHTML = loadingState();
        run(() => renderUserDetail(decodeURIComponent(m[1])));
    }

    function loadingState() {
        return '<div class="state-msg"><div class="spinner"></div><div class="state-title">Loading\u2026</div></div>';
    }
    function emptyState(title, sub) {
        return `<div class="state-msg"><div class="state-title">${esc(title)}</div>${sub ? `<div>${esc(sub)}</div>` : ''}</div>`;
    }
    function errorState(msg, retry) {
        return `<div class="state-msg"><div class="state-title">Unable to load</div><div>${esc(msg || 'Something went wrong. Please try again.')}</div>` +
            (retry ? `<div class="mt-2"><button class="btn btn-outline btn-sm" onclick="(${retry})()">Try again</button></div>` : '') + '</div>';
    }

    function showPanel(id) {
        clearHash();
        currentPanel = id;
        document.querySelectorAll('#portalNav a[data-panel]').forEach(a =>
            a.classList.toggle('active', a.dataset.panel === id));
        closeMobileNav();
        setPageTitle(panelTitle(id));
        const panel = PANELS.find(p => p.id === id);
        $('portalContent').innerHTML = loadingState();
        run(() => panel.render());
    }

    function card(title, bodyHtml, actions) {
        return `<div class="card mb-4"><div class="card-header"><div class="card-title">${esc(title)}</div>` +
            (actions ? `<div>${actions}</div>` : '') +
            `</div><div class="card-content">${bodyHtml}</div></div>`;
    }

    const field = (label, id, html) => `<div class="form-group"><label class="form-label">${esc(label)}</label>${html}</div>`;
    const input = (id, opt) => `<input id="${id}" class="form-input" ${opt || ''}>`;
    const num = (id, opt) => `<input id="${id}" type="number" class="form-input" ${opt || ''}>`;
    const select = (val, opts) => `<select class="form-select">${opts.map(o => `<option ${o.v === val ? 'selected' : ''} value="${esc(o.v)}">${esc(o.l)}</option>`).join('')}</select>`;

    /* Shared overlay dialog (consistent modals for confirmations & prompts) */
    function dialog(html) {
        const d = document.createElement('div');
        d.className = 'modal-backdrop';
        d.innerHTML = `<div class="modal-box">${html}</div>`;
        document.body.appendChild(d);
        const close = () => d.remove();
        d.addEventListener('click', e => { if (e.target === d) close(); });
        d.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', close));
        d.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
        return { el: d, close, get: (sel) => d.querySelector(sel) };
    }
    function confirmDialog(title, message, onOk, okLabel) {
        const m = dialog(`<h3>${esc(title)}</h3><p class="text-muted">${esc(message)}</p>
            <div class="flex end gap">
              <button class="btn btn-outline" data-close>Cancel</button>
              <button class="btn btn-primary" id="__ok">${esc(okLabel || 'Confirm')}</button>
            </div>`);
        m.get('#__ok').addEventListener('click', () => { m.close(); onOk(); });
    }
    function promptDialog(title, message, onOk, placeholder) {
        const m = dialog(`<h3>${esc(title)}</h3><p class="text-muted">${esc(message)}</p>
            <input id="__in" class="form-input" placeholder="${esc(placeholder || '')}">
            <div class="flex end gap">
              <button class="btn btn-outline" data-close>Cancel</button>
              <button class="btn btn-primary" id="__ok">Submit</button>
            </div>`);
        m.get('#__ok').addEventListener('click', () => { onOk(m.get('#__in').value.trim()); m.close(); });
    }

    /* ---------------- USER ---------------- */

    const tripsStatusPill = (s) => `<span class="pill ${s === 'BOOKED' ? 'good' : s === 'COMPLETED' ? 'ok' : s === 'PLANNED' ? 'info' : 'warn'}">${esc(s)}</span>`;

    const destCover = (destName) => {
        if (!window.TM_DESTINATIONS) return '';
        const name = String(destName || '').trim().toLowerCase();
        const hit = (window.TM_DESTINATIONS.find(d =>
            d.name.toLowerCase() === name ||
            name.includes(d.name.toLowerCase()) ||
            d.name.toLowerCase().includes(name)));
        return (hit && hit.img) || '';
    };

    const daysBetween = (a, b) => {
        if (!a || !b) return 1;
        const d = Math.round((new Date(b) - new Date(a)) / 86400000);
        return Number.isFinite(d) && d >= 0 ? d + 1 : 1;
    };

    const tripMeta = (x) => {
        const d = daysBetween(x.startDate, x.endDate);
        const n = (x.startDate && x.endDate) ? Math.max(0, d - 1) : 1;
        return `${esc((x.startDate || '').slice(0, 10))} \u2192 ${esc((x.endDate || '').slice(0, 10))} \u00b7 ${d} day${d > 1 ? 's' : ''} / ${n} night${n === 1 ? '' : 's'} \u00b7 ${x.travelers} traveler${x.travelers > 1 ? 's' : ''}`;
    };

    /* One cinematic card per complete trip, shared by the dashboard and My Bookings. */
    function tripCinCard(x) {
        const cover = destCover(x.destination);
        const isTicketable = x.status === 'BOOKED' || x.status === 'COMPLETED';
        const unpaid = x.paymentStatus === 'PENDING' || x.paymentStatus === 'FAILED';
        return `
        <article class="cin-trip" data-reveal>
            <div class="cin-cover ${cover ? '' : 'cin-cover-fb'}">
                ${cover ? `<img src="${cover}" alt="${esc(x.destination)}" loading="lazy" decoding="async" onerror="this.closest('.cin-cover').classList.add('cin-cover-fb')">` : ''}
                <span class="cin-cover-shade"></span>
                <div class="cin-route-cap">
                    <span class="cin-orig">${esc(x.origin)}</span><i></i><span class="cin-dest">${esc(x.destination)}</span>
                </div>
            </div>
            <div class="cin-body">
                <div class="cin-meta">${tripMeta(x)}</div>
                <div class="cin-pills">
                    ${tripsStatusPill(x.status)}<span class="pill ${unpaid ? 'warn' : 'good'}">${unpaid ? 'Payment pending' : 'Paid'}</span>
                    ${x.delay && x.delay.status === 'ACTIVE' ? `<span class="pill warn">Delay ${esc(String(x.delay.minutes))} min</span>` : ''}
                </div>
                <div class="cin-actions">
                    <button class="btn btn-primary btn-sm" onclick="TM.tripDetail('${x._id}')">View details</button>
                    ${isTicketable ? `<button class="btn btn-outline btn-sm" onclick="TM.tripTicket('${x._id}', this)">Download PDF</button>` : ''}
                    ${unpaid ? `<button class="btn btn-outline btn-sm" onclick="TM.tripPay('${x._id}', this)">Pay from wallet</button>` : ''}
                    <a class="btn btn-outline btn-sm" href="/pages/trip.html?id=${x._id}">Open trip</a>
                    ${isTicketable ? `<button class="btn btn-outline btn-sm" onclick="TM.reviewTrip('${x._id}', '${esc(x.origin)}', '${esc(x.destination)}')">Rate</button>` : ''}
                </div>
                ${(x.bookingErrors || []).length ? `<p class="cin-note">Some services could not be booked: ${esc(x.bookingErrors.join('; '))}</p>` : ''}
            </div>
        </article>`;
    }

    function tripPlannedCard(x) {
        return `
        <article class="cin-trip cin-trip-planned" data-reveal>
            <div class="cin-body">
                <div class="cin-route-cap">
                    <span class="cin-orig">${esc(x.origin)}</span><i></i><span class="cin-dest">${esc(x.destination)}</span>
                </div>
                <div class="cin-meta">${tripMeta(x)}</div>
                <div class="cin-pills">${tripsStatusPill(x.status)}${styleLabel(x.travelStyle) ? `<span class="pill info">${esc(styleLabel(x.travelStyle))}</span>` : ''}</div>
                <div class="cin-actions">
                    <a class="btn btn-primary btn-sm" href="/pages/trip.html?id=${x._id}">Review &amp; Book</a>
                    <button class="btn btn-outline btn-sm" onclick="TM.tripDetail('${x._id}')">Preview</button>
                </div>
            </div>
        </article>`;
    }

    const bookingDetailText = (b) => {
        const dt = b.details || {};
        const parts = [];
        if (dt.checkin) parts.push('In ' + esc(String(dt.checkin).slice(0, 10)));
        if (dt.checkout) parts.push('Out ' + esc(String(dt.checkout).slice(0, 10)));
        if (dt.startTime) parts.push(esc(dt.startTime) + (dt.endTime ? '\u2013' + esc(dt.endTime) : ''));
        if (dt.distanceKm) parts.push(esc(dt.distanceKm) + ' km');
        if (dt.seatType) parts.push('Seat ' + esc(dt.seatType));
        if (dt.location) parts.push(esc(dt.location));
        return parts.length ? parts.join(' \u00b7 ') : '\u2014';
    };

    window.TM.tripTicket = async (id, btn) => run(async () => {
        btn.disabled = true;
        try { await api.downloadTripTicket(id); toast('Trip ticket downloaded.'); }
        finally { btn.disabled = false; }
    });

    window.TM.tripPay = async (id, btn) => run(async () => {
        btn.disabled = true;
        try {
            const res = await api.tripPay(id);
            toast(res.message || 'Payment complete.');
            if (currentPanel === 'overview') await userOverview();
            else await userMyBookings();
        } finally { btn.disabled = false; }
    });

    window.TM.tripDetail = async (id) => run(async () => {
        const trip = await api.getTrip(id);
        const d = trip.trip || {};
        const its = (d.bookings || []).filter(b => b.status !== 'CANCELLED');
        const unpaid = its.filter(b => b.paymentStatus === 'PENDING' || b.paymentStatus === 'FAILED');
        const totalPaid = its.filter(b => b.paymentStatus === 'WALLET' || b.paymentStatus === 'COMPLETED')
            .reduce((s, b) => s + (+b.total || 0), 0);
        const bookRows = its.map(b => `<tr>
            <td>${esc((b.date || '').slice(0, 10) || '\u2014')}</td>
            <td><span class="pill info">${esc(b.type)}</span> ${esc(b.itemTitle || b.foodName || (b.details && b.details.location) || '\u2014')}</td>
            <td>${bookingDetailText(b)}</td>
            <td>${esc(b.provider || '\u2014')}</td>
            <td>${money(b.total)}</td>
            <td><span class="pill ${b.status === 'CONFIRMED' ? 'good' : b.status === 'CANCELLED' || b.status === 'REJECTED' ? 'bad' : 'info'}">${esc(b.status)}</span></td>
            <td><span class="pill ${b.paymentStatus === 'WALLET' || b.paymentStatus === 'COMPLETED' || b.paymentStatus === 'PAID' ? 'good' : b.paymentStatus === 'FAILED' ? 'bad' : 'warn'}">${esc(b.paymentStatus)}</span></td>
        </tr>`).join('')
            || '<tr><td colspan="7" class="text-muted">No active bookings on this trip.</td></tr>';
        const token = await api.tripToken(id).catch(() => null);
        const m = dialog(`
            <div class="cin-modal-head">
                <div class="cin-modal-route">${esc(d.origin)} <i></i> ${esc(d.destination)}</div>
                <div class="cin-modal-meta">${esc(d.reference)} \u00b7 ${esc((d.startDate || '').slice(0, 10))} \u2192 ${esc((d.endDate || '').slice(0, 10))} \u00b7 ${d.travelers} traveler${d.travelers > 1 ? 's' : ''}</div>
                <div class="cin-pills">
                    ${tripsStatusPill(d.status)}<span class="pill ${unpaid.length ? 'warn' : 'good'}">${unpaid.length ? 'Payment pending' : 'Paid'}</span>
                    ${d.delay && d.delay.status === 'ACTIVE' ? `<span class="pill warn">Delay ${esc(String(d.delay.minutes))} min</span>` : ''}
                </div>
            </div>
            <div class="table-scroll"><table class="row-table cin-trip-table" style="width:100%">
                <tr><th>Date</th><th>Service</th><th>Details</th><th>Provider</th><th>Amount</th><th>Status</th><th>Payment</th></tr>
                ${bookRows}</table></div>
            <p class="cin-sub" style="margin-top:.7rem;">Paid via wallet: <strong>${money(totalPaid)}</strong>${unpaid.length ? ` \u00b7 ${unpaid.length} booking(s) still unpaid` : ''}</p>
            <div class="flex end gap" style="margin-top:1rem;">
                ${token ? `<a class="btn btn-outline" target="_blank" href="/pages/verify.html?token=${encodeURIComponent(token.token)}#trip">Verify QR</a>` : ''}
                ${d.status === 'BOOKED' || d.status === 'COMPLETED' ? `<button class="btn btn-outline" onclick="TM.tripTicket('${id}', this)">Download PDF</button>` : ''}
                <button class="btn btn-outline" data-close>Close</button>
                ${unpaid.length ? `<button class="btn btn-primary" id="__paynow">Pay from wallet</button>` : ''}
            </div>`);
        const payNow = m.get('#__paynow');
        if (payNow) payNow.addEventListener('click', () => run(async () => {
            await api.tripPay(id);
            toast('Trip payment completed.');
            m.close();
            if (currentPanel === 'overview') await userOverview();
            else await userMyBookings();
        }));
    });

    async function userOverview() {
        const [bk, tr] = await Promise.all([
            api.getBookings().catch(() => ({ bookings: [] })),
            api.getTrips().catch(() => []),
        ]);
        const trips = tr || [];
        const booked = trips.filter(t => t.status === 'BOOKED' || t.status === 'COMPLETED');
        const planned = trips.filter(t => t.status === 'PLANNED');
        const shown = [...booked, ...planned];
        const rows = (bk.bookings || []).length ? (bk.bookings || []).map(x => `
            <tr>
                <td>${esc(x.reference)}</td><td><span class="pill info">${esc(x.type)}</span></td>
                <td>${money(x.total)}</td><td><span class="pill ${x.status === 'CONFIRMED' ? 'good' : x.status === 'CANCELLED' || x.status === 'REJECTED' ? 'bad' : 'info'}">${esc(x.status)}</span></td>
                <td>${esc(x.date)}</td>
                <td>
                    ${x.status === 'CONFIRMED' ? `<button class="btn btn-outline btn-sm" onclick="TM.ticket('${x._id}', this)">PDF</button>` : ''}
                    <button class="btn btn-outline btn-sm" onclick="TM.cancel('${x._id}', this)" ${x.status !== 'CONFIRMED' ? 'disabled' : ''}>Cancel</button>
                </td>
            </tr>`).join('')
            : '<tr><td colspan="6" class="text-muted">No individual service bookings yet.</td></tr>';
        $('portalContent').innerHTML = `
            <div class="overview-head">
                <section class="cin-hero-dash">
                    <div class="cin-hero-dash-inner">
                        <span class="cin-eyebrow">Welcome back</span>
                        <h1 class="cin-display">Namaste,<br><em>${esc((user.name || 'Traveller').split(' ')[0])}</em></h1>
                        <p class="cin-lede">Plan your perfect journey, book it in seconds, and carry it all on one ticket.</p>
                        <div class="cin-ctas">
                            <button class="btn btn-primary btn-lg" onclick="showPanel('plantrip')">Plan My Trip</button>
                            <button class="btn btn-ghost btn-lg" onclick="showPanel('book')">My Bookings</button>
                        </div>
                    </div>
                </section>
            </div>
            ${shown.length ? `
            <section class="cin-section">
                <div class="cin-head"><span class="cin-eyebrow">MY TRAVELS</span><h2 class="cin-title">One journey,<br>one ticket</h2></div>
                <div class="cin-trip-grid">
                    ${booked.map(tripCinCard).join('')}
                </div>
                ${planned.length ? `
                    <div class="cin-head" style="margin-top:2.5rem;"><span class="cin-eyebrow">PLANNED AHEAD</span><h2 class="cin-title">Ready when you are</h2></div>
                    <div class="cin-trip-grid">${planned.map(tripPlannedCard).join('')}</div>` : ''}
            </section>` : `
            <section class="cin-section">
                <div class="cin-head"><span class="cin-eyebrow">YOUR NEXT JOURNEY</span><h2 class="cin-title">Ready when<br>you are</h2></div>
                <div class="cin-empty">
                    <p>No trips yet. Plan your first journey with TripMind AI and carry it on a single beautiful ticket.</p>
                    <div class="cin-ctas"><a class="btn btn-primary btn-lg" href="/pages/planner.html">Plan My First Trip</a></div>
                </div>
            </section>`}
            <section class="cin-section cin-section-alt">
                <div class="cin-head"><span class="cin-eyebrow">EXPLORE INDIA</span><h2 class="cin-title">Wander<br><em>able India</em></h2></div>
                <div class="dest-grid" id="dashDestGrid"></div>
            </section>
            <section class="cin-section">
                <div class="cin-head"><span class="cin-eyebrow">INDIVIDUAL BOOKINGS</span><h2 class="cin-title">Standalone<br>services</h2></div>
                <div class="table-scroll"><table class="row-table" style="width:100%">
                    <tr><th>Reference</th><th>Type</th><th>Total</th><th>Status</th><th>Date</th><th></th></tr>
                    ${rows}
                </table></div>
                <div id="ub_timeline"></div>
            </section>`;
        if (window.tmRenderDestGrid) window.tmRenderDestGrid('#dashDestGrid', { limit: 4 });
        if (window.tmReveal) window.tmReveal(document.getElementById('portalContent'));
        await renderBookingDetails(bk.bookings || []);
        window.TM.cancel = async (id, btn) => run(async () => {
            await api.cancelBooking(id);
            toast('Booking cancelled.');
            showPanel('overview');
        });
        window.TM.ticket = async (id, btn) => run(async () => {
            btn.disabled = true;
            try { await api.downloadTicket(id); toast('Ticket downloaded.'); }
            finally { btn.disabled = false; }
        });
    }

    async function renderBookingDetails(bookings) {
        const wrap = $('ub_timeline');
        if (!wrap) return;
        wrap.innerHTML = bookings.length ? bookings.map(x => `
            <details class="card mb-4" style="padding:0">
                <summary class="card-tl" style="padding:.7rem 1rem;cursor:pointer;font-weight:600;">
                    <span class="pill info">${esc(x.type)}</span> ${esc(x.reference)}
                    <span class="text-muted">\u00b7 ${money(x.total)} \u00b7 ${esc(x.date)}</span>
                </summary>
                <div class="card-content" style="padding-top:0">
                    <div class="flex" style="gap:1rem;flex-wrap:wrap;">
                        <div style="flex:1;min-width:200px;">
                            <h4>Journey timeline</h4>
                            ${timelineSteps(x)}
                        </div>
                        <div style="flex:1;min-width:200px;max-width:340px;">
                            ${bookingFacts(x)}
                        </div>
                    </div>
                </div>
            </details>`).join('') : '<p class="text-muted">No bookings yet.</p>';
    }

    function timelineSteps(x) {
        const div = (label, note, done) => `
            <div class="flex" style="align-items:flex-start;gap:.6rem;margin-bottom:.5rem;">
                <span style="width:10px;height:10px;border-radius:50%;margin-top:4px;background:${done ? '#2563eb' : '#cbd5e1'};flex:none;"></span>
                <div><b>${esc(label)}</b><br><span class="text-muted" style="font-size:12px;">${esc(note)}</span></div>
            </div>`;
        const steps = [];
        steps.push(div('Booking created', (x.createdAt || '').replace('T', ' ').slice(0, 16), true));
        if (x.paymentStatus === 'WALLET' && x.walletPaid) {
            steps.push(div('Payment (wallet)', money(x.walletPaid) + (x.walletTxnId ? ' \u00b7 ' + x.walletTxnId : ''), x.status !== 'CANCELLED'));
        } else {
            steps.push(div('Payment marked ' + x.paymentStatus, 'Settled at the counter', x.status !== 'CANCELLED'));
        }
        if (x.type === 'GUIDE' && x.status === 'PENDING') steps.push(div('Guide request', 'Awaiting guide confirmation', false));
        if (x.status === 'CANCELLED') steps.push(div('Cancelled', 'Refunded if paid from wallet', false));
        else steps.push(div(x.status === 'COMPLETED' ? 'Completed' : 'Confirmed', 'Ticket is valid for travel on ' + x.date, true));
        return steps.join('');
    }

    function bookingFacts(x) {
        const d = x.details || {};
        const facts = { Reference: x.reference, Type: x.type, Status: x.status,
            'Payment': x.paymentStatus, 'Travelers': x.qty };
        if (x.transportId) facts['Transport'] = x.transportId.slice(0, 13) + '\u2026';
        const rows = Object.entries(facts).map(([k, v]) =>
            `<tr><td class="text-muted">${esc(k)}</td><td>${esc(String(v))}</td></tr>`).join('');
        return `<h4>At a glance</h4><table class="row-table" style="width:100%">${rows}</table>
                <button class="btn btn-outline btn-sm mt-4" onclick="TM.verify('${x._id}', this)">Verify ticket</button>`;
    }

    window.TM.verify = async (id, btn) => run(async () => {
        const res = await api.bookingToken(id);
        window.open('/pages/verify.html?token=' + encodeURIComponent(res.token), '_blank');
    });

    /* ---------------------------------------------------------------------
       Passenger picker
       Shared by every booking dialog. Selecting travellers is optional: if
       nobody is picked the server still records a headcount of the seats
       bought, so an existing booking flow never breaks.
       --------------------------------------------------------------------- */
    let partyCache = null;

    async function loadParty() {
        if (partyCache) return partyCache;
        try { partyCache = await api.passengers(); }
        catch (e) { partyCache = []; }
        return partyCache;
    }

    async function partyPickerMarkup(expected) {
        const people = await loadParty();
        if (!people.length) {
            return `<div class="party-pick">
                <p class="text-muted" style="margin:0;">No saved travellers. <a href="/pages/passengers.html" target="_blank" rel="noopener">Add passenger details</a> so operators can prepare \u2014 it is optional.</p>
            </div>`;
        }
        const rows = people.map(p => `<label class="party-pick__row">
            <input type="checkbox" data-px="${esc(p.id)}" ${p.isDefault ? 'checked' : ''}>
            <span class="party-pick__name">${esc(p.fullName)}</span>
            <span class="party-pick__meta">${esc([
                p.age != null ? 'Age ' + p.age : null,
                p.ageBand || null,
                p.health && p.health.consent && p.health.mobility && p.health.mobility !== 'NONE' ? 'access needs' : null
            ].filter(Boolean).join(' \u00b7 ') || 'Saved traveller')}</span>
        </label>`).join('');
        return `<fieldset class="party-pick" data-party data-expected="${expected || 0}">
            <legend class="party-pick__legend">Who is travelling? <span class="text-muted">optional</span></legend>
            ${rows}
            <p class="party-pick__note" data-party-note>Partners only ever see a headcount and coarse flags \u2014 never a name, age or health note.</p>
        </fieldset>`;
    }

    function partySelected(scope) {
        const box = (scope || document).querySelector('[data-party]');
        if (!box) return [];
        const expected = parseInt(box.dataset.expected || '0', 10);
        const picked = Array.from(box.querySelectorAll('[data-px]:checked')).map(i => i.dataset.px);
        const note = box.querySelector('[data-party-note]');
        if (note) {
            if (expected && picked.length > expected) {
                note.textContent = `You picked ${picked.length} travellers for ${expected} seat${expected > 1 ? 's' : ''}. Reduce the selection or buy more seats.`;
                note.classList.add('is-late');
            } else if (expected && picked.length && picked.length < expected) {
                note.textContent = `${expected - picked.length} seat${expected - picked.length > 1 ? 's' : ''} still unnamed \u2014 that is fine, we will just record the headcount.`;
                note.classList.remove('is-late');
            } else {
                note.textContent = 'Partners only ever see a headcount and coarse flags \u2014 never a name, age or health note.';
                note.classList.remove('is-late');
            }
        }
        if (expected && picked.length > expected) throw new Error('You selected more travellers than seats on this booking.');
        return picked;
    }

    /* ---------------------------------------------------------------------
       Pre-trip checklist
       The list is generated once and stored against the booking, so progress
       survives refreshes, a new device, and an AI regeneration. Nothing from a
       traveller's profile is sent to the model: the booking only carries a
       headcount and coarse flags.
       --------------------------------------------------------------------- */
    const CHECKLIST_CATEGORY = {
        DOCUMENTS: 'Documents', MONEY: 'Money', HEALTH: 'Health', LUGGAGE: 'Luggage',
        CONNECTIVITY: 'Connectivity', LOCAL: 'Local', SAFETY: 'Safety', OTHER: 'Other'
    };

    function checklistDueLabel(item) {
        if (!item.dueDate) return '';
        const days = Math.round(
            (new Date(item.dueDate + 'T00:00:00') - new Date(new Date().toDateString())) / 86400000);
        if (days === 0) return 'today';
        if (days === 1) return 'tomorrow';
        if (days > 1) return `in ${days} days`;
        if (days === -1) return 'yesterday';
        return `${Math.abs(days)} days ago`;
    }

    function checklistItemsMarkup(doc) {
        if (!doc.items || !doc.items.length) {
            return '<p class="text-muted">Nothing on the list yet.</p>';
        }
        return doc.items.map(i => {
            const due = checklistDueLabel(i);
            const overdue = i.dueDate && !i.done && due.indexOf('ago') > -1;
            return `<li class="ck-item ${i.done ? 'is-done' : ''}">
                <label class="ck-item__label">
                    <input type="checkbox" data-ck="${esc(i.id)}" ${i.done ? 'checked' : ''}>
                    <span class="ck-item__body">
                        <span class="ck-item__text">${esc(i.text)}</span>
                        <span class="ck-item__meta">
                            <span class="pill">${esc(CHECKLIST_CATEGORY[i.category] || 'Other')}</span>
                            ${due ? `<span class="ck-item__due ${overdue ? 'is-late' : ''}">${esc(due)}</span>` : ''}
                        </span>
                    </span>
                </label>
                <button class="ck-item__del" type="button" data-ck-del="${esc(i.id)}" title="Remove">&times;</button>
            </li>`;
        }).join('');
    }

    async function openChecklist(bookingId) {
        const m = dialog(`<h3>Pre-trip preparation</h3>
            <p class="text-muted" id="ckSub">Reading your booking\u2026</p>
            <ul class="ck-list" id="ckList"></ul>
            <div class="ck-add">
                <input id="ckNew" class="form-input" placeholder="Add your own item\u2026">
                <button class="btn btn-outline btn-sm" id="ckAddBtn">Add</button>
            </div>
            <div class="flex between mt-4" style="align-items:center;">
                <span class="ck-progress" id="ckProgress"></span>
                <span class="flex gap">
                    <button class="btn btn-outline" id="ckRegen" data-close>Close</button>
                    <button class="btn btn-primary" id="ckGen">Generate checklist</button>
                    <button class="btn btn-outline" id="ckAgain" hidden>Refresh suggestions</button>
                </span>
            </div>`);
        m.get('#ckGen').addEventListener('click', () => loadChecklist(m, bookingId, true));
        m.get('#ckAgain').addEventListener('click', () => run(async () => {
            if (!confirm('Ask the planner for a fresh set of suggestions? Your ticks are kept.')) return;
            m.get('#ckAgain').disabled = true;
            try { paintChecklist(m, await api.regenerateChecklist(bookingId)); toast('Checklist refreshed.'); }
            finally { m.get('#ckAgain').disabled = false; }
        }));
        m.get('#ckAddBtn').addEventListener('click', () => run(async () => {
            const input = m.get('#ckNew');
            const text = input.value.trim();
            if (!text) return;
            input.value = '';
            paintChecklist(m, await api.addChecklistItem(bookingId, text));
        }));
        m.get('#ckNew').addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); m.get('#ckAddBtn').click(); }
        });
        m.get('#ckList').addEventListener('change', e => {
            const box = e.target.closest('[data-ck]');
            if (!box) return;
            run(async () => {
                paintChecklist(m, await api.setChecklistItem(bookingId, box.dataset.ck, box.checked));
            });
        });
        m.get('#ckList').addEventListener('click', e => {
            const del = e.target.closest('[data-ck-del]');
            if (!del) return;
            run(async () => {
                paintChecklist(m, await api.deleteChecklistItem(bookingId, del.dataset.ckDel));
            });
        });
        loadChecklist(m, bookingId, false);
    }

    function paintChecklist(m, payload) {
        const doc = payload.checklist || {};
        const progress = payload.progress || {};
        m.get('#ckSub').textContent = doc.generatedAt
            ? (doc.source === 'AI' ? 'Generated by the TripMind planner.' : 'Generated from the TripMind template.')
            : 'Nothing generated for this booking yet.';
        m.get('#ckList').innerHTML = checklistItemsMarkup(doc);
        m.get('#ckProgress').textContent = (progress.done || 0) + ' of ' + (progress.total || 0) + ' done';
        const has = !!(doc.items && doc.items.length);
        m.get('#ckGen').hidden = has;
        m.get('#ckAgain').hidden = !has;
    }

    async function loadChecklist(m, bookingId, generate) {
        try {
            const existing = await api.checklist(bookingId).catch(() => null);
            if (existing && existing.checklist && existing.checklist.items
                && existing.checklist.items.length) {
                paintChecklist(m, existing);
                return;
            }
            if (!generate) { paintChecklist(m, { checklist: {}, progress: {} }); return; }
            m.get('#ckGen').disabled = true;
            m.get('#ckSub').textContent = 'Building your list\u2026 this takes a few seconds.';
            paintChecklist(m, await api.generateChecklist(bookingId));
        } catch (e) {
            m.get('#ckSub').textContent = e.message || 'Could not load the checklist.';
        } finally {
            m.get('#ckGen').disabled = false;
        }
    }

    /* Consolidated My Bookings: one card per booked trip (with ONE downloadable
       PDF ticket per trip) plus the individual service bookings underneath. */
    async function userMyBookings() {
        const [bk, trips] = await Promise.all([
            api.getBookings().catch(() => ({ bookings: [] })),
            api.getTrips().catch(() => []),
        ]);
        const list = bk.bookings || [];
        const booked = (trips || []).filter(t => t.status === 'BOOKED' || t.status === 'COMPLETED');
        const planned = (trips || []).filter(t => t.status === 'PLANNED');
        const rows = list.length ? list.map(x => `
            <tr>
                <td>${esc(x.reference)}</td>
                <td><span class="pill info">${esc(x.type)}</span></td>
                <td>${esc(x.date)}</td>
                <td>${money(x.total)}</td>
                <td><span class="pill ${x.status === 'CONFIRMED' ? 'good' : x.status === 'CANCELLED' || x.status === 'REJECTED' ? 'bad' : 'info'}">${esc(x.status)}</span></td>
                <td>
                    ${x.status === 'CONFIRMED' ? `<button class="btn btn-outline btn-sm" onclick="TM.ticket('${x._id}', this)">PDF</button>` : ''}
                    ${x.status === 'CONFIRMED' ? `<button class="btn btn-outline btn-sm" onclick="TM.checklist('${x._id}')">Prep</button>` : ''}
                    <button class="btn btn-outline btn-sm" onclick="TM.verify('${x._id}', this)" ${x.status !== 'CONFIRMED' ? 'disabled' : ''}>Verify</button>
                    <button class="btn btn-outline btn-sm" onclick="TM.cancel('${x._id}', this)" ${x.status !== 'CONFIRMED' ? 'disabled' : ''}>Cancel</button>
                </td>
            </tr>`).join('')
            : '<tr><td colspan="6" class="text-muted">No individual service bookings yet.</td></tr>';
        $('portalContent').innerHTML = `
            <div class="bookings-head">
                <span class="cin-eyebrow">MY BOOKINGS</span>
                <h1 class="cin-title">Every booked trip arrives<br>as <em>one ticket</em></h1>
                <p class="cin-sub">A single consolidated PDF with one QR code \u2014 transport, stays, food and experiences together.</p>
            </div>
            ${booked.length ? `
                <section class="cin-section">
                    <div class="cin-head"><span class="cin-eyebrow">BOOKED TRIPS</span><h2 class="cin-title">Your journeys</h2></div>
                    <div class="cin-trip-grid">${booked.map(tripCinCard).join('')}</div>
                </section>` : `
                <section class="cin-section">
                    <div class="cin-empty"><p>No booked trips yet \u2014 plan a trip with TripMind AI and every service will land on one ticket.</p></div>
                </section>`}
            ${planned.length ? `
                <section class="cin-section">
                    <div class="cin-head"><span class="cin-eyebrow">PLANNED AHEAD</span><h2 class="cin-title">Almost there</h2></div>
                    <div class="cin-trip-grid">${planned.map(tripPlannedCard).join('')}</div>
                </section>` : ''}
            <section class="cin-section cin-section-alt">
                <div class="cin-head"><span class="cin-eyebrow">INDIVIDUAL BOOKINGS</span><h2 class="cin-title">Standalone<br>services</h2></div>
                <p class="cin-sub">Transport, stays and experiences booked outside an AI trip.</p>
                <div class="table-scroll"><table class="row-table" style="width:100%">
                    <tr><th>Reference</th><th>Type</th><th>Date</th><th>Total</th><th>Status</th><th></th></tr>
                    ${rows}
                </table></div>
                <div id="ub_timeline"></div>
            </section>`;
        if (window.tmReveal) window.tmReveal(document.getElementById('portalContent'));
        renderBookingDetails(list);
        window.TM.cancel = async (id, btn) => run(async () => {
            await api.cancelBooking(id);
            toast('Booking cancelled.');
            showPanel('book');
        });
        window.TM.ticket = async (id, btn) => run(async () => {
            btn.disabled = true;
            try { await api.downloadTicket(id); toast('Ticket downloaded.'); }
            finally { btn.disabled = false; }
        });
        /* AI-assisted pre-trip checklist, stored per booking. The traveller keeps
           the tick marks if the AI rewrites the list later. */
        window.TM.checklist = (id) => openChecklist(id);
        window.TM.reviewTrip = async (id, origin, destination) => {
            const m = dialog(`<h3>Review your trip</h3>
                <p class="text-muted">${esc(origin)} \u2192 ${esc(destination)}</p>
                ${field('Your rating', 'tr_stars', `<select id="tr_stars" class="form-select">${[1,2,3,4,5].map(s => `<option value="${s}" ${s === 5 ? 'selected' : ''}>${'\u2605'.repeat(s)}${'\u2606'.repeat(5 - s)}</option>`).join('')}</select>`)}
                ${field('Your comment (optional)', 'tr_comment', `<textarea id="tr_comment" class="form-textarea" placeholder="What did you like or dislike?"></textarea>`)}
                <div class="flex end gap">
                    <button class="btn btn-outline" data-close>Cancel</button>
                    <button class="btn btn-primary" id="__ok">Submit Review</button>
                </div>`);
            m.get('#__ok').addEventListener('click', () => run(async () => {
                await api.addTripReview(id, +m.get('#tr_stars').value, m.get('#tr_comment').value);
                toast('Thanks for your feedback!');
                m.close();
            }));
        };
    }

    function userProfilePanel() {
        const p = user.preferences || {};
        $('portalContent').innerHTML = card('My Profile', `
            <div class="form-row">
                ${field('Name', 'mp_name', input('mp_name', 'value="' + esc(user.name || '') + '"'))}
                ${field('Email', 'mp_email', `<input id="mp_email" class="form-input" readonly value="${esc(user.email || '')}">`)}
                ${field('Mobile', 'mp_mobile', `<input id="mp_mobile" class="form-input" readonly value="${esc(user.mobile || '')}">`)}
            </div>
            <div class="form-row">
                ${field('Identification', 'mp_idnum', `<input id="mp_idnum" class="form-input" value="${esc((user.identityType || '') + ' \u00b7 ' + (user.identityNumber || ''))}" readonly>`)}
                ${field('Dietary preference', 'mp_diet', `<select id="mp_diet" class="form-select">
                    <option value="vegetarian" ${p.dietary === 'vegetarian' ? 'selected' : ''}>Vegetarian</option>
                    <option value="non_veg" ${p.dietary === 'non_veg' ? 'selected' : ''}>Non-Vegetarian</option>
                    <option value="vegan" ${p.dietary === 'vegan' ? 'selected' : ''}>Vegan</option></select>`)}
                ${field('Travel style', 'mp_style', `<select id="mp_style" class="form-select">
                    <option value="BUDGET" ${p.travelStyle === 'BUDGET' ? 'selected' : ''}>Budget</option>
                    <option value="BALANCED" ${p.travelStyle === 'BALANCED' ? 'selected' : ''}>Comfort</option>
                    <option value="PREMIUM" ${p.travelStyle === 'PREMIUM' ? 'selected' : ''}>Premium</option></select>`)}
            </div>
            <button class="btn btn-primary" onclick="TM.saveUserProfile()">Save Profile</button>
            <p class="text-muted mt-4">Email and mobile are locked for verification & tickets.</p>`);
        window.TM.saveUserProfile = () => run(async () => {
            await api.updateProfile({
                name: $('mp_name').value.trim(),
                preferences: { dietary: $('mp_diet').value, travelStyle: $('mp_style').value },
            });
            user.name = $('mp_name').value.trim();
            toast('Profile updated.');
            userProfilePanel();
        });
    }

    /* Single \u201cPlan My Trip\u201d flow: every booking type plus the AI planner are
       reachable from one panel. Default tab is Transport. */
    async function userPlanTrip() {
        $('portalContent').innerHTML = `
            <div class="card mb-4">
                <div class="card-content">
                    <div class="flex justify-between" style="align-items:center;">
                        <div>
                            <div class="card-title">Plan your next trip</div>
                            <p class="text-muted">Choose what you want to book \u2014 or let TripMind\u2019s AI design the whole trip for you.</p>
                        </div>
                        <a class="btn btn-primary" href="/pages/planner.html">Plan a Trip</a>
                    </div>
                </div>
            </div>
            <div class="pt-tabs flex" style="gap:.5rem;flex-wrap:wrap;margin-bottom:1rem;">
                <button class="btn btn-primary btn-sm pt-tab" data-tab="transport">Transport</button>
                <button class="btn btn-outline btn-sm pt-tab" data-tab="stays">Stays</button>
                <button class="btn btn-outline btn-sm pt-tab" data-tab="dining">Dining</button>
                <button class="btn btn-outline btn-sm pt-tab" data-tab="experiences">Experiences</button>
                <button class="btn btn-outline btn-sm pt-tab" data-tab="guides">Local Guides</button>
            </div>
            <div id="pt_body"></div>`;
        document.querySelectorAll('.pt-tab').forEach(b => b.addEventListener('click', () => {
            document.querySelectorAll('.pt-tab').forEach(x => x.classList.remove('btn-primary'));
            document.querySelectorAll('.pt-tab').forEach(x => x.classList.add('btn-outline'));
            b.classList.remove('btn-outline');
            b.classList.add('btn-primary');
            renderPtTab(b.dataset.tab);
        }));
        renderPtTab('transport');
    }

    function renderPtTab(tab) {
        const body = $('pt_body');
        if (tab === 'transport') body.innerHTML = ptTransportHtml();
        else if (tab === 'stays') body.innerHTML = ptHotelsHtml();
        else if (tab === 'dining') body.innerHTML = ptDiningHtml();
        else if (tab === 'explorations' || tab === 'experiences') body.innerHTML = ptToursHtml();
        else if (tab === 'guides') body.innerHTML = ptGuidesHtml();
    }

    function ptTransportHtml() {
        return `
            <div class="card mb-4">
                <div class="card-content">
                    <p class="text-muted">Search buses, trains, flights and cabs. Bookings appear instantly in My Bookings with a PDF ticket.</p>
                    <div class="form-row">
                        ${field('From', 'pt_from', input('pt_from', 'placeholder="KPR, Coimbatore"'))}
                        ${field('To', 'pt_to', input('pt_to', 'placeholder="Chennai"'))}
                        ${field('Type', 'pt_type', `<select id="pt_type" class="form-select">
                            ${['', 'BUS', 'TRAIN', 'FLIGHT', 'CAB', 'AUTO'].map(t => `<option value="${t}">${t === '' ? 'Any' : t}</option>`).join('')}</select>`)}
                        ${field('Travel date', 'pt_date', input('pt_date', 'type="date"'))}
                    </div>
                    <button class="btn btn-primary" onclick="TM.ptSearch()">Search Transports</button>
                    <div id="pt_results" class="mt-4"></div>
                </div>
            </div>`;
    }

    function ptHotelsHtml() {
        return `
            <div class="card mb-4">
                <div class="card-content">
                    <p class="text-muted">Find stays by city and category, then book rooms.</p>
                    <div class="form-row">
                        ${field('City', 'pt_hcity', input('pt_hcity', 'value="Chennai"'))}
                        ${field('Category', 'pt_hcat', `<select id="pt_hcat" class="form-select">
                            ${['', 'Budget', 'Mid-Range', 'Luxury', 'Boutique', 'Resort'].map(c => `<option value="${c}">${c || 'Any'}</option>`).join('')}</select>`)}
                        ${field('Guests', 'pt_hguests', num('pt_hguests', 'value="2"'))}
                    </div>
                    <button class="btn btn-primary" onclick="TM.ptHotels()">Search Hotels</button>
                    <div id="pt_hresults" class="mt-4"></div>
                </div>
            </div>`;
    }

    function ptDiningHtml() {
        return `
            <div class="card mb-4">
                <div class="card-content">
                    <p class="text-muted">Browse verified restaurants and their menus.</p>
                    <div class="form-row">
                        ${field('City', 'pt_dcity', input('pt_dcity', 'value="Chennai"'))}
                    </div>
                    <button class="btn btn-primary" onclick="TM.ptDine()">Browse Restaurants</button>
                    <div id="pt_dresults" class="mt-4"></div>
                </div>
            </div>`;
    }

    function ptToursHtml() {
        return `
            <div class="card mb-4">
                <div class="card-content">
                    <p class="text-muted">Book tourist spot entries and guided tours & experiences.</p>
                    <div class="form-row">
                        ${field('City', 'pt_tcity', input('pt_tcity', 'value="Chennai"'))}
                    </div>
                    <button class="btn btn-primary" onclick="TM.ptTours()">Browse Experiences</button>
                    <div id="pt_tresults" class="mt-4"></div>
                </div>
            </div>`;
    }

    function ptGuidesHtml() {
        return `
            <div class="card mb-4">
                <div class="card-content">
                    <p class="text-muted">Request a local guide for a date and time slot. The guide confirms before the request is locked.</p>
                    <div class="form-row">
                        ${field('Location', 'pt_gloc', input('pt_gloc', 'placeholder="e.g. Marina Beach"'))}
                        ${field('Guiding date', 'pt_gdate', input('pt_gdate', 'type="date"'))}
                    </div>
                    <button class="btn btn-primary" onclick="TM.ptGuides()">Find Guides</button>
                    <div id="pt_gresults" class="mt-4"></div>
                </div>
            </div>`;
    }

    window.TM.ptSearch = () => run(async () => {
        const res = await api.transportSearch({
            origin: $('pt_from').value.trim(), destination: $('pt_to').value.trim(),
            type: $('pt_type').value,
        });
        const t = res.transports || [];
        // The server labels results that only reach the requested destination
        // without boarding at the requested origin. Showing them silently, as
        // this did before, implies the traveller can catch them, which is not
        // true - so the caveat goes above the table, where it is read before
        // any row rather than after clicking Book.
        const partial = res.partialMatch;
        const caveat = partial
            ? `<p class="text-muted" style="margin:0 0 .6rem;"><strong>Partial match.</strong>
                ${esc(res.note || 'These reach your destination but do not depart from your origin.')}
                You will need your own way to the departure point.</p>`
            : '';
        const rowCaveat = x => x.matchQuality === 'destination-only'
            ? ' <span class="pill warn" title="Does not depart from your origin">Not from your origin</span>'
            : '';
        $('pt_results').innerHTML = t.length ? `${caveat}<table class="row-table" style="width:100%">
            <tr><th>Type</th><th>Service</th><th>Route</th><th>When</th><th>Price</th><th></th></tr>` +
            t.map(x => `<tr><td><span class="pill info">${esc(x.type)}</span></td>
                <td>${esc(x.serviceName)}${rowCaveat(x)}</td><td>${esc(x.summary)}</td>
                <td>${esc(x.details?.boardingTime || x.details?.departureTime || x.details?.baseLocation || '-')}</td>
                <td>${money(x.details ? fareOf(x.details) : 0)}</td>
                <td><button class="btn btn-primary btn-sm" onclick="TM.ptBookTransport('${x.transportId}', '${x.type}')">Book</button></td></tr>`).join('') + '</table>'
            : '<p class="text-muted">No transports found for this corridor.</p>';
    });
    window.TM.ptBookTransport = async (tid, type) => {
        const date = $('pt_date').value || new Date().toISOString().slice(0, 10);
        const seatType = window.prompt('Seat / class type (e.g. SLEEPER, SL, Economy):', type === 'BUS' ? 'SLEEPER' : type === 'TRAIN' ? 'SL' : type === 'FLIGHT' ? 'Economy' : 'Standard') || 'Standard';
        const qty = parseInt(window.prompt('Number of seats/units:', '2') || '2', 10);
        if (!(qty > 0)) { toast('Enter how many seats you need.'); return; }
        const m = dialog(`<h3>Book this ${esc(String(type).toLowerCase())} service</h3>
            <p class="text-muted">${esc(qty)} seat${qty > 1 ? 's' : ''} \u00b7 ${esc(seatType)} \u00b7 ${esc(date)}</p>
            <div id="pt_party"></div>
            <div class="flex end gap">
                <button class="btn btn-outline" data-close>Cancel</button>
                <button class="btn btn-primary" id="__ok">Confirm Booking</button>
            </div>`);
        m.get('#pt_party').innerHTML = await partyPickerMarkup(qty);
        m.get('#__ok').addEventListener('click', () => run(async () => {
            const details = {};
            if (type === 'CAB' || type === 'AUTO') {
                const km = parseFloat(window.prompt('Trip distance (km) for the fare quote:', '10'));
                if (!(km > 0)) { toast('Distance in km is required for cab/auto fares.'); return; }
                details.distanceKm = km;
            }
            let passengerIds;
            try { passengerIds = partySelected(m.el); }
            catch (e) { toast(e.message); return; }
            await api.createBooking({
                type: 'TRANSPORT', transportId: tid, qty, seatType, date, details,
                passengerIds,
            });
            m.close();
            toast('Transport booked.');
            window.TM.ptSearch();
        }));
    };
    window.TM.ptHotels = () => run(async () => {
        const res = await api.searchHotels({
            city: $('pt_hcity').value.trim() || undefined,
            category: $('pt_hcat').value || undefined,
            guests: +$('pt_hguests').value || undefined,
        });
        const hs = res.hotels || [];
        $('pt_hresults').innerHTML = hs.length ? hs.map(h => `
            <div class="card mb-4" style="background:var(--slate-50);">
                <div class="card-content">
                    <div class="flex justify-between">
                        <div><b>${esc(h.name)}</b>
                            <span class="pill info">${esc(h.category)}</span>
                            <span class="text-muted">${'\u2605'.repeat(Math.max(1, h.starRating || 1))}</span><br>
                            <span class="text-muted">${esc(h.city)}, ${esc(h.address)}</span>
                            <span class="text-muted"> \u00b7 ${h.availableRooms || 0} rooms available</span>
                        </div>
                        <button class="btn btn-outline btn-sm" onclick="TM.ptHotelDetail('${h.id}')">View rooms</button>
                    </div>
                </div>
            </div>`).join('')
            : '<p class="text-muted">No hotels found with availability.</p>';
    });
    window.TM.ptHotelDetail = async (id) => run(async () => {
        const h = await api.getHotel(id);
        const rooms = (h.hotel.roomTypes || []).map(r => `
            <div class="room-type-row">
                <div>
                    <b>${esc(r.name)}</b>
                    ${r.ac ? '<span class="pill info">AC</span>' : '<span class="pill warn">Non-AC</span>'}
                    <span class="text-muted">${esc(r.bedType)} \u00b7 up to ${r.maxOccupancy} guests</span>
                </div>
                <div class="text-muted">${r.availableRooms} available of ${r.totalRooms}</div>
                <div><b>${money(r.pricePerNight)}</b>/night</div>
                <button class="btn btn-primary btn-sm" onclick="TM.ptBookHotel('${h.hotel.id}', '${r.id}', '${esc(r.name)}', ${r.pricePerNight})">Book</button>
            </div>`).join('') || '<p class="text-muted">No room types available.</p>';
        $('pt_hresults').innerHTML = card(h.hotel.name, `
            <p>${esc(h.hotel.description || '')}</p>
            <p class="text-muted">${esc(h.hotel.address)} \u00b7 ${esc(h.hotel.city)}<br>
            Check-in ${esc(h.hotel.checkInTime)} \u00b7 Check-out ${esc(h.hotel.checkOutTime)}<br>
            Amenities: ${esc((h.hotel.amenities || []).join(', '))}</p>
            <div class="hr-label">Room types</div>${rooms}`);
    });
    window.TM.ptBookHotel = async (hid, rtid, name, price) => {
        const m = dialog(`<h3>Book \u00b7 ${esc(name)}</h3>
            <div class="form-row">
                ${field('Check-in', 'b_in', input('b_in', 'type="date" value="' + new Date().toISOString().slice(0, 10) + '"'))}
                ${field('Check-out', 'b_out', input('b_out', 'type="date" value="' + new Date(Date.now() + 86400000).toISOString().slice(0, 10) + '"'))}
                ${field('Rooms', 'b_rooms', num('b_rooms', 'value="1" min="1"'))}
                ${field('Guests', 'b_guests', num('b_guests', 'value="2" min="1"'))}
            </div>
            <p class="text-muted">Nightly rate: ${money(price)} per room. Availability is confirmed at booking time.</p>
            <div id="pt_party"></div>
            <div class="flex end gap">
                <button class="btn btn-outline" data-close>Cancel</button>
                <button class="btn btn-primary" id="__ok">Confirm Booking</button>
            </div>`);
        const syncParty = async () => {
            const guests = +m.get('#b_guests').value || 1;
            m.get('#pt_party').innerHTML = await partyPickerMarkup(guests);
        };
        await syncParty();
        m.get('#b_guests').addEventListener('change', syncParty);
        m.get('#__ok').addEventListener('click', () => run(async () => {
            const rooms = +m.get('#b_rooms').value || 1;
            const guests = +m.get('#b_guests').value || 2;
            const nights = Math.max(1, Math.round((new Date(m.get('#b_out').value) - new Date(m.get('#b_in').value)) / 86400000));
            let passengerIds;
            try { passengerIds = partySelected(m.el); }
            catch (e) { toast(e.message); return; }
            await api.createBooking({
                type: 'HOTEL', hotelId: hid, roomTypeId: rtid, qty: rooms,
                date: m.get('#b_in').value,
                details: { checkin: m.get('#b_in').value, checkout: m.get('#b_out').value, nights, guests },
                unitPrice: price * nights,
                passengerIds,
            });
            m.close();
            toast('Hotel booked successfully.');
            window.TM.ptHotels();
        }));
    };
    window.TM.ptDine = () => run(async () => {
        const res = await api.getRestaurants({ city: $('pt_dcity').value.trim() || undefined });
        const rs = res.restaurants || [];
        $('pt_dresults').innerHTML = rs.length ? rs.map(r => `
            <div class="card mb-4" style="background:var(--slate-50);">
                <div class="card-content">
                    <div class="flex justify-between">
                        <div>
                            <b>${esc(r.name)}</b>
                            <span class="pill info">${esc(r.restaurantType || 'Restaurant')}</span><br>
                            <span class="text-muted">${esc(r.address || '')}</span><br>
                            <span class="text-muted">${esc((r.cuisines || []).join(', '))}</span>
                        </div>
                        <button class="btn btn-outline btn-sm" onclick="TM.ptMenu('${r.id}')">Menu</button>
                    </div>
                </div>
            </div>`).join('')
            : '<p class="text-muted">No restaurants found.</p>';
    });
    window.TM.ptMenu = async (id) => run(async () => {
        const r = await api.getRestaurant(id);
        const items = (r.restaurant.menu || []).map(f => `
            <div class="flex justify-between" style="padding:.4rem 0;border-bottom:1px dashed var(--slate-200,#e2e8f0);">
                <div><b>${esc(f.name)}</b> <span class="text-muted">\u00b7 ${esc(f.category || '')}</span>
                    ${f.veg ? '<span class="pill ok">Veg</span>' : '<span class="pill bad">Non-Veg</span>'}</div>
                <div>${money(f.price)}</div>
            </div>`).join('');
        $('pt_dresults').innerHTML = card(r.restaurant.name, `
            <p class="text-muted">${esc(r.restaurant.address || '')}</p>
            <div class="hr-label">Menu</div>
            ${items || '<p class="text-muted">Menu not published yet.</p>'}`);
    });
    window.TM.ptGuides = () => run(async () => {
        const res = await api.browseGuides({ location: $('pt_gloc').value.trim(), date: $('pt_gdate').value });
        const g = res.guides || [];
        $('pt_gresults').innerHTML = g.length ? g.map(x => `
            <div class="card mb-4" style="background:var(--slate-50);">
                <div class="card-content">
                    <div class="flex justify-between">
                        <div><b>${esc(x.name)}</b> <span class="text-muted">(${esc((x.profile?.specialty) || 'Guide')})</span></div>
                        <button class="btn btn-primary btn-sm" onclick="TM.ptBookGuide('${x.userId}', '${esc((x.profile?.specialty) || (x.location || ''))}')">Book ${money((x.pricing || {}).pricePerHour)}/hr</button>
                    </div>
                </div>
            </div>`).join('')
            : '<p class="text-muted">No guides available for that location/date.</p>';
    });
    window.TM.ptBookGuide = async (gid, loc) => {
        const m = dialog(`<h3>Request a Guide</h3>
            ${field('Date', 'bg_date', input('bg_date', 'type="date" value="' + new Date().toISOString().slice(0, 10) + '"'))}
            <div class="form-row">
                ${field('From (24h)', 'bg_f', input('bg_f', 'value="09:00"'))}
                ${field('To (24h)', 'bg_t', input('bg_t', 'value="13:00"'))}
            </div>
            ${field('Location', 'bg_loc', input('bg_loc', 'value="' + esc(loc || '') + '"'))}
            ${field('Travellers', 'bg_qty', num('bg_qty', 'value="1" min="1"'))}
            <p class="text-muted">The guide will confirm your request.</p>
            <div id="pt_party"></div>
            <div class="flex end gap">
                <button class="btn btn-outline" data-close>Cancel</button>
                <button class="btn btn-primary" id="__ok">Send Request</button>
            </div>`);
        const syncParty = async () => {
            m.get('#pt_party').innerHTML = await partyPickerMarkup(+m.get('#bg_qty').value || 1);
        };
        await syncParty();
        m.get('#bg_qty').addEventListener('change', syncParty);
        m.get('#__ok').addEventListener('click', () => run(async () => {
            const qty = +m.get('#bg_qty').value || 1;
            let passengerIds;
            try { passengerIds = partySelected(m.el); }
            catch (e) { toast(e.message); return; }
            await api.createBooking({
                type: 'GUIDE', guideId: gid, qty,
                date: m.get('#bg_date').value,
                details: { startTime: m.get('#bg_f').value, endTime: m.get('#bg_t').value, location: m.get('#bg_loc').value.trim() },
                passengerIds,
            });
            m.close();
            toast('Request sent to the guide.');
        }));
    };

    /* Passenger feedback: rate services + review AI trips in one place. */
    async function userFeedbackPanel() {
        const [elig, mine, trips] = await Promise.all([
            api.ratingEligible().catch(() => ({ bookings: [] })),
            api.myRatings().catch(() => ({ ratings: [] })),
            api.getTrips().catch(() => []),
        ]);
        const rows = (elig.bookings || []).map(b => `
            <tr>
                <td>${esc(b.reference)}</td>
                <td><span class="pill info">${esc(b.type)}</span></td>
                <td>${esc(b.serviceName)}</td>
                <td>${money(b.total)}</td>
                <td class="flex gap">
                    <button class="btn btn-outline btn-sm" data-rev-type="${esc(b.type)}" data-rev-id="${esc(b.serviceId)}" data-rev-name="${esc(b.serviceName)}">Read reviews</button>
                    <button class="btn btn-primary btn-sm" data-rate="${b.bookingId}" data-name="${esc(b.serviceName)}" data-bid="${b.reference}">Rate \u2605</button>
                </td>
            </tr>`).join('') || '<tr><td colspan="5" class="text-muted">No rateable bookings yet.</td></tr>';
        const mineRows = (mine.ratings || []).map(r => `
            <tr><td>${esc(r.reference || '\u2014')}</td><td><span class="pill info">${esc(r.serviceType)}</span></td>
            <td>${'\u2605'.repeat(r.rating)}<span class="text-muted">${'\u2605'.repeat(5 - r.rating)}</span></td>
            <td>${esc(r.comment || '')}</td></tr>`).join('') ||
            '<tr><td colspan="4" class="text-muted">You have not written any reviews yet.</td></tr>';
        const t = (Array.isArray(trips) ? trips : []).filter(x => x.status === 'BOOKED');
        $('portalContent').innerHTML =
            card('Rate a Booking',
                `<p class="text-muted">Only completed / confirmed bookings can be rated. Ratings power TripMind\u2019s AI booking recommendations.</p>
                 <table class="row-table" style="width:100%"><tr><th>Booking</th><th>Type</th><th>Service</th><th>Total</th><th>Actions</th></tr>${rows}</table>`) +
            card('My Reviews', `<table class="row-table" style="width:100%"><tr><th>Booking</th><th>Type</th><th>Rating</th><th>Comment</th></tr>${mineRows}</table>`) +
            (t.length ? card('Trip Feedback',
                `<p class="text-muted">How was your AI-planned trip?</p>
                 ${t.map(x => `<div class="flex justify-between" style="padding:.5rem 0;">
                     <div><b>${esc(x.origin)} \u2192 ${esc(x.destination)}</b>
                         <span class="form-input text-muted" style="display:inline-block;margin-left:.5rem;">${esc((x.startDate || '').slice(0, 10))}</span></div>
                     <button class="btn btn-outline btn-sm" onclick="TM.reviewTrip('${x._id}', '${esc(x.origin)}', '${esc(x.destination)}')">Review trip</button>
                 </div>`).join('')}`) : '');
        document.querySelectorAll('[data-rate]').forEach(btn => btn.addEventListener('click', () => {
            const bookingId = btn.dataset.rate;
            const name = btn.dataset.name;
            const m = dialog(`<h3>Rate ${esc(name)}</h3>
                <p class="text-muted">${esc('Booking ' + btn.dataset.bid)}</p>
                <div class="form-group"><label class="form-label">Your rating</label>
                  <div class="star-row" id="__stars">
                    ${[1, 2, 3, 4, 5].map(i => `<button type="button" class="star-btn" data-v="${i}">\u2605</button>`).join('')}
                  </div></div>
                <div class="form-group"><label class="form-label">Comment (optional)</label>
                  <textarea id="__cmt" class="form-input" rows="2" placeholder="Tell us how it went"></textarea></div>
                <div class="flex end gap">
                  <button class="btn btn-outline" data-close>Cancel</button>
                  <button class="btn btn-primary" id="__ok">Submit Review</button>
                </div>`);
            let stars = 0;
            m.el.querySelectorAll('.star-btn').forEach(b => b.addEventListener('click', () => {
                stars = +b.dataset.v;
                m.el.querySelectorAll('.star-btn').forEach(x =>
                    x.style.color = +x.dataset.v <= stars ? '#eab308' : '#cbd5e1');
            }));
            m.get('#__ok').addEventListener('click', () => run(async () => {
                if (!stars) { toast('Pick between 1 and 5 stars.', true); return; }
                await api.addRating({ bookingId, rating: stars, comment: m.get('#__cmt').value });
                toast('Thanks for your review!');
                m.close();
                showPanel('pfeedback');
            }));
        }));
        document.querySelectorAll('[data-rev-type]').forEach(btn => btn.addEventListener('click', () =>
            TM.serviceReviews(btn.dataset.revType, btn.dataset.revId, btn.dataset.revName)));
    }

    /* Read the aggregate rating + written reviews for one service. Used from
       the feedback panel so a traveller can see what others said before they
       rate, and reusable anywhere a service id/type is known. */
    window.TM.serviceReviews = (type, id, name) => run(async () => {
        const m = dialog(`<h3>Reviews &amp; ratings</h3>
            <p class="text-muted">${esc(name || 'This service')}</p>
            <div id="__rev"><div class="state-msg"><div class="spinner"></div><div class="state-title">Loading reviews\u2026</div></div></div>
            <div class="flex end gap" style="margin-top:.9rem;"><button class="btn btn-outline" data-close>Close</button></div>`);
        const box = m.get('#__rev');
        const r = await api.serviceRating(type, id);
        const count = r.count || 0;
        const dist = r.distribution || {};
        if (!count) {
            box.innerHTML = '<p class="text-muted">No reviews yet. Only a traveller who booked this service can rate it.</p>';
            return;
        }
        const summary = `<div class="rev-summary">
            <div class="rev-avg"><b>${r.avg != null ? Number(r.avg).toFixed(1) : '\u2014'}</b>
                <span>${'\u2605'.repeat(Math.round(r.avg || 0))}</span>
                <small>${count} rating${count === 1 ? '' : 's'}</small></div>
            <div class="rev-dist">${[5, 4, 3, 2, 1].map(s => {
                const c = dist[String(s)] || 0;
                const pct = count ? Math.round(c / count * 100) : 0;
                return `<div class="rev-dist__row"><span>${s} \u2605</span>
                    <span class="rev-dist__track"><i style="width:${pct}%"></i></span><span>${c}</span></div>`;
            }).join('')}</div></div>`;
        const reviews = r.reviews || [];
        box.innerHTML = summary + (reviews.length
            ? reviews.map(rv => `<div class="rev-item"><div class="rev-item__top">
                    <b>${esc(rv.reviewer || 'A traveller')}</b>
                    <span class="star-mini">${'\u2605'.repeat(rv.rating || 0)}</span></div>
                    ${rv.comment ? `<p>${esc(rv.comment)}</p>` : ''}
                    <small class="text-muted">${esc(String(rv.createdAt || '').slice(0, 10))}</small></div>`).join('')
            : '<p class="text-muted">No written comments yet \u2014 only star ratings so far.</p>');
    });

    async function userWallet() {
        const w = await api.getWallet();
        const rows = (w.transactions || []).map(t => `<tr>
            <td>${esc(t.type)}</td>
            <td>${esc(t.description || '')}</td>
            <td>${t.amount > 0 ? '+' : ''}${money(t.amount)}</td>
            <td>${esc(t.ref || '')}</td>
            <td>${esc(String(t.createdAt).slice(0, 16).replace('T', ' '))}</td>
            <td>${money(t.balance || 0)}</td></tr>`).join('') ||
            '<tr><td colspan="6" class="text-muted">No transactions yet.</td></tr>';
        $('portalContent').innerHTML = card('Wallet', `
            <div class="stats-grid">
                <div class="stat-card"><div class="stat-label">Balance</div><div class="stat-value">${money(w.balance)}</div></div>
                <div class="stat-card"><div class="stat-label">Total Deposited</div><div class="stat-value">${money(w.totalDeposited)}</div></div>
                <div class="stat-card"><div class="stat-label">Total Spent</div><div class="stat-value">${money(w.totalSpent)}</div></div>
            </div>
            <div class="flex gap" style="margin-top:1rem;">
                ${field('Add funds (\u20b9)', 'wl_amount', num('wl_amount', 'value="1000"'))}
                <button class="btn btn-primary" onclick="TM.depositWallet()">Add Funds</button>
            </div>`) +
            card('Transactions', `<table class="row-table" style="width:100%">
                <tr><th>Type</th><th>Description</th><th>Amount</th><th>Reference</th><th>When</th><th>Balance</th></tr>
                ${rows}</table>`);
        window.TM.depositWallet = () => run(async () => {
            const amount = parseFloat($('wl_amount').value);
            if (!(amount > 0)) { toast('Enter a valid amount.'); return; }
            const res = await api.walletDeposit(amount);
            toast('\u20b9' + res.balance + ' available in wallet.');
            await userWallet();
        });
    }

    function fareOf(d) {
        if (!d) return 0;
        const f = d.fare || {};
        for (const k of ['price', 'baseFare', 'sleeper', 'seater']) if (f[k]) return f[k];
        // For cabs/autos show the baseFare (pickup charge) when available; the per-km
        // rate is the pricing dimension in the fleet list (shown separately).
        if (f.baseFare) return f.baseFare;
        if (f.pricePerKm || f.perKm) return 0;
        const arr = d.coaches || d.classes || [];
        if (arr[0] && arr[0].price) return arr[0].price;
        return 0;
    }

    /* ---------------- TRANSPORT ADMIN ---------------- */

    async function transportProfile() {
        const res = await api.transportService();
        const p = res.profile || {};
        const service = p.serviceName || user.name || 'Unnamed Service';
        const loc = bizLoc();
        $('portalContent').innerHTML = card('Company Profile', `
            <p class="text-muted">Your company details were captured at registration and reviewed by the Main Admin. They are shown read-only here.</p>
            <div class="detail-list">
                ${infoRow('Service name', service)}
                ${infoRow('Company / service name (registered)', regVal('Company / service name'))}
                ${infoRow('Service area', regVal('Primary service area'))}
                ${infoRow('City', regVal('City'))}
                ${infoRow('Company address', regVal('Company address'))}
                ${infoRow('Contact', regVal('Contact number') || p.contact || (user.registration || {}).Contact)}
                ${infoRow('GST number', user.gst)}
                ${infoRow('Drivers', regVal('Number of drivers'))}
                ${infoRow('Description', regVal('Company description') || p.description)}
                ${infoRow('Weekly working hours', wkHoursText())}
                ${infoRow('Business location', loc.lat && loc.lng ? `${loc.address || ''} \u00b7 ${loc.lat}, ${loc.lng}` : loc.address)}
            </div>
            <div class="flex gap mt-4">
                <button class="btn btn-outline" onclick="showPanel('register')">Manage Transport</button>
                <button class="btn btn-outline" onclick="showPanel('fleet')">Upcoming Passengers</button>
            </div>`);
    }

    async function transportRegister() {
        let types = [
            { value: 'BUS', label: 'Bus' }, { value: 'TRAIN', label: 'Train' },
            { value: 'FLIGHT', label: 'Flight' }, { value: 'CAB', label: 'Cab' }, { value: 'AUTO', label: 'Auto Rickshaw' },
        ];
        try { const r = await api.transportTypes(); if (r.types && r.types.length) types = r.types; } catch (e) { /* keep fallback */ }
        const typeSel = (id) => `<select id="${id}" class="form-select">${types.map(t => `<option value="${esc(t.value)}">${esc(t.label)}</option>`).join('')}</select>`;

        $('portalContent').innerHTML = card('Manage Transport', `
            <p class="text-muted">One company \u00b7 many vehicles. Each vehicle is a real database record and is approved separately by the Main Admin before it can be booked.</p>
            <div id="tr_summary" class="stats-grid mb-4"></div>
            <div class="flex justify-between" style="align-items:center;margin-bottom:.75rem;">
                <div class="card-title">Your fleet</div>
                <button class="btn btn-primary btn-sm" onclick="TM.trOpenForm()">+ Add Vehicle</button>
            </div>
            <div id="tr_cards" class="vehicle-grid"></div>`);

        window.TM.trOpenForm = () => {
            const m = dialog(`<h3>Register a vehicle</h3>
                <div class="form-row">${field('Type', 'tr_type', typeSel('tr_type'))}</div>
                <div id="tr_form"></div>
                <div id="tr_err" class="mt-2"></div>
                <div class="flex end gap" style="margin-top:1.25rem;">
                    <button class="btn btn-outline" data-close>Cancel</button>
                    <button class="btn btn-primary" onclick="TM.trSubmit()">Register Vehicle</button>
                </div>`);
            window.__trDialog = m;
            renderTrForm($('tr_type').value);
            $('tr_type').addEventListener('change', () => renderTrForm($('tr_type').value));
        };
        window.TM.addRow = () => addTrRow($('tr_stops'), 'row-stops');
        window.TM.addCoach = () => addTrRow($('tr_coaches'), 'row-coaches');
        window.TM.addStation = () => addTrRow($('tr_stations'), 'row-stations');
        window.TM.addClass = () => addTrRow($('tr_classes'), 'row-classes');
        run(async () => {
            const res = await api.getTransports();
            const t = res.transports || [];
            $('tr_summary').innerHTML = `
                <div class="stat-card"><div class="stat-label">Total vehicles</div><div class="stat-value">${t.length}</div></div>
                <div class="stat-card"><div class="stat-label">Approved</div><div class="stat-value">${t.filter(x => x.status === 'APPROVED').length}</div></div>
                <div class="stat-card"><div class="stat-label">Pending approval</div><div class="stat-value">${t.filter(x => x.status === 'PENDING').length}</div></div>
                <div class="stat-card"><div class="stat-label">Passengers</div><div class="stat-value"><a href="#" onclick="event.preventDefault();showPanel('fleet');" class="text-link">View</a></div></div>`;
            $('tr_cards').innerHTML = t.length ? t.map(x => `
                <div class="card vehicle-card">
                    <div class="card-content">
                        <div class="flex justify-between" style="align-items:flex-start;gap:.5rem;">
                            <span class="pill info">${esc(x.type)}</span>
                            ${x.status === 'APPROVED' ? '<span class="pill good">APPROVED</span>' : x.status === 'REJECTED' ? '<span class="pill bad">REJECTED</span>' : '<span class="pill warn">PENDING</span>'}
                        </div>
                        <div class="mt-2" style="font-weight:600;">${esc(vehicleTitle(x.details || x))}</div>
                        <div class="text-muted" style="font-size:.8rem;">${esc(x.summary)}</div>
                        <button class="btn btn-outline btn-sm mt-3" onclick="TM.vehicleDetail('${x.transportId}')">View details</button>
                    </div>
                </div>`).join('')
                : '<p class="text-muted">No vehicles registered yet \u2014 add your first vehicle.</p>';
        });
    }

    function vehicleTitle(d) {
        if (d.busNumber) return 'Bus ' + d.busNumber;
        if (d.trainNumber) return d.trainName || ('Train ' + d.trainNumber);
        if (d.flightNumber) return 'Flight ' + d.flightNumber;
        if (d.vehicleNumber) return d.vehicleType ? (d.vehicleNumber + ' \u00b7 ' + d.vehicleType) : d.vehicleNumber;
        return d.serviceName || String(d._id || '').slice(0, 12);
    }

    window.TM.vehicleDetail = (tid) => run(async () => {
        const res = await api.getTransport(tid);
        const d = (res.transport && res.transport.details) || res.transport;
        const m = dialog(`<h3>${esc(vehicleTitle(d))}</h3>
            <div class="detail-list">
                ${infoRow('Type', d.type)}
                ${infoRow('Status', d.status)}
                ${infoRow('Service', d.serviceName || '\u2014')}
                ${d.busNumber ? infoRow('Bus number', d.busNumber) : ''}
                ${d.trainNumber ? infoRow('Train', d.trainNumber + (d.trainName ? ' \u00b7 ' + d.trainName : '')) : ''}
                ${d.flightNumber ? infoRow('Flight', d.flightNumber + (d.departureAirport ? ' \u00b7 ' + (d.departureAirport + ' \u2192 ' + d.arrivalAirport) : '')) : ''}
                ${d.vehicleNumber ? infoRow('Vehicle number', d.vehicleNumber) : ''}
                ${d.boardingPoint ? infoRow('Route', d.boardingPoint + ' \u2192 ' + d.droppingPoint) : ''}
                ${d.boardingStation ? infoRow('Route', d.boardingStation + ' \u2192 ' + d.destinationStation) : ''}
                ${d.boardingTime ? infoRow('Departure', d.boardingTime + (d.boardingDay != null ? ' (Day +' + d.boardingDay + ')' : '')) : ''}
                ${d.droppingTime ? infoRow('Arrival', d.droppingTime + (d.droppingDay != null ? ' (Day +' + d.droppingDay + ')' : '')) : ''}
                ${d.totalSeats ? infoRow('Total seats', d.totalSeats) : ''}
                ${d.seatingCapacity ? infoRow('Seating capacity', d.seatingCapacity) : ''}
                ${d.serviceArea ? infoRow('Service area', d.serviceArea) : ''}
                ${d.baseLocation ? infoRow('Base location', d.baseLocation) : ''}
                ${d.fare && typeof d.fare === 'object' ? infoRow('Fare', Object.entries(d.fare).filter(([,v]) => v != null && v !== '').map(([k, v]) => k + ': ' + v).join(' \u00b7 ')) : ''}
                ${d.createdAt ? infoRow('Registered on', String(d.createdAt).replace('T', ' ').slice(0, 16)) : ''}
            </div>
            <div class="flex end gap"><button class="btn btn-outline" data-close>Close</button></div>`);
    });

    function renderTrForm(type) {
        const f = $('tr_form'), h = {
            BUS: `
                <div class="form-row">
                    ${field('Bus number', 't1', input('t1', 'placeholder="e.g. TN38-AB-1427"'))}
                    ${field('Boarding point', 't2', input('t2', 'placeholder="Boarding point / terminal"'))}
                    ${field('Boarding day', 't3', `<select id="t3" class="form-select">${dayOptions()}</select>`)}
                    ${field('Boarding time (24h)', 't4', input('t4', 'placeholder="21:30"'))}
                    ${field('Dropping point', 't5', input('t5', 'placeholder="Dropping point / terminal"'))}
                    ${field('Dropping day', 't6', `<select id="t6" class="form-select">${dayOptions(1)}</select>`)}
                    ${field('Dropping time (24h)', 't7', input('t7', 'placeholder="05:30"'))}
                </div>
                <div class="hr-label">Boarding point location (Google Maps)</div>
                <p class="text-sm text-muted" style="margin:.35rem 0 .6rem;">Pick the exact boarding point on the map so the AI can bill your home\u2192boarding transfer from the real road distance.</p>
                <div style="display:grid;grid-template-columns:1fr auto;gap:.4rem;margin-bottom:.5rem;">
                    <input id="tbpAddr" class="form-input" placeholder="Search boarding point\u2026">
                    <button class="btn btn-outline" type="button" onclick="TM.pickBusPoint('boarding')">Pick on map</button>
                </div>
                <input id="tbLat" type="hidden"><input id="tbLng" type="hidden">
                <div id="tbpMap" style="height:180px;border:1px solid var(--slate-100);border-radius:.6rem;display:none;margin-bottom:.6rem;"></div>
                <p class="text-sm text-muted" id="tbpNote" style="font-size:.75rem;">Optional \u2014 if you skip it, transfers fall back to the boarding point name/address.</p>
                <div class="hr-label">Dropping point location (Google Maps)</div>
                <div style="display:grid;grid-template-columns:1fr auto;gap:.4rem;margin-bottom:.5rem;">
                    <input id="tdpAddr" class="form-input" placeholder="Search dropping point\u2026">
                    <button class="btn btn-outline" type="button" onclick="TM.pickBusPoint('dropping')">Pick on map</button>
                </div>
                <input id="tdLat" type="hidden"><input id="tdLng" type="hidden">
                <div id="tdpMap" style="height:180px;border:1px solid var(--slate-100);border-radius:.6rem;display:none;margin-bottom:.6rem;"></div>
                <p class="text-sm text-muted" style="font-size:.75rem;">Optional \u2014 used for arrival\u2192stay and return-home transfer fares.</p>
                <div class="hr-label">Seats</div>
                <div class="form-row">
                    ${field('Total seats', 't8', num('t8', 'value="32"'))}
                    ${field('Sleeper seats', 't9', num('t9', 'value="24"'))}
                    ${field('Seater seats', 't10', num('t10', 'value="8"'))}
                </div>
                <div class="form-row">
                    ${field('Sleeper fare (\u20b9)', 't11', num('t11', ''))}
                    ${field('Seater fare (\u20b9)', 't12', num('t12', ''))}
                    ${field('Single-seat available', 't13', `<select id="t13" class="form-select"><option value="true">Yes</option><option value="false">No</option></select>`)}
                    ${field('Double-seat available', 't14', `<select id="t14" class="form-select"><option value="true">Yes</option><option value="false">No</option></select>`)}
                </div>
                <div class="hr-label">Intermediate stops</div>
                <button class="btn btn-outline btn-sm" onclick="TM.addRow()">+ Stop</button>
                <div id="tr_stops"></div>`,
            TRAIN: `
                <div class="form-row">
                    ${field('Train number', 't1', input('t1', 'placeholder="e.g. 12675"'))}
                    ${field('Train name', 't2', input('t2', 'placeholder="Train name"'))}
                    ${field('Boarding station', 't3', input('t3', 'placeholder="Boarding station"'))}
                    ${field('Destination station', 't4', input('t4', 'placeholder="Destination station"'))}
                </div>
                <div class="hr-label">Coach configuration</div>
                <button class="btn btn-outline btn-sm" onclick="TM.addCoach()">+ Coach type</button>
                <div id="tr_coaches"><div class="coach-row" style="display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.5rem;">
                    <input class="form-input" placeholder="Code" value="SL" style="flex:0 0 70px;">
                    <input class="form-input" placeholder="Label" value="Sleeper Class" style="flex:1 1 140px;">
                    <input class="form-input" type="number" placeholder="Coaches" value="1" style="flex:0 0 90px;">
                    <input class="form-input" type="number" placeholder="Cap/coach" value="72" style="flex:0 0 100px;">
                    <input class="form-input" type="number" placeholder="Price \u20b9" style="flex:0 0 90px;"></div></div>
                <div class="hr-label">Stations</div>
                <button class="btn btn-outline btn-sm" onclick="TM.addStation()">+ Station</button>
                <div id="tr_stations"><div class="station-row" style="display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.5rem;">
                    <input class="form-input" placeholder="Station" style="flex:1 1 140px;">
                    <input class="form-input" placeholder="Day" value="0" style="flex:0 0 60px;">
                    <input class="form-input" placeholder="Arrival 24h" style="flex:0 0 110px;">
                    <input class="form-input" placeholder="Departure 24h" style="flex:0 0 110px;"></div></div>`,
            FLIGHT: `
                <div class="form-row">
                    ${field('Flight number', 't1', input('t1', 'placeholder="e.g. KS-882"'))}
                    ${field('Departure airport', 't2', input('t2', 'placeholder="Departure airport"'))}
                    ${field('Arrival airport', 't3', input('t3', 'placeholder="Arrival airport"'))}
                    ${field('Boarding day', 't4', `<select id="t4" class="form-select">${dayOptions()}</select>`)}
                    ${field('Boarding time (24h)', 't5', input('t5', 'placeholder="09:40"'))}
                    ${field('Arrival day', 't6', `<select id="t6" class="form-select">${dayOptions()}</select>`)}
                    ${field('Arrival time (24h)', 't7', input('t7', 'placeholder="10:50"'))}
                    ${field('Layover airport (optional)', 't8', input('t8', ''))}
                    ${field('Total seats', 't9', num('t9', 'value="150"'))}
                    ${field('Cabin baggage', 't10', input('t10', 'value="7 kg"'))}
                    ${field('Check-in baggage', 't11', input('t11', 'value="15 kg"'))}
                </div>
                <div class="hr-label">Cabin classes</div>
                <button class="btn btn-outline btn-sm" onclick="TM.addClass()">+ Class</button>
                <div id="tr_classes"><div class="class-row" style="display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.5rem;">
                    <input class="form-input" placeholder="Name" value="Economy" style="flex:1 1 120px;">
                    <input class="form-input" type="number" placeholder="Seats" value="120" style="flex:0 0 80px;">
                    <input class="form-input" type="number" placeholder="Price \u20b9" style="flex:0 0 90px;"></div></div>`,
            CAB: cabForm('CAB'), AUTO: cabForm('AUTO'),
        }[type];
        f.innerHTML = h;
    }

    function cabForm(type) {
        return `
            <div class="form-row">
                ${field('Vehicle number', 't1', input('t1', 'placeholder="TN38-DV-8802"'))}
                ${field('Vehicle type', 't2', input('t2', type === 'CAB' ? 'placeholder="Sedan / Innova / Etios"' : 'value="AUTO"'))}
                ${field('Seating capacity', 't3', num('t3', 'value="' + (type === 'CAB' ? 4 : 3) + '"'))}
                ${field('AC', 't4', `<select id="t4" class="form-select"><option value="true">Yes</option><option value="false">No</option></select>`)}
                ${field('Driver name', 't5', input('t5', ''))}
                ${field('Driver phone', 't6', input('t6', ''))}
                ${field('Service area', 't7', input('t7', 'placeholder="Primary service area"'))}
                ${field('Base location', 't8', input('t8', 'placeholder="Base / home location"'))}
                ${field('Available from (24h)', 't9', input('t9', 'value="06:00"'))}
                ${field('Available to (24h)', 't10', input('t10', 'value="22:00"'))}
                ${field('Base fare (\u20b9)', 't11', num('t11', ''))}
                ${field('Per km (\u20b9)', 't12', num('t12', ''))}
                ${field('Minimum (\u20b9)', 't13', num('t13', ''))}
            </div>`;
    }

    function dayOptions(def) {
        return Array.from({ length: 7 }, (_, i) => `<option ${i === (def ?? 0) ? 'selected' : ''} value="${i}">Day ${i}</option>`).join('');
    }

    function addTrRow(container, cls) {
        let html;
        if (cls === 'row-stops') html = `<div class="stop-row" style="display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.5rem;"><input class="form-input" placeholder="Stop name" style="flex:1 1 140px;"><input class="form-input" placeholder="Day" value="0" style="flex:0 0 60px;"><input class="form-input" placeholder="Time 24h" style="flex:0 0 110px;"></div>`;
        if (cls === 'row-coaches') html = `<div class="coach-row" style="display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.5rem;"><input class="form-input" placeholder="Code" style="flex:0 0 70px;"><input class="form-input" placeholder="Label" style="flex:1 1 140px;"><input class="form-input" type="number" placeholder="Coaches" style="flex:0 0 90px;"><input class="form-input" type="number" placeholder="Cap/coach" style="flex:0 0 100px;"><input class="form-input" type="number" placeholder="Price \u20b9" style="flex:0 0 90px;"></div>`;
        if (cls === 'row-stations') html = `<div class="station-row" style="display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.5rem;"><input class="form-input" placeholder="Station" style="flex:1 1 140px;"><input class="form-input" placeholder="Day" value="0" style="flex:0 0 60px;"><input class="form-input" placeholder="Arrival 24h" style="flex:0 0 110px;"><input class="form-input" placeholder="Departure 24h" style="flex:0 0 110px;"></div>`;
        if (cls === 'row-classes') html = `<div class="class-row" style="display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.5rem;"><input class="form-input" placeholder="Name" style="flex:1 1 120px;"><input class="form-input" type="number" placeholder="Seats" style="flex:0 0 80px;"><input class="form-input" type="number" placeholder="Price \u20b9" style="flex:0 0 90px;"></div>`;
        container.insertAdjacentHTML('beforeend', html);
    }

    function collectRows(container, fields) {
        return [...container.querySelectorAll(':scope > div')].map(r => {
            const vals = [...r.querySelectorAll('input')].map(i => i.value.trim());
            const o = {};
            fields.forEach((name, i) => o[name] = vals[i] ?? '');
            return o;
        }).filter(o => Object.values(o).some(v => v !== ''));
    }

    window.TM.trSubmit = () => run(async () => {
        const type = $('tr_type').value;
        const e = document.getElementById('tr_err');
        e.textContent = '';
        const data = { type };
        const v = (id) => ($(id) ? $(id).value : '').trim();

        if (type === 'BUS') {
            Object.assign(data, {
                busNumber: v('t1'), boardingPoint: v('t2'), boardingDay: +v('t3'), boardingTime: v('t4'),
                droppingPoint: v('t5'), droppingDay: +v('t6'), droppingTime: v('t7'),
                totalSeats: +v('t8'), sleeperSeats: +v('t9'), seaterSeats: +v('t10'),
                sleeperFare: +v('t11'), seaterFare: +v('t12'),
                singleSeat: v('t13') === 'true', doubleSeat: v('t14') === 'true',
                seatTypes: ['SLEEPER', 'SEATER'], fare: { sleeper: +v('t11'), seater: +v('t12') },
                stops: collectRows($('tr_stops'), ['name', 'day', 'time']),
                boardingLat: v('tbLat') || undefined, boardingLng: v('tbLng') || undefined,
                droppingLat: v('tdLat') || undefined, droppingLng: v('tdLng') || undefined,
            });
            if (+v('t9') + +v('t10') !== +v('t8')) { e.innerHTML = 'Sleeper + Seater must equal Total Seats.'; return; }
        }
        if (type === 'TRAIN') {
            const coaches = collectRows($('tr_coaches'), ['code', 'label', 'coachCount', 'capacityPerCoach', 'price']);
            Object.assign(data, {
                trainNumber: v('t1'), trainName: v('t2'),
                boardingStation: v('t3'), destinationStation: v('t4'),
                coaches, totalCoaches: coaches.reduce((s, c) => s + (+c.coachCount || 0), 0),
                stations: collectRows($('tr_stations'), ['name', 'day', 'arrivalTime', 'departureTime']),
                daysOfWeek: [0, 1, 2, 3, 4, 5, 6],
            });
        }
        if (type === 'FLIGHT') {
            Object.assign(data, {
                flightNumber: v('t1'), departureAirport: v('t2'), arrivalAirport: v('t3'),
                boardingDay: +v('t4'), boardingTime: v('t5'), arrivalDay: +v('t6'), arrivalTime: v('t7'),
                layoverAirport: v('t8') || undefined, totalSeats: +v('t9'),
                classes: collectRows($('tr_classes'), ['name', 'seats', 'price']),
                cabinBaggage: v('t10'), checkinBaggage: v('t11'),
            });
        }
        if (type === 'CAB' || type === 'AUTO') {
            Object.assign(data, {
                vehicleNumber: v('t1'), vehicleType: v('t2'), seatingCapacity: +v('t3'),
                ac: v('t4') === 'true', driver: { name: v('t5'), phone: v('t6') },
                serviceArea: v('t7'), baseLocation: v('t8'),
                availableTimings: { from: v('t9'), to: v('t10') },
                fare: { baseFare: +v('t11'), perKm: +v('t12'), minimum: +v('t13') },
            });
        }
        await api.registerTransport(data);
        toast('Transport registered!');
        if (window.__trDialog) { window.__trDialog.close(); window.__trDialog = null; }
        showPanel('register');
    });

    /* Provider-side Google Maps picker for the bus boarding/dropping point.
     * The traveller's home\u2192boarding transfer is billed from the real road
     * distance between these coordinates and their Google-picked start point,
     * so the provider supplies the exact boarding location here. */
    let __trBusPickers = {};
    window.TM.pickBusPoint = async (which) => {
        const isB = which === 'boarding';
        const addrId = isB ? 'tbpAddr' : 'tdpAddr';
        const latId = isB ? 'tbLat' : 'tdLat';
        const lngId = isB ? 'tbLng' : 'tdLng';
        const mapId = isB ? 'tbpMap' : 'tdpMap';
        const noteId = isB ? 'tbpNote' : 'tdpNote';
        const mapEl = document.getElementById(mapId);
        if (!mapEl) return;
        if (!window.TM_MAPS || !(await window.TM_MAPS.init())) {
            showToast('Google Maps is not configured \u2014 the boarding point will be stored by name only.');
            return;
        }
        mapEl.style.display = 'block';
        const note = document.getElementById(noteId);
        if (note) note.textContent = 'Search a place or click / drag the marker to set the exact location.';
        if (!__trBusPickers[which]) {
            __trBusPickers[which] = window.TM_MAPS.initLocationPicker({
                addressId: addrId, latId, lngId, mapId,
            });
        }
    };

    async function transportFleet() {
        const [res, bk] = await Promise.all([
            api.getTransports().catch(() => ({ transports: [] })),
            api.providerBookings('TRANSPORT').catch(() => ({ bookings: [] })),
        ]);
        const transports = res.transports || [];
        const route = (tid) => {
            const x = transports.find(v => v.transportId === tid);
            return x ? `${x.type} \u00b7 ${x.summary}` : (tid ? tid.slice(0, 13) + '\u2026' : '\u2014');
        };
        const all = bk.bookings || [];
        const today = new Date().toISOString().slice(0, 10);
        const upcoming = all.filter(x => x.status !== 'CANCELLED' && x.status !== 'REJECTED'
            && (x.date || '') >= today);
        const completed = all.filter(x => x.status === 'COMPLETED' || (x.status === 'CANCELLED')
            || (x.date || '') < today);
        const rowHtml = (x) => `
            <tr>
                <td>${esc(x.reference)}</td>
                <td>${esc(route(x.transportId))}</td>
                <td>${esc((x.customer || {}).name || 'Traveler')}</td>
                <td>${esc((x.customer || {}).mobile || '\u2014')}</td>
                <td>${esc(x.date)}</td>
                <td>${esc(String(x.details?.seatType || x.seatType || '\u2014'))}</td>
                <td>${x.qty}</td>
                <td>${money(x.total)}</td>
                <td><span class="pill ${x.status === 'CONFIRMED' ? 'good' : x.status === 'COMPLETED' ? 'ok' : x.status === 'CANCELLED' || x.status === 'REJECTED' ? 'bad' : 'info'}">${esc(x.status)}</span></td>
                <td>${payPill(x.paymentStatus || (x.walletPaid ? 'PAID' : 'PENDING'))}</td>
                <td><button class="btn btn-outline btn-sm" onclick="TM.passengerDetail('${x._id}')">View</button></td>
            </tr>`;
        const table = (rows) => `<div class="table-scroll"><table class="row-table" style="width:100%">
            <tr><th>Ref</th><th>Vehicle</th><th>Passenger</th><th>Mobile</th><th>Date</th><th>Seat</th><th>Qty</th><th>Total</th><th>Status</th><th>Payment</th><th></th></tr>
            ${rows.length ? rows.map(rowHtml).join('') : '<tr><td colspan="11" class="text-muted">No passengers here.</td></tr>'}</table></div>`;
        $('portalContent').innerHTML = card('Upcoming Passengers', `
            <div class="stats-grid mb-4">
                <div class="stat-card"><div class="stat-label">Upcoming</div><div class="stat-value">${upcoming.length}</div></div>
                <div class="stat-card"><div class="stat-label">Completed</div><div class="stat-value">${completed.length}</div></div>
                <div class="stat-card"><div class="stat-label">Total passengers</div><div class="stat-value">${all.reduce((s, x) => s + (x.qty || 0), 0)}</div></div>
            </div>
            <div class="flex" style="gap:.5rem;margin-bottom:1rem;">
                <button class="btn btn-primary btn-sm" onclick="TM.fleetTab('up')">Upcoming</button>
                <button class="btn btn-outline btn-sm" onclick="TM.fleetTab('done')">Completed</button>
            </div>
            <div id="fleet_body">${table(upcoming)}</div>`);
        window.TM.fleetTab = (which) => {
            $('fleet_body').innerHTML = which === 'done' ? table(completed) : table(upcoming);
            document.querySelectorAll('#fleet_body button').forEach(() => {});
        };
        window.TM.passengerDetail = (bid) => {
            const x = all.find(b => b._id === bid);
            if (!x) return;
            const m = dialog(`<h3>${esc(x.reference)}</h3>
                <div class="detail-list">
                    ${infoRow('Passenger', (x.customer || {}).name || '\u2014')}
                    ${infoRow('Mobile', (x.customer || {}).mobile || '\u2014')}
                    ${infoRow('Email', (x.customer || {}).email || '\u2014')}
                    ${infoRow('Vehicle', route(x.transportId))}
                    ${infoRow('Travel date', x.date)}
                    ${infoRow('Seat class', String(x.details?.seatType || x.seatType || '\u2014'))}
                    ${infoRow('Seats', x.qty)}
                    ${infoRow('Total', money(x.total))}
                    ${infoRow('Payment', x.paymentStatus + (x.walletPaid ? ' \u00b7 ' + money(x.walletPaid) : ''))}
                    ${infoRow('Status', x.status)}
                </div>
                <div class="flex end gap"><button class="btn btn-outline" data-close>Close</button></div>`);
        };
    }

    /* ---------------- TOURIST SPOT ADMIN ---------------- */

    function fileToDataUrl(file) {
        return new Promise((resolve, reject) => {
            if (!file) return resolve('');
            const r = new FileReader();
            r.onload = () => resolve(r.result);
            r.onerror = reject;
            r.readAsDataURL(file);
        });
    }

    function touristSpotForm() {
        const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
        $('portalContent').innerHTML = card('Add a Tourist Spot', `
            <div class="form-row">
                ${field('Name', 'sp_name', input('sp_name', 'placeholder="Kapaleeshwarar Temple"'))}
                ${field('Category', 'sp_cat', `<select id="sp_cat" class="form-select">
                    ${['HISTORICAL', 'BEACH', 'MUSEUM', 'SHRINE', 'PARK', 'OTHER'].map(c => `<option>${c}</option>`).join('')}</select>`)}
                ${field('Popularity (0-100)', 'sp_pop', num('sp_pop', 'value="80"'))}
                ${field('Entry fee (\u20b9, 0 = free)', 'sp_fee', num('sp_fee', 'value="0"'))}
                ${field('Visiting travelers', 'sp_trav', num('sp_trav', 'value="0"'))}
                ${field('Opening time (24h)', 'sp_open', input('sp_open', 'value="09:00"'))}
                ${field('Closing time (24h)', 'sp_close', input('sp_close', 'value="18:00"'))}
            </div>
            <div class="hr-label">Location</div>
            <div class="form-row">
                ${field('Location name', 'sp_loc', input('sp_loc', 'placeholder="Mylapore"'))}
                ${field('City', 'sp_city', input('sp_city', 'placeholder="Chennai"'))}
                ${field('District', 'sp_dist', input('sp_dist', 'placeholder="Chennai"'))}
            </div>
            <div class="form-row">
                ${field('State', 'sp_state', input('sp_state', 'placeholder="Tamil Nadu"'))}
                ${field('Country', 'sp_country', input('sp_country', 'placeholder="India"'))}
            </div>
            <input type="hidden" id="sp_lat"><input type="hidden" id="sp_lng">
            <div class="form-group">
                <label class="form-label">Pick on map</label>
                <div id="sp_map" style="height:260px;border:1px solid var(--slate-100);border-radius:.6rem;"></div>
                <p class="text-muted" id="sp_map_note" style="font-size:.78rem;"></p>
            </div>
            ${field('Map place / address', 'sp_addr', `<textarea id="sp_addr" class="form-textarea" rows="2" placeholder="Street address of the spot"></textarea>`)}
            <div class="hr-label">Optimal visiting time slots (min 5)</div>
            <div id="sp_slots"></div>
            <button class="btn btn-outline btn-sm" onclick="TM.addSpotSlot()">+ Time slot</button>
            <div class="hr-label">Working days</div>
            <div>${DAYS.map(d => `<label style="display:inline-block;margin:.2rem .6rem .2rem 0;"><input type="checkbox" class="sp_day" value="${d}" checked> ${d}</label>`).join('')}</div>
            <div class="hr-label">Photos (min 5 required)</div>
            <div class="form-group">
                <input id="sp_imgs" type="file" class="form-input" multiple accept=".jpg,.jpeg,.png">
                <p class="hint">Select at least 5 images of the spot.</p>
            </div>
            ${field('Description', 'sp_desc', `<textarea id="sp_desc" class="form-textarea" placeholder="Short description of the spot"></textarea>`)}
            <button class="btn btn-primary" onclick="TM.saveSpot()">Publish Spot</button>
            <div id="sp_err" class="mt-2"></div>`);

        $('sp_slots').insertAdjacentHTML('beforeend', spotSlotRow());
        window.TM.addSpotSlot = () => $('sp_slots').insertAdjacentHTML('beforeend', spotSlotRow());
        window.TM.initSpotMap = async () => {
            await window.TM_MAPS.init();
            const note = document.getElementById('sp_map_note');
            if (window.TM_MAPS.ready) {
                window.TM_MAPS.initLocationPicker({
                    addressId: 'sp_addr', latId: 'sp_lat', lngId: 'sp_lng', mapId: 'sp_map', required: true,
                });
                note.textContent = 'Search a place or click / drag the marker to set coordinates \u2014 the exact spot location is required.';
            } else {
                document.getElementById('sp_map').style.display = 'none';
                note.textContent = 'Manual mode \u2014 set GOOGLE_MAPS_API_KEY to enable the map picker.';
            }
        };
        window.TM.initSpotMap();
        window.TM.saveSpot = () => run(async () => {
            const err = $('sp_err');
            err.textContent = '';
            const imgs = $('sp_imgs');
            if (!imgs.files || imgs.files.length < 5) {
                err.innerHTML = 'Provide at least 5 images.';
                return;
            }
            const images = await Promise.all(Array.from(imgs.files).map(fileToDataUrl));
            const slots = [...document.querySelectorAll('#sp_slots .sp-slot')].map(r => {
                const [f, t] = [...r.querySelectorAll('input')].map(i => i.value.trim());
                return { from: f, to: t };
            }).filter(s => s.from && s.to);
            const workingDays = [...document.querySelectorAll('.sp_day:checked')].map(x => x.value);
            if (!($('sp_lat').value && $('sp_lng').value)) {
                err.innerHTML = 'Pick the exact spot location on the map first.';
                return;
            }
            await api.createSpot({
                name: $('sp_name').value.trim(), city: $('sp_city').value.trim(),
                category: $('sp_cat').value, popularity: +$('sp_pop').value,
                entryFee: +$('sp_fee').value, visitingTravelers: +$('sp_trav').value,
                openingTime: $('sp_open').value, closingTime: $('sp_close').value,
                locationName: $('sp_loc').value.trim(), address: $('sp_addr').value.trim(),
                locationCity: $('sp_city').value.trim(), district: $('sp_dist').value.trim(),
                state: $('sp_state').value.trim(), country: $('sp_country').value.trim(),
                lat: $('sp_lat').value, lng: $('sp_lng').value,
                recommendedTimes: slots, optimalTimes: slots, workingDays,
                images,
                description: $('sp_desc').value.trim(),
            });
            toast('Spot published.');
            showPanel('cat');
        });
    }

    function spotSlotRow() {
        return `<div class="sp-slot" style="display:flex;gap:.5rem;align-items:center;margin:.35rem 0;">
            <input class="form-input" type="time" value="09:00" style="flex:1">
            <span class="text-muted">\u2192</span>
            <input class="form-input" type="time" value="10:00" style="flex:1">
            <button class="btn btn-outline btn-sm" onclick="this.closest('.sp-slot').remove()">Remove</button>
        </div>`;
    }

    async function touristCatalogue() {
        const [spots, locs] = await Promise.all([api.getSpots(), api.getGuideLocations()]);
        const sp = spots.spots || [], gl = locs.locations || [];
        $('portalContent').innerHTML =
            card('Registered Spots',
                sp.length ? `<table class="row-table" style="width:100%"><tr><th>Spot</th><th>Category</th><th>City</th><th>Fee</th></tr>` +
                sp.map(s => `<tr><td>${esc(s.name)}</td><td>${esc(s.category)}</td><td>${esc(s.city)}</td><td>${money(s.entryFee)}</td></tr>`).join('') + '</table>'
                : '<p class="text-muted">No spots yet.</p>') +
            card('Authorized Guide Locations',
                gl.length ? `<table class="row-table" style="width:100%"><tr><th>Location</th><th>City</th><th>Spots</th></tr>` +
                gl.map(x => `<tr><td>${esc(x.name)}</td><td>${esc(x.city)}</td><td>${esc((x.spots || []).join(', '))}</td></tr>`).join('') + '</table>'
                : '<p class="text-muted">None yet.</p>') +
            card('Add Authorized Guide Location', `
                <div class="form-row">
                    ${field('Location name', 'gl_name', input('gl_name', 'placeholder="Mylapore"'))}
                    ${field('City', 'gl_city', input('gl_city', 'value="Chennai"'))}
                    ${field('Spots at this location (comma separated)', 'gl_spots', input('gl_spots', 'placeholder="Kapaleeshwarar Temple"'))}
                </div>
                <button class="btn btn-primary" onclick="TM.saveLoc()">Add Location</button>`);
        window.TM.saveLoc = () => run(async () => {
            await api.addGuideLocation({
                name: $('gl_name').value.trim(), city: $('gl_city').value.trim(),
                spots: $('gl_spots').value.split(',').map(s => s.trim()).filter(Boolean),
            });
            toast('Location added.');
            showPanel('cat');
        });
    }

    /* ---------------- GUIDE ---------------- */

    async function guideProfile() {
        const res = await api.getGuideProfile();
        const p = res.profile || {};
        const loc = bizLoc();
        $('portalContent').innerHTML = card('Guide Profile', `
            <p class="text-muted">Your guide details were captured at registration and reviewed by the Main Admin. They are shown read-only here.</p>
            <div class="detail-list">
                ${infoRow('Name', user.name)}
                ${infoRow('Experience (years)', regVal('Experience (years)') || p.experience)}
                ${infoRow('Languages', regVal('Languages spoken') ? regList('Languages spoken').join(', ') : ((p.languages || []).join(', ') || ''))}
                ${infoRow('Specialty', regVal('Specialty') || p.specialty)}
                ${infoRow('Charges per hour', regVal('Charges per hour (\u20b9)') ? money(parseFloat(regVal('Charges per hour (\u20b9)')) || 0) : (p.pricePerHour ? money(p.pricePerHour) : ''))}
                ${infoRow('Charges per day', regVal('Charges per day (\u20b9)') ? money(parseFloat(regVal('Charges per day (\u20b9)')) || 0) : (p.pricePerDay ? money(p.pricePerDay) : ''))}
                ${infoRow('Base location', regVal('Base location') || p.location || '')}
                ${infoRow('About me', regVal('About me') || p.description)}
                ${infoRow('Availability status', p.status || 'ACTIVE')}
                ${infoRow('Weekly working hours', wkHoursText())}
                ${infoRow('Business location', loc.lat && loc.lng ? `${loc.address || ''} \u00b7 ${loc.lat}, ${loc.lng}` : loc.address)}
            </div>
            <div class="flex gap mt-4">
                <button class="btn btn-outline" onclick="showPanel('gavail')">Availability</button>
                <button class="btn btn-outline" onclick="showPanel('gassign')">Assignments</button>
            </div>`);
    }

    function guidePricing() {
        $('portalContent').innerHTML = card('Guide Pricing', `
            <div class="form-row">
                ${field('Price per hour (\u20b9)', 'g_ph', num('g_ph', 'placeholder="500"'))}
                ${field('Price per day (\u20b9)', 'g_pd', num('g_pd', 'placeholder="3000"'))}
            </div>
            <button class="btn btn-primary mt-2" onclick="TM.saveGPricing()">Save Pricing</button>`);
        window.TM.saveGPricing = () => run(async () => {
            await api.guidePricing({ pricePerHour: +$('g_ph').value, pricePerDay: +$('g_pd').value });
            toast('Pricing saved.');
        });
    }

    async function guideAvailability() {
        const prof = await api.getGuideProfile();
        const weeks = (prof.availability || []).slice().sort((a, b) => (a.weekStart || '').localeCompare(b.weekStart || ''));

        const today = new Date();
        const monday = new Date(today);
        const sinceMonday = (today.getDay() + 6) % 7;
        monday.setDate(today.getDate() - sinceMonday);
        const toIso = d => { const x = new Date(d); x.setMinutes(x.getMinutes() - x.getTimezoneOffset()); return x.toISOString().slice(0, 10); };
        const defaultWeek = toIso(monday);
        const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

        const dayRows = Array.from({ length: 7 }, (_, i) => {
            const d = new Date(monday); d.setDate(monday.getDate() + i);
            const ds = toIso(d);
            return `<div class="ga-day" style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;padding:.3rem 0;">
                <label style="min-width:110px;"><input type="checkbox" class="ga_on" value="${ds}"> ${dayNames[d.getDay()]} (${ds})</label>
                <input class="form-input" placeholder="From" value="09:00" style="flex:0 0 90px;">
                <input class="form-input" placeholder="To" value="17:00" style="flex:0 0 90px;">
            </div>`;
        }).join('');

        const weeksHtml = weeks.length ? `<table class="row-table" style="width:100%">
            <tr><th>Week</th><th>Range</th><th>Days</th><th>Status</th></tr>` +
            weeks.map(w => `<tr><td>${esc(w.weekId || '')}</td>
                <td>${esc(w.weekStart || '')} \u2192 ${esc(w.weekEnd || '')}</td>
                <td>${(w.days || []).length}</td>
                <td><span class="pill ok">LOCKED</span></td></tr>`).join('') + '</table>'
            : '<p class="text-muted">No availability submitted yet.</p>';

        $('portalContent').innerHTML = card('Mark Weekly Availability', `
            <p class="text-muted" style="font-size:.85rem;margin-bottom:.5rem;">
                Availability is submitted per week and <b>locked</b> after submission. Pick the week starting on a <b>Monday</b> \u2014 past weeks are disabled.</p>
            <div class="form-row">
                ${field('Week starting (Monday)', 'g_week', `<input id="g_week" type="date" class="form-input" value="${defaultWeek}" min="${defaultWeek}" onchange="TM.onGalWeek(this.value)">`)}
            </div>
            ${dayRows}
            ${field('Service area (city)', 'g_city', `<input id="g_city" class="form-input" value="${esc((prof.profile || {}).city || '')}" placeholder="e.g. Chennai"><div class="hint">The city from your registration is used to match passenger requests. Days you mark available become directly bookable \u2014 there is no spot-level authorization.</div>`)}
            <button class="btn btn-primary mt-2" onclick="TM.saveGAvail()">Submit & Lock Week</button>
            <hr class="my-4">
            <div class="card-title" style="margin-bottom:.75rem;">Submitted Weeks</div>
            ${weeksHtml}`);

        window.TM.onGalWeek = (val) => {
            if (val && val < defaultWeek) { $('g_week').value = defaultWeek; toast('Past weeks cannot be selected.', true); }
        };
        const mondayOfWeek = (iso) => {
            const d = new Date(iso + 'T00:00:00');
            return d.getDay() === 1 ? iso : null;
        };
        $('g_week').addEventListener('change', () => {
            const val = $('g_week').value;
            if (val && !mondayOfWeek(val)) { toast('Week start must be a Monday.', true); $('g_week').value = defaultWeek; }
        });

        window.TM.saveGAvail = () => run(async () => {
            const weekStart = $('g_week').value;
            const city = ($('g_city').value || '').trim() || (prof.profile || {}).city || '';
            if (!city) { toast('Add your service area (city).', true); return; }
            const locations = [city];
            const days = [...document.querySelectorAll('.ga_on:checked')].map(cb => {
                const row = cb.closest('.ga-day');
                const inputs = [...row.querySelectorAll('input[type=text], input:not([type=checkbox]).form-input')];
                return { date: cb.value, from: inputs[0].value, to: inputs[1].value, locations };
            });
            if (!days.length) { toast('Enable at least one day of the week.', true); return; }
            try {
                await api.guideAvailability({ weekStart, days });
                toast('Availability submitted. The week is now locked.');
                guideAvailability();
            } catch (err) {
                toast(err.message, true);
            }
        });
    }

    /* ---------------- HOTEL ADMIN ---------------- */

    const STANDARD_AMENITIES = ['Wi-Fi', 'Parking', 'Restaurant', 'Room Service', 'AC', 'TV', 'Breakfast', 'Swimming Pool', 'Gym', 'Laundry', '24/7 Front Desk'];

    function roomTypeRow() {
        return `<div class="rt-row" style="display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.5rem;">
            <input class="form-input" placeholder="Name" style="flex:1 1 120px;">
            <input class="form-input" placeholder="Category" style="flex:0 0 110px;">
            <input class="form-input" type="number" placeholder="Rooms" style="flex:0 0 80px;">
            <input class="form-input" type="number" placeholder="Price \u20b9" style="flex:0 0 90px;">
            <input class="form-input" placeholder="Room numbers (comma separated)" style="flex:1 1 200px;">
            <select class="form-select" style="flex:0 0 80px;"><option value="true">AC</option><option value="false">Non-AC</option></select>
            <select class="form-select" style="flex:0 0 120px;">${['Single Bed', 'Double Bed', 'Twin Bed', 'King Bed', 'Queen Bed', 'Multiple Beds', 'Other'].map(b => `<option>${b}</option>`).join('')}</select>
            <input class="form-input" type="number" placeholder="Beds" value="1" style="flex:0 0 60px;">
            <input class="form-input" type="number" placeholder="Max occ" value="2" style="flex:0 0 70px;">
        </div>`;
    }

    function hotelProfile() {
        const loc = bizLoc();
        $('portalContent').innerHTML = card('Hotel Profile', `
            <p class="text-muted">Your property details were captured at registration and reviewed by the Main Admin. They are shown read-only here.</p>
            <div class="detail-list">
                ${infoRow('Hotel name', regVal('Hotel name'))}
                ${infoRow('Category', regVal('Hotel category'))}
                ${infoRow('Star rating', regVal('Star rating'))}
                ${infoRow('City', regVal('City'))}
                ${infoRow('Address', regVal('Address'))}
                ${infoRow('Contact number', regVal('Contact number'))}
                ${infoRow('Contact email', regVal('Contact email'))}
                ${infoRow('Check-in time', regVal('Check-in time (24h)'))}
                ${infoRow('Check-out time', regVal('Check-out time (24h)'))}
                ${infoRow('Total rooms', regVal('Total number of rooms'))}
                ${infoRow('GST number', user.gst)}
                ${infoRow('Weekly working hours', wkHoursText())}
                ${infoRow('Business location', loc.lat && loc.lng ? `${loc.address || ''} \u00b7 ${loc.lat}, ${loc.lng}` : loc.address)}
            </div>
            <div class="flex gap mt-4">
                <button class="btn btn-outline" onclick="showPanel('hinv')">Room Inventory</button>
                <button class="btn btn-outline" onclick="showPanel('hbook')">Hotel Bookings</button>
            </div>`);
    }

    function roomCardsHtml(h) {
        const all = (h.roomTypes || []).map(rt =>
            (rt.roomNumbers || []).map(num => `
                <div class="card room-card">
                    <div class="card-content">
                        <div class="flex justify-between" style="align-items:center;gap:.5rem;">
                            <b>Room ${esc(String(num))}</b>
                            <span class="pill info">${esc(rt.category || rt.name || 'Room')}</span>
                        </div>
                        <div class="text-muted" style="font-size:.8rem;">${esc(rt.bedType || '\u2014')} \u00b7 ${money(rt.pricePerNight)}/night</div>
                        <div class="text-muted" style="font-size:.8rem;">${rt.maxOccupancy || rt.numberOfBeds || 1} guest(s)</div>
                    </div>
                </div>`).join('')).join('');
        return all ? `<div class="room-grid">${all}</div>` : '';
    }

    async function hotelInventory() {
        const hs = await api.getMyHotels();
        const hotels = hs.hotels || [];
        if (!hotels.length) {
            $('portalContent').innerHTML = card('Room Inventory', `
                <p class="text-muted">Your hotel is declared at registration. Set a default nightly rate to publish your room inventory (room numbers are generated automatically).</p>
                <div class="form-row">
                    ${field('Default room price (\u20b9/night)', 'hi_price', num('hi_price', 'value="1500"'))}
                    ${field('Bed type', 'hi_bed', `<select id="hi_bed" class="form-select">
                        ${['Single Bed', 'Double Bed', 'Twin Bed', 'King Bed', 'Queen Bed', 'Multiple Beds'].map(b => `<option>${b}</option>`).join('')}</select>`)}
                </div>
                <button class="btn btn-primary" onclick="TM.initHotel()">Publish Room Inventory</button>
                <div id="hi_err" class="mt-2"></div>`);
            window.TM.initHotel = () => run(async () => {
                const err = $('hi_err');
                err.textContent = '';
                const price = +$('hi_price').value || 0;
                if (!(price > 0)) { err.textContent = 'Enter a valid nightly price.'; return; }
                const total = parseInt(regVal('Total number of rooms') || '1', 10) || 1;
                const roomNumbers = Array.from({ length: total }, (_, i) => String(101 + i));
                await api.createHotel({
                    name: regVal('Hotel name') || user.name,
                    category: regVal('Hotel category') || 'Other',
                    starRating: parseInt(regVal('Star rating') || '3', 10),
                    city: regVal('City') || 'Chennai',
                    state: '', country: 'India',
                    address: regVal('Address') || regVal('Location Address') || '',
                    contactNumber: regVal('Contact number') || user.mobile,
                    email: regVal('Contact email'),
                    checkInTime: regVal('Check-in time (24h)') || '12:00',
                    checkOutTime: regVal('Check-out time (24h)') || '11:00',
                    lat: regVal('Latitude') || null, lng: regVal('Longitude') || null,
                    amenities: [],
                    totalRooms: total,
                    roomTypes: [{ name: regVal('Hotel category') || 'Room', category: regVal('Hotel category') || '',
                        totalRooms: total, pricePerNight: price, ac: true,
                        bedType: $('hi_bed').value, numberOfBeds: 1, maxOccupancy: 2,
                        roomNumbers }],
                    description: '',
                });
                toast('Room inventory published.');
                hotelInventory();
            });
            return;
        }
        const h = hotels[0];
        const blockEditor = (rt) => `<input onchange="TM.blockRt('${h.id}', '${rt.id}', this.value)"
            value="${rt.blockedRooms}" class="form-input" type="number" min="0" style="width:70px;">`;
        window.__hotelForBookings = h;
        $('portalContent').innerHTML = card(`${h.name} \u00b7 Room Inventory`, `
            <div class="stats-grid mb-4">
                <div class="stat-card"><div class="stat-label">Total rooms</div><div class="stat-value">${h.totalRooms}</div></div>
                <div class="stat-card"><div class="stat-label">Booked</div><div class="stat-value">${h.bookedRooms || 0}</div></div>
                <div class="stat-card"><div class="stat-label">Blocked</div><div class="stat-value">${h.blockedRooms || 0}</div></div>
                <div class="stat-card"><div class="stat-label">Available</div><div class="stat-value">${h.availableRooms || 0}</div></div>
            </div>
            <div class="table-scroll"><table class="row-table" style="width:100%">
                <tr><th>Room type</th><th>Total</th><th>Booked</th><th>Blocked</th><th>Available</th><th>Occupancy</th><th>Price</th><th>Room numbers</th></tr>` +
            (h.roomTypes || []).map(r => `<tr>
                <td>${esc(r.name)}</td><td>${r.totalRooms}</td><td>${r.bookedRooms}</td>
                <td>${blockEditor(r)}</td>
                <td><b>${r.availableRooms}</b></td>
                <td>${Math.round(100 * r.bookedRooms / Math.max(1, r.totalRooms))}%</td>
                <td>${money(r.pricePerNight)}/night</td>
                <td style="max-width:180px;word-break:break-word;">${esc((r.roomNumbers || []).join(', '))}</td></tr>`).join('') + '</table></div>' +
            `<div class="hr-label">Rooms (one card per room)</div>` +
            (roomCardsHtml(h) || '<p class="text-muted">No room numbers created yet.</p>') +
            `<div class="hr-label">Add Room</div>
            <div class="form-row">
                ${field('Room number', 'ar_num', input('ar_num', 'placeholder="e.g. 205"'))}
                ${field('Category', 'ar_cat', `<select id="ar_cat" class="form-select">
                    ${['Budget', 'Mid-Range', 'Luxury', 'Boutique', 'Resort', 'Other'].map(c => `<option>${c}</option>`).join('')}</select>`)}
                ${field('Bed type', 'ar_bed', `<select id="ar_bed" class="form-select">
                    ${['Single Bed', 'Double Bed', 'Twin Bed', 'King Bed', 'Queen Bed', 'Multiple Beds'].map(b => `<option>${b}</option>`).join('')}</select>`)}
                ${field('AC', 'ar_ac', `<select id="ar_ac" class="form-select"><option value="true">AC</option><option value="false">Non-AC</option></select>`)}
                ${field('Price (\u20b9/night)', 'ar_price', num('ar_price', 'value="1500"'))}
                ${field('Max guests', 'ar_occ', num('ar_occ', 'value="2"'))}
            </div>
            <button class="btn btn-primary" onclick="TM.addRoom()">Add Room</button>
            <div id="ar_err" class="mt-2"></div>`);
        window.TM.blockRt = (hid, rtid, v) => run(async () => {
            await api.blockRooms(hid, rtid, +v || 0);
            toast('Room availability updated.');
            hotelInventory();
        });
        window.TM.addRoom = () => run(async () => {
            const err = $('ar_err');
            err.textContent = '';
            const num = $('ar_num').value.trim();
            if (!num) { err.textContent = 'Room number is required.'; return; }
            await api.addHotelRoom(window.__hotelForBookings.id, {
                roomNumber: num, category: $('ar_cat').value, bedType: $('ar_bed').value,
                ac: $('ar_ac').value === 'true', pricePerNight: +$('ar_price').value || 0,
                maxOccupancy: +$('ar_occ').value || 2, numberOfBeds: 1,
            });
            toast('Room added.');
            hotelInventory();
        });
    }

    async function hotelBookings() {
        const [hb, hs] = await Promise.all([
            api.getHotelBookings().catch(() => ({ bookings: [] })),
            api.getMyHotels().catch(() => ({ hotels: [] })),
        ]);
        const hotelName = (id) => {
            const h = (hs.hotels || []).find(x => x.id === id);
            return h ? h.name : (id ? id.slice(0, 13) + '\u2026' : '\u2014');
        };
        const all = hb.bookings || [];
        const today = new Date().toISOString().slice(0, 10);
        const upcoming = all.filter(x => x.status !== 'CANCELLED' && x.status !== 'REJECTED'
            && ((x.details || {}).checkin || x.date || '') >= today);
        const completed = all.filter(x => x.status === 'COMPLETED' || (x.status === 'CANCELLED')
            || ((x.details || {}).checkin || x.date || '') < today);
        const rowHtml = (x) => `<tr>
            <td>${esc(x.reference)}</td>
            <td>${esc(hotelName(x.hotelId))}</td>
            <td>${x.qty} room(s)</td>
            <td>${esc((x.details || {}).checkin || '')}</td>
            <td>${esc((x.details || {}).checkout || '')}</td>
            <td>${esc((x.details || {}).guests || x.qty)}</td>
            <td>${money(x.total)}</td>
            <td><span class="pill ${x.status === 'CONFIRMED' ? 'good' : x.status === 'COMPLETED' ? 'ok' : x.status === 'CANCELLED' || x.status === 'REJECTED' ? 'bad' : 'info'}">${esc(x.status)}</span></td></tr>`;
        const table = (rows) => `<table class="row-table" style="width:100%">
            <tr><th>Ref</th><th>Hotel</th><th>Rooms</th><th>Check-in</th><th>Check-out</th><th>Guests</th><th>Total</th><th>Status</th></tr>
            ${rows.length ? rows.map(rowHtml).join('') : '<tr><td colspan="8" class="text-muted">No bookings here.</td></tr>'}</table>`;
        $('portalContent').innerHTML = card('Hotel Bookings', `
            <div class="stats-grid mb-4">
                <div class="stat-card"><div class="stat-label">Upcoming</div><div class="stat-value">${upcoming.length}</div></div>
                <div class="stat-card"><div class="stat-label">Completed</div><div class="stat-value">${completed.length}</div></div>
                <div class="stat-card"><div class="stat-label">Total stay-guest nights</div><div class="stat-value">${all.reduce((s, x) => s + (x.qty || 0) * ((x.details || {}).nights || 1), 0)}</div></div>
            </div>
            <div class="flex" style="gap:.5rem;margin-bottom:1rem;">
                <button class="btn btn-primary btn-sm" onclick="TM.hbookTab('up')">Upcoming</button>
                <button class="btn btn-outline btn-sm" onclick="TM.hbookTab('done')">Completed</button>
            </div>
            <div id="hbook_body">${table(upcoming)}</div>`);
        window.TM.hbookTab = (which) => {
            $('hbook_body').innerHTML = which === 'done' ? table(completed) : table(upcoming);
        };
    }

    /* ---------------- RESTAURANT ADMIN ---------------- */

    function fileToDataUrl(file) {
        return new Promise((resolve, reject) => {
            if (!file) return resolve('');
            const r = new FileReader();
            r.onload = () => resolve(r.result);
            r.onerror = reject;
            r.readAsDataURL(file);
        });
    }

    async function restaurantList() {
        const mine = (await api.getMyRestaurants()).restaurants || [];
        $('portalContent').innerHTML = card('My Restaurants', mine.length ?
            mine.map(r => `<div class="card mb-4"><div class="card-header"><div class="card-title">${esc(r.name)} <span class="role-badge">${esc(r.restaurantType || 'Restaurant')}</span></div>
            <div><a class="btn btn-outline btn-sm" onclick="TM.editRest('${r.id}')">Edit</a>
                 <a class="btn btn-primary btn-sm" onclick="TM.pickRest('${r.id}')">Food Items</a></div></div>
            <div class="card-content">
                <div class="text-sm" style="opacity:.85;">${esc(r.city || '')}${r.address ? ' \u00b7 ' + esc(r.address) : ''}</div>
                <div class="text-sm mt-2">${esc((r.cuisines || []).join(', '))}</div>
                <div class="text-sm mt-2"><span class="pill ok">${esc(r.status)}</span></div>
            </div></div>`).join('')
            : '<p class="text-muted">No restaurant created yet \u2014 start in <a onclick="TM.newRest()">Restaurant Profile</a>.</p>');
    }

    async function restaurantForm() {
        let r = null;
        try { const mine = (await api.getMyRestaurants()).restaurants || []; r = mine[0] || null; } catch (e) { r = null; }
        const loc = bizLoc();
        const regHours = wkHoursText();
        $('portalContent').innerHTML = card('Restaurant Profile', `
            <p class="text-muted">Your restaurant details were captured at registration and reviewed by the Main Admin. They are shown read-only here.</p>
            <div class="detail-list">
                ${infoRow('Restaurant name', regVal('Restaurant name') || (r ? r.name : ''))}
                ${infoRow('Restaurant type', regVal('Restaurant type') || (r ? r.restaurantType : ''))}
                ${infoRow('City', regVal('City') || (r ? r.city : ''))}
                ${infoRow('Address', regVal('Address') || (r ? r.address : ''))}
                ${infoRow('Contact number', regVal('Contact number') || (r ? r.contactNumber : ''))}
                ${infoRow('Contact email', regVal('Contact email') || (r ? r.email : ''))}
                ${infoRow('Cuisines', (regVal('Cuisines') || '').trim() || (r ? (r.cuisines || []).join(', ') : ''))}
                ${infoRow('GST number', user.gst)}
                ${infoRow('Weekly working hours', regHours)}
                ${infoRow('Business location', loc.lat && loc.lng ? `${loc.address || ''} \u00b7 ${loc.lat}, ${loc.lng}` : loc.address)}
                ${r ? infoRow('Publishing status', r.status) : ''}
            </div>
            <div class="flex gap mt-4">
                <button class="btn btn-outline" onclick="showPanel('rfood')">Food Items</button>
            </div>`);
        window.TM.newRest = () => { window.__restEditId = null; showPanel('restform'); };
        window.TM.pickRest = (id) => { window.__foodRestaurant = id; showPanel('rfood'); };
        window.TM.editRest = () => showPanel('restform');
    }

    /* Restaurant orders: food bookings placed on this restaurant's catalogue. */
    async function restaurantOrdersPanel() {
        const rows = await api.providerBookings('RESTAURANT').catch(() => []);
        const paid = rows.filter(b => b.paymentStatus === 'WALLET' || b.paymentStatus === 'COMPLETED');
        const pending = rows.filter(b => b.paymentStatus === 'PENDING' && b.status !== 'CANCELLED');
        const cancelled = rows.filter(b => b.status === 'CANCELLED' || b.status === 'REJECTED');
        const table = rows.length ? `<table class="row-table" style="width:100%">
            <tr><th>Reference</th><th>Customer</th><th>Item</th><th>Qty</th><th>Date</th><th>Total</th><th>Payment</th><th>Status</th></tr>` +
            rows.map(b => `<tr>
                <td>${esc(b.reference)}</td>
                <td>${esc((b.customer || {}).name || '\u2014')}</td>
                <td>${esc(b.foodName || '\u2014')}</td>
                <td>${b.qty}</td>
                <td>${esc(b.date || '\u2014')}</td>
                <td>${money(b.total)}</td>
                <td><span class="pill ${b.paymentStatus === 'WALLET' || b.paymentStatus === 'COMPLETED' ? 'good' : b.paymentStatus === 'PENDING' ? 'warn' : 'info'}">${esc(b.paymentStatus || '\u2014')}</span></td>
                <td>${esc(b.status)}</td>
            </tr>`).join('') + '</table>'
            : '<p class="text-muted">No orders yet. Orders open up as travellers book food items from your restaurant.</p>';
        $('portalContent').innerHTML = card('Restaurant Orders', `
            <div class="stats-grid mb-4">
                <div class="stat-card"><div class="stat-value">${rows.length}</div><div class="stat-label">Total orders</div></div>
                <div class="stat-card"><div class="stat-value">${pending.length}</div><div class="stat-label">Unpaid</div></div>
                <div class="stat-card"><div class="stat-value">${paid.length}</div><div class="stat-label">Paid</div></div>
                <div class="stat-card"><div class="stat-value">${cancelled.length}</div><div class="stat-label">Cancelled</div></div>
            </div>
            <div class="table-scroll">${table}</div>`);
    }

    async function foodItemsPanel() {
        const mine = (await api.getMyRestaurants()).restaurants || [];
        let rid = window.__foodRestaurant || (mine.length ? mine[0].id : null);
        if (!mine.some(r => r.id === rid)) rid = mine.length ? mine[0].id : null;
        window.__foodRestaurant = rid;

        let foodHtml = '<p class="text-muted">Select a restaurant to manage its food items.</p>';
        if (rid) {
            const items = await api.getFoodItems(rid);
            const avail = items.filter(f => f.available !== false).length;
            const cats = [...new Set(items.map(f => f.category).filter(Boolean))];
            foodHtml = `<div class="stats-grid mb-4">
                    <div class="stat-card"><div class="stat-value">${items.length}</div><div class="stat-label">Food items</div></div>
                    <div class="stat-card"><div class="stat-value">${avail}</div><div class="stat-label">Available now</div></div>
                    <div class="stat-card"><div class="stat-value">${cats.length}</div><div class="stat-label">Categories</div></div>
                </div>` + (items.length ? items.map(f => `
                <div class="card mb-4"><div class="card-content">
                    <div class="flex items-center gap-2">
                        ${f.image && f.image.startsWith('data:') ? `<img src="${f.image}" alt="" style="width:56px;height:56px;border-radius:.5rem;object-fit:cover;">` : ''}
                        <div>
                            <div class="font-bold">${esc(f.name)}</div>
                            <div class="text-xs text-muted">${esc(f.category)} \u00b7 ${esc(f.description || '')} \u00b7 ${f.prepTimeMinutes} min</div>
                        </div>
                    </div>
                    <div class="flex justify-between items-center mt-2">
                        <b>${money(f.price)}</b>
                        <div class="flex gap-2">
                            <button class="btn btn-outline btn-sm" onclick="TM.toggleFood('${f.id}', '${f.available ? 'false' : 'true'}')">${f.available ? 'Mark unavailable' : 'Mark available'}</button>
                            <button class="btn btn-outline btn-sm" onclick="TM.removeFood('${f.id}')">Remove</button>
                        </div>
                    </div>
                </div></div>`).join('') : '<p class="text-muted">No food items yet \u2014 add one below.</p>');
        }

        $('portalContent').innerHTML = card('Food Items', `
            ${mine.length > 1 ? `
            <div class="form-group">
                <label class="form-label">Restaurant</label>
                <select id="food_rest" class="form-select" onchange="TM.switchRest(this.value)">
                    ${mine.map(r => `<option value="${r.id}" ${r.id === rid ? 'selected' : ''}>${esc(r.name)}</option>`).join('')}
                </select>
            </div>` : ''}
            ${foodHtml}
            <hr class="my-4">
            ${rid ? `
            <div class="card-title" style="margin-bottom:.75rem;">Add Food Item</div>
            <div class="form-row">
                ${field('Name', 'fd_name', input('fd_name', 'placeholder="Chicken Biryani"'))}
                ${field('Price (\u20b9)', 'fd_price', num('fd_price', 'step="0.5"'))}
                ${field('Category', 'fd_cat', select('VEG', [{ v: 'VEG', l: 'Veg' }, { v: 'NON_VEG', l: 'Non-Veg' }, { v: 'VEGAN', l: 'Vegan' }, { v: 'BEVERAGE', l: 'Beverage' }, { v: 'DESSERT', l: 'Dessert' }, { v: 'OTHER', l: 'Other' }]))}
                ${field('Prep time (min)', 'fd_prep', num('fd_prep', 'value="15"'))}
            </div>
            ${field('Food image *', 'fd_img', '<input id="fd_img" type="file" class="form-input" accept=".jpg,.jpeg,.png">')}
            ${field('Description', 'fd_desc', `<textarea id="fd_desc" class="form-textarea" rows="2"></textarea>`)}
            <button class="btn btn-primary mt-2" onclick="TM.submitFood()">Add Food Item</button>
            <div id="fd_err" class="mt-2"></div>` : ''}`);
        window.TM.switchRest = (v) => { window.__foodRestaurant = v; foodItemsPanel(); };
        window.TM.submitFood = () => run(async () => {
            const err = $('fd_err');
            err.textContent = '';
            const file = $('fd_img').files[0];
            if (!file) { err.innerHTML = 'A food image is required.'; return; }
            const image = await fileToDataUrl(file);
            await api.createFoodItem(rid, {
                name: $('fd_name').value.trim(), price: +$('fd_price').value,
                category: $('fd_cat').value, prepTimeMinutes: +$('fd_prep').value || 0,
                description: $('fd_desc').value.trim(), image,
            });
            toast('Food item added.');
            foodItemsPanel();
        });
        window.TM.toggleFood = (fid, available) => run(async () => {
            await api.updateFoodItem(rid, fid, { available: available === 'true' });
            toast('Updated.');
            foodItemsPanel();
        });
        window.TM.removeFood = (fid) => run(async () => {
            await api.deleteFoodItem(rid, fid);
            toast('Food item removed.');
            foodItemsPanel();
        });
    }

    /* ---------------- TOURIST ADMIN: TOURS ---------------- */

    async function touristTours() {
        const spots = (await api.getSpots()).spots || [];
        const tours = (await api.getTours()).tours || [];
        $('portalContent').innerHTML =
            card('Add a Tour / Experience', `
                <div class="form-row">
                    ${field('Spot', 'tt_spot', `<select id="tt_spot" class="form-select">
                        ${spots.map(s => `<option value="${s._id}">${esc(s.name)} (${esc(s.city)})</option>`).join('')}</select>`)}
                    ${field('Tour name', 'tt_name', input('tt_name', 'placeholder="Mahabalipuram Heritage Tour"'))}
                    ${field('Duration (hrs)', 'tt_dur', num('tt_dur', 'value="3"'))}
                    ${field('Cost (\u20b9/person)', 'tt_cost', num('tt_cost', 'value="1500"'))}
                    ${field('Max participants', 'tt_max', num('tt_max', 'value="20"'))}
                    ${field('Guide required', 'tt_req', `<select id="tt_req" class="form-select">
                        <option value="true">Yes</option><option value="false">No</option></select>`)}
                    ${field('Available times (from \u2192 to)', 'tt_f', input('tt_f', 'value="10:00"'))}
                    ${field('', 'tt_t', input('tt_t', 'value="13:00"'))}
                </div>
                ${field('Included services (comma separated)', 'tt_inc', input('tt_inc', 'placeholder="Entry ticket, Heritage guide"'))}
                ${field('Description', 'tt_desc', `<textarea id="tt_desc" class="form-textarea" placeholder="What does the tour include?"></textarea>`)}
                <button class="btn btn-primary" onclick="TM.submitTour()">Publish Tour</button>`) +
            card('My Tours',
                tours.length ? `<table class="row-table" style="width:100%">
                    <tr><th>Tour</th><th>Hrs</th><th>Cost</th><th>Capacity</th><th>Included</th><th>Status</th></tr>` +
                tours.map(t => `<tr><td>${esc(t.name)}</td><td>${t.duration}</td><td>${money(t.cost)}</td>
                    <td>${t.bookedParticipants || 0}/${t.maxParticipants}</td>
                    <td>${esc((t.includedServices || []).join(', '))}</td>
                    <td><span class="pill ${t.status === 'APPROVED' ? 'ok' : 'warn'}">${esc(t.status)}</span></td></tr>`).join('') + '</table>'
                : '<p class="text-muted">No tours yet.</p>');
        window.TM.submitTour = () => run(async () => {
            await api.createTour({
                spotId: $('tt_spot').value, name: $('tt_name').value.trim(),
                duration: +$('tt_dur').value, cost: +$('tt_cost').value,
                maxParticipants: +$('tt_max').value, guideRequired: $('tt_req').value === 'true',
                availableTimes: [{ from: $('tt_f').value, to: $('tt_t').value, note: '' }],
                includedServices: $('tt_inc').value.split(',').map(s => s.trim()).filter(Boolean),
                description: $('tt_desc').value.trim(),
            });
            toast('Tour published.');
            showPanel('tourform');
        });
    }

    /* ---------------- GUIDE: REQUESTS & ASSIGNMENTS ---------------- */

    async function guideRequests() {
        const r = await api.guideRequests();
        const reqs = r.requests || [];
        $('portalContent').innerHTML = card('Incoming Tour Requests',
            reqs.length ? reqs.map(x => `
                <div class="card mb-4" style="background:var(--slate-50);">
                    <div class="card-content">
                        <div><b>${esc(x.date)}</b> \u00b7
                            <span class="text-muted">${esc((x.details || {}).startTime || 'full day')} \u2192 ${esc((x.details || {}).endTime || '')}</span></div>
                        <p class="text-muted">Ref ${esc(x.reference)} \u00b7 ${x.qty} guest(s)</p>
                        <div class="flex gap">
                            <button class="btn btn-success btn-sm" onclick="TM.respond('${x._id}', 'ACCEPT')">Accept</button>
                            <button class="btn btn-outline btn-sm" onclick="TM.respond('${x._id}', 'REJECT')">Decline</button>
                        </div>
                    </div>
                </div>`).join('')
            : '<p class="text-muted">No pending requests.</p>');
        window.TM.respond = (id, action) => confirmDialog(action === 'ACCEPT' ? 'Accept request' : 'Decline request',
            action === 'ACCEPT' ? 'Confirm this guiding assignment?' : 'This will decline the guest request.',
            () => run(async () => {
                await api.guideRespond(id, action);
                toast(action === 'ACCEPT' ? 'Assignment confirmed.' : 'Request declined.');
                guideRequests();
            }), action === 'ACCEPT' ? 'Accept' : 'Decline');
    }

    async function guideAssignments() {
        const a = await api.guideAssignments();
        const up = a.upcoming || [], done = a.completed || [];
        const rows = (list) => list.length ? list.map(x => `<tr>
            <td>${esc(x.date)}</td><td>${esc(x.reference)}</td>
            <td>${esc((x.details || {}).location || '')}</td><td>${esc((x.details || {}).startTime || '')} \u2192 ${esc((x.details || {}).endTime || '')}</td>
            <td>${money(x.total)}</td></tr>`).join('') : '<tr><td colspan="5" class="text-muted">None.</td></tr>';
        $('portalContent').innerHTML =
            card('Upcoming Assignments', `<table class="row-table" style="width:100%"><tr><th>Date</th><th>Ref</th><th>Location</th><th>Slot</th><th>Fee</th></tr>${rows(up)}</table>`) +
            card('Completed Assignments', `<table class="row-table" style="width:100%"><tr><th>Date</th><th>Ref</th><th>Location</th><th>Slot</th><th>Fee</th></tr>${rows(done)}</table>`);
    }

    /* ---------------- ADMIN ---------------- */

    async function providerStatsPanel() {
        const s = await api.providerStats();
        const quick = (label, id) => `<a class="btn btn-outline btn-sm" onclick="showPanel('${id}')">${esc(label)}</a>`;
        let rows, actions = [];
        if (s.role === 'TRANSPORT_ADMIN') {
            rows = [
                ['Vehicles', s.fleet], ['Approved', s.approvedFleet], ['Pending review', s.pendingFleet],
                ['Fleet capacity', s.fleetCapacity], ['Seats sold', s.seatsBooked],
                ['Bookings', s.bookings], ['Confirmed', s.confirmedBookings],
                ['Upcoming passengers', s.upcomingBookings], ['Completed trips', s.completedTrips],
                ['Revenue', money(s.revenue)],
            ];
            actions = [quick('Fleet snapshots', 'register'), quick('Upcoming passengers', 'fleet')];
        } else if (s.role === 'GUIDE') {
            rows = [
                ['Assignments', s.assignments], ['Completed assignments', s.completed],
                ['Pending requests', s.pendingRequests], ['Upcoming', s.upcoming],
                ['Available days', s.availableDays], ['Rate (\u20b9/hr)', money(s.pricingPerHour)],
                ['Earnings', money(s.earnings)],
            ];
            actions = [quick('My availability', 'gavail'), quick('Requests', 'greq'), quick('Assignments', 'gassign')];
        } else if (s.role === 'RAILWAY_ADMIN') {
            rows = [
                ['Trains', s.fleet], ['Approved', s.approvedFleet], ['Pending review', s.pendingFleet],
                ['Seats sold', s.seatsBooked],
                ['Bookings', s.bookings], ['Confirmed', s.confirmedBookings],
                ['Upcoming passengers', s.upcomingBookings], ['Completed trips', s.completedTrips],
                ['Revenue', money(s.revenue)],
            ];
            actions = [quick('Manage trains', 'register'), quick('Railway lounges', 'rlounges'), quick('Passenger bookings', 'fleet')];
        } else if (s.role === 'HOTEL_ADMIN') {
            rows = [
                ['Hotels', s.hotels], ['Approved', s.approvedHotels], ['Pending review', s.pendingHotels],
                ['Rooms', s.totalRooms], ['Occupied rooms', s.roomsOccupied], ['Occupancy', s.occupancyPct + '%'],
                ['Bookings', s.bookings], ['Confirmed', s.confirmedBookings], ['Revenue', money(s.revenue)],
            ];
            actions = [quick('Room inventory', 'hinv'), quick('Hotel bookings', 'hbook'), quick('Profile', 'hotel')];
        } else if (s.role === 'RESTAURANT_ADMIN') {
            rows = [
                ['Restaurants', s.restaurants], ['Approved', s.approvedRestaurants],
                ['Pending review', s.pendingRestaurants], ['Food items', s.foodItems],
                ['Available food', s.availableItems], ['Seat bookings', s.bookings],
                ['Food orders', s.orders], ['Confirmed orders', s.confirmedOrders],
                ['Revenue', money(s.revenue)],
            ];
            actions = [quick('Food items', 'rfood'), quick('Restaurant profile', 'restform')];
        } else {
            rows = [
                ['My bookings', s.bookings], ['Planned trips', s.plannedTrips],
                ['Booked trips', s.bookedTrips], ['Completed trips', s.completedTrips],
                ['Total spent', money(s.spent)],
            ];
            actions = [quick('Plan my trip', 'plantrip'), quick('My bookings', 'book')];
        }
        const cards = rows.map(([l, v]) =>
            `<div class="stat-card"><div class="stat-value">${v}</div><div class="stat-label">${esc(l)}</div></div>`).join('');
        $('portalContent').innerHTML = card('My Dashboard (live from the database)',
            `<div class="stats-grid">${cards}</div>
             <div class="flex gap mt-4">${actions.join('')}</div>
             <p class="text-muted" style="font-size:.85rem;margin-top:1rem;">Every number is computed from your own catalogue and bookings \u2014 no mocked values.</p>`);
    }

    function tripsChartHtml(s) {
        const series = s.tripsCompletedByMonth || {};
        const months = Object.keys(series).sort();
        if (!months.length) return emptyState('No completed trips yet', 'Completed passenger trips will appear here.');
        const max = Math.max(1, ...Object.values(series));
        const cols = months.map(m => {
            const v = series[m];
            const h = Math.max(3, Math.round(v / max * 100));
            const label = new Date(m + '-01T00:00:00').toLocaleDateString('en-IN', { month: 'short' });
            const title = `${v} completed trip${v === 1 ? '' : 's'} \u00b7 ${m}`;
            return `<div class="trip-col" title="${esc(title)}">
                    <div class="trip-value">${esc(v)}</div>
                    <div class="trip-bar" style="height:${h}%"></div>
                    <div class="trip-week">${esc(label)}</div>
                </div>`;
        }).join('');
        return `<div class="chart-wrap">
            <div class="chart-grid"><i></i><i></i><i></i></div>
            <div class="trips-chart">${cols}</div>
        </div>
        <div class="admin-section-note">${esc(s.tripsCompletedTotal || 0)} total passenger trips completed in the last 12 months <span class="em">(live booking data)</span>.</div>`;
    }

    async function adminDashboard() {
        const s = await api.adminStats();
        const roleCounts = s.roles || {};
        const order = ['ADMIN', 'RAILWAY_ADMIN', 'TRANSPORT_ADMIN', 'HOTEL_ADMIN', 'RESTAURANT_ADMIN',
            'TOURIST_SPOT_ADMIN', 'GUIDE', 'USER'];
        const rows = order.filter(k => roleCounts[k]).map(k => [k, roleCounts[k]]);
        const total = s.users || rows.reduce((a, [, v]) => a + v, 0);
        const maxR = Math.max(1, ...rows.map(([, v]) => v));
        const pendingProviders = (s.providerApproval || {}).PENDING || 0;

        const statsTable = rows.length ? `<div class="table-scroll"><table class="admin-table">
            <thead><tr><th>Role</th><th>Accounts</th><th>Share</th></tr></thead>
            <tbody>${rows.map(([k, v]) => `
                <tr>
                    <td class="u-name">${esc(ROLE_LABEL[k] || k)}</td>
                    <td>${esc(v)}</td>
                    <td><span class="text-muted">${total ? Math.round(v / total * 100) : 0}%</span></td>
                </tr>`).join('')}</tbody>
        </table></div>` : emptyState('No accounts yet', 'Registered users will appear here.');

        const roleChart = rows.length ? rows.map(([k, v]) => {
            const w = Math.round(v / maxR * 100);
            return `<div class="mg-row">
                <span class="mg-label">${esc(ROLE_LABEL[k] || k)}</span>
                <div class="mg-track"><div class="mg-fill" style="width:${w}%"></div></div>
                <span class="mg-value">${esc(v)}</span>
            </div>`;
        }).join('') : '<p class="text-muted">No users yet.</p>';

        $('portalContent').innerHTML = `
            <div class="admin-head">
                <div>
                    <h1>Admin Dashboard</h1>
                    <div class="admin-head-sub">Live overview of the TripMind AI platform</div>
                </div>
            </div>
            <section class="admin-section">
                <div class="admin-section-title">Platform Overview</div>
                <div class="metric-band">
                    <div class="metric"><span class="metric-label">Total Registered Users</span><span class="metric-value">${esc(total)}</span></div>
                    <div class="metric"><span class="metric-label">Pending Provider Approvals</span><span class="metric-value">${esc(pendingProviders)}</span></div>
                    <div class="metric"><span class="metric-label">Revenue (confirmed)</span><span class="metric-value">${money(s.revenue)}</span></div>
                </div>
                <div class="overview-grid">
                    <div>
                        <div class="subsection-title">Accounts by role</div>
                        ${statsTable}
                    </div>
                    <div>
                        <div class="subsection-title">Role distribution</div>
                        ${roleChart}
                    </div>
                </div>
            </section>
            <section class="admin-section">
                <div class="admin-section-title">Trips Completed by Passengers</div>
                ${tripsChartHtml(s)}
            </section>`;
    }

    function roleFriendly(role) {
        return ROLE_LABEL[role] || String(role || '').replace(/_/g, ' ');
    }

    /* Status pill based on account approval + account status fields. */
    function statusPills(u) {
        const appr = u.approvalStatus || 'APPROVED';
        const pill = { APPROVED: 'ok', REJECTED: 'bad', SUSPENDED: 'dark', PENDING: 'warn' }[appr] || 'neutral';
        const apprPill = `<span class="pill ${pill}">${esc(appr)}</span>`;
        const acct = u.status || 'ACTIVE';
        return acct !== 'ACTIVE' ? apprPill + ' <span class="pill neutral">Account ' + esc(acct) + '</span>' : apprPill;
    }

    function mediaType(value) {
        const m = /^data:([^;,]+)/i.exec(String(value == null ? '' : value));
        return m ? (m[1].split('/')[0] || 'file').toLowerCase() : null;
    }
    function mediaSub(value) {
        const m = /^data:([^;,]+)/i.exec(String(value == null ? '' : value));
        return m ? (m[1].split('/')[1] || 'file').toUpperCase() : '';
    }

    /* One click-to-zoom image tile. Handles data: URIs and remote URLs with a
       broken-image fallback; never renders raw base64/URL text. */
    function imageTile(value, alt) {
        const s = String(value == null ? '' : value);
        if (!s) return '';
        if (mediaType(s) === 'image' || /^https?:/i.test(s)) {
            return `<div class="image-tile" tabindex="0" role="button"
                        onclick="TM.zoom('${esc(s)}')"
                        onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();TM.zoom('${esc(s)}');}"
                        data-src="${esc(s)}" title="Click to view larger">
                    <img src="${esc(s)}" alt="${esc(alt || 'uploaded image')}" loading="lazy"
                         referrerpolicy="no-referrer"
                         onerror="this.onerror=null;this.outerHTML='<div class=&quot;tile-empty&quot;>Image unavailable</div>';">
                </div>`;
        }
        return '';
    }

    /* Documents: image proofs render as thumbnails, everything else as a chip. */
    function documentChips(docs) {
        if (!Array.isArray(docs) || !docs.length) return '<span class="text-muted">None provided</span>';
        return '<div class="doc-list">' + docs.map((d, i) => {
            const s = String(d == null ? '' : d);
            if (!s) return '';
            if (mediaType(s) === 'image') {
                return `<span class="doc-chip small-img">${imageTile(s, 'Document ' + (i + 1))}</span>`;
            }
            if (/^data:/i.test(s)) return `<span class="doc-chip">Document ${i + 1} <span class="text-muted">(${esc(mediaSub(s) || 'file')})</span></span>`;
            if (/^https?:/i.test(s)) return `<span class="doc-chip">Document ${i + 1} <a href="${esc(s)}" target="_blank" rel="noopener">Open</a></span>`;
            return `<span class="doc-chip">${esc(String(s).slice(0, 40))}</span>`;
        }).join('') + '</div>';
    }

    /* Registration fields \u2192 label/value rows (blobs are summarized, never dumped). */
    function regRows(registration) {
        const reg = registration || {};
        const entries = Object.entries(reg).filter(([, v]) => v !== null && v !== undefined && String(v).trim() !== '');
        if (!entries.length) return '<span class="text-muted">No additional details submitted during registration.</span>';
        return entries.map(([k, v]) => {
            const sv = String(v);
            if (/^data:/i.test(sv)) v = `Uploaded file (${esc(mediaSub(sv) || 'attachment')})`;
            else if (/^https?:/i.test(sv)) v = `<a href="${esc(sv)}" target="_blank" rel="noopener">Open link</a>`;
            else v = esc(sv);
            return `<div class="detail-item"><span class="k">${esc(k)}</span><span class="v">${v}</span></div>`;
        }).join('');
    }

    function section(title, bodyHtml) {
        return `<section class="admin-section"><div class="admin-section-title">${esc(title)}</div>${bodyHtml}</section>`;
    }

    window.TM.zoom = (src) => {
        const m = dialog(`<div class="lightbox-img"><img src="${esc(src)}" alt="" referrerpolicy="no-referrer"></div>
            <div class="flex end gap"><button class="btn btn-outline" data-close>Close</button></div>`);
        const box = m.el.querySelector('.modal-box');
        if (box) box.classList.add('wide');
    };

    async function adminApprovals() {
        setPageTitle('Partner approvals');
        window.apprRole = window.apprRole || 'ALL';
        $('portalContent').innerHTML = '<div id="approvalsRoot"></div>';
        await renderApprovals('PENDING');
    }

    async function renderApprovals(status = 'PENDING') {
        const root = document.getElementById('approvalsRoot');
        if (!root) return;
        root.innerHTML = loadingState();
        try {
            const res = await api.adminPartners({ status });
            const partners = res.partners || [];
            const roleFilter = window.apprRole || 'ALL';
            const shown = roleFilter === 'ALL' ? partners
                : partners.filter(p => p.role === roleFilter);

            window.TM.apprFilterRole = (r) => { window.apprRole = r; renderApprovals(status); };
            window.TM.apprFilterStatus = (s) => {
                window.apprStatus = s;
                document.querySelectorAll('[data-appr-status]').forEach(b =>
                    b.classList.toggle('btn-primary', b.dataset.apprStatus === s));
                renderApprovals(s);
            };
            window.TM.apprView = (pid) => openApproval(
                partners.find(p => p.id === pid) || {});
            window.TM.apprApprove = (pid) => {
                const p = partners.find(x => x.id === pid) || {};
                confirmDialog('Approve partner',
                    `Approve ${esc(p.partnerLabel || p.role)} account of ${esc(p.name || 'this partner')}? They will be able to sign in and publish immediately.`,
                    () => run(async () => {
                        await api.partnerDecision(pid, 'approve');
                        toast('Approved. The partner can now sign in and publish.');
                        renderApprovals(status);
                    }), 'Approve');
            };
            window.TM.apprReject = (pid) => promptDialog('Reject partner',
                'Give the partner a reason. They will see it, so be specific about what to fix:',
                (reason) => run(async () => {
                    await api.partnerDecision(pid, 'reject', reason);
                    toast('Rejected and the reason was recorded.');
                    renderApprovals(status);
                }), 'Not compliant with platform guidelines');

            const statusTabs = ['PENDING', 'APPROVED', 'REJECTED', 'ALL'].map(s =>
                `<button class="btn btn-sm ${s === status ? 'btn-primary' : 'btn-outline'}" data-appr-status="${s}" onclick="TM.apprFilterStatus('${s}')">${s[0] + s.slice(1).toLowerCase()}</button>`).join(' ');

            const roleTabs = ['ALL'].concat(res.roles || []).map(r =>
                `<button class="btn btn-sm ${r === roleFilter ? 'btn-primary' : 'btn-outline'}" onclick="TM.apprFilterRole('${r}')">${r === 'ALL' ? 'All roles' : esc(roleFriendly(r))}</button>`).join(' ');

            const head = `<div class="admin-head"><div><h1>Partner approvals</h1>
                <div class="admin-head-sub">Every operational role is reviewed by the Main Admin before it can publish.</div></div></div>
                <div class="flex gap" style="margin-bottom:.75rem;">${statusTabs}</div>
                <div class="flex gap" style="margin-bottom:1rem;">${roleTabs}</div>`;

            if (!shown.length) {
                root.innerHTML = head + section(
                    status === 'PENDING' ? 'Pending partner registrations' : 'Partner accounts',
                    emptyState('Nothing here',
                        status === 'PENDING'
                            ? 'Every partner registration has had a decision. New submissions land here automatically.'
                            : 'No partner accounts match this filter.'));
                return;
            }

            const rows = shown.map(p => {
                const reg = p.registration || {};
                const where = [reg.address, reg.city, reg.district].filter(Boolean).join(', ');
                const docs = (p.documents || []).length;
                const stamp = (p.approvedAt || p.rejectedAt || p.createdAt || '').slice(0, 10);
                return `<tr>
                    <td>
                        <div class="u-name">${esc(p.name)}</div>
                        <div class="u-email">${esc(p.email)}</div>
                        ${where ? `<div class="u-email">${esc(where)}</div>` : ''}
                    </td>
                    <td><span class="pill info">${esc(p.partnerLabel || roleFriendly(p.role))}</span></td>
                    <td>
                        ${docs} document${docs === 1 ? '' : 's'}
                        ${p.imageCount ? ` \u00b7 ${p.imageCount} photo${p.imageCount === 1 ? '' : 's'}` : ''}
                    </td>
                    <td>${esc(stamp)}</td>
                    <td><span class="pill ${p.approvalStatus === 'APPROVED' ? 'ok' : p.approvalStatus === 'REJECTED' ? 'bad' : 'warn'}">${esc(p.approvalStatus || 'PENDING')}</span></td>
                    <td>
                        <div class="flex gap">
                            <button class="btn btn-outline btn-sm" onclick="TM.apprView('${p.id}')">Review</button>
                            ${p.approvalStatus === 'PENDING' ? `
                                <button class="btn btn-success btn-sm" onclick="TM.apprApprove('${p.id}')">Approve</button>
                                <button class="btn btn-danger btn-sm" onclick="TM.apprReject('${p.id}')">Reject</button>` : ''}
                        </div>
                    </td>
                </tr>`;
            }).join('');

            root.innerHTML = head + section(
                status === 'PENDING' ? 'Pending partner registrations' : 'Partner accounts',
                `<div class="table-scroll"><table class="admin-table">
                    <thead><tr><th>Partner</th><th>Role</th><th>Evidence</th><th>Date</th><th>Status</th><th>Actions</th></tr></thead>
                    <tbody>${rows}</tbody></table></div>
                 <div class="admin-section-note">${shown.length} partner account${shown.length === 1 ? '' : 's'}. A rejection needs a reason and unpublishes any listing immediately; re-approving publishes it again.</div>`);
        } catch (e) {
            root.innerHTML = section('Partner approvals', errorState(e.message, '() => renderApprovals()'));
        }
    }

function openApproval(u) {
    if (!u || !u.id) return;
    const reg = u.registration || {};
    /* Documents may arrive either as a plain data-URI list (legacy) or as the
       new {id, label, classification, source} records. Render both. */
    const docRecords = (u.documents || []).filter(d => d && typeof d === 'object');
    const docUris = (u.documents || []).filter(d => typeof d === 'string');
    const reqs = (u.requirements || u.verification || []);
    const statusPill = { APPROVED: 'ok', REJECTED: 'bad' }[u.approvalStatus] || 'warn';
    const regRowsHtml = Object.entries(reg).filter(([, v]) => v != null && String(v).trim() !== '' &&
    !/^data:/i.test(String(v)))
    .map(([k, v]) => `<div class="detail-item"><span class="k">${esc(k)}</span><span class="v">${
    Array.isArray(v) ? esc(v.join(', ')) : esc(String(v))
    }</span></div>`).join('');
    const m = dialog(`
    <h3>Partner registration review</h3>
    <div class="text-muted" style="font-size:.85rem;margin-bottom:.75rem;">
    ${esc(u.name)} &middot; ${esc(u.email)} &middot; ${esc(u.partnerLabel || roleFriendly(u.role))} &middot;
    <span class="pill ${statusPill}">${esc(u.approvalStatus || 'PENDING')}</span></div>
    ${u.identityNumber ? `<div class="detail-item"><span class="k">${esc(u.identityType || 'ID')}</span><span class="v">${esc(u.identityNumber)}</span></div>` : ''}
    ${u.mobile ? `<div class="detail-item"><span class="k">Mobile</span><span class="v">${esc(u.mobile)}</span></div>` : ''}
    <div class="detail-list">${regRowsHtml}</div>
    ${reqs.length ? `<div class="subsection-title" style="margin-top:1rem;">Verification requirements for this role</div>
    <ul class="appr-reqs">${reqs.map(r => {
        const cls = r.requirement === 'MANDATORY' ? 'bad' : r.requirement === 'CONDITIONAL' ? 'warn' : 'info';
        const submitted = (docRecords.find(d => d.id === r.id) || {}).data;
        return `<li>
    <span class="pill ${cls}">${esc(r.requirement || 'OPTIONAL')}</span>
    <span class="appr-req__label">${esc(r.label || r.id)}${r.verified === false ? ' <span class="text-muted">(threshold unverified)</span>' : ''}</span>
    <span class="appr-req__note">${esc(r.condition || r.help || '')}${submitted ? '' : ' \u00b7 not supplied'}</span>
    <span class="appr-req__src">${esc(r.source || '')}</span>
    </li>`; }).join('')}</ul>` : ''}
    ${docRecords.length ? `<div class="subsection-title" style="margin-top:1rem;">Submitted documents</div>
    <ul class="appr-reqs">${docRecords.map(d => `<li>
    <span class="pill ${d.data ? 'ok' : 'bad'}">${d.data ? 'Attached' : 'Missing'}</span>
    <span class="appr-req__label">${esc(d.label || d.id)}</span>
    <span class="appr-req__src">${esc(d.type || '')}</span>
    </li>`).join('')}</ul>` : ''}
    ${docUris.length ? `<div class="subsection-title" style="margin-top:1rem;">Documents / Proof</div>${documentChips(docUris)}` : ''}
    ${u.imageCount ? `<div class="subsection-title" style="margin-top:1rem;">Uploaded images</div><p class="text-muted">${u.imageCount} photo${u.imageCount === 1 ? '' : 's'} received and passed the format and size check.</p>` : ''}
    ${u.approvalReason ? `<p class="text-muted" style="margin-top:1rem;">Recorded reason: ${esc(u.approvalReason)}</p>` : ''}
    <div class="flex end gap" style="margin-top:1.25rem;">
    <button class="btn btn-outline" data-close>Close</button>
    ${u.approvalStatus === 'PENDING' ? `
    <button class="btn btn-danger" id="__rej">Reject</button>
    <button class="btn btn-success" id="__appr">Approve</button>` : ''}
    </div>`);
    const box = m.el.querySelector('.modal-box');
    if (box) box.classList.add('wide');
    const appr = m.get('#__appr');
    if (appr) appr.addEventListener('click', () => { m.close(); window.TM.apprApprove(u.id); });
    const rej = m.get('#__rej');
    if (rej) rej.addEventListener('click', () => { m.close(); window.TM.apprReject(u.id); });
    }


    /* Preserved across View \u2192 Back navigation so search/role state survives. */
    const USER_FILTERS = [
        ['', 'All Users'],
        ['TRANSPORT_ADMIN', 'Transport Admin'],
        ['HOTEL_ADMIN', 'Hotel Admin'],
        ['RESTAURANT_ADMIN', 'Restaurant Admin'],
        ['TOURIST_SPOT_ADMIN', 'Travel Spot Admin'],
        ['GUIDE', 'Guide'],
        ['USER', 'Normal User'],
    ];
    const auState = { role: '', q: '' };

    async function adminAllUsers() {
        setPageTitle('All Users');
        $('portalContent').innerHTML = `
            <div class="admin-head">
                <div>
                    <h1>All Users</h1>
                    <div class="admin-head-sub">Approved accounts only \u2014 pending and rejected registrations are excluded.</div>
                </div>
            </div>
            <section class="admin-section">
                <div class="admin-section-title">Approved Users</div>
                <div class="toolbar">
                    <select id="auRole" class="form-select">
                        ${USER_FILTERS.map(([v, l]) => `<option value="${v}" ${auState.role === v ? 'selected' : ''}>${esc(l)}</option>`).join('')}
                    </select>
                    <input id="auQ" class="form-input" type="search" placeholder="Search by name or email" value="${esc(auState.q)}">
                    <button class="btn btn-primary btn-sm" id="auSearch">Search</button>
                    <button class="btn btn-outline btn-sm" id="auReset">Reset</button>
                </div>
                <div id="auBody">${loadingState()}</div>
            </section>`;

        $('auSearch').addEventListener('click', () => {
            auState.q = ($('auQ').value || '').trim();
            $('auQ').value = auState.q;
            auRender();
        });
        $('auQ').addEventListener('keydown', e => {
            if (e.key === 'Enter') {
                auState.q = ($('auQ').value || '').trim();
                $('auQ').value = auState.q;
                auRender();
            }
        });
        $('auReset').addEventListener('click', () => {
            auState.role = ''; auState.q = '';
            $('auRole').value = ''; $('auQ').value = '';
            auRender();
        });
        $('auRole').addEventListener('change', () => { auState.role = $('auRole').value; auRender(); });
        auRender();
    }

    async function auRender() {
        const body = $('auBody');
        if (!body) return;
        body.innerHTML = loadingState();
        const params = {};
        if (auState.role) params.role = auState.role;
        if (auState.q) params.q = auState.q;
        let users = [];
        try {
            const res = await api.adminUsers(params);
            users = res.users || [];
        } catch (e) {
            body.innerHTML = errorState(e.message, '() => auRender()');
            return;
        }
        if (!users.length) {
            body.innerHTML = (auState.q || auState.role)
                ? emptyState('No matching users', 'Try a different search or role filter.')
                : emptyState('No approved users found', 'Approved accounts will appear here.');
            return;
        }
        const rows = users.map(u => `<tr>
            <td class="u-name">${esc(u.name)}</td>
            <td class="u-email">${esc(u.email)}</td>
            <td>${esc(roleFriendly(u.role))}</td>
            <td>${esc((u.createdAt || '').slice(0, 10))}</td>
            <td>${statusPills(u)}</td>
            <td>
                <div class="flex gap">
                    <button class="btn btn-outline btn-sm" onclick="TM.viewUser('${u.id}')">View</button>
                    <button class="btn btn-danger btn-sm" ${u.approvalStatus === 'SUSPENDED' ? 'disabled' : ''}
                        onclick="TM.confirmSuspend('${u.id}', ${JSON.stringify(u.name)})">
                        ${u.approvalStatus === 'SUSPENDED' ? 'Suspended' : 'Suspend'}
                    </button>
                </div>
            </td></tr>`).join('');
        body.innerHTML = `<div class="table-scroll"><table class="admin-table">
            <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Registered</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>${rows}</tbody></table>
            <div class="admin-section-note">Showing ${users.length} approved account${users.length === 1 ? '' : 's'}.</div></div>`;
    }

    window.TM.viewUser = (id) => { location.hash = 'user/' + id; };
    window.TM.confirmSuspend = (id, name) => {
        confirmDialog('Suspend this user?',
            `Suspending ${esc(name || 'this account')} will immediately prevent them from logging in or using the platform. The account remains stored and can be restored by an Administrator.`,
            () => run(async () => {
                await api.adminSetApproval(id, 'SUSPENDED');
                toast('User suspended.');
                auRender();
            }), 'Suspend User');
    };

    /* ---------------- ADMIN: USER DETAILS (separate page) ---------------- */

    async function renderUserDetail(uid) {
        $('portalContent').innerHTML = loadingState();
        try {
            const res = await api.adminUsers();
            const u = (res.users || []).find(x => x.id === uid);
            if (!u) {
                $('portalContent').innerHTML = `<div class="admin-head"><div><h1>User Details</h1></div></div>` +
                    section('User Details', emptyState('User not found', 'This account is not an approved user or no longer exists.'));
                return;
            }
            const imgs = (Array.isArray(u.images) ? u.images : []).filter(Boolean);
            const docs = (Array.isArray(u.documents) ? u.documents : []).filter(Boolean);
            const suspended = u.approvalStatus === 'SUSPENDED';
            const basic = `
                <div class="detail-list">
                    <div class="detail-item"><span class="k">Full name</span><span class="v">${esc(u.name)}</span></div>
                    <div class="detail-item"><span class="k">Email</span><span class="v">${esc(u.email)}</span></div>
                    <div class="detail-item"><span class="k">Role</span><span class="v">${esc(roleFriendly(u.role))}</span></div>
                    <div class="detail-item"><span class="k">Registered</span><span class="v">${esc((u.createdAt || '').replace('T', ' ').slice(0, 16))}</span></div>
                    <div class="detail-item"><span class="k">Approval status</span><span class="v">${statusPills(u)}</span></div>
                    ${u.approvalReason ? `<div class="detail-item"><span class="k">Admin note</span><span class="v">${esc(u.approvalReason)}</span></div>` : ''}
                </div>`;
            $('portalContent').innerHTML = `
                <div class="ud-head">
                    <div class="ud-title">
                        <button class="btn btn-outline btn-sm" onclick="TM.gotoUsers()">
                            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 12H5M11 19l-7-7 7-7"></path></svg>
                            Back to All Users
                        </button>
                        <div>
                            <h2>User Details</h2>
                            <div class="ud-email">${esc(u.email)}</div>
                        </div>
                    </div>
                    ${statusPills(u)}
                </div>
                <div class="details-grid">
                    ${section('Basic Information', basic)}
                    ${section('Organization / Professional Details', regRows(u.registration))}
                </div>
                <div class="details-grid">
                    ${section('Documents / Proof', documentChips(docs))}
                    ${section('Status', `
                        <div class="detail-list">
                            <div class="detail-item"><span class="k">Approval status</span><span class="v">${statusPills(u)}</span></div>
                            ${u.approvalReason ? `<div class="detail-item"><span class="k">Admin note</span><span class="v">${esc(u.approvalReason)}</span></div>` : ''}
                        </div>
                        <div class="mt-2">
                            ${suspended
                                ? '<p class="text-muted" style="font-size:.85rem;">This account is currently suspended. The user cannot log in or use the platform.</p>'
                                : ''}
                            <button class="btn btn-danger mt-2" ${suspended ? 'disabled' : ''} onclick="TM.suspendDetail('${u.id}')">
                                ${suspended ? 'Account Suspended' : 'Suspend User'}
                            </button>
                        </div>`)}
                </div>
                ${section('Uploaded Images', imgs.length
                    ? `<div class="image-grid">${imgs.map(i => imageTile(i, 'uploaded image')).join('')}</div>
                       <div class="admin-section-note">Click any image to view it larger.</div>`
                    : emptyState('No images uploaded', 'This account did not upload photographs during registration.'))}
            `;
        } catch (e) {
            $('portalContent').innerHTML = section('User Details', errorState(e.message, '() => renderUserDetail(\'' + uid + '\')'));
        }
    }

    window.TM.suspendDetail = (uid) => {
        confirmDialog('Suspend this user?',
            'Suspending this account will immediately prevent the user from logging in or using the platform. The account remains stored and can be restored later by an Administrator.',
            () => run(async () => {
                await api.adminSetApproval(uid, 'SUSPENDED');
                toast('User suspended.');
                renderUserDetail(uid);
            }), 'Suspend User');
    };
    window.TM.gotoUsers = () => {
        if (location.hash) history.replaceState(null, '', location.pathname + location.search);
        showPanel('users');
    };

    /* ---------------- ADMIN: PLANS OF USERS ---------------- */
    async function adminPlans() {
        const trips = (await api.adminTrips().catch(() => [])) || [];
        const statuses = ['ALL', 'PLANNED', 'BOOKED', 'DRAFT'];
        const usersWithTrips = new Set(trips.map(t => t.userId)).size;
        const stay = (t) => t.status === 'BOOKED' || t.status === 'PLANNED';
        const statCards = `
            <div class="stats-grid mb-4">
                <div class="stat-card"><div class="stat-label">Total trips</div><div class="stat-value">${trips.length}</div></div>
                <div class="stat-card"><div class="stat-label">Booked</div><div class="stat-value">${trips.filter(t => t.status === 'BOOKED').length}</div></div>
                <div class="stat-card"><div class="stat-label">Planned</div><div class="stat-value">${trips.filter(t => t.status === 'PLANNED').length}</div></div>
                <div class="stat-card"><div class="stat-label">Users with trips</div><div class="stat-value">${usersWithTrips}</div></div>
            </div>`;
        const filterBtns = statuses.map(s =>
            `<button class="btn btn-sm ${s === 'ALL' ? 'btn-primary' : 'btn-outline'}" onclick="TM.plansTab('${s}')">${s}</button>`).join(' ');
        const rowHtml = (x) => `<tr>
            <td>${esc((x.user || {}).name || (x.userId || '\u2014').slice(0, 8) + '\u2026')}<div class="text-muted" style="font-size:.75rem;">${esc((x.user || {}).email || '')}</div></td>
            <td>${esc(x.origin)} \u2192 ${esc(x.destination)}</td>
            <td>${esc((x.startDate || '').slice(0, 10))} \u2192 ${esc((x.endDate || '').slice(0, 10))}</td>
            <td>${esc(styleLabel(x.travelStyle) || '\u2014')}</td>
            <td><span class="pill ${x.status === 'BOOKED' ? 'ok' : x.status === 'PLANNED' ? 'info' : 'warn'}">${esc(x.status)}</span></td>
            <td>${x.totalEstimatedCost ? money(x.totalEstimatedCost) : '\u2014'}</td>
            <td>
                <button class="btn btn-outline btn-sm" onclick="TM.planDetail('${x._id}')">View</button>
                <button class="btn btn-outline btn-sm" onclick="TM.tripTicket('${x._id}', this)" ${x.status === 'BOOKED' || x.status === 'COMPLETED' ? '' : 'disabled'}>Ticket</button>
            </td></tr>`;
        const table = (rows) => `<table class="row-table" style="width:100%">
            <tr><th>User</th><th>Route</th><th>Dates</th><th>Style</th><th>Status</th><th>Cost</th><th></th></tr>
            ${rows.length ? rows.map(rowHtml).join('') : '<tr><td colspan="7" class="text-muted">No trips match this filter.</td></tr>'}</table>`;
        $('portalContent').innerHTML = card('Plans of Users', `
            ${statCards}
            <div class="flex" style="gap:.5rem;margin-bottom:1rem;">${filterBtns}</div>
            <div id="plans_body">${table(trips)}</div>`);
        window.TM.plansTab = (which) => {
            const rows = which === 'ALL' ? trips : trips.filter(x => x.status === which);
            $('plans_body').innerHTML = table(rows);
        };
        window.TM.planDetail = (id) => {
            const x = trips.find(t => t._id === id);
            if (!x) return;
            const its = (x.itineraries || []).map(it => `
                <div style="border-top:1px solid var(--slate-100);padding:.6rem 0;">
                    <div class="flex justify-between">
                        <b>${esc(it.title || 'Itinerary option')}</b>
                        <span>${it.totalCost ? money(it.totalCost) : ''}</span>
                    </div>
                    <div class="text-muted" style="font-size:.8rem;">${esc(((it.days || []).map(d =>
                        `${d.day}: ${(d.activities || []).map(a => a.name || a.spotName || '').join(', ')}`).join(' \u00b7 ')).slice(0, 240))}${(it.days || []).length ? '\u2026' : ''}</div>
                </div>`).join('') || '<p class="text-muted">No itineraries generated yet.</p>';
            const m = dialog(`<h3>${esc(x.origin)} \u2192 ${esc(x.destination)}</h3>
                <div class="detail-list">
                    ${infoRow('User', (x.user || {}).name + ((x.user || {}).mobile ? ' \u00b7 ' + (x.user.mobile) : ''))}
                    ${infoRow('Email', (x.user || {}).email || '\u2014')}
                    ${infoRow('Travel dates', `${(x.startDate || '').slice(0, 10)} \u2192 ${(x.endDate || '').slice(0, 10)}`)}
                    ${infoRow('Travelers', x.travelers)}
                    ${infoRow('Style', styleLabel(x.travelStyle) || '\u2014')}
                    ${infoRow('Budget', x.budgetUnlimited ? 'Unlimited' : money(x.budget))}
                    ${infoRow('Status', x.status)}
                    ${x.totalEstimatedCost ? infoRow('Estimated cost', money(x.totalEstimatedCost)) : ''}
                </div>
                <div class="card-title" style="margin-top:1rem;">Plans</div>
                ${its}
                <div class="flex end gap">
                    <a class="btn btn-outline" href="/pages/trip.html?id=${x._id}">Open planner</a>
                    <button class="btn btn-outline" onclick="TM.tripTicket('${x._id}', this)" ${x.status === 'BOOKED' || x.status === 'COMPLETED' ? '' : 'disabled'}>Download ticket</button>
                    <button class="btn btn-primary" data-close>Close</button>
                </div>`);
        };
        window.TM.tripTicket = async (id, btn) => run(async () => {
            btn.disabled = true;
            try { await api.downloadTripTicket(id); toast('Trip ticket downloaded.'); }
            finally { btn.disabled = false; }
        });
    }

    /* ---------------- ADMIN: AI FEEDBACK ANALYSIS ---------------- */
    async function adminFeedbackAnalysis() {
        $('portalContent').innerHTML = card('AI Feedback Analysis',
            `<p class="text-muted">AI-powered analysis of all user trip reviews \u2014 runs automatically, nothing is stored.</p>
             <div id="fb_result" class="mt-4"><p class="text-muted">Analysing reviews\u2026</p></div>`);
        run(async () => {
            const box = document.getElementById('fb_result');
            try {
                const res = await api.feedbackAnalysis();
                const none = !res || !res.rawReviewCount;
                box.innerHTML = none
                    ? '<p class="text-muted">No trip reviews have been submitted yet. Reviews become analysable as soon as passengers complete trips.</p>'
                    : `<div class="card" style="background:var(--slate-50);">
                        <div class="card-content">
                            <h3>Summary</h3>
                            <p>${esc(res.summary || '\u2014')}</p>
                            <div class="flex gap mt-2" style="flex-wrap:wrap;">
                                <span class="pill ok">Positive: ${res.sentiment?.positive || 0}</span>
                                <span class="pill info">Neutral: ${res.sentiment?.neutral || 0}</span>
                                <span class="pill warn">Negative: ${res.sentiment?.negative || 0}</span>
                                <span class="text-muted">(${res.rawReviewCount || 0} reviews analysed)</span>
                            </div>
                            ${res.themes && res.themes.length ? `
                                <h3 class="mt-4">Key themes</h3>
                                <table class="row-table" style="width:100%">
                                    <tr><th>Theme</th><th>Count</th><th>Sentiment</th></tr>
                                    ${res.themes.map(t => `<tr><td>${esc(t.theme)}</td><td>${t.count}</td>
                                        <td><span class="pill ${t.sentiment === 'positive' ? 'ok' : t.sentiment === 'negative' ? 'warn' : 'info'}">${esc(t.sentiment)}</span></td></tr>`).join('')}
                                </table>` : ''}
                            ${res.suggestions && res.suggestions.length ? `
                                <h3 class="mt-4">Suggested improvements</h3>
                                <ul style="margin-left:1rem;">
                                    ${res.suggestions.map(s => `<li>${esc(s)}</li>`).join('')}
                                </ul>` : ''}
                        </div>
                    </div>`;
            } catch (e) {
                box.innerHTML = `<p class="text-muted">Could not run the analysis: ${esc(e.message)}</p>`;
            }
        });
    }

    /* ---------------- "What TripMind Learned" (Admin ML console) ----------------
       The ML layer already stores one `ml_models` row per model with its
       priority, status, version, sample count, evaluation metrics and training
       timestamp, and exposes live output for clustering, segmentation, demand
       and anomaly detection. This panel is the read side of that: it renders
       what the models actually learned, and lets an admin retrain. Nothing is
       faked - a model with no history is labelled INITIAL/COLD_START, not
       dressed up as trained. */
    function mlFriendly(name) {
        const meta = { travel_cost_prediction: 'Travel Cost Prediction',
            travel_time_prediction: 'Travel Time Prediction',
            tourist_spot_recommendation: 'Tourist Spot Recommendation',
            hotel_recommendation: 'Hotel Recommendation',
            transport_recommendation: 'Transport Recommendation',
            guide_recommendation: 'Guide Recommendation',
            itinerary_optimization: 'Itinerary Optimization',
            ai_requirement_extraction: 'AI Requirement Extraction',
            content_based_recommendation: 'Content-Based Recommendation',
            user_segmentation: 'User Segmentation',
            tourist_spot_clustering: 'Tourist Spot Clustering',
            visiting_time_recommendation: 'Visiting Time Recommendation',
            demand_prediction: 'Demand Prediction',
            anomaly_detection: 'Anomaly Detection',
            collaborative_filtering: 'Collaborative Filtering',
            personalized_trip_ranking: 'Personalized Trip Ranking',
            delay_prediction: 'Delay Prediction' };
        return meta[name] || String(name || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    }
    const mlNum = (v) => (v === null || v === undefined || v === '') ? '\u2014' : Number(v).toLocaleString('en-IN');
    const mlStatusPill = (s) => {
        const v = String(s || 'INITIAL').toUpperCase();
        const cls = v === 'ACTIVE' ? 'ok' : v === 'COLD_START' ? 'info' : v === 'ERROR' ? 'bad' : 'warn';
        return `<span class="pill ${cls}">${esc(v.replace(/_/g, ' '))}</span>`;
    };
    function mlMetricChips(metrics) {
        const m = metrics || {};
        const keys = Object.keys(m);
        if (!keys.length) return '<span class="text-muted">\u2014</span>';
        return keys.map(k => {
            let v = m[k];
            if (v && typeof v === 'object') v = Array.isArray(v) ? v.length + ' items' : Object.keys(v).length + ' keys';
            return `<span class="pill neutral">${esc(k)}: ${esc(v)}</span>`;
        }).join(' ');
    }
    function mlWhen(iso) {
        return iso ? esc(String(iso).slice(0, 19).replace('T', ' ')) : '\u2014';
    }

    async function adminMlInsights() {
        setPageTitle('What TripMind Learned');
        $('portalContent').innerHTML = '<div id="mlRoot"></div>';
        await renderMlInsights();
    }

    function mlClustersHtml(env) {
        if (env && env.error) return `<p class="text-muted">Could not load clusters: ${esc(env.error)}</p>`;
        const rows = (env && env.result && env.result.clusters) || [];
        if (!rows.length) return emptyState('No clusters yet', 'Approved tourist spots are needed before locations can be grouped.');
        return `<div class="table-scroll"><table class="admin-table">
            <thead><tr><th>Learned theme</th><th>Spots</th><th>Members</th></tr></thead>
            <tbody>${rows.map(c => {
                const names = (c.members || []).map(m => m && m.name).filter(Boolean);
                return `<tr>
                    <td class="u-name">${esc(c.theme || 'Mixed')}</td>
                    <td>${esc(c.count || names.length)}</td>
                    <td class="text-muted">${esc(names.slice(0, 8).join(', '))}${names.length > 8 ? ' \u2026' : ''}</td>
                </tr>`;
            }).join('')}</tbody></table></div>
            <div class="admin-section-note">Grouped by location, category, popularity, rating and price <span class="em">(k-means)</span>.</div>`;
    }

    function mlSegmentsHtml(env) {
        if (env && env.error) return `<p class="text-muted">Could not load segments: ${esc(env.error)}</p>`;
        const rows = (env && env.result && env.result.segments) || [];
        if (!rows.length) return emptyState('No traveller segments yet', 'Segments appear once travellers have planned trips.');
        return `<div class="table-scroll"><table class="admin-table">
            <thead><tr><th>Segment</th><th>Travellers</th><th>Avg budget</th></tr></thead>
            <tbody>${rows.map(s => `<tr>
                <td class="u-name">${esc(s.segment || 'Traveller')}</td>
                <td>${esc(s.count || (s.members || []).length)}</td>
                <td>${money(s.avgBudget)}</td>
            </tr>`).join('')}</tbody></table></div>`;
    }

    function mlDemandHtml(env) {
        if (env && env.error) return `<p class="text-muted">Could not load the forecast: ${esc(env.error)}</p>`;
        const f = (env && env.result && env.result.forecast) || {};
        const types = Object.keys(f);
        if (!types.length) return emptyState('No demand history yet', 'Forecasts appear once bookings accumulate.');
        return types.map(t => {
            const days = f[t] || [];
            return `<div class="subsection-title" style="margin-top:.6rem;">${esc(t)}</div>
            <div class="table-scroll"><table class="row-table" style="width:100%">
                <tr><th>Date</th><th>Day</th><th>Expected bookings</th></tr>
                ${days.slice(0, 7).map(d => `<tr><td>${esc(d.date)}</td><td>${esc(d.weekday || '')}</td><td>${esc(d.expected)}</td></tr>`).join('')}
            </table></div>`;
        }).join('');
    }

    function mlAnomaliesHtml(env) {
        if (env && env.error) return `<p class="text-muted">Could not load anomalies: ${esc(env.error)}</p>`;
        const rows = (env && env.result && env.result.anomalies) || [];
        const samples = env && env.result && env.result.samples;
        if (!rows.length) {
            return emptyState('No anomalies flagged', samples
                ? `Scanned ${samples} bookings; none crossed the anomaly threshold.`
                : 'Anomaly detection needs at least 6 bookings.');
        }
        return `<div class="table-scroll"><table class="admin-table">
            <thead><tr><th>Reference</th><th>Type</th><th>User</th><th>Amount</th><th>Status</th><th>Score</th></tr></thead>
            <tbody>${rows.map(a => `<tr>
                <td class="u-name">${esc(a.reference || a.bookingId || '')}</td>
                <td>${esc(a.type || '')}</td>
                <td>${esc(a.userName || a.userId || '')}</td>
                <td>${money(a.amount)}</td>
                <td>${esc(a.status || '')}</td>
                <td><span class="pill ${Number(a.anomalyScore) >= 0.85 ? 'bad' : 'warn'}">${esc(a.anomalyScore)}</span></td>
            </tr>`).join('')}</tbody></table></div>`;
    }

    async function renderMlInsights() {
        const root = document.getElementById('mlRoot');
        if (!root) return;
        root.innerHTML = loadingState();
        const [status, clusters, segments, demand, anomalies] = await Promise.all([
            api.mlStatus().catch(e => ({ error: e.message })),
            api.mlClusters().catch(e => ({ error: e.message })),
            api.mlSegments().catch(e => ({ error: e.message })),
            api.mlDemand().catch(e => ({ error: e.message })),
            api.mlAnomalies({ limit: 15 }).catch(e => ({ error: e.message })),
        ]);

        if (status && status.error) {
            root.innerHTML = errorState(status.error, 'TM.mlInsightsReload');
            return;
        }
        const models = (status && status.models) || [];
        const counts = (status && status.statusCounts) || {};
        const cold = (counts.COLD_START || 0) + (counts.INITIAL || 0);
        const lastTrained = status && status.trainedAt;

        const head = `<div class="admin-head">
            <div>
                <h1>What TripMind Learned</h1>
                <div class="admin-head-sub">Every ML model, its version, training samples and live output \u2014 read straight from the database.</div>
            </div>
            <div class="flex gap">
                <button class="btn btn-outline" onclick="TM.mlInsightsReload()">Refresh</button>
                <button class="btn btn-primary" onclick="TM.mlInsightsTrain()">Run training</button>
            </div>
        </div>`;

        const registry = `<section class="admin-section">
            <div class="admin-section-title">Model registry</div>
            <div class="metric-band">
                <div class="metric"><span class="metric-value">${models.length}</span><span class="metric-label">Models tracked</span></div>
                <div class="metric"><span class="metric-value">${counts.ACTIVE || 0}</span><span class="metric-label">Active (data-backed)</span></div>
                <div class="metric"><span class="metric-value">${cold}</span><span class="metric-label">Cold start / initial</span></div>
                <div class="metric"><span class="metric-value" style="font-size:1.05rem;">${mlWhen(lastTrained)}</span><span class="metric-label">Last full training</span></div>
            </div>
            ${models.length ? `<div class="table-scroll"><table class="admin-table">
                <thead><tr><th>Model</th><th>Pri</th><th>Category</th><th>Status</th><th>Ver</th><th>Samples</th><th>Learned metrics</th><th>Trained</th></tr></thead>
                <tbody>${models.map(m => `<tr>
                    <td class="u-name">${esc(mlFriendly(m.model))}<div class="u-email">${esc(m.model_type || '')}</div></td>
                    <td>P${esc(m.priority || '?')}</td>
                    <td>${esc(m.category || '')}</td>
                    <td>${mlStatusPill(m.status)}</td>
                    <td>v${esc(m.version || 0)}</td>
                    <td>${mlNum(m.samples)}</td>
                    <td>${mlMetricChips(m.metrics)}</td>
                    <td class="text-muted">${mlWhen(m.trainedAt)}</td>
                </tr>`).join('')}</tbody>
            </table></div>` : emptyState('No models registered yet', 'Run training to populate the registry.')}
            <div class="admin-section-note">Status is honest about data volume: <span class="em">ACTIVE</span> means the engine is trained on real records; <span class="em">COLD START</span> / <span class="em">INITIAL</span> means it falls back to a rule or content-based baseline until enough history exists.</div>
        </section>`;

        root.innerHTML = head + registry
            + section('Tourist spot clusters (learned grouping)', mlClustersHtml(clusters))
            + section('Traveller segments (learned behaviour)', mlSegmentsHtml(segments))
            + section('Demand forecast (next 7 days per service)', mlDemandHtml(demand))
            + section('Anomaly watch (isolation-forest style)', mlAnomaliesHtml(anomalies));
    }

    window.TM.mlInsightsReload = () => run(() => renderMlInsights());
    window.TM.mlInsightsTrain = () => run(async () => {
        toast('Training all models\u2026');
        const res = await api.mlTrain();
        const ms = res && res.summary && res.summary.elapsedMs;
        toast('Training complete' + (ms ? ' \u00b7 ' + ms + ' ms' : ''));
        await renderMlInsights();
    });

    async function railwayLounges() {
        $('portalContent').innerHTML = card('Railway Lounges',
            `<p class="text-muted">Manage the premium waiting lounges at Coimbatore Junction and Chennai Central that your Railways account offers.</p>
             <div class="flex gap mt-2" style="margin-bottom:1rem;">
                <button class="btn btn-primary" onclick="TM.addLounge()">Add Lounge</button>
                <button class="btn btn-outline" onclick="TM.reloadLounges()">Refresh</button>
             </div>
             <div id="rl_list"><p class="text-muted">Loading\u2026</p></div>`);
        TM.reloadLounges();
    }

    window.TM.addLounge = () => {
        const m = dialog(`<h3>Add Railway Lounge</h3>
            <div class="form-group"><label class="form-label">Lounge name *</label>
                <input id="lg_name" class="form-input" placeholder="e.g. Executive AC Lounge"></div>
            <div class="form-group"><label class="form-label">Railway station *</label>
                <input id="lg_station" class="form-input" placeholder="e.g. Coimbatore Junction"></div>
            <div class="form-group"><label class="form-label">City *</label>
                <input id="lg_city" class="form-input" placeholder="e.g. Coimbatore"></div>
            <div class="form-group"><label class="form-label">Terminal / area</label>
                <input id="lg_terminal" class="form-input" placeholder="e.g. Platform 1"></div>
            <div class="form-group"><label class="form-label">Price per person (\u20b9) *</label>
                <input id="lg_price" type="number" class="form-input" value="750"></div>
            <div class="form-group"><label class="form-label">Max capacity *</label>
                <input id="lg_cap" type="number" class="form-input" value="60"></div>
            <div class="form-group"><label class="form-label">Amenities (comma separated)</label>
                <input id="lg_amen" class="form-input" value="Recliners, Wi-Fi, Snacks, AC"></div>
            <div class="form-group"><label class="form-label">Description</label>
                <textarea id="lg_desc" class="form-textarea" rows="2"></textarea></div>
            <div class="flex end gap">
              <button class="btn btn-outline" data-close>Cancel</button>
              <button class="btn btn-primary" id="__ok">Save Lounge</button>
            </div>`);
        m.get('#__ok').addEventListener('click', () => {
            const g = (id) => (m.get(id) ? m.get(id).value.trim() : '');
            run(async () => {
                const body = {
                    name: g('#lg_name'), railwayStation: g('#lg_station'), city: g('#lg_city'),
                    terminal: g('#lg_terminal'), pricePerPerson: Number(g('#lg_price')),
                    maxCapacity: Number(g('#lg_cap')),
                    amenities: g('#lg_amen').split(',').map(s => s.trim()).filter(Boolean),
                    description: g('#lg_desc'),
                };
                if (!body.name || !body.railwayStation || !body.city) {
                    alert('Lounge name, station and city are required.'); return;
                }
                await api.createLounge(body);
                m.close();
                TM.reloadLounges();
            });
        });
    };

    window.TM.reloadLounges = () => {
        const box = document.getElementById('rl_list');
        if (!box) return;
        run(async () => {
            try {
                const res = await api.getLounges();
                const lounges = res.lounges || [];
                if (!lounges.length) { box.innerHTML = '<p class="text-muted">No lounges registered yet. Add the first one above.</p>'; return; }
                box.innerHTML = `<table class="row-table" style="width:100%">
                    <tr><th>Lounge</th><th>Station</th><th>City</th><th>Price/Person</th><th>Capacity</th><th>Status</th><th></th></tr>
                    ${lounges.map(l => `<tr>
                        <td><b>${esc(l.name)}</b><br><small class="text-muted">${esc(l.terminal || '')} \u00b7 ${esc(l.hours || '')}</small></td>
                        <td>${esc(l.railwayStation)}</td>
                        <td>${esc(l.city)}</td>
                        <td>\u20b9${Number(l.pricePerPerson || 0).toLocaleString('en-IN')}</td>
                        <td>${l.maxCapacity}</td>
                        <td><span class="pill ${l.status === 'APPROVED' ? 'ok' : l.status === 'PENDING' ? 'info' : 'warn'}">${esc(l.status || '')}</span></td>
                        <td>
                            <button class="btn btn-outline btn-sm" onclick="TM.delLounge('${l.id}')">Delete</button>
                        </td>
                    </tr>`).join('')}
                </table>`;
            } catch (e) {
                box.innerHTML = `<p class="text-muted">Could not load lounges: ${esc(e.message)}</p>`;
            }
        });
    };

    window.TM.delLounge = (id) => {
        if (!confirm('Delete this lounge?')) return;
        run(async () => {
            await api.deleteLounge(id);
            TM.reloadLounges();
        });
    };

    init().catch(e => {
        console.error(e);
        if ($('portalContent')) $('portalContent').innerHTML = `<div class="card"><div class="card-content text-muted">Failed to load portal: ${esc(e.message)}</div></div>`;
    });
})();