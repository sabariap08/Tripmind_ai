/* TripMind AI — Explore India destination gallery.
   DB-driven: tiles are built from approved tourist spots (GET /api/spots).
   Images are hotlinked from the Unsplash CDN (Unsplash License: free to use,
   no attribution required). Tiles render lazily and fall back to a branded
   gradient card if an image ever fails, so the layout never breaks.
   Shared by the landing page (index.html) and the passenger dashboard
   (portal.html) via window.TM_DESTINATIONS / tmRenderDestGrid. */
(function () {
    'use strict';

    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    /* Approved spots -> tile. Kept on window.TM_DESTINATIONS so the portal can
       reuse the same cover art for trip cards (see portal.js destCover). */
    window.TM_DESTINATIONS = [];

    const PLANNER = (d) => `/pages/planner.html?destination=${encodeURIComponent(d.city || d.name)}`
        + (`&spot=${encodeURIComponent(d.name)}`);

    const tile = (d) => `
        <a class="dest-tile" href="${PLANNER(d)}" data-reveal>
            <img class="dest-img" src="${d.img}" alt="${esc(d.name)}, ${esc(d.state)}"
                 loading="lazy" decoding="async" data-name="${esc(d.name)}"
                 onerror="window.tmDestFallback && tmDestFallback(this)">
            <span class="dest-shade"></span>
            <span class="dest-cap">
                <span class="dest-state">${esc(d.state || 'India')}</span>
                <strong>${esc(d.name)}</strong>
                <small>${esc(d.tagline)}</small>
            </span>
        </a>`;

    const cityOf = (s) => (s.location && s.location.city) || s.city || '';
    const stateOf = (s) => (s.location && s.location.state) || s.state || '';
    const taglineFor = (s) => {
        if (s.category) return 'Approved ' + String(s.category).replace(/_/g, ' ').toLowerCase();
        const d = String(s.description || '').trim();
        return d.length > 72 ? d.slice(0, 72).trim() + '…' : (d || 'Explore India');
    };

    /* Load once; cached per page load. Never breaks the layout when offline. */
    let _load = null;
    window.tmLoadDestinations = function () {
        if (!_load) {
            _load = (async () => {
                const res = await api.getSpots({ approved: 1 });
                const spots = (res && res.spots) || [];
                const list = spots
                    .filter(s => s && s.status === 'APPROVED' && Array.isArray(s.images)
                        && s.images.length && s.images[0])
                    .map(s => ({
                        name: s.name,
                        city: cityOf(s),
                        state: stateOf(s),
                        tagline: taglineFor(s),
                        img: s.images[0],
                    }));
                list.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
                window.TM_DESTINATIONS = list;
                return list;
            })().catch(() => (window.TM_DESTINATIONS = []));
        }
        return _load;
    };

    window.tmDestFallback = function (img) {
        if (!img || img.dataset.fbk) return;
        img.dataset.fbk = '1';
        const name = (img.getAttribute('data-name') || 'India').trim();
        const initial = name.charAt(0).toUpperCase();
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="700" height="520">
            <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stop-color="#0f172a"/><stop offset="1" stop-color="#334155"/>
            </linearGradient></defs>
            <rect width="700" height="520" fill="url(#g)"/>
            <circle cx="350" cy="230" r="112" fill="none" stroke="#f59e0b" stroke-width="3" opacity="0.9"/>
            <text x="350" y="278" font-family="-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
                  font-size="110" font-weight="700" fill="#fbbf24" text-anchor="middle">${initial}</text>
        </svg>`;
        img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
    };

    window.tmRenderDestGrid = function (el, opts) {
        if (typeof el === 'string') el = document.querySelector(el);
        if (!el) return;
        const limit = opts && opts.limit ? opts.limit : Infinity;
        window.tmLoadDestinations().then(list => {
            el.innerHTML = list.slice(0, Math.min(limit, list.length)).map(tile).join('');
            if (window.tmReveal) setTimeout(() => window.tmReveal(el), 0);
        }).catch(() => { el.innerHTML = ''; });
    };

    window.tmReveal = function (root) {
        const els = (root || document).querySelectorAll('[data-reveal]');
        if (!('IntersectionObserver' in window)) {
            els.forEach(e => e.classList.add('revealed'));
            return;
        }
        const io = new IntersectionObserver((entries, obs) => {
            entries.forEach(en => {
                if (en.isIntersecting) {
                    en.target.classList.add('revealed');
                    obs.unobserve(en.target);
                }
            });
        }, { threshold: 0.12 });
        els.forEach(e => io.observe(e));
    };
})();