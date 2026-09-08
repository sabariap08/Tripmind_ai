/* TripMind AI — Explore India destination gallery.
   Images are hotlinked from the Unsplash CDN (Unsplash License: free to use,
   no attribution required). Tiles render lazily and fall back to a branded
   gradient card if an image ever fails, so the layout never breaks.
   Shared by the landing page (index.html) and the passenger dashboard
   (portal.html) via window.TM_DESTINATIONS / tmRenderDestGrid. */
(function () {
    'use strict';

    const WIDTH = 700;

    const DESTINATIONS = [
        { name: 'Agra', state: 'Uttar Pradesh', tagline: 'Timeless Taj Mahal', imgId: 'photo-1564507592333-c60657eea523' },
        { name: 'Jaipur', state: 'Rajasthan', tagline: 'The Pink City', imgId: 'photo-1599661046289-e31897846e41' },
        { name: 'Alleppey', state: 'Kerala', tagline: 'Backwater houseboats', imgId: 'photo-1602216056096-3b40cc0c9944' },
        { name: 'Goa', state: 'West Coast', tagline: 'Golden sun-kissed beaches', imgId: 'photo-1512343879784-a960bf40e7f2' },
        { name: 'Varanasi', state: 'Uttar Pradesh', tagline: 'Sacred river ghats', imgId: 'photo-1561361513-2d000a50f0dc' },
        { name: 'Himachal', state: 'Himalayas', tagline: 'Alpine valleys & pine', imgId: 'photo-1626621341517-bbf3d9990a23' },
        { name: 'Andaman', state: 'Islands', tagline: 'Turquoise lagoons', imgId: 'photo-1544550581-5f7ceaf7f992' },
        { name: 'Rajasthan', state: 'Desert Royal', tagline: 'Grand forts & palaces', imgId: 'photo-1477587458883-47145ed94245' }
    ];

    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    const imgUrl = (id) => `https://images.unsplash.com/${id}?auto=format&fit=crop&w=${WIDTH}&q=70`;

    const tile = (d) => `
        <a class="dest-tile" href="/register.html" data-reveal>
            <img class="dest-img" src="${imgUrl(d.imgId)}" alt="${esc(d.name)}, ${esc(d.state)}"
                 loading="lazy" decoding="async" data-name="${esc(d.name)}"
                 onerror="window.tmDestFallback && tmDestFallback(this)">
            <span class="dest-shade"></span>
            <span class="dest-cap">
                <span class="dest-state">${esc(d.state)}</span>
                <strong>${esc(d.name)}</strong>
                <small>${esc(d.tagline)}</small>
            </span>
        </a>`;

    window.TM_DESTINATIONS = DESTINATIONS;

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
        const limit = opts && opts.limit ? opts.limit : DESTINATIONS.length;
        el.innerHTML = DESTINATIONS.slice(0, Math.min(limit, DESTINATIONS.length)).map(tile).join('');
        if (window.tmReveal) setTimeout(() => window.tmReveal(el), 0);
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